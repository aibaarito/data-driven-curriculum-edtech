"""Application configuration loaded from environment variables."""
from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql+psycopg://ddc:ddc_dev_pw@127.0.0.1:55433/ddc"
    max_upload_mb: float = 10.0
    max_upload_rows: int = 200_000
    preview_ttl_minutes: int = 60
    cors_origins: str = "http://localhost:3010,http://127.0.0.1:3010"

    # --- Access control -------------------------------------------------------------------------------
    # API_TOKEN set   -> every /api request except /api/health needs "Authorization: Bearer <API_TOKEN>".
    # API_TOKEN unset -> restricted local-demo mode: only loopback clients (127.0.0.1 / ::1) are served.
    api_token: str = ""
    # Destructive reset is OFF unless ENABLE_DATA_RESET=true AND an ADMIN_TOKEN is configured; the request must
    # then carry "X-Admin-Token: <ADMIN_TOKEN>".
    enable_data_reset: bool = False
    admin_token: str = ""

    # LLM (optional). Without a key the app uses deterministic explanations.
    llm_provider: str = "anthropic"  # "anthropic" | "openai_compatible" | "none"
    llm_api_key: str = ""
    llm_model: str = "claude-sonnet-5-5"
    llm_base_url: str = ""  # only for openai_compatible
    llm_timeout_seconds: float = 30.0

    @field_validator("database_url", mode="before")
    @classmethod
    def psycopg_database_url(cls, value: str) -> str:
        # Railway supplies postgresql://. Change only the driver prefix: do not
        # decode/re-encode credentials, IPv6 hosts or connection query parameters.
        for prefix in ("postgresql://", "postgres://"):
            if value.startswith(prefix):
                return "postgresql+psycopg://" + value[len(prefix):]
        return value

    @property
    def llm_enabled(self) -> bool:
        return self.llm_provider != "none" and bool(self.llm_api_key.strip())

    @property
    def max_upload_bytes(self) -> int:
        return int(self.max_upload_mb * 1024 * 1024)

    @property
    def reset_enabled(self) -> bool:
        return self.enable_data_reset and len(self.admin_token.strip()) >= 16


@lru_cache
def get_settings() -> Settings:
    return Settings()
