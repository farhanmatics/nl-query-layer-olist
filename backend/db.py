import asyncpg
from asyncpg.pool import Pool
from typing import Optional
from config import settings
import logging

logger = logging.getLogger(__name__)

_pool: Optional[Pool] = None


class RowCapExceeded(Exception):
    """Raised when a query returns more rows than the global cap."""

    def __init__(self, row_count: int, cap: int):
        self.row_count = row_count
        self.cap = cap
        super().__init__(
            f"Query returned {row_count} rows, exceeding the {cap}-row cap. "
            "Use aggregation or pagination to narrow results."
        )


async def get_pool() -> Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            settings.db_url,
            min_size=settings.db_pool_min,
            max_size=settings.db_pool_max,
            command_timeout=settings.db_statement_timeout / 1000,
        )
        logger.info(f"Created asyncpg pool: {settings.db_pool_min}-{settings.db_pool_max} connections")
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
        logger.info("Closed asyncpg pool")


async def check_db_health() -> bool:
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute("SELECT 1")
        return True
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        return False


async def execute_query(query: str, *args, enforce_cap: bool = True) -> list[dict]:
    """Run a read query and return rows as dicts.

    The global row cap guards *user-facing* result sets (what could flow into the
    model context). Trusted internal bulk reads that legitimately exceed the cap
    — e.g. loading the full city dictionary at startup — pass enforce_cap=False.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(f"SET statement_timeout = {settings.db_statement_timeout}")
        rows = await conn.fetch(query, *args)
        if enforce_cap and len(rows) > settings.max_result_rows:
            raise RowCapExceeded(len(rows), settings.max_result_rows)
        return [dict(row) for row in rows]


async def execute_scalar(query: str, *args):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(f"SET statement_timeout = {settings.db_statement_timeout}")
        result = await conn.fetchval(query, *args)
        return result
