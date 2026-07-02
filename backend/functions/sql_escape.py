"""Phase 4 — fenced read-only SQL execution."""
import logging
from typing import Optional

from config import settings
from db import execute_query
from errors import client_error
from schemas.base import SchemaConfig
from validation.sql_guard import SqlValidationError, validate_and_prepare_sql

logger = logging.getLogger(__name__)

RUN_READONLY_SQL_SCHEMA = {
    "name": "run_readonly_sql",
    "description": (
        "Execute a validated read-only SELECT against allowlisted tables. "
        "Used only via the meta 'query' escape hatch after backend validation."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "sql": {
                "type": "string",
                "description": "A single SELECT statement (LIMIT enforced by backend)",
            },
        },
        "required": ["sql"],
    },
}


def make_run_readonly_sql(cfg: SchemaConfig) -> dict:
    allowed = frozenset(cfg.tables.values())

    async def execute(sql: str) -> dict:
        if not settings.sql_escape_enabled:
            return {
                "error": "SQL escape hatch is disabled on this server.",
                "filters": {},
            }
        try:
            prepared, meta = validate_and_prepare_sql(
                sql,
                allowed,
                max_limit=settings.sql_escape_max_limit,
            )
        except SqlValidationError as e:
            logger.warning(f"SQL validation rejected query: {e}")
            return {"error": str(e), "filters": {"sql": sql}}

        filters = dict(meta)
        try:
            rows = await execute_query(prepared, enforce_cap=True)
            columns = list(rows[0].keys()) if rows else []
            return {
                "rows": rows,
                "columns": columns,
                "row_count": len(rows),
                "filters": filters,
            }
        except Exception as e:
            logger.error(f"run_readonly_sql failed: {e}", exc_info=True)
            return {
                "error": client_error(e, "The SQL query could not be executed."),
                "filters": filters,
            }

    return {"schema": RUN_READONLY_SQL_SCHEMA, "execute": execute}
