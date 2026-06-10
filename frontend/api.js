/**
 * Talk to the FastAPI backend (health, ingest, query, agent).
 */

const Api = (() => {
  const STORAGE_KEY = "content_hub_api_base";

  function getBase() {
    const input = document.getElementById("apiBase");
    const fromInput = input?.value?.trim();
    if (fromInput) return fromInput.replace(/\/$/, "");
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored) return stored.replace(/\/$/, "");
    return window.location.origin;
  }

  function setBase(url) {
    const normalized = url.replace(/\/$/, "");
    localStorage.setItem(STORAGE_KEY, normalized);
    const input = document.getElementById("apiBase");
    if (input) input.value = normalized;
  }

  async function discoverBase() {
    const stored = localStorage.getItem(STORAGE_KEY)?.replace(/\/$/, "");
    const origin = window.location.origin;
    const tryList = [stored, origin, "http://127.0.0.1:8001"].filter(
      (b) => b && !b.startsWith("file:")
    );

    for (const base of tryList) {
      try {
        const r = await fetch(`${base}/api/v1/health`);
        if (r.ok) return base;
      } catch {
        /* try next URL */
      }
    }
    return stored || "http://127.0.0.1:8001";
  }

  async function request(path, options = {}) {
    const url = `${getBase()}${path}`;
    const headers = { ...(options.headers || {}) };

    let body = options.body;
    if (body && !(body instanceof FormData)) {
      headers["Content-Type"] = "application/json";
      body = JSON.stringify(body);
    }

    const response = await fetch(url, { ...options, headers, body });
    const text = await response.text();
    let data;
    try {
      data = text ? JSON.parse(text) : null;
    } catch {
      data = { detail: text || response.statusText };
    }

    if (!response.ok) {
      const detail = data?.detail;
      let message = `Request failed (${response.status})`;
      if (typeof detail === "string") message = detail;
      if (Array.isArray(detail)) {
        message = detail.map((d) => d.msg || JSON.stringify(d)).join(", ");
      }
      throw new Error(message);
    }
    return data;
  }

  return {
    getBase,
    setBase,
    discoverBase,
    health() {
      return request("/api/v1/health");
    },
    clearIndex() {
      return request("/api/v1/index", { method: "DELETE" });
    },
    ingestUpload(file) {
      const form = new FormData();
      form.append("file", file);
      return request("/api/v1/ingest/upload", { method: "POST", body: form });
    },
    query(question, topK) {
      const body = { question };
      if (topK) body.top_k = Number(topK);
      return request("/api/v1/query", { method: "POST", body });
    },
    listPersonas() {
      return request("/api/v1/agent/personas");
    },
    agentQuery(question, personaId, topK) {
      const body = { question };
      if (personaId) body.persona_id = personaId;
      if (topK) body.top_k = Number(topK);
      return request("/api/v1/agent/query", { method: "POST", body });
    },
  };
})();
