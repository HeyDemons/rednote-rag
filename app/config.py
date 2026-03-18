"""
Application configuration.
"""

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Runtime settings loaded from environment variables."""

    app_name: str = Field(default="rednote-rag")
    app_host: str = Field(default="0.0.0.0")
    app_port: int = Field(default=8000)
    debug: bool = Field(default=True)
    sql_echo: bool = Field(default=False)

    openai_api_key: str = Field(default="")
    openai_base_url: str = Field(default="https://api.openai.com/v1")
    llm_model: str = Field(default="gpt-4.1-mini")
    embedding_model: str = Field(default="text-embedding-3-small")
    embedding_dimension: int = Field(default=256)
    rag_chunk_size: int = Field(default=600)
    rag_chunk_overlap: int = Field(default=100)
    allow_local_embed_fallback: bool = Field(default=False)
    ocr_enabled: bool = Field(default=False)
    ocr_model: str = Field(default="")
    ocr_max_images_per_note: int = Field(default=6)
    ocr_timeout_seconds: int = Field(default=30)

    database_url: str = Field(default="sqlite+aiosqlite:///./data/rednote_rag.db")
    chroma_persist_directory: str = Field(default="./data/chroma_db")

    xhs_cookie_source: str = Field(default="auto")
    xhs_request_delay: float = Field(default=1.0)
    xhs_force_refresh_on_login: bool = Field(default=True)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()


def ensure_directories() -> None:
    """Ensure local runtime directories exist."""
    for rel_path in ("data", "logs", settings.chroma_persist_directory):
        path = BASE_DIR / rel_path if not rel_path.startswith("./") else BASE_DIR / rel_path[2:]
        path.mkdir(parents=True, exist_ok=True)
