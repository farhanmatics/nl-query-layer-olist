from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator
import logging
import time
import uuid
from typing import Optional
from datetime import datetime
from validation.cities import load_known_cities

from config import settings
from db import get_pool, close_pool, check_db_health
from audit import audit_logger, build_record
from errors import client_error

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="NL Query Layer", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=True,
    )
