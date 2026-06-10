import asyncio
import logging
import shutil
from contextlib import asynccontextmanager
from functools import lru_cache
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse

from app import __version__
from app.config import Settings, get_settings
from app.models import (
    AgentQueryRequest,
    AgentQueryResponse,
    HealthResponse,
    IngestPathRequest,
    IngestResponse,
    PersonaInfo,
    PersonasListResponse,
    QueryRequest,
    QueryResponse,
)
from app.rag import Agent, SUPPORTED, circuit_open, circuit_reason, get_store, grounded_answer, list_personas, llm_auth_status, reset_circuit, warm_store

ROOT = Path(__file__).resolve().parent.parent
UI = ROOT / "frontend"
log = logging.getLogger(__name__)


@lru_cache
def cfg() -> Settings:
    return get_settings()


@lru_cache
def store():
    return get_store(cfg())


@lru_cache
def agent() -> Agent:
    return Agent(cfg(), store())


@asynccontextmanager
async def lifespan(_):
    reset_circuit()
    logging.basicConfig(level=getattr(logging, cfg().log_level.upper(), logging.INFO))
    for name in ("httpx", "httpcore", "sentence_transformers", "chromadb", "huggingface_hub"):
        logging.getLogger(name).setLevel(logging.WARNING)
    log.info("Loading embedding model (one-time, ~30s on first run)...")
    n = await asyncio.to_thread(warm_store, cfg())
    log.info("Ready — %d chunks in index", n)
    yield


app = FastAPI(title="Content Hub", version=__version__, lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.exception_handler(Exception)
async def err(_, exc):
    # #region agent log
    try:
        import json, time
        with open(ROOT / "debug-621a4d.log", "a", encoding="utf-8") as f:
            f.write(json.dumps({"sessionId": "621a4d", "timestamp": int(time.time() * 1000), "location": "server.py:err", "message": "exception", "data": {"type": type(exc).__name__, "msg": str(exc)[:200]}, "hypothesisId": "F"}) + "\n")
    except Exception:
        pass
    # #endregion
    return JSONResponse(status_code=503, content={"detail": f"{type(exc).__name__}: failed. Set ENABLE_LLM=false if quota exceeded."})


@app.get("/api/v1/health", response_model=HealthResponse)
def health():
    s = cfg()
    auth_ok, auth_msg = llm_auth_status(s)
    if s.enable_llm and s.llm_ok() and auth_ok and not circuit_open():
        mode = s.llm_provider
    elif s.enable_llm and s.llm_ok() and not auth_ok:
        mode = f"extractive (invalid API key: {auth_msg[:40]})"
    elif circuit_open():
        mode = f"extractive ({circuit_reason()[:50]})"
    else:
        mode = "extractive"
    resp = HealthResponse(status="ok", version=__version__, document_count=store().count(), enable_llm=s.enable_llm, llm_mode=mode)
    # #region agent log
    try:
        import json, time
        with open(ROOT / "debug-621a4d.log", "a", encoding="utf-8") as f:
            f.write(json.dumps({"sessionId": "621a4d", "timestamp": int(time.time() * 1000), "location": "server.py:health", "message": "health response", "data": {"version": resp.version, "fields": list(resp.model_dump().keys())}, "hypothesisId": "B,D"}) + "\n")
    except Exception:
        pass
    # #endregion
    return resp


@app.post("/api/v1/ingest/upload", response_model=IngestResponse)
async def ingest_upload(file: UploadFile = File(...)):
    ext = Path(file.filename or "").suffix.lower()
    if ext not in SUPPORTED:
        raise HTTPException(400, detail=f"Allowed: {sorted(SUPPORTED)}")
    dest = cfg().upload_dir / (file.filename or "upload")
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("wb") as f:
        shutil.copyfileobj(file.file, f)
    try:
        return await asyncio.to_thread(store().ingest, dest)
    except FileNotFoundError as exc:
        raise HTTPException(404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, detail=str(exc)) from exc


@app.post("/api/v1/ingest/path", response_model=IngestResponse)
async def ingest_path(body: IngestPathRequest):
    p = Path(body.file_path)
    if not p.is_file():
        raise HTTPException(404, detail=str(p))
    return await asyncio.to_thread(store().ingest, p)


@app.delete("/api/v1/index")
async def clear_index():
    removed = await asyncio.to_thread(store().clear_all)
    return {"status": "ok", "removed_chunks": removed}


@app.post("/api/v1/query", response_model=QueryResponse)
async def query(body: QueryRequest):
    reset_circuit()
    chunks = await asyncio.to_thread(store().retrieve, body.question, body.top_k, body.score_threshold)
    return await asyncio.to_thread(grounded_answer, cfg(), body.question, chunks)


@app.get("/api/v1/agent/personas", response_model=PersonasListResponse)
def personas():
    return PersonasListResponse(
        personas=[
            PersonaInfo(id=p.id, name=p.name, description=p.description, supported_intents=p.supported_intents)
            for p in list_personas()
        ]
    )


@app.post("/api/v1/agent/query", response_model=AgentQueryResponse)
async def agent_query(body: AgentQueryRequest):
    reset_circuit()
    return await asyncio.to_thread(agent().run, body.question, body.persona_id, body.top_k, body.score_threshold)


if UI.is_dir():

    @app.get("/")
    def home():
        return FileResponse(UI / "index.html")

    @app.get("/health")
    def health_redirect():
        return RedirectResponse("/api/v1/health", 307)

    for fn in ("styles.css", "api.js", "app.js"):
        fp = UI / fn
        if fp.is_file():

            @app.get(f"/{fn}")
            def static(p=fp):
                return FileResponse(p)
