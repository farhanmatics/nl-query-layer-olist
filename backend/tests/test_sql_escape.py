"""Integration tests for run_readonly_sql (requires Postgres)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from schemas import get_active_config  # noqa: E402
from functions.sql_escape import make_run_readonly_sql  # noqa: E402


@pytest.mark.asyncio
async def test_run_readonly_sql_scalar(monkeypatch):
    monkeypatch.setattr("functions.sql_escape.settings.sql_escape_enabled", True)
    cfg = get_active_config()
    fn = make_run_readonly_sql(cfg)["execute"]
    result = await fn(
        sql=(
            "SELECT COUNT(*) AS n FROM olist_orders_dataset "
            "WHERE order_status = 'delivered'"
        )
    )
    assert "error" not in result
    assert result["row_count"] == 1
    assert result["rows"][0]["n"] > 0


@pytest.mark.asyncio
async def test_run_readonly_sql_rejects_write(monkeypatch):
    monkeypatch.setattr("functions.sql_escape.settings.sql_escape_enabled", True)
    cfg = get_active_config()
    fn = make_run_readonly_sql(cfg)["execute"]
    result = await fn(sql="DELETE FROM olist_orders_dataset")
    assert result.get("error")


@pytest.mark.asyncio
async def test_run_readonly_sql_join(monkeypatch):
    monkeypatch.setattr("functions.sql_escape.settings.sql_escape_enabled", True)
    cfg = get_active_config()
    fn = make_run_readonly_sql(cfg)["execute"]
    result = await fn(
        sql=(
            "SELECT c.customer_state, COUNT(*) AS orders "
            "FROM olist_orders_dataset o "
            "JOIN olist_customers_dataset c ON o.customer_id = c.customer_id "
            "GROUP BY c.customer_state "
            "ORDER BY orders DESC "
            "LIMIT 3"
        )
    )
    assert "error" not in result
    assert len(result["rows"]) <= 3
