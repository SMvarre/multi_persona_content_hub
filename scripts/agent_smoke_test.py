import logging
from pathlib import Path

from app.config import get_settings
from app.rag import Agent, get_store

logging.basicConfig(level=logging.INFO)
s = get_settings()
st = get_store(s)
if Path("data/samples/sample.txt").is_file():
    st.ingest(Path("data/samples/sample.txt").resolve())
r = Agent(s, st).run("What embedding model does this system use?")
print(r.intent, r.persona_name, r.tools_used, r.answer[:600])
