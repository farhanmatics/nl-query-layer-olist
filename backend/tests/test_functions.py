"""Direct function unit tests against the real (read-only) database.

These bypass the LLM entirely — they call each function's execute() with known
args and assert on the SQL results. Requires Postgres with the Olist data loaded
(but NOT Ollama). Run:

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

TOTAL_ORDERS = 99441  # known row count of olist_orders_dataset


async def test_count_orders_total():
    result = await count_orders.execute()
    assert "error" not in result
    assert result["count"] == TOTAL_ORDERS


async def test_count_orders_delivered_positive():
    result = await count_orders.execute(status="delivered")
    assert result["count"] > 0
    assert result["count"] <= TOTAL_ORDERS
    assert result["filters"]["status"] == "delivered"


async def test_count_orders_unknown_city_errors():
    result = await count_orders.execute(city="nowhereville_xyz")
    assert "error" in result


async def test_get_revenue_total_positive():
    result = await get_revenue.execute()
    assert "error" not in result
    assert result["revenue"] > 0


async def test_get_revenue_group_by_state():
    result = await get_revenue.execute(group_by="state")
    assert "error" not in result
    assert len(result["breakdown"]) > 0
    assert "state" in result["breakdown"][0]
    assert "revenue" in result["breakdown"][0]


async def test_get_revenue_group_by_category_uses_items():
    result = await get_revenue.execute(group_by="category")
    assert "error" not in result
    assert len(result["breakdown"]) > 0
    assert "category" in result["breakdown"][0]


async def test_get_revenue_invalid_group_by():
    result = await get_revenue.execute(group_by="banana")
    assert "error" in result


async def test_count_low_reviews_positive():
    result = await count_low_reviews.execute(score_max=2)
    assert "error" not in result
    assert result["count"] > 0
    assert result["filters"]["score_max"] == 2


async def test_top_products_count():
    result = await top_products.execute(by="count", limit=5)
    assert "error" not in result
    assert len(result["products"]) == 5
    assert result["by"] == "count"


async def test_top_products_revenue():
    result = await top_products.execute(by="revenue", limit=3)
    assert "error" not in result
    assert len(result["products"]) == 3
    assert isinstance(result["products"][0]["value"], float)


async def test_top_products_invalid_by():
    result = await top_products.execute(by="popularity")
    assert "error" in result


async def test_list_orders_pagination():
    result = await list_orders.execute(limit=10)
    assert "error" not in result
    assert len(result["orders"]) <= 10
    assert result["total_count"] == TOTAL_ORDERS
    assert result["limit"] == 10


async def test_list_orders_limit_clamped():
    result = await list_orders.execute(limit=9999)
    assert "error" not in result
    assert result["limit"] <= 50
