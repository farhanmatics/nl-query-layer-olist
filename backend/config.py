from pydantic_settings import BaseSettings
from datetime import datetime


class Settings(BaseSettings):
    db_url: str = "postgresql://nlq_readonly:changeme@localhost/olist"
    # Admin/superuser connection used ONLY by migrate.py (needs CREATE + CREATEROLE).
    # Never used by the running app, which connects read-only via db_url.
    migration_db_url: str = "postgresql://localhost/olist"
    db_pool_min: int = 2
    db_pool_max: int = 10
    db_statement_timeout: int = 5000

    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen3.5:2b"
    llm_timeout_seconds: int = 90
    llm_max_attempts: int = 2

    # Layer 1 cache: question -> tool call (the LLM translation step only).
    # Safe to cache aggressively; it stores no data and is auto-invalidated when
    # the system prompt changes (the key hashes the prompt).
    llm_cache_enabled: bool = True
    llm_cache_ttl_seconds: int = 86400
    llm_cache_max_entries: int = 1024

    reference_date: str = "2018-08-20"
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    allowed_origins: str = "http://localhost:3000,http://localhost:5173"

    class Config:
        env_file = ".env"
        case_sensitive = False

    @property
    def allowed_origins_list(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]

    @property
    def reference_datetime(self) -> datetime:
        return datetime.strptime(self.reference_date, "%Y-%m-%d")


settings = Settings()
