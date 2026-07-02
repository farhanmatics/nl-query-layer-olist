"""Tests for fenced SQL validation (Phase 4)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from validation.sql_guard import SqlValidationError, validate_and_prepare_sql  # noqa: E402

ALLOWED = frozenset(
    {
        "olist_orders_dataset",
        "olist_customers_dataset",
        "olist_order_items_dataset",
    }
)


def test_accepts_simple_select_and_injects_limit():
    sql, meta = validate_and_prepare_sql(
        "SELECT order_id FROM olist_orders_dataset",
        ALLOWED,
        max_limit=50,
    )
    assert "LIMIT 50" in sql.upper()
    assert meta["limit_applied"] == 50


def test_rejects_insert():
    with pytest.raises(SqlValidationError, match="SELECT"):
        validate_and_prepare_sql(
            "INSERT INTO olist_orders_dataset VALUES (1)",
            ALLOWED,
        )


def test_rejects_unknown_table():
    with pytest.raises(SqlValidationError, match="not allowlisted"):
        validate_and_prepare_sql(
            "SELECT * FROM secret_table LIMIT 1",
            ALLOWED,
        )


def test_rejects_multiple_statements():
    with pytest.raises(SqlValidationError, match="single"):
        validate_and_prepare_sql(
            "SELECT 1; SELECT 2 FROM olist_orders_dataset",
            ALLOWED,
        )


def test_caps_excessive_limit():
    sql, meta = validate_and_prepare_sql(
        "SELECT order_id FROM olist_orders_dataset LIMIT 500",
        ALLOWED,
        max_limit=100,
    )
    assert "LIMIT 100" in sql.upper()
    assert meta["limit_applied"] == 100


def test_accepts_with_clause():
    sql, _ = validate_and_prepare_sql(
        "WITH x AS (SELECT order_id FROM olist_orders_dataset LIMIT 5) "
        "SELECT * FROM x",
        ALLOWED,
        max_limit=20,
    )
    assert "LIMIT" in sql.upper()
