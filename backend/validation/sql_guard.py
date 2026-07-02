"""Fenced read-only SQL validation (Phase 4 escape hatch).

The model may propose a SELECT; the backend validates structure, allowlisted
tables, and mandatory LIMIT before execution. Write/DDL paths are rejected.
"""
from __future__ import annotations

import re
from typing import FrozenSet, Tuple

# Word-boundaried forbidden tokens (write/DDL/admin).
_FORBIDDEN = re.compile(
    r"\b("
    r"insert|update|delete|merge|drop|alter|create|truncate|grant|revoke|"
    r"copy|execute|prepare|deallocate|listen|notify|"
    r"vacuum|analyze|refresh|comment|reindex|"
    r"pg_sleep|pg_read_file|lo_import|lo_export|dblink"
    r")\b",
    re.IGNORECASE,
)

_SET_ROLE = re.compile(r"\bset\s+(role|session\s+authorization)\b", re.IGNORECASE)

_LINE_COMMENT = re.compile(r"--[^\n]*")
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)

_TABLE_REF = re.compile(
    r"\b(?:from|join)\s+"
    r"(?:only\s+)?"
    r"(?:lateral\s+)?"
    r"(?:(?:public|pg_catalog)\.)?"
    r'(?:"([a-z_][a-z0-9_$]*)"|([a-z_][a-z0-9_]*))',
    re.IGNORECASE,
)

_LIMIT_CLAUSE = re.compile(r"\blimit\s+(\d+)", re.IGNORECASE)

_CTE_NAME = re.compile(
    r"\b(?:with(?:\s+recursive)?|,)\s*([a-z_][a-z0-9_]*)\s+as\s*\(",
    re.IGNORECASE,
)


def _extract_cte_names(sql: str) -> set[str]:
    return {m.group(1).lower() for m in _CTE_NAME.finditer(sql)}


class SqlValidationError(ValueError):
    """Raised when generated SQL fails the fence checks."""


def _strip_comments(sql: str) -> str:
    text = _BLOCK_COMMENT.sub(" ", sql)
    return _LINE_COMMENT.sub(" ", text)


def _normalize_sql(sql: str) -> str:
    text = (sql or "").strip()
    if not text:
        raise SqlValidationError("SQL is empty")
    text = _strip_comments(text).strip()
    while text.endswith(";"):
        text = text[:-1].strip()
    if ";" in text:
        raise SqlValidationError("Only a single SQL statement is allowed")
    return " ".join(text.split())


def _extract_tables(sql: str) -> set[str]:
    tables: set[str] = set()
    for m in _TABLE_REF.finditer(sql):
        name = (m.group(1) or m.group(2) or "").lower()
        if name and not name.startswith("("):
            tables.add(name)
    return tables


def _ensure_select_only(sql: str) -> None:
    head = sql.lstrip()[:20].lower()
    if not (head.startswith("select") or head.startswith("with")):
        raise SqlValidationError("Only SELECT queries are allowed")
    if _FORBIDDEN.search(sql):
        raise SqlValidationError("Query contains forbidden keywords")
    if _SET_ROLE.search(sql):
        raise SqlValidationError("SET ROLE / session changes are not allowed")
    blocked = {"information_schema", "pg_catalog", "pg_toast"}
    for t in _extract_tables(sql):
        if t in blocked or t.startswith("pg_"):
            raise SqlValidationError(f"System catalog access is not allowed ({t})")


def _enforce_limit(sql: str, max_limit: int) -> Tuple[str, int]:
    matches = list(_LIMIT_CLAUSE.finditer(sql))
    if not matches:
        capped = max_limit
        return f"{sql} LIMIT {capped}", capped
    last = matches[-1]
    try:
        requested = int(last.group(1))
    except ValueError as e:
        raise SqlValidationError("Invalid LIMIT value") from e
    if requested < 1:
        raise SqlValidationError("LIMIT must be at least 1")
    capped = min(requested, max_limit)
    if capped != requested:
        start, end = last.span()
        sql = sql[:start] + f"LIMIT {capped}" + sql[end:]
    return sql, capped


def validate_and_prepare_sql(
    sql: str,
    allowed_tables: FrozenSet[str],
    max_limit: int = 100,
) -> Tuple[str, dict]:
    """Validate model-proposed SQL and return (executable_sql, audit_metadata).

    Raises SqlValidationError on any fence violation.
    """
    if max_limit < 1:
        raise SqlValidationError("max_limit must be positive")

    normalized = _normalize_sql(sql)
    _ensure_select_only(normalized)

    referenced = _extract_tables(normalized) - _extract_cte_names(normalized)
    if not referenced:
        raise SqlValidationError("Query must reference at least one allowlisted table")

    allowed_lower = {t.lower() for t in allowed_tables}
    unknown = sorted(t for t in referenced if t not in allowed_lower)
    if unknown:
        raise SqlValidationError(
            f"Table(s) not allowlisted: {', '.join(unknown)}"
        )

    prepared, limit = _enforce_limit(normalized, max_limit)
    return prepared, {"sql": sql.strip(), "limit_applied": limit}
