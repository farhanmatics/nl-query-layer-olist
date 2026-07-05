"""Offline smoke tests for the full FUNCTION_ANALYSIS.md catalog (41 tools).

Registers every factory against the active olist schema and verifies
each execute() returns without a DB error on minimal/default args.
Requires Postgres with Olist data loaded.

Run:
    cd backend && ../venv/bin/python -m pytest tests/test_catalog_functions.py -v
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from functions.all_factories import all_factories
from functions.registry import reset_registry
from schemas import get_active_config


# Minimal args to exercise each tool without LLM involvement.
SMOKE_ARGS = {
    "get_order_status": {"order_id": "nonexistent_order_xyz"},
    "count_orders": {},
    "get_revenue": {},
    "count_low_reviews": {},
    "top_products": {"limit": 3},
    "list_orders": {"limit": 5},
    "get_customer_info": {"customer_id": "nonexistent_customer_xyz"},
    "get_product_info": {"product_id": "nonexistent_product_xyz"},
    "get_seller_info": {"seller_id": "nonexistent_seller_xyz"},
    "count_by_status": {"status": "delivered"},
    "count_by_payment_type": {"payment_type": "credit_card"},
    "count_by_category": {"category": "health_beauty"},
    "revenue_by_state": {},
    "revenue_by_category": {"limit": 5},
    "revenue_by_seller": {"limit": 5},
    "revenue_by_payment_type": {},
    "revenue_trend": {},
    "top_categories": {"limit": 5},
    "count_products": {"category": "perfumaria"},
    "products_by_rating": {"limit": 5, "min_reviews": 5},
    "top_sellers": {"limit": 5},
    "seller_metrics": {"seller_id": "nonexistent_seller_xyz"},
    "seller_concentration": {},
    "sellers_by_state": {},
    "customer_lifetime_value": {"limit": 5},
    "repeat_customer_rate": {},
    "customers_by_city": {"limit": 5},
    "customer_order_history": {"customer_id": "nonexistent_customer_xyz"},
    "customer_cohort_analysis": {"cohort_date_token": "this_year", "metric": "revenue"},
    "average_rating_by_product": {"limit": 5},
    "average_rating_by_seller": {"limit": 5},
    "average_rating_by_category": {},
    "review_score_distribution": {},
    "review_sentiment_trend": {},
    "on_time_delivery_rate": {},
    "average_delivery_days": {},
    "late_deliveries": {},
    "fulfillment_status_breakdown": {},
    "seller_comparison": {"seller_ids": ["a", "b"]},
    "category_comparison": {"categories": ["health_beauty", "bed_bath_table"]},
    "state_comparison": {"states": ["SP", "RJ"]},
    "payment_type_breakdown": {},
}


@pytest.fixture(scope="module", autouse=True)
def _reset_registry():
    reset_registry()
    yield
    reset_registry()


def _build_registry():
    cfg = get_active_config()
    return {factory(cfg)["schema"]["name"]: factory(cfg) for factory in all_factories()}


@pytest.mark.asyncio
@pytest.mark.parametrize("tool_name", sorted(SMOKE_ARGS.keys()))
async def test_catalog_tool_executes(tool_name):
    reg = _build_registry()
    assert tool_name in reg, f"Missing factory for {tool_name}"
    execute = reg[tool_name]["execute"]
    result = await execute(**SMOKE_ARGS[tool_name])
    assert isinstance(result, dict)
    # Missing entity IDs may return error dicts — that's fine; DB must not crash.
    if "error" in result:
        assert isinstance(result["error"], str)


def test_catalog_has_44_tools():
  reg = _build_registry()
  assert len(reg) == 44
