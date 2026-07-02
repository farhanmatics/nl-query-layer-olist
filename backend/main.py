from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator
import logging
import time
import uuid
from collections import defaultdict
from typing import Optional, Union
from datetime import datetime
from validation.cities import load_known_cities

from config import settings
from db import get_pool, close_pool, check_db_health, RowCapExceeded
from audit import audit_logger, build_record
from errors import client_error

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="NL Query Layer", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class RateLimiter:
    """Simple in-memory sliding-window rate limiter (per IP).

    Not a replacement for a reverse-proxy limiter in production, but sufficient
    for single-tenant local/VPS deployments. Thread-safe enough for asyncio
    (single-threaded event loop) — no locks needed.
    """

    def __init__(self, max_requests: int, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window = window_seconds
        self.requests: dict[str, list[float]] = defaultdict(list)

    def is_allowed(self, key: str) -> bool:
        if self.max_requests <= 0:
            return True
        now = time.time()
        cutoff = now - self.window
        self.requests[key] = [t for t in self.requests[key] if t > cutoff]
        if len(self.requests[key]) >= self.max_requests:
            return False
        self.requests[key].append(now)
        return True

    def reset(self):
        self.requests.clear()


rate_limiter = RateLimiter(settings.rate_limit_per_minute)


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    if settings.rate_limit_per_minute > 0 and request.url.path.startswith("/api/"):
        client_ip = request.client.host if request.client else "unknown"
        if not rate_limiter.is_allowed(client_ip):
            return JSONResponse(
                status_code=429,
                content={
                    "error": f"Rate limit exceeded ({settings.rate_limit_per_minute} requests/minute)"
                },
            )
    return await call_next(request)


class QueryRequest(BaseModel):
    # min_length rejects empty questions; the upper bound is enforced from
    # settings (configurable) so an oversized request is rejected with HTTP 422
    # before it ever reaches the model or DB (basic DoS hardening).
    question: str = Field(..., min_length=1)
    # Optional B0 conversational session id. Absent = single-shot, no context.
    # When present, the backend resolves this turn against the prior turn's
    # state in the same session.
    session_id: Optional[str] = Field(default=None, max_length=128)

    @field_validator("question")
    @classmethod
    def _within_max_length(cls, v: str) -> str:
        if len(v) > settings.max_question_length:
            raise ValueError(
                f"question exceeds max length of {settings.max_question_length}"
            )
        return v


class ClarifyOption(BaseModel):
    label: str
    reply: str


class ClarifyBlock(BaseModel):
    prompt: str
    options: list[Union[str, ClarifyOption]]


class MeasureBlock(BaseModel):
    id: str
    definition: str


class QueryContext(BaseModel):
    inherited: bool = False
    from_operation: Optional[str] = None
    carried: dict = Field(default_factory=dict)
    clarify: Optional[ClarifyBlock] = None


class QueryResponse(BaseModel):
    operation: Optional[str] = None
    meta_operation: Optional[str] = None
    filters: Optional[dict] = None
    result: Optional[dict] = None
    formatted_answer: Optional[str] = None
    source: Optional[str] = None
    measure: Optional[MeasureBlock] = None
    error: Optional[str] = None
    cached: bool = False
    guard: Optional[dict] = None
    context: Optional[QueryContext] = None


class HealthResponse(BaseModel):
    db: str
    llm: str
    meta_tools: str = "disabled"
    sql_escape: str = "disabled"
    timestamp: str


@app.on_event("startup")
async def startup():
    logger.info("Starting up...")

    # Production safety: refuse to boot with the placeholder session secret OR
    # with insecure cookies — both would expose auth sessions. Hard-fail rather
    # than warn, so a misconfigured prod deploy can't silently run unsafe.
    from config import DEFAULT_SESSION_SECRET
    if settings.is_production:
        if settings.session_secret == DEFAULT_SESSION_SECRET:
            raise RuntimeError(
                "SESSION_SECRET is still the default in a production environment. "
                "Set a strong, unique SESSION_SECRET in the environment before boot."
            )
        if not settings.cookie_secure:
            raise RuntimeError(
                "COOKIE_SECURE is false in a production environment — auth cookies "
                "would ride over plaintext HTTP. Set COOKIE_SECURE=true (behind "
                "HTTPS) before boot."
            )
        if not settings.dashscope_api_key.strip():
            raise RuntimeError(
                "DASHSCOPE_API_KEY is missing in a production environment. "
                "Set a valid DashScope API key in the environment before boot."
            )

    pool = await get_pool()
    logger.info("Database pool initialized")

    # Phase 3 — load the active schema config first. Everything else
    # (cities, categories, function registry, prompt) reads from it.
    from schemas import get_active_config
    schema_cfg = get_active_config()
    logger.info(
        f"Active schema: {schema_cfg.name!r} "
        f"({schema_cfg.display_name}) "
        f"tables={len(schema_cfg.tables)} columns={len(schema_cfg.columns)}"
    )

    cities = await load_known_cities()
    logger.info(f"Known cities loaded for validation: {len(cities)}")
    from validation.detectors import set_known_cities
    set_known_cities(cities)

    from validation.categories import load_known_categories
    from validation.detectors import set_known_categories
    categories = await load_known_categories()
    logger.info(f"Known categories loaded for validation: {len(categories)}")
    set_known_categories(categories)

    # App-state DB (B1/B2). Migrations are applied here so the boot path is
    # self-contained: a fresh checkout with no DB applied yet just works.
    from appdb import get_conn, cleanup_expired_sessions
    from migrate_app import MIGRATIONS_DIR
    from config import settings as _settings
    import aiosqlite as _aiosqlite
    import os as _os
    from pathlib import Path as _Path
    # Apply pending migrations against the app-state DB.
    parent = _os.path.dirname(
        _appdb_url_to_path(_settings.app_db_url)
    )
    if parent:
        _os.makedirs(parent, exist_ok=True)
    conn = await get_conn()
    await conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        "  version text PRIMARY KEY,"
        "  applied_at TEXT NOT NULL"
        ")"
    )
    async with conn.execute("SELECT version FROM schema_migrations") as cur:
        applied = {r[0] for r in await cur.fetchall()}
    for f in sorted(_Path(MIGRATIONS_DIR).glob("*.sql")):
        if f.stem in applied:
            continue
        await conn.execute("BEGIN")
        await conn.executescript(f.read_text())
        await conn.execute(
            "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
            (f.stem, datetime.utcnow().isoformat()),
        )
        await conn.commit()
        logger.info(f"App-state migration applied: {f.name}")
    expired = await cleanup_expired_sessions()
    if expired:
        logger.info(f"Cleaned up {expired} expired auth session(s)")


def _appdb_url_to_path(url: str) -> str:
    if url.startswith("sqlite:///"):
        return url[len("sqlite:///"):]
    if url.startswith("sqlite://"):
        return url[len("sqlite://"):]
    return url


@app.on_event("shutdown")
async def shutdown():
    logger.info("Shutting down...")
    await close_pool()
    logger.info("Database pool closed")
    from appdb import close_conn
    await close_conn()


# Auth routes (B2). Cookie session + CSRF, see auth_routes.py for the contract.
from auth_routes import router as auth_router, require_user as _require_user
app.include_router(auth_router)

# Chat session routes (B3). IDOR-safe via require_owned_session.
from session_routes import router as session_router
app.include_router(session_router)


@app.get("/api/health", response_model=HealthResponse)
async def health_check():
    db_healthy = await check_db_health()
    llm_healthy = await check_llm_health()

    return HealthResponse(
        db="ok" if db_healthy else "error",
        llm="ok" if llm_healthy else "error",
        meta_tools="enabled" if settings.meta_tools_enabled else "disabled",
        sql_escape="enabled" if settings.sql_escape_enabled else "disabled",
        timestamp=datetime.utcnow().isoformat(),
    )


@app.post("/api/query", response_model=QueryResponse)
async def query(request: Request, body: QueryRequest):
    request_id = uuid.uuid4().hex
    start = time.perf_counter()
    # B-X: capture identity for the audit log if the caller is authed.
    # `require_user` raises 401 if the cookie is missing/invalid, which is
    # the wrong default for /api/query (it should still work anon while
    # B2 is rolling out). Use the resolve dependency instead.
    from auth_routes import _resolve_session
    user = await _resolve_session(request.cookies.get("nlq_session"))
    user_id = user["id"] if user else None

    # B3: when the caller is authed AND a session_id is provided, verify
    # ownership before we hand it to the orchestrator. A cross-user
    # session_id is treated as "doesn't exist" — never a leak. When user_id
    # is None, fall through: the session_id is treated as a client-minted
    # UUID (F2-early mode) and the orchestrator uses its B0 in-memory store.
    cross_user = False
    if user_id and body.session_id:
        import appdb
        cross_user = not await appdb.session_belongs_to_user(body.session_id, user_id)

    if cross_user:
        # Rejected IDOR attempt. Skip the orchestrator entirely (no rows
        # written) but still fall through to the audit tail below — a
        # cross-user session id is exactly what belongs in the security log.
        logger.warning(f"Cross-user session_id rejected for user {user_id}")
        response_dict = {"error": "Session not found"}
    else:
        try:
            logger.info(f"Processing query: {body.question}")
            from orchestrator import process_question

            response_dict = await process_question(
                body.question, body.session_id, user_id=user_id
            )
        except RowCapExceeded as e:
            logger.warning(f"Row cap exceeded: {e}")
            response_dict = {
                "error": (
                    f"Query returned too many rows ({e.row_count}). "
                    "Please narrow your filters or use pagination."
                )
            }
        except Exception as e:
            logger.error(f"Query failed: {e}", exc_info=True)
            response_dict = {"error": client_error(e, "The query could not be processed.")}

    latency_ms = int((time.perf_counter() - start) * 1000)
    if settings.audit_log_enabled:
        audit_logger.log(
            build_record(
                request_id,
                body.question,
                response_dict,
                latency_ms,
                user_id=user_id,
                session_id=body.session_id,
            )
        )
    return QueryResponse(**response_dict)


@app.get("/api/cache/stats")
async def cache_stats():
    """Layer 1 (LLM translation) cache stats: hits, misses, hit rate, size."""
    from cache import translation_cache

    return translation_cache.stats()


@app.post("/api/cache/clear")
async def cache_clear(_user: dict = Depends(_require_user)):
    """Flush the translation cache (e.g. after changing the prompt manually).

    Mutating + global-impact, so it requires an authenticated user.
    """
    from cache import translation_cache

    translation_cache.clear()
    return {"cleared": True}


async def check_llm_health() -> bool:
    from model_client import get_model_client

    return await get_model_client().health_check()


class EvalCaseResult(BaseModel):
    id: str
    question: str
    passed: bool
    reason: str
    expected_operation: Optional[str] = None
    actual_operation: Optional[str] = None


class EvalResponse(BaseModel):
    total: int
    passed: int
    failed: int
    pass_rate: float
    threshold: float
    threshold_met: bool
    results: list[EvalCaseResult]


@app.post("/api/eval", response_model=EvalResponse)
async def run_eval(_user: dict = Depends(_require_user)):
    """Run the eval set and return pass/fail results for CI integration.

    Heavy (many LLM calls) and so gated behind an authenticated user; CI must
    authenticate (or call the eval harness directly) rather than hit this open.

    Loads eval_set.json, runs each case through the orchestrator, and scores
    tool-selection + filter faithfulness. Returns HTTP 200 regardless of pass
    rate — the caller (CI) decides whether to fail based on `threshold_met`.
    """
    import json
    from pathlib import Path
    from orchestrator import process_question

    eval_file = Path(__file__).parent / "tests" / "eval_set.json"
    if not eval_file.exists():
        raise HTTPException(status_code=404, detail="eval_set.json not found")

    data = json.loads(eval_file.read_text())
    cases = data.get("cases", [])
    threshold = 0.85

    results: list[EvalCaseResult] = []

    for case in cases:
        case_id = case.get("id", "unknown")
        question = case.get("question", "")
        expected_op = case.get("expected_operation")
        expected_filters = case.get("expected_filters", {})
        expects_error = case.get("expected_error", False)

        try:
            response = await process_question(question)
        except Exception as e:
            results.append(
                EvalCaseResult(
                    id=case_id,
                    question=question,
                    passed=False,
                    reason=f"exception: {e!r}",
                    expected_operation=expected_op,
                    actual_operation=None,
                )
            )
            continue

        actual_op = response.get("operation")
        actual_filters = response.get("filters") or {}
        error = response.get("error")

        if expects_error:
            if not error:
                passed = False
                reason = f"expected error, got operation={actual_op}"
            elif expected_op and actual_op and actual_op != expected_op:
                passed = False
                reason = f"errored but routed to {actual_op!r}, expected {expected_op!r}"
            else:
                passed = True
                reason = "error as expected"
        elif error:
            passed = False
            reason = f"unexpected error: {error}"
        elif actual_op != expected_op:
            passed = False
            reason = f"operation {actual_op!r} != expected {expected_op!r}"
        elif not _filters_match(expected_filters, actual_filters):
            passed = False
            reason = f"filters {actual_filters} !⊇ {expected_filters}"
        else:
            passed = True
            reason = "ok"

        results.append(
            EvalCaseResult(
                id=case_id,
                question=question,
                passed=passed,
                reason=reason,
                expected_operation=expected_op,
                actual_operation=actual_op,
            )
        )

    total = len(results)
    passed_count = sum(1 for r in results if r.passed)
    failed_count = total - passed_count
    pass_rate = passed_count / total if total else 0.0

    return EvalResponse(
        total=total,
        passed=passed_count,
        failed=failed_count,
        pass_rate=round(pass_rate, 4),
        threshold=threshold,
        threshold_met=pass_rate >= threshold,
        results=results,
    )


def _filters_match(expected: dict, actual: dict) -> bool:
    """Check if actual filters contain all expected filters (with '*' wildcard support)."""
    actual = actual or {}
    for key, value in expected.items():
        if value == "*":
            if key not in actual or actual[key] in (None, "", [], {}):
                return False
        else:
            if actual.get(key) != value:
                return False
    return True


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=True,
    )
