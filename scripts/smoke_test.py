import logging
from pathlib import Path

from app.config import get_settings
from app.rag import get_store, grounded_answer

logging.basicConfig(level=logging.INFO)

s = get_settings()
st = get_store(s)
r = st.ingest(Path("data/samples/sample.txt").resolve())
print(f"Ingested {r.chunk_count} chunks")
chunks = st.retrieve("What embedding model is used?")
ans = grounded_answer(s, "What embedding model is used?", chunks)
print(ans.answer[:500])
print(ans.citations)
