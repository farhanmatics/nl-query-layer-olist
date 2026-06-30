from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator
import logging
import time
import uuid
from collections import defaultdict
from typing import Optional
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

    @field_validator("question")
    @classmethod
    def _within_max_length(cls, v: str) -> str:
        if len(v) > settings.max_question_length:
            raise ValueError(
                f"question exceeds max length of {settings.max_question_length}"
            )
        return v


class QueryResponse(BaseModel):
    operation: Optional[str] = None
    filters: Optional[dict] = None
    result: Optional[dict] = None
    formatted_answer: Optional[str] = None
    source: Optional[str] = None
    error: Optional[str] = None
    cached: bool = False
    guard: Optional[dict] = None


class HealthResponse(BaseModel):
    db: str
    llm: str
    timestamp: str


@app.on_event("startup")
async def startup():
    logger.info("Starting up...")
    pool = await get_pool()
    logger.info("Database pool initialized")
    await load_known_cities()
    logger.info("Known cities loaded for validation")


@app.on_event("shutdown")
async def shutdown():
    logger.info("Shutting down...")
    await close_pool()
    logger.info("Database pool closed")


@app.get("/api/health", response_model=HealthResponse)
async def health_check():
    db_healthy = await check_db_health()
    llm_healthy = await check_llm_health()

    return HealthResponse(
        db="ok" if db_healthy else "error",
        llm="ok" if llm_healthy else "error",
        timestamp=datetime.utcnow().isoformat(),
    )


@app.post("/api/query", response_model=QueryResponse)
async def query(request: QueryRequest):
    request_id = uuid.uuid4().hex
    start = time.perf_counter()
    try:
        logger.info(f"Processing query: {request.question}")
        from orchestrator import process_question

        response_dict = await process_question(request.question)
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
            build_record(request_id, request.question, response_dict, latency_ms)
        )
    return QueryResponse(**response_dict)


@app.get("/api/cache/stats")
async def cache_stats():
    """Layer 1 (LLM translation) cache stats: hits, misses, hit rate, size."""
    from cache import translation_cache

    return translation_cache.stats()


@app.post("/api/cache/clear")
async def cache_clear():
    """Flush the translation cache (e.g. after changing the prompt manually)."""
    from cache import translation_cache

    translation_cache.clear()
    return {"cleared": True}


async def check_llm_health() -> bool:
    try:
        import httpx

        async with httpx.AsyncClient() as client:
            response = await client.get(f"{settings.ollama_base_url}/api/tags", timeout=2)
            return response.status_code == 200
    except Exception as e:
        logger.error(f"LLM health check failed: {e}")
        return False


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
async def run_eval():
    """Run the eval set and return pass/fail results for CI integration.

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
