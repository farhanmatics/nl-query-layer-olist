from pydantic_settings import BaseSettings
from datetime import datetime
from pathlib import Path

# .env lives at the repo root (one level above backend/). Without this,
# `cd backend && uvicorn main:app` would not see DASHSCOPE_API_KEY etc.
_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"

# The placeholder session secret. The boot path refuses to start in production
# while this is still in use (see main.startup).
DEFAULT_SESSION_SECRET = "dev-only-change-me-in-production-please"


class Settings(BaseSettings):
    db_url: str = "postgresql://nlq_readonly:changeme@localhost/olist"
    # Admin/superuser connection used ONLY by migrate.py (needs CREATE + CREATEROLE).
    # Never used by the running app, which connects read-only via db_url.
    migration_db_url: str = "postgresql://localhost/olist"
    db_pool_min: int = 2
    db_pool_max: int = 10
    db_statement_timeout: int = 5000

    # DashScope cloud LLM (qwen3.7-plus via MultiModalConversation API).
    dashscope_api_key: str = ""
    dashscope_base_url: str = "https://dashscope-intl.aliyuncs.com/api/v1"
    dashscope_model: str = "qwen3.7-plus"
    # Fine-tuned model ID from DashScope Model Studio (set after SFT job completes).
    dashscope_finetune_model: str = ""
    use_finetuned_model: bool = False
    # Thinking mode is incompatible with JSON structured output for tool calls.
    dashscope_enable_thinking: bool = False
    llm_timeout_seconds: int = 30
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

    # Phase 3 — which schema config to load at startup. One of the keys
    # registered in `schemas/__init__.py::_BUILTIN`. Add a new schema by
    # dropping a config module under `schemas/<name>/` and registering
    # the loader — then set SCHEMA_NAME=<name>. The orchestrator's prompt,
    # validation layer, and SQL emitter all read from this config.
    schema_name: str = "olist"

    allowed_origins: str = "http://localhost:3000,http://localhost:5173"

    # Phase 2 audit log: one JSON line per request for trust/verification.
    audit_log_enabled: bool = True
    audit_log_path: str = "logs/audit.jsonl"

    # Hardening: never leak raw exception/DB internals to the client by default.
    # Flip on in dev to surface the real error text in API responses.
    expose_internal_errors: bool = False

    # Hardening: bound request size to reject oversized questions (basic DoS).
    max_question_length: int = 2000

    # Hardening: global row cap — any query returning more than this is rejected
    # at the query layer. Functions that legitimately return many rows (list_orders,
    # top_products) already paginate/limit below this threshold.
    max_result_rows: int = 200

    # Hardening: simple in-memory rate limiter (requests per minute per IP).
    # Set to 0 to disable. Not a replacement for a real reverse-proxy limiter
    # in production, but sufficient for single-tenant local/VPS deployments.
    rate_limit_per_minute: int = 30

    # B0 conversational resolution: ephemeral context TTL (minutes).
    # session_id -> ConversationState entries expire after this long so a stale
    # session can't cause a "carried from 2 hours ago" follow-up to land wrong.
    context_ttl_minutes: int = 30
    context_max_entries: int = 1024

    # B1/B2 — app-state store and auth. SQLite is the dev/single-tenant engine;
    # a Postgres DSN is a drop-in later. The running app connects with both
    # this URL (read-write) and db_url (read-only Olist). Keep them separate.
    app_db_url: str = "sqlite:///app_state.db"

    # Deployment environment. When "production"/"prod", the boot path enforces
    # strict checks (refuses the default session_secret below) and expects
    # cookie_secure=true. Keep "development" for local work.
    environment: str = "development"

    # Secure flag on the auth cookies. MUST be true on any HTTPS/production
    # deploy so the session cookie is never sent over plaintext. This is
    # explicit config rather than inferred from the bind address, because
    # production typically still binds 0.0.0.0 behind a reverse proxy.
    cookie_secure: bool = False

    # B2 — auth secrets. The session secret signs the *session cookie token*
    # (itsdangerous wrapper around the auth_sessions row id). The CSRF token is
    # a separate random value (double-submit), not signed with this. MUST be
    # overridden in production — the boot path refuses the default below.
    session_secret: str = DEFAULT_SESSION_SECRET
    session_ttl_minutes: int = 43200  # 30 days (fixed expiry; not yet rolling)

    # Stricter per-email+IP rate limit on /api/auth/*. Brutes blunt.
    # Format: "max_attempts/window_seconds". 0 means disabled.
    auth_rate_limit: str = "5/900"  # 5 failures per 15 minutes

    # Argon2id cost knobs. Tunable per environment. Defaults are reasonable
    # for production (tens of ms to verify on a modern CPU).
    argon2_time_cost: int = 3
    argon2_memory_cost: int = 65536  # 64 MiB
    argon2_parallelism: int = 1

    # Meta-tool layer (P0): LLM sees ~7 shapes; backend routes to internal functions.
    meta_tools_enabled: bool = False

    # Phase 4 — fenced read-only SQL escape hatch (meta-tool: query).
    sql_escape_enabled: bool = False
    sql_escape_max_limit: int = 100

    # Multi-step planner: LLM emits mode=single|chain with up to planner_max_steps.
    planner_enabled: bool = False
    planner_max_steps: int = 3

    class Config:
        env_file = str(_ENV_FILE)
        case_sensitive = False

    @property
    def is_production(self) -> bool:
        return self.environment.strip().lower() in ("production", "prod")

    @property
    def allowed_origins_list(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]

    @property
    def reference_datetime(self) -> datetime:
        return datetime.strptime(self.reference_date, "%Y-%m-%d")

    @property
    def active_llm_model(self) -> str:
        """Base or fine-tuned DashScope model ID for inference."""
        if self.use_finetuned_model and self.dashscope_finetune_model.strip():
            return self.dashscope_finetune_model.strip()
        return self.dashscope_model


settings = Settings()
