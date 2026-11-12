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

    # LLM (optional). Without a configured provider the app uses deterministic explanations.
    # "ollama" is a local model served by Ollama's native API (no key); the others are remote APIs needing a key.
    llm_provider: str = "anthropic"  # "anthropic" | "openai_compatible" | "ollama" | "none"
    llm_api_key: str = ""
    llm_model: str = "claude-sonnet-5-5"
    llm_base_url: str = ""  # openai_compatible: required; ollama: defaults to http://127.0.0.1:11434
    llm_timeout_seconds: float = 30.0  # per model call
    # Whole explanation request (both attempts together); 0 = 2 x llm_timeout_seconds.
    llm_total_timeout_seconds: float = 0.0
    llm_max_concurrency: int = 1  # model calls in flight per backend process; others fall back instead of queuing
    llm_max_output_tokens: int = 2048  # ollama num_predict
    llm_context_tokens: int = 8192  # ollama num_ctx
    llm_max_input_chars: int = 24000  # facts + prompt; larger requests use the deterministic explainer (no truncation)
    llm_keep_alive: str = "10m"  # ollama: how long the model stays loaded after a request

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
        if self.llm_provider == "ollama":
            return bool(self.llm_model.strip())  # local server: no API key involved
        return self.llm_provider != "none" and bool(self.llm_api_key.strip())

    @property
    def llm_total_timeout(self) -> float:
        return self.llm_total_timeout_seconds or 2 * self.llm_timeout_seconds

    @property
    def max_upload_bytes(self) -> int:
        return int(self.max_upload_mb * 1024 * 1024)

    @property
    def reset_enabled(self) -> bool:
        return self.enable_data_reset and len(self.admin_token.strip()) >= 16


@lru_cache
def get_settings() -> Settings:
    return Settings()
