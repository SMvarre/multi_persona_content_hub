import uvicorn

from app.config import get_settings

if __name__ == "__main__":
    uvicorn.run("app.server:app", host="0.0.0.0", port=8001, log_level=get_settings().log_level.lower())
