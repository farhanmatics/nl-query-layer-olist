from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import logging
from datetime import datetime

from config import settings
from db import get_pool, close_pool, check_db_health
from orchestrator import process_question

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="NL Query Layer", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class QueryRequest(BaseModel):
    question: str


class QueryResponse(BaseModel):
    operation: str | None = None
    filters: dict | None = None
    result: dict | None = None
    formatted_answer: str | None = None
    source: str | None = None
    error: str | None = None


class HealthResponse(BaseModel):
    db: str
    llm: str
    timestamp: str


@app.on_event("startup")
async def startup():
    logger.info("Starting up...")
    pool = await get_pool()
    logger.info("Database pool initialized")


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
    try:
        logger.info(f"Processing query: {request.question}")
        response = await process_question(request.question)
        return response
    except Exception as e:
        logger.error(f"Query failed: {e}", exc_info=True)
        return QueryResponse(error=f"Query processing failed: {str(e)}")


async def check_llm_health() -> bool:
    try:
        import requests
        from config import settings

        response = requests.get(f"{settings.ollama_base_url}/api/tags", timeout=2)
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
