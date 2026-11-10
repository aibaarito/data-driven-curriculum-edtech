"""Application configuration loaded from environment variables."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql+psycopg://ddc:ddc_dev_pw@127.0.0.1:55433/ddc"
    max_upload_mb: float = 10.0
    max_upload_rows: int = 200_000
    cors_origins: str = "http://localhost:3010,http://127.0.0.1:3010"

    # LLM (optional). Without a key the app uses deterministic explanations.
    llm_provider: str = "anthropic"  # "anthropic" | "openai_compatible" | "none"
    llm_api_key: str = ""
    llm_model: str = "claude-sonnet-5-5"
    llm_base_url: str = ""  # only for openai_compatible
    llm_timeout_seconds: float = 30.0

    @property
    def llm_enabled(self) -> bool:
        return self.llm_provider != "none" and bool(self.llm_api_key.strip())


@lru_cache
def get_settings() -> Settings:
    return Settings()
