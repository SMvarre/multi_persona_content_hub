"""RAG + LLM + persona agent."""

import json
import re
from pathlib import Path

from langchain_community.document_loaders import TextLoader
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_community.vectorstores import Chroma
from langchain_core.documents import Document
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.config import Settings
from app.models import (
    AgentWorkflowResult,
    ChunkRecord,
    IngestionResult,
    IntentType,
    PersonaDefinition,
    QueryResult,
    RetrievedChunk,
    ToolExecutionRecord,
)

SUPPORTED = {".pdf", ".txt"}
REFUSAL = "I cannot answer this question based on the provided documents."
CITE = "Cite as [1], [2] only — never file paths."
LOG_PATH = Path(__file__).resolve().parent.parent / "debug-621a4d.log"

RAG_SYSTEM = f"""You are a precise assistant. Answer ONLY from the provided context.

Use this Markdown structure:
## Summary
1–2 sentences that directly answer the question.

## Answer
Clear, well-organized explanation with bullet points where helpful. Put [1], [2] inline after each factual claim.

## Sources
List which citation numbers you used (e.g. [1], [3]).

Rules:
- No filler, hedging, or generic AI phrases.
- If context is insufficient, reply exactly: {REFUSAL}
- {CITE}"""


def _debug_log(location: str, message: str, data: dict, hypothesis_id: str = "X"):
    # #region agent log
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(
                json.dumps(
                    {
                        "sessionId": "621a4d",
                        "timestamp": int(__import__("time").time() * 1000),
                        "location": location,
                        "message": message,
                        "data": data,
                        "hypothesisId": hypothesis_id,
                    }
                )
                + "\n"
            )
    except Exception:
        pass
    # #endregion

_circuit_open = False
_circuit_reason = ""
_llm_auth_cache: dict = {"ok": None, "msg": "", "at": 0.0}


def circuit_open():
    return _circuit_open


def circuit_reason():
    return _circuit_reason


def reset_circuit():
    global _circuit_open, _circuit_reason
    _circuit_open = _circuit_reason = ""


def llm_auth_status(s: Settings) -> tuple[bool, str]:
    """Ping provider so health/UI can show invalid keys before queries fail."""
    import time

    now = time.time()
    if now - _llm_auth_cache["at"] < 120 and _llm_auth_cache["ok"] is not None:
        return _llm_auth_cache["ok"], _llm_auth_cache["msg"]

    if not s.enable_llm:
        return False, "ENABLE_LLM=false"
    if not s.llm_ok():
        return False, "no API key in .env"

    ok, msg = True, "ok"
    if s.llm_provider == "openrouter":
        try:
            import httpx

            r = httpx.get(
                f"{s.openrouter_base_url.rstrip('/')}/auth/key",
                headers={"Authorization": f"Bearer {s.openrouter_api_key}"},
                timeout=10,
            )
            ok = r.status_code == 200
            if not ok:
                body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
                msg = body.get("error", {}).get("message", r.text[:80])
        except Exception as e:
            ok, msg = False, str(e)[:80]

    _llm_auth_cache.update(ok=ok, msg=msg, at=now)
    _debug_log("rag.py:llm_auth_status", "checked", {"ok": ok, "msg": msg[:80]}, "C")
    return ok, msg


def _text(content):
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        return "".join(
            b.get("text", "") if isinstance(b, dict) else str(b) for b in content
        ).strip()
    return str(content).strip()


def chat(llm, messages):
    global _circuit_open, _circuit_reason
    if not llm or _circuit_open:
        return None
    try:
        _langchain_compat()
        out = _text(llm.invoke(messages).content)
        _debug_log("rag.py:chat", "llm ok", {"len": len(out or "")}, "C")
        return out
    except Exception as e:
        _circuit_open, _circuit_reason = True, f"{type(e).__name__}: {e}"
        _debug_log("rag.py:chat", "llm failed", {"type": type(e).__name__, "msg": str(e)[:200]}, "C")
        return None


def _langchain_compat():
    """langchain 1.x removed module-level flags that langchain-core 0.3 still reads."""
    import langchain

    defaults = {"verbose": False, "debug": False, "llm_cache": None}
    for attr, val in defaults.items():
        if not hasattr(langchain, attr):
            setattr(langchain, attr, val)


def get_llm(s: Settings):
    global _circuit_open, _circuit_reason
    if not s.enable_llm or _circuit_open or not s.llm_ok():
        return None
    try:
        _langchain_compat()
        if s.llm_provider == "openrouter":
            from langchain_openai import ChatOpenAI

            return ChatOpenAI(
                model=s.llm_model,
                temperature=s.llm_temperature,
                api_key=s.openrouter_api_key,
                base_url=s.openrouter_base_url,
                max_retries=s.llm_max_retries,
                default_headers={
                    "HTTP-Referer": "http://127.0.0.1:8001",
                    "X-Title": "Multi-Persona Content Hub",
                },
            )
        from langchain_google_genai import ChatGoogleGenerativeAI

        return ChatGoogleGenerativeAI(
            model=s.llm_model,
            temperature=s.llm_temperature,
            google_api_key=s.gemini_api_key,
            max_retries=s.llm_max_retries,
        )
    except Exception as e:
        _circuit_open, _circuit_reason = True, f"{type(e).__name__}: {e}"
        # #region agent log
        try:
            with open(Path(__file__).resolve().parent.parent / "debug-621a4d.log", "a", encoding="utf-8") as f:
                f.write(json.dumps({"sessionId": "621a4d", "timestamp": int(__import__("time").time() * 1000), "location": "rag.py:get_llm", "message": "llm init failed", "data": {"type": type(e).__name__, "msg": str(e)[:200]}, "hypothesisId": "F"}) + "\n")
        except Exception:
            pass
        # #endregion
        return None


class Citations:
    def __init__(self, chunks):
        self.chunks = chunks
        self.nums = {c.chunk_id: i for i, c in enumerate(chunks, 1)}

    def ref(self, cid):
        n = self.nums.get(cid)
        return f"[{n}]" if n else ""

    def ctx(self):
        lines = []
        for c in self.chunks:
            n = self.nums[c.chunk_id]
            name = Path(c.source.replace("\\", "/")).name or "document"
            lines.append(f"[{n}] {name} · excerpt {c.chunk_index + 1}\n{c.content.strip()}\n")
        return "\n".join(lines)

    def list(self):
        return [
            f"{self.ref(c.chunk_id)} {Path(c.source.replace('\\', '/')).name or 'document'} · excerpt {c.chunk_index + 1}"
            for c in self.chunks
        ]

    def clean(self, text):
        if not text:
            return text
        for cid, n in sorted(self.nums.items(), key=lambda x: -len(x[0])):
            text = text.replace(f"[{cid}]", f"[{n}]")
        return re.sub(r"\n{3,}", "\n\n", text).strip()


_STOP = frozenset({"what", "which", "does", "this", "that", "with", "from", "have", "your", "about", "system", "use"})


def _query_terms(query: str) -> list[str]:
    return [t.lower() for t in re.findall(r"\w{3,}", query) if t not in _STOP]


def _term_in_text(term: str, text: str) -> bool:
    if term in text:
        return True
    for root in (term.rstrip("s"), term.rstrip("ing"), term.rstrip("ed")):
        if len(root) >= 4 and root in text:
            return True
    return False


def _rerank(query: str, chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
    terms = _query_terms(query)
    if not terms:
        return chunks

    def boosted(c: RetrievedChunk) -> float:
        text = c.content.lower()
        name = Path(c.source.replace("\\", "/")).name.lower()
        bonus = sum(0.06 for t in terms if _term_in_text(t, text))
        bonus += sum(0.04 for t in terms if _term_in_text(t, name))
        return c.score + bonus

    return sorted(chunks, key=boosted, reverse=True)


def _extractive_structured_answer(question: str, chunks: list[RetrievedChunk], footer: str = "") -> str:
    """Build readable Markdown from retrieved sentences when LLM is unavailable."""
    cite = Citations(chunks)
    terms = _query_terms(question)
    picked: list[tuple[RetrievedChunk, str]] = []
    seen: set[str] = set()

    for c in chunks:
        flat = c.content.replace("\n", " ")
        for sent in re.split(r"(?<=[.!?])\s+", flat):
            s = sent.strip()
            if len(s) < 25:
                continue
            if terms and not any(_term_in_text(t, s.lower()) for t in terms):
                continue
            key = s[:100]
            if key in seen:
                continue
            seen.add(key)
            picked.append((c, s))
            if len(picked) >= 6:
                break
        if len(picked) >= 6:
            break

    if not picked:
        for c in chunks[:3]:
            s = c.content.strip().replace("\n", " ")[:280]
            picked.append((c, s))

    lines = [
        "## Summary",
        picked[0][1] if picked else REFUSAL,
        "",
        "## Answer",
    ]
    for c, s in picked[:5]:
        lines.append(f"- {cite.ref(c.chunk_id)} {s}")
    lines.extend(["", "## Sources", ", ".join(cite.list())])
    if footer:
        lines.extend(["", f"*{footer}*"])
    return "\n".join(lines)


def excerpts(chunks, intro="", footer="", n=None):
    chunks = chunks[:n] if n else chunks
    c = Citations(chunks)
    lines = [intro] if intro else []
    for x in c.chunks:
        name = Path(x.source.replace("\\", "/")).name or "document"
        lines.append(f"{c.ref(x.chunk_id)} *{name} · excerpt {x.chunk_index + 1}*\n{x.content.strip()}")
    if footer:
        lines.append(footer)
    return "\n\n".join(lines)


def _query_result(cite, chunks, answer, refused=False):
    return QueryResult(
        answer=answer,
        citations=cite.list(),
        retrieved_chunks=chunks,
        grounded=True,
        refused=refused,
    )


def grounded_answer(s: Settings, question: str, chunks: list[RetrievedChunk]) -> QueryResult:
    if not chunks:
        return _query_result(Citations([]), chunks, REFUSAL, refused=True)
    cite = Citations(chunks)
    _debug_log(
        "rag.py:grounded_answer",
        "retrieved",
        {"n": len(chunks), "scores": [c.score for c in chunks[:6]], "q": question[:80]},
        "B",
    )
    llm = get_llm(s)
    if not llm:
        _, auth_msg = llm_auth_status(s)
        return _query_result(
            cite,
            chunks,
            _extractive_structured_answer(
                question,
                chunks[: s.top_k],
                f"LLM unavailable ({auth_msg}). Update OPENROUTER_API_KEY in .env for synthesized answers.",
            ),
        )
    ans = chat(
        llm,
        [
            SystemMessage(content=RAG_SYSTEM),
            HumanMessage(content=f"Context:\n{cite.ctx()}\n\nQuestion: {question}"),
        ],
    )
    if not ans:
        return _query_result(
            cite,
            chunks,
            _extractive_structured_answer(
                question,
                chunks[: s.top_k],
                f"LLM error: {circuit_reason() or 'unavailable'}",
            ),
        )
    return _query_result(cite, chunks, cite.clean(ans), refused=REFUSAL.lower() in ans.lower())


def load_doc(path: Path) -> list[Document]:
    path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    if path.suffix.lower() not in SUPPORTED:
        raise ValueError(f"Unsupported: {path.suffix}")
    src = str(path)
    if path.suffix.lower() == ".pdf":
        from pypdf import PdfReader

        pages = []
        for i, page in enumerate(PdfReader(str(path)).pages):
            text = (page.extract_text() or "").strip()
            if text:
                pages.append(text)
        if not pages:
            return []
        # One document → fewer splits, faster ingest, better cross-page context
        return [
            Document(
                page_content="\n\n".join(pages),
                metadata={"source": src, "file_name": path.name, "page_count": len(pages)},
            )
        ]
    docs = TextLoader(str(path), encoding="utf-8").load()
    for d in docs:
        d.metadata.update(source=src, file_name=path.name)
    return docs


_store: "Store | None" = None


def get_store(s: Settings) -> "Store":
    global _store
    if _store is None:
        _store = Store(s)
    return _store


class Store:
    def __init__(self, s: Settings):
        self.s = s
        emb = HuggingFaceEmbeddings(
            model_name=s.embedding_model_name,
            model_kwargs={"device": "cpu"},
            encode_kwargs={"normalize_embeddings": True},
        )
        self.chroma = Chroma(
            collection_name=s.chroma_collection_name,
            embedding_function=emb,
            persist_directory=str(s.chroma_persist_dir),
        )
        self.split = RecursiveCharacterTextSplitter(
            chunk_size=s.chunk_size,
            chunk_overlap=s.chunk_overlap,
            separators=["\n\n", "\n", ". ", " ", ""],
        )

    def count(self):
        return self.chroma._collection.count()

    def clear_all(self) -> int:
        coll = self.chroma._collection
        data = coll.get()
        ids = data.get("ids") or []
        if ids:
            coll.delete(ids=ids)
        n = len(ids)
        _debug_log("rag.py:clear_all", "cleared", {"removed": n}, "A")
        return n

    def _purge_source(self, source: str) -> int:
        coll = self.chroma._collection
        try:
            existing = coll.get(where={"source": source})
            ids = existing.get("ids") or []
            if ids:
                coll.delete(ids=ids)
            return len(ids)
        except Exception:
            return 0

    def ingest(self, path: Path) -> IngestionResult:
        import time

        t0 = time.time()
        src = str(path.resolve())
        removed = self._purge_source(src)
        splits = self.split.split_documents(load_doc(path))
        chunks = []
        for i, d in enumerate(splits):
            fn = d.metadata.get("file_name", path.name)
            safe = re.sub(r"[^\w.\-]", "_", fn)
            chunks.append(
                ChunkRecord(
                    chunk_id=f"{safe}#{i}",
                    source=src,
                    content=d.page_content,
                    chunk_index=i,
                    metadata={"file_name": fn},
                )
            )
        if not chunks:
            return IngestionResult(sources=[src], chunk_count=0, chunk_ids=[])
        batch = self.s.ingest_batch_size
        for i in range(0, len(chunks), batch):
            part = chunks[i : i + batch]
            self.chroma.add_documents(
                [
                    Document(
                        page_content=c.content,
                        metadata={"chunk_id": c.chunk_id, "source": c.source, "chunk_index": c.chunk_index},
                    )
                    for c in part
                ],
                ids=[c.chunk_id for c in part],
            )
        ms = int((time.time() - t0) * 1000)
        _debug_log(
            "rag.py:ingest",
            "done",
            {"file": path.name, "chunks": len(chunks), "removed": removed, "ms": ms},
            "A",
        )
        return IngestionResult(sources=[src], chunk_count=len(chunks), chunk_ids=[c.chunk_id for c in chunks])

    def retrieve(self, query, top_k=None, score_threshold=None):
        k = top_k or self.s.top_k
        thr = score_threshold if score_threshold is not None else self.s.similarity_threshold
        out = []
        try:
            total = self.count()
            search_k = min(max(k * 8, 40), max(80, total // 30 + k))
            pairs = self.chroma.similarity_search_with_relevance_scores(query, k=search_k)
        except Exception:
            pairs = [(d, 1.0 - i * 0.05) for i, d in enumerate(self.chroma.similarity_search(query, k=k))]
        for d, sc in pairs:
            m = d.metadata
            out.append(
                RetrievedChunk(
                    chunk_id=str(m.get("chunk_id", "?")),
                    source=str(m.get("source", "?")),
                    content=d.page_content,
                    score=round(float(sc), 4),
                    chunk_index=int(m.get("chunk_index", -1)),
                )
            )
        # Apply threshold but never return empty if Chroma found candidates
        filtered = [c for c in out if c.score >= thr]
        out = filtered if filtered else out
        out = _rerank(query, out)[:k]
        _debug_log(
            "rag.py:retrieve",
            "scores",
            {"n": len(out), "scores": [c.score for c in out], "thr": thr},
            "B",
        )
        return out


def warm_store(s: Settings) -> int:
    """Load embedding model once at startup (avoids multi-minute wait on first upload)."""
    return get_store(s).count()


# --- Agent / Personas ---

def _p(id, name, desc, intents, style, tools):
    return PersonaDefinition(id=id, name=name, description=desc, supported_intents=intents, style_guidelines=style, preferred_tools=tools)


PERSONA_RULES = {
    "technical_writer": """You are the Technical Writer persona (identifier: technical_writer).
Write crystal-clear, concise, accurate documentation. Use active voice and imperatives; avoid passive voice, vague metaphors, and filler.
Use logical Markdown hierarchies, structured bullets, and clean code blocks when appropriate.
Deliver production-ready content only — no generic AI fluff.""",
    "educator": """You are the Educator persona (identifier: educator).
Break down complex code, algorithms, or technical concepts for learners. Use real-world analogies before technical detail.
Maintain an encouraging, clear, structured tone. Define advanced terms before using them.
Deliver production-ready teaching content — no generic AI fluff.""",
    "social_media_manager": """You are the Social Media Manager persona (identifier: social_media_manager).
Write high-converting, platform-specific copy for engagement, reach, or conversion.
No generic AI hooks, robot emojis on every line, or spam hashtag blocks.
Deliver production-ready posts — no generic AI fluff.""",
    "research_analyst": """You are the Research Analyst persona (identifier: research_analyst).
Use a data-first, objective, analytical mindset. Back assertions with metrics, frameworks, or cited document evidence.
Use tables, pros/cons bullets, risk notes, and executive summaries when useful.
Avoid emotional language, bias, and hype. Deliver actionable insight — no generic AI fluff.""",
}

INTENT_RULES = {
    ("technical_writer", "technical_documentation"): """Task: technical_documentation (Docs).
Structure: Prerequisites (if setup is needed) → step-by-step implementation → Expected Outcome or troubleshooting.
Follow standard technical writing principles.""",
    ("technical_writer", "general_qa"): """Task: general_qa.
Explain architectures or workflows simply without losing technical precision.""",
    ("educator", "education_explanation"): """Task: education_explanation (Teaching).
Structure exactly in three parts:
1) High-level conceptual summary
2) Visual text mental-model or line-by-line breakdown
3) Short interactive checkpoint question to test understanding""",
    ("educator", "general_qa"): """Task: general_qa (Teaching).
Teach the concept clearly using analogy + structured steps + one checkpoint question.""",
    ("social_media_manager", "social_content"): """Task: social_content (Posts).
Structure exactly:
**Hook:** compelling first line to stop scrolling
**Body:** punchy value lines with clean line breaks
**CTA:** one clear call to action
Adapt tone if the user names a channel (LinkedIn=data-driven, X/Twitter=conversational/threaded, short-form=brief/visual script).""",
    ("social_media_manager", "general_qa"): """Task: general_qa (Posts).
Answer in social-ready format with Hook, Body, and CTA when promoting or explaining a topic.""",
    ("research_analyst", "research_analysis"): """Task: research_analysis.
Structure: executive summary → dimensional analysis (market/technical/logical) → evidence-backed findings → risks/limitations → actionable recommendations.""",
    ("research_analyst", "general_qa"): """Task: general_qa.
Break analysis into clear dimensions with cited evidence from context. Include pros/cons or risks where relevant.""",
}

PERSONAS = {
    p.id: p
    for p in [
        _p(
            "technical_writer",
            "Technical Writer",
            "Crystal-clear docs, APIs, and technical Q&A grounded in your sources.",
            ["technical_documentation", "general_qa", "docs"],
            PERSONA_RULES["technical_writer"],
            ["summarize"],
        ),
        _p(
            "educator",
            "Educator",
            "Structured teaching: concepts, mental models, and checkpoint questions.",
            ["education_explanation", "general_qa", "teaching"],
            PERSONA_RULES["educator"],
            ["summarize"],
        ),
        _p(
            "social_media_manager",
            "Social Media Manager",
            "Platform-aware posts with Hook, Body, and CTA from your knowledge base.",
            ["social_content", "general_qa", "posts"],
            PERSONA_RULES["social_media_manager"],
            ["web_search"],
        ),
        _p(
            "research_analyst",
            "Research Analyst",
            "Evidence-led analysis, comparisons, and executive summaries.",
            ["research_analysis", "general_qa"],
            PERSONA_RULES["research_analyst"],
            ["web_search", "summarize"],
        ),
    ]
}

INTENT_PERSONA = {
    "technical_documentation": "technical_writer",
    "education_explanation": "educator",
    "social_content": "social_media_manager",
    "research_analysis": "research_analyst",
    "general_qa": "research_analyst",
}

TASK_ALIASES = {
    "docs": "technical_documentation",
    "technical documentation": "technical_documentation",
    "technical_documentation": "technical_documentation",
    "teaching": "education_explanation",
    "education_explanation": "education_explanation",
    "posts": "social_content",
    "social_content": "social_content",
    "social content": "social_content",
    "research": "research_analysis",
    "research_analysis": "research_analysis",
    "general_qa": "general_qa",
    "general qa": "general_qa",
    "use persona": "general_qa",
}

PERSONA_ALIASES = {
    "technical writer": "technical_writer",
    "technical_writer": "technical_writer",
    "educator": "educator",
    "social media manager": "social_media_manager",
    "social_media_manager": "social_media_manager",
    "research analyst": "research_analyst",
    "research_analyst": "research_analyst",
}

KW = {
    IntentType.TECHNICAL_DOCUMENTATION: (
        "api", "code", "deploy", "install", "configure", "readme", "documentation", "docs", "endpoint", "sdk",
    ),
    IntentType.EDUCATION_EXPLANATION: (
        "explain", "learn", "tutorial", "teach", "beginner", "how does", "what is", "understand", "lesson",
    ),
    IntentType.SOCIAL_CONTENT: (
        "tweet", "linkedin", "post", "caption", "hook", "cta", "instagram", "thread", "social",
    ),
    IntentType.RESEARCH_ANALYSIS: (
        "research", "analyze", "report", "compare", "market", "trend", "risk", "pros", "cons", "data",
    ),
}


def list_personas():
    return list(PERSONAS.values())


def _normalize_intent(raw: str) -> str:
    key = (raw or "").strip().lower()
    return TASK_ALIASES.get(key, key if key in INTENT_PERSONA else "general_qa")


def _parse_orchestrator_command(q: str):
    """Parse: Persona: [Name] | Task: [Sub-task] -> [Instructions]"""
    m = re.search(
        r"persona\s*:\s*([^|]+)\|\s*task\s*:\s*([^\-]+?)(?:\s*->\s*(.+))?$",
        q.strip(),
        re.I | re.S,
    )
    if not m:
        return None
    persona_key = m.group(1).strip().lower()
    task_raw = m.group(2).strip()
    instructions = (m.group(3) or "").strip()
    persona_id = PERSONA_ALIASES.get(persona_key)
    if not persona_id:
        for alias, pid in PERSONA_ALIASES.items():
            if alias in persona_key or persona_key in alias:
                persona_id = pid
                break
    intent = _normalize_intent(task_raw)
    clean_q = instructions or q
    return {"persona_id": persona_id, "intent": intent, "question": clean_q}


def persona_system_prompt(persona: PersonaDefinition, intent: str) -> str:
    base = PERSONA_RULES.get(persona.id, persona.style_guidelines)
    extra = INTENT_RULES.get((persona.id, intent), "")
    parts = [base]
    if extra:
        parts.append(extra)
    parts.append(f"Active intent: {intent}. Stay in {persona.name} voice only; do not blend other personas.")
    parts.append(
        "Output in Markdown with clear headings and bullets. Lead with the deliverable the user asked for — "
        "not a preamble. Every factual claim must cite [1], [2] from context."
    )
    parts.append(CITE)
    parts.append(
        f"Use ONLY facts from Context and Tools. If insufficient, reply exactly: {REFUSAL}"
    )
    return "\n\n".join(parts)


def _intent(s, q, persona: PersonaDefinition | None = None):
    parsed = _parse_orchestrator_command(q)
    if parsed and parsed.get("intent"):
        return parsed["intent"]

    llm = get_llm(s)
    if llm:
        labels = ", ".join(i.value for i in IntentType)
        t = chat(
            llm,
            [
                SystemMessage(
                    content=(
                        f'Classify intent. Reply JSON only: {{"intent":"one_of"}}. '
                        f"Valid: {labels}"
                    )
                ),
                HumanMessage(content=q),
            ],
        )
        if t and (m := re.search(r"\{.*\}", t, re.S)):
            try:
                return _normalize_intent(json.loads(m.group()).get("intent", "general_qa"))
            except json.JSONDecodeError:
                pass

    q_lower = q.lower()
    valid = {e.value for e in IntentType}
    if persona:
        search_space = {IntentType(k): KW[IntentType(k)] for k in persona.supported_intents if k in valid}
        if not search_space:
            search_space = KW
    else:
        search_space = KW

    best, sc = "general_qa", 0
    for it, words in search_space.items():
        key = it.value if hasattr(it, "value") else str(it)
        if key not in INTENT_PERSONA:
            continue
        hit = sum(w in q_lower for w in words)
        if hit > sc:
            sc, best = hit, key

    if persona and best == "general_qa" and len(persona.supported_intents) == 1:
        return persona.supported_intents[0]
    if persona and best == "general_qa":
        for pref in ("technical_documentation", "education_explanation", "social_content", "research_analysis"):
            if pref in persona.supported_intents:
                return pref
    return best


def _tools(s, q, intent, persona):
    if not s.enable_tool_calling:
        return []
    q = q.lower()
    out = []
    if s.enable_web_search and "web_search" in persona.preferred_tools:
        if any(w in q for w in ("latest", "news", "today", "market")) or intent == "research_analysis":
            out.append("web_search")
    if "summarize" in persona.preferred_tools and any(w in q for w in ("summary", "summarize", "brief")):
        out.append("summarize")
    return out[: s.max_tool_iterations]


def _run_tool(s, name, q):
    if name == "web_search" and s.enable_web_search:
        try:
            from langchain_community.tools import DuckDuckGoSearchRun

            return ToolExecutionRecord(name, q[:120], str(DuckDuckGoSearchRun(max_results=s.web_search_max_results).invoke(q)), True)
        except Exception as e:
            return ToolExecutionRecord(name, q[:120], str(e), False)
    if name == "summarize":
        return ToolExecutionRecord(name, q[:120], f"(Summarize: {q[:200]})", True)
    return ToolExecutionRecord(name, q[:120], "Unknown", False)


def _extractive_persona_answer(persona: PersonaDefinition, intent: str, chunks, tools, question: str = "") -> str:
    body = _extractive_structured_answer(
        question or f"{persona.name} {intent}",
        chunks,
        f"{persona.name} · extractive mode — set a valid API key for full persona output.",
    )
    if persona.id == "social_media_manager" and intent == "social_content" and not question:
        body = (
            f"**{persona.name}** (extractive — set LLM keys for full Hook/Body/CTA)\n\n"
            "**Hook:**\n" + (chunks[0].content[:280] if chunks else "(no context)") + "\n\n"
            "**Body:**\n" + "\n".join(f"- {c.content[:200].strip()}" for c in chunks[:3]) + "\n\n"
            "**CTA:** Review the cited sources and adapt for your channel."
        )
    elif persona.id == "educator" and intent == "education_explanation":
        body = (
            f"**{persona.name}** (extractive)\n\n"
            "**1) Summary:**\n" + (chunks[0].content[:400] if chunks else REFUSAL) + "\n\n"
            "**2) Breakdown:**\n" + excerpts(chunks[1:4]) + "\n\n"
            "**3) Checkpoint:** What part of the above would you explain in your own words?"
        )
    elif persona.id == "research_analyst":
        body = (
            f"**{persona.name}** (extractive)\n\n"
            "**Executive summary:**\n" + (chunks[0].content[:350] if chunks else REFUSAL) + "\n\n"
            "**Evidence from sources:**\n" + excerpts(chunks[:5])
        )
    for t in tools:
        if t.success:
            body += f"\n\n**[{t.tool_name}]**\n{t.output[:500]}"
    return body


def _agent_answer(s, q, persona, intent, ctx, chunks, tools):
    cite = Citations(chunks)
    if not ctx.strip() and not any(t.success for t in tools):
        return REFUSAL, [], True
    llm = get_llm(s)
    if not llm:
        return _extractive_persona_answer(persona, intent, chunks, tools, q), cite.list(), False
    tool_txt = "\n\n".join(f"[{t.tool_name}]\n{t.output}" for t in tools if t.success) or "(none)"
    ans = chat(
        llm,
        [
            SystemMessage(content=persona_system_prompt(persona, intent)),
            HumanMessage(
                content=(
                    f"Context from indexed documents:\n{ctx}\n\n"
                    f"Tool outputs:\n{tool_txt}\n\n"
                    f"User request:\n{q}\n\n"
                    f"Respond fully in {persona.name} style for intent '{intent}'."
                )
            ),
        ],
    )
    if not ans:
        return _extractive_persona_answer(persona, intent, chunks, tools, q), cite.list(), False
    return cite.clean(ans), cite.list(), REFUSAL.lower() in ans.lower()


class Agent:
    def __init__(self, s: Settings, store: Store):
        self.s, self.store = s, store

    def run(self, q, persona_id=None, top_k=None, score_threshold=None) -> AgentWorkflowResult:
        parsed = _parse_orchestrator_command(q)
        question = parsed["question"] if parsed else q
        if parsed and parsed.get("persona_id"):
            persona_id = parsed["persona_id"]

        persona = PERSONAS.get(persona_id) if persona_id in PERSONAS else None
        intent = _intent(self.s, question, persona)
        if not persona:
            persona = PERSONAS.get(
                INTENT_PERSONA.get(intent, self.s.default_persona_id),
                PERSONAS[self.s.default_persona_id],
            )
        planned = _tools(self.s, question, intent, persona)
        tools = [_run_tool(self.s, n, question) for n in planned]
        tctx = "\n\n".join(f"[{t.tool_name}]\n{t.output}" for t in tools if t.success)
        rk = top_k or (self.s.agent_top_k if persona_id else self.s.top_k)
        chunks = self.store.retrieve(question, rk, score_threshold)
        _debug_log(
            "rag.py:agent.run",
            "persona",
            {"persona": persona.id, "intent": intent, "top_k": rk, "chunks": len(chunks)},
            "E",
        )
        ctx = Citations(chunks).ctx()
        if tctx:
            ctx = f"{ctx}\n\nTOOLS:\n{tctx}"
        ans, cites, refused = _agent_answer(self.s, question, persona, intent, ctx, chunks, tools)
        return AgentWorkflowResult(
            answer=ans,
            persona_id=persona.id,
            persona_name=persona.name,
            intent=intent,
            citations=cites,
            retrieved_chunks=chunks,
            tool_executions=tools,
            tools_used=planned,
            refused=refused,
        )
