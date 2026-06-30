"""Direct function unit tests against the real (read-only) database.

These bypass the LLM entirely — they call each function's execute() with known
args and assert on the SQL results. Requires Postgres with the Olist data loaded
(but NOT Ollama).

Phase 3 note: functions are now schema-aware factories. The test loads
the active SchemaConfig (defaulting to olist) and asks each factory to
build an execute() bound to that config. Run:

    cd backend && ../venv/bin/python -m pytest tests/test_functions.py -v
"""
import sys
from pathlib import Path

# Allow running from the backend/ directory.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from functions import (  # noqa: E402
    count_orders,
    get_revenue,
    count_low_reviews,
    top_products,
    list_orders,
)
from schemas import get_active_config  # noqa: E402

TOTAL_ORDERS = 99441  # known row count of olist_orders_dataset


def _execute(module):
    """Resolve a function module's factory against the active schema
    config and return the bound execute coroutine."""
    cfg = get_active_config()
    entry = module.make_count_orders(cfg) if module is count_orders else \
            module.make_get_revenue(cfg) if module is get_revenue else \
            module.make_count_low_reviews(cfg) if module is count_low_reviews else \
            module.make_top_products(cfg) if module is top_products else \
            module.make_list_orders(cfg)
    return entry["execute"]


async def test_count_orders_total():
    execute = _execute(count_orders)
    result = await execute()
    assert "error" not in result
    assert result["count"] == TOTAL_ORDERS


async def test_count_orders_delivered_positive():
    execute = _execute(count_orders)
    result = await execute(status="delivered")
    assert result["count"] > 0
    assert result["count"] <= TOTAL_ORDERS
    assert result["filters"]["status"] == "delivered"


async def test_count_orders_unknown_city_errors():
    execute = _execute(count_orders)
    result = await execute(city="nowhereville_xyz")
    assert "error" in result


async def test_get_revenue_total_positive():
    execute = _execute(get_revenue)
    result = await execute()
    assert "error" not in result
    assert result["revenue"] > 0


async def test_get_revenue_group_by_state():
    execute = _execute(get_revenue)
    result = await execute(group_by="state")
    assert "error" not in result
    assert len(result["breakdown"]) > 0
    assert "state" in result["breakdown"][0]
    assert "revenue" in result["breakdown"][0]


async def test_get_revenue_state_filter():
    """Regression: col_state is extracted as a string at factory time;
    using .column on it raises AttributeError."""
    execute = _execute(get_revenue)
    result = await execute(state="SP")
    assert "error" not in result
    assert result["revenue"] > 0
    assert result["filters"]["state"] == "SP"


async def test_get_revenue_city_filter():
    execute = _execute(get_revenue)
    result = await execute(city="sao paulo")
    assert "error" not in result
    assert result["revenue"] > 0
    assert result["filters"]["city"] == "sao paulo"


async def test_get_revenue_group_by_category_uses_items():
    execute = _execute(get_revenue)
    result = await execute(group_by="category")
    assert "error" not in result
    assert len(result["breakdown"]) > 0
    assert "category" in result["breakdown"][0]


async def test_get_revenue_invalid_group_by():
    execute = _execute(get_revenue)
    result = await execute(group_by="banana")
    assert "error" in result


async def test_count_low_reviews_positive():
    execute = _execute(count_low_reviews)
    result = await execute(score_max=2)
    assert "error" not in result
    assert result["count"] > 0
    assert result["filters"]["score_max"] == 2


async def test_top_products_count():
    execute = _execute(top_products)
    result = await execute(by="count", limit=5)
    assert "error" not in result
    assert len(result["products"]) == 5
    assert result["by"] == "count"


async def test_top_products_revenue():
    execute = _execute(top_products)
    result = await execute(by="revenue", limit=3)
    assert "error" not in result
    assert len(result["products"]) == 3
    assert isinstance(result["products"][0]["value"], float)


async def test_top_products_invalid_by():
    execute = _execute(top_products)
    result = await execute(by="popularity")
    assert "error" in result


async def test_list_orders_pagination():
    execute = _execute(list_orders)
    result = await execute(limit=10)
    assert "error" not in result
    assert len(result["orders"]) <= 10
    assert result["total_count"] == TOTAL_ORDERS
    assert result["limit"] == 10


async def test_list_orders_limit_clamped():
    execute = _execute(list_orders)
    result = await execute(limit=9999)
    assert "error" not in result
    assert result["limit"] <= 50
