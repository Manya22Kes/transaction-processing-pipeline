"""Central application configuration."""

from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",  # silently ignore unknown env vars
    )

    # ── Application
    app_env: str = Field(default="development")
    app_debug: bool = Field(default=False)
    app_host: str = Field(default="0.0.0.0")
    app_port: int = Field(default=8000)

    # ── Database
    database_url: str = Field(
        default="postgresql://txn_user:txn_secret_password@postgres:5432/transactions_db"
    )

    # ── Redis 
    redis_url: str = Field(default="redis://redis:6379/0")

    # ── Celery
    celery_broker_url: str = Field(default="redis://redis:6379/0")
    celery_result_backend: str = Field(default="redis://redis:6379/1")

    # ── Google Gemini
    gemini_api_key: str = Field(default="")
    gemini_model: str = Field(default="gemini-1.5-flash")

    # ── File upload
    upload_dir: Path = Field(default=Path("/app/uploads"))
    max_upload_size_mb: int = Field(default=50)

    # ── LLM retry
    llm_max_retries: int = Field(default=3)
    llm_retry_base_delay: float = Field(default=2.0)

    # ── Computed helpers
    @property
    def max_upload_size_bytes(self) -> int:
        return self.max_upload_size_mb * 1024 * 1024

    @field_validator("upload_dir", mode="before")
    @classmethod
    def ensure_upload_dir(cls, v: str | Path) -> Path:
        path = Path(v)
        path.mkdir(parents=True, exist_ok=True)
        return path


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


# Module-level convenience export
settings = get_settings()
