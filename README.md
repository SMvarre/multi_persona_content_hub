# Multi-Persona Content Hub

Grounded RAG over your documents with four AI personas (Technical Writer, Educator, Social Media Manager, Research Analyst). Upload PDFs or text, query with citations, or run persona-aware agent workflows.

**Version:** 0.3.0

## Quick start

1. Create a virtual environment and install dependencies:

   ```powershell
   python -m venv .venv
   .\.venv\Scripts\pip install -r requirements.txt
   ```

2. Copy `.env.example` to `.env` and set your LLM API key (`OPENROUTER_API_KEY` or `GEMINI_API_KEY`).

3. Start the server:

   ```powershell
   .\scripts\run.ps1
   ```

4. Open **http://127.0.0.1:8001** in your browser.

## Architecture

See **[docs/STRUCTURE_AND_BLUEPRINT.md](docs/STRUCTURE_AND_BLUEPRINT.md)** for the full directory tree, module responsibilities, API routes, data-flow diagrams, and configuration reference.

## API overview

| Method | Route | Description |
|--------|-------|-------------|
| GET | `/api/v1/health` | Status and indexed chunk count |
| POST | `/api/v1/ingest/upload` | Upload and index a PDF/TXT |
| DELETE | `/api/v1/index` | Clear the vector index |
| POST | `/api/v1/query` | Grounded RAG query |
| GET | `/api/v1/agent/personas` | List personas |
| POST | `/api/v1/agent/query` | Persona agent query |

## Smoke tests

```powershell
$env:PYTHONPATH = (Get-Location).Path
.\.venv\Scripts\python.exe scripts\smoke_test.py
.\.venv\Scripts\python.exe scripts\agent_smoke_test.py
```

## Stack

FastAPI · ChromaDB · SentenceTransformers (`all-MiniLM-L6-v2`) · LangChain · optional OpenRouter/Gemini LLM
