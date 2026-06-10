from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    data_dir: Path = Path("data")
    upload_dir: Path = Path("data/uploads")
    chroma_persist_dir: Path = Path("data/chroma")
    chroma_collection_name: str = "rag_documents"
    embedding_model_name: str = "all-MiniLM-L6-v2"
    chunk_size: int = Field(default=1400, ge=64)
    chunk_overlap: int = Field(default=120, ge=0)
    ingest_batch_size: int = Field(default=128, ge=8, le=256)
    top_k: int = Field(default=6, ge=1, le=20)
    agent_top_k: int = Field(default=8, ge=1, le=20)
    similarity_threshold: float = Field(default=0.2, ge=0.0, le=1.0)
    llm_provider: Literal["gemini", "openrouter"] = "gemini"
    gemini_api_key: str | None = Field(default=None, validation_alias=AliasChoices("GEMINI_API_KEY", "GOOGLE_API_KEY"))
    openrouter_api_key: str | None = Field(default=None, validation_alias=AliasChoices("OPENROUTER_API_KEY", "OPEN_ROUTER_API_KEY"))
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    llm_model: str = "gemini-2.0-flash"
    llm_temperature: float = Field(default=0.0, ge=0.0, le=1.0)
    llm_max_retries: int = Field(default=2, ge=0, le=5)
    enable_llm: bool = True
    enable_web_search: bool = True
    enable_tool_calling: bool = True
    max_tool_iterations: int = Field(default=2, ge=0, le=5)
    default_persona_id: str = "research_analyst"
    web_search_max_results: int = Field(default=5, ge=1, le=10)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    def llm_ok(self) -> bool:
        return bool(self.openrouter_api_key if self.llm_provider == "openrouter" else self.gemini_api_key)

    def ensure_directories(self) -> None:
        for p in (self.data_dir, self.upload_dir, self.chroma_persist_dir):
            p.mkdir(parents=True, exist_ok=True)


def get_settings() -> Settings:
    s = Settings()
    s.ensure_directories()
    return s
