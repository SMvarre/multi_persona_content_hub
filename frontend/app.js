/**
 * Multi-Persona Content Hub — UI application logic.
 */

const VIEW_META = {
  dashboard: { title: "Dashboard", subtitle: "System overview and quick actions" },
  documents: { title: "Documents", subtitle: "Upload and index PDF / TXT files" },
  rag: { title: "RAG Query", subtitle: "Grounded Q&A from your knowledge base" },
  agent: { title: "Persona Agent", subtitle: "Orchestrator personas with intent-specific structure (Hook/Body/CTA, teaching checkpoints, docs, analysis)" },
  personas: { title: "Personas", subtitle: "Available content personas and intents" },
};

let personasCache = [];
const APP_BUILD = "fast3-debug";
const UI_STATE_KEY = "content_hub_ui_state";

const PERSONA_THEME_CLASS = {
  "": "theme-auto",
  research_analyst: "theme-research_analyst",
  educator: "theme-educator",
  technical_writer: "theme-technical_writer",
  social_media_manager: "theme-social_media_manager",
};

const PERSONA_VISUAL_CLASS = {
  research_analyst: "persona-visual--accent",
  educator: "persona-visual--accent",
  technical_writer: "persona-visual--accent",
  social_media_manager: "persona-visual--accent",
};

function $(id) {
  return document.getElementById(id);
}

function toast(message, type = "info") {
  // #region agent log
  fetch('http://127.0.0.1:7914/ingest/dd8b0dc0-0cd9-4bb4-80f8-fa6b0c77e77b',{method:'POST',headers:{'Content-Type':'application/json','X-Debug-Session-Id':'621a4d'},body:JSON.stringify({sessionId:'621a4d',location:'app.js:toast',message:'toast shown',data:{text:message,type,build:APP_BUILD},timestamp:Date.now(),hypothesisId:'A,C,E'})}).catch(()=>{});
  // #endregion
  const container = $("toasts");
  const el = document.createElement("div");
  el.className = `toast ${type}`;
  el.textContent = message;
  container.appendChild(el);
  setTimeout(() => el.remove(), 4500);
}

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

/** Friendly label for chunk_id (hides Windows paths). */
function chunkDisplayLabel(chunkId, chunkIndex) {
  const id = chunkId || "";
  let m = id.match(/([^/\\#]+)#chunk_(\d+)$/);
  if (m) return `${m[1]} · excerpt ${parseInt(m[2], 10) + 1}`;
  m = id.match(/([^/\\#]+)#(\d+)$/);
  if (m) return `${m[1]} · excerpt ${parseInt(m[2], 10) + 1}`;
  if (chunkIndex >= 0) return `excerpt ${chunkIndex + 1}`;
  return id.length > 48 ? `${id.slice(0, 45)}…` : id;
}

function getActivePersonaId() {
  return $("globalPersona")?.value || $("agentPersona")?.value || "";
}

function syncPersonaSelects(value) {
  ["globalPersona", "agentPersona"].forEach((id) => {
    const el = $(id);
    if (el) el.value = value;
  });
  applyPersonaTheme(value);
}

function applyPersonaTheme(personaId) {
  const themeClass = PERSONA_THEME_CLASS[personaId] || "theme-auto";
  document.body.className = themeClass;
  const app = $("app");
  if (app) app.dataset.persona = personaId || "auto";

  const visual = $("personaVisual");
  if (visual) {
    visual.innerHTML = `<span class="persona-orb ${personaId ? "" : "persona-orb--auto"}"></span>`;
  }

  const p = personasCache.find((x) => x.id === personaId);
  const label = $("personaBannerLabel");
  const badge = $("personaBannerBadge");
  if (label) {
    label.textContent = p ? p.name : "Auto-detect intent";
  }
  if (badge) {
    badge.textContent = p ? p.id.replace(/_/g, " ") : "All personas";
    badge.className = "micro-badge micro-badge--accent";
  }
}

function chunksPanelHtml(chunks) {
  if (!chunks?.length) {
    return '<div class="clay-card card"><p class="empty-hint" style="margin:0">No chunks retrieved.</p></div>';
  }
  const n = chunks.length;
  return `<div class="clay-card card"><h4>Retrieved context <span class="chunks-meta">${n} chunk${n === 1 ? "" : "s"} · rank #1–#${n}</span></h4>${chunks
    .map(
      (c, i) => `
    <div class="chunk">
      <div class="chunk-header">
        <span class="chunk-rank" title="Retrieval rank (#1 = most relevant to your question)">#${i + 1}</span>
        <span class="chunk-label">${escapeHtml(chunkDisplayLabel(c.chunk_id, c.chunk_index))}</span>
        ${i === 0 ? '<span class="chunk-rank-badge">Best match</span>' : ""}
      </div>
      <p style="margin:0.35rem 0 0;font-size:0.82rem">${escapeHtml(c.content)}</p>
    </div>`
    )
    .join("")}</div>`;
}

function renderChunks(container, chunks) {
  container.innerHTML = chunksPanelHtml(chunks);
}

function saveUiState() {
  try {
    const state = {
      ragMessages: $("ragMessages")?.innerHTML ?? "",
      agentMessages: $("agentMessages")?.innerHTML ?? "",
      activeView: document.querySelector(".nav-pill.active")?.dataset.view ?? "dashboard",
    };
    localStorage.setItem(UI_STATE_KEY, JSON.stringify(state));
  } catch {
    /* ignore quota errors */
  }
}

function restoreUiState() {
  try {
    const raw = localStorage.getItem(UI_STATE_KEY);
    if (!raw) return false;
    const state = JSON.parse(raw);
    if (state.ragMessages) $("ragMessages").innerHTML = state.ragMessages;
    if (state.agentMessages) $("agentMessages").innerHTML = state.agentMessages;
    if (state.activeView) switchView(state.activeView);
    return true;
  } catch {
    return false;
  }
}

function appendMessage(containerId, role, body, meta = "") {
  const container = $(containerId);
  const empty = container.querySelector(".empty-hint");
  if (empty) empty.remove();

  const el = document.createElement("div");
  el.className = `message ${role}${body.includes("cannot answer") ? " refused" : ""}`;
  el.innerHTML = `
    ${meta ? `<div class="meta">${escapeHtml(meta)}</div>` : ""}
    <div class="body">${escapeHtml(body)}</div>
  `;
  container.appendChild(el);
  container.scrollTop = container.scrollHeight;
  saveUiState();
}

function setLoading(containerId, label) {
  const container = $(containerId);
  const el = document.createElement("div");
  el.className = "message assistant loading";
  el.dataset.loading = "1";
  el.innerHTML = `<div class="meta">${escapeHtml(label)}</div><div class="body loading-dots">Working</div>`;
  container.appendChild(el);
  container.scrollTop = container.scrollHeight;
  return el;
}

function clearLoading(containerId) {
  $(containerId).querySelectorAll('[data-loading="1"]').forEach((n) => n.remove());
}

async function refreshHealth() {
  const statusEl = $("connectionStatus");
  const dot = statusEl.querySelector("span:last-child") || statusEl;

  try {
    const h = await Api.health();
    // #region agent log
    fetch('http://127.0.0.1:7914/ingest/dd8b0dc0-0cd9-4bb4-80f8-fa6b0c77e77b',{method:'POST',headers:{'Content-Type':'application/json','X-Debug-Session-Id':'621a4d'},body:JSON.stringify({sessionId:'621a4d',location:'app.js:refreshHealth',message:'health ok',data:{base:Api.getBase(),version:h.version,api_build:h.api_build,hasApiBuild:Object.prototype.hasOwnProperty.call(h,'api_build'),build:APP_BUILD},timestamp:Date.now(),hypothesisId:'A,B'})}).catch(()=>{});
    // #endregion
    statusEl.classList.add("online");
    statusEl.classList.remove("offline");
    statusEl.innerHTML = `<span class="status-dot" aria-hidden="true"></span><span class="status-text">Connected · ${h.document_count} chunks</span>`;

    $("healthStatus").textContent = h.llm_mode ? `${h.status} · ${h.llm_mode}` : h.status;
    $("healthDocs").textContent = String(h.document_count);
    $("versionBadge").textContent = `v${h.version}`;
    $("docCountBadge").textContent = `${h.document_count} chunks`;
    return h;
  } catch (e) {
    // #region agent log
    fetch('http://127.0.0.1:7914/ingest/dd8b0dc0-0cd9-4bb4-80f8-fa6b0c77e77b',{method:'POST',headers:{'Content-Type':'application/json','X-Debug-Session-Id':'621a4d'},body:JSON.stringify({sessionId:'621a4d',location:'app.js:refreshHealth',message:'health failed',data:{base:Api.getBase(),error:String(e.message||e),build:APP_BUILD},timestamp:Date.now(),hypothesisId:'B,C'})}).catch(()=>{});
    // #endregion
    statusEl.classList.add("offline");
    statusEl.classList.remove("online");
    statusEl.innerHTML = `<span class="status-dot" aria-hidden="true"></span><span class="status-text">Offline</span>`;
    $("healthStatus").textContent = "unreachable";
    throw e;
  }
}

function populatePersonaSelects(personas) {
  personasCache = personas;
  const opts = personas
    .map((p) => `<option value="${escapeHtml(p.id)}">${escapeHtml(p.name)}</option>`)
    .join("");

  ["globalPersona", "agentPersona"].forEach((id) => {
    const sel = $(id);
    if (!sel) return;
    const first =
      sel.id === "globalPersona"
        ? '<option value="">✨ Auto-detect intent</option>'
        : sel.querySelector('option[value=""]')?.outerHTML || '<option value="">Auto</option>';
    sel.innerHTML = first + opts;
  });

  const globalSel = $("globalPersona");
  if (globalSel && !globalSel.dataset.bound) {
    globalSel.dataset.bound = "1";
    globalSel.addEventListener("change", () => syncPersonaSelects(globalSel.value));
  }

  applyPersonaTheme(globalSel?.value || "");

  const grid = $("personasGrid");
  grid.innerHTML = personas
    .map(
      (p) => `
    <article class="clay-card persona-card" role="listitem" tabindex="0" data-persona-id="${escapeHtml(p.id)}" aria-label="Select ${escapeHtml(p.name)} persona">
      <div class="persona-card__visual ${PERSONA_VISUAL_CLASS[p.id] || ""}" aria-hidden="true"></div>
      <span class="micro-badge micro-badge--accent">Persona</span>
      <h3>${escapeHtml(p.name)}</h3>
      <p class="persona-id">${escapeHtml(p.id)}</p>
      <p>${escapeHtml(p.description)}</p>
      <div class="persona-tags">${(p.supported_intents || [])
        .map((i) => `<span class="micro-badge micro-badge--accent">${escapeHtml(i)}</span>`)
        .join("")}</div>
      <button type="button" class="btn btn-secondary btn-sm persona-use-btn">Use persona</button>
    </article>`
    )
    .join("");

  grid.querySelectorAll(".persona-card").forEach((card) => {
    const use = () => {
      const id = card.dataset.personaId;
      syncPersonaSelects(id);
      toast(`Persona: ${personasCache.find((x) => x.id === id)?.name || id}`, "success");
    };
    card.querySelector(".persona-use-btn")?.addEventListener("click", (e) => {
      e.stopPropagation();
      use();
    });
    card.addEventListener("click", use);
    card.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        use();
      }
    });
  });
}

function switchView(viewId) {
  document.querySelectorAll(".nav-pill").forEach((btn) => {
    const on = btn.dataset.view === viewId;
    btn.classList.toggle("active", on);
    if (on) btn.setAttribute("aria-current", "page");
    else btn.removeAttribute("aria-current");
  });
  document.querySelectorAll(".view").forEach((v) => v.classList.remove("active"));
  $(`view-${viewId}`).classList.add("active");

  const meta = VIEW_META[viewId];
  $("viewTitle").textContent = meta.title;
  $("viewSubtitle").textContent = meta.subtitle;
  saveUiState();
}

async function handleRagSubmit(e) {
  e.preventDefault();
  const q = $("ragQuestion").value.trim();
  if (!q) return;

  appendMessage("ragMessages", "user", q, "You");
  $("ragQuestion").value = "";
  setLoading("ragMessages", "RAG");

  try {
    const res = await Api.query(q, $("ragTopK").value || undefined);
    clearLoading("ragMessages");
    appendMessage("ragMessages", "assistant", res.answer, res.refused ? "Refused" : "Grounded answer");
    renderChunks($("ragContext"), res.retrieved_chunks);
    if (res.citations?.length) {
      $("ragContext").innerHTML += `<div class="card" style="margin-top:0.75rem"><h4>Citations</h4>${res.citations
        .map((c) => `<span class="tag">${escapeHtml(c)}</span>`)
        .join("")}</div>`;
    }
  } catch (err) {
    clearLoading("ragMessages");
    appendMessage("ragMessages", "assistant", err.message, "Error");
    toast(err.message, "error");
  }
}

async function handleAgentSubmit(e) {
  e.preventDefault();
  const q = $("agentQuestion").value.trim();
  if (!q) return;

  appendMessage("agentMessages", "user", q, "You");
  $("agentQuestion").value = "";
  setLoading("agentMessages", "Agent workflow");

  try {
    const res = await Api.agentQuery(q, getActivePersonaId() || undefined);
    clearLoading("agentMessages");
    appendMessage(
      "agentMessages",
      "assistant",
      res.answer,
      `${res.persona_name} · ${res.intent}`
    );

    const meta = $("agentMeta");
    meta.innerHTML = `
      <div class="clay-card card">
        <h4>Routing</h4>
        <p style="margin:0"><strong>Persona:</strong> ${escapeHtml(res.persona_name)}</p>
        <p style="margin:0.35rem 0"><strong>Intent:</strong> ${escapeHtml(res.intent)}</p>
        <p style="margin:0.35rem 0"><strong>Tools:</strong> ${(res.tools_used || []).map((t) => `<span class="tag">${escapeHtml(t)}</span>`).join("") || "none"}</p>
        <p style="margin:0.5rem 0 0"><span class="tag ${res.grounded ? "pass" : ""}">grounded</span>
        ${res.refused ? '<span class="tag fail">refused</span>' : ""}</p>
      </div>
    `;
    meta.insertAdjacentHTML("beforeend", chunksPanelHtml(res.retrieved_chunks));
  } catch (err) {
    clearLoading("agentMessages");
    appendMessage("agentMessages", "assistant", err.message, "Error");
    toast(err.message, "error");
  }
}

async function uploadFile(file) {
  $("uploadProgress").classList.remove("hidden");
  $("ingestResult").classList.add("hidden");
  $("progressFill").style.width = "15%";
  const mb = (file.size / (1024 * 1024)).toFixed(1);
  $("uploadStatus").textContent = `Uploading ${file.name} (${mb} MB)…`;

  try {
    $("progressFill").style.width = "40%";
    $("uploadStatus").textContent = `Indexing ${file.name} — embedding chunks (large PDFs can take 1–3 min)…`;
    const res = await Api.ingestUpload(file);
    $("progressFill").style.width = "100%";
    $("uploadStatus").textContent = "Done";
    $("ingestResult").classList.remove("hidden");
    $("ingestResult").innerHTML = `
      <strong>Ingested successfully</strong><br/>
      Chunks: ${res.chunk_count}<br/>
      <small>${escapeHtml(res.chunk_ids?.[0] || "")}</small>
    `;
    toast(`${file.name} indexed (${res.chunk_count} chunks)`, "success");
    await refreshHealth();
  } catch (err) {
    $("uploadStatus").textContent = "Failed";
    toast(err.message, "error");
  } finally {
    setTimeout(() => $("uploadProgress").classList.add("hidden"), 800);
  }
}

function initNavigation() {
  document.querySelectorAll(".nav-pill").forEach((btn) => {
    btn.addEventListener("click", () => switchView(btn.dataset.view));
  });
}

function initDashboardActions() {
  document.querySelectorAll("[data-goto]").forEach((btn) => {
    btn.addEventListener("click", () => switchView(btn.dataset.goto));
  });
  $("clearIndexBtn")?.addEventListener("click", async () => {
    if (!confirm("Clear all indexed chunks? Re-upload documents after.")) return;
    try {
      const r = await Api.clearIndex();
      toast(`Index cleared (${r.removed_chunks} chunks removed)`, "success");
      await refreshHealth();
    } catch (e) {
      toast(e.message, "error");
    }
  });
}

function initDocuments() {
  const dropzone = $("dropzone");
  const input = $("fileInput");

  dropzone.addEventListener("click", () => input.click());
  input.addEventListener("change", () => {
    if (input.files[0]) uploadFile(input.files[0]);
  });

  dropzone.addEventListener("dragover", (e) => {
    e.preventDefault();
    dropzone.classList.add("dragover");
  });
  dropzone.addEventListener("dragleave", () => dropzone.classList.remove("dragover"));
  dropzone.addEventListener("drop", (e) => {
    e.preventDefault();
    dropzone.classList.remove("dragover");
    const file = e.dataTransfer.files[0];
    if (file) uploadFile(file);
  });
}

function initChatPlaceholders() {
  ["ragMessages", "agentMessages"].forEach((id) => {
    $(id).innerHTML = '<p class="empty-hint">No messages yet. Send a query to begin.</p>';
  });
}

async function initApiBase() {
  const input = $("apiBase");
  const base = await Api.discoverBase();
  // #region agent log
  fetch('http://127.0.0.1:7914/ingest/dd8b0dc0-0cd9-4bb4-80f8-fa6b0c77e77b',{method:'POST',headers:{'Content-Type':'application/json','X-Debug-Session-Id':'621a4d'},body:JSON.stringify({sessionId:'621a4d',location:'app.js:initApiBase',message:'api base resolved',data:{base,stored:localStorage.getItem('content_hub_api_base'),origin:window.location.origin,build:APP_BUILD},timestamp:Date.now(),hypothesisId:'B,C'})}).catch(()=>{});
  // #endregion
  input.value = base;
  Api.setBase(base);

  input.addEventListener("change", async () => {
    Api.setBase(input.value.trim());
    try {
      await refreshHealth();
    } catch {
      const recovered = await Api.discoverBase();
      input.value = recovered;
      Api.setBase(recovered);
      await refreshHealth().catch(() => toast("Could not reach API — use port 8001", "error"));
    }
  });
}

async function init() {
  // #region agent log
  fetch('http://127.0.0.1:7914/ingest/dd8b0dc0-0cd9-4bb4-80f8-fa6b0c77e77b',{method:'POST',headers:{'Content-Type':'application/json','X-Debug-Session-Id':'621a4d'},body:JSON.stringify({sessionId:'621a4d',location:'app.js:init',message:'app init',data:{build:APP_BUILD,scriptSrc:document.querySelector('script[src*="app.js"]')?.src||null},timestamp:Date.now(),hypothesisId:'A'})}).catch(()=>{});
  // #endregion
  await initApiBase();
  initNavigation();
  initDashboardActions();
  initDocuments();
  applyPersonaTheme(getActivePersonaId());
  if (!restoreUiState()) {
    initChatPlaceholders();
  }

  $("ragForm").addEventListener("submit", handleRagSubmit);
  $("agentForm").addEventListener("submit", handleAgentSubmit);

  try {
    await refreshHealth();
  } catch {
    toast("API not reachable — start server with scripts\\run.ps1 and use http://127.0.0.1:8001", "error");
  }

  try {
    const { personas } = await Api.listPersonas();
    populatePersonaSelects(personas);
  } catch (e) {
    toast(`Could not load personas: ${e.message}`, "error");
  }
}

document.addEventListener("DOMContentLoaded", init);
