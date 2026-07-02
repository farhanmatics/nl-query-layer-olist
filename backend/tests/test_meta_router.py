"""Tests for meta_router (meta-tool → internal function mapping)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from meta_router import (  # noqa: E402
    apply_entity_intent,
    apply_rank_defaults,
    apply_sum_defaults,
    inherit_meta_filters,
    measure_for_tool,
    resolve_meta_call,
)


def test_route_count_products_perfumaria():
    tool, args = resolve_meta_call(
        "count",
        {"entity": "products", "category": "perfumaria"},
        "how many products in perfumaria",
    )
    assert tool == "count_products"
    assert args == {"category": "perfumaria"}


def test_route_count_by_category_orders():
    tool, args = resolve_meta_call(
        "count",
        {"entity": "orders", "category": "perfumaria", "date_token": "last_year"},
        "how many perfumaria orders last year",
    )
    assert tool == "count_by_category"
    assert args["category"] == "perfumaria"
    assert args["date_token"] == "last_year"


def test_entity_override_catalog_phrase():
    args = apply_entity_intent(
        "how many products do we have in perfumaria",
        {"entity": "orders", "category": "perfumaria"},
    )
    assert args["entity"] == "products"


def test_route_lookup_order():
    tool, args = resolve_meta_call(
        "lookup",
        {"entity": "order", "id": "abc123"},
    )
    assert tool == "get_order_status"
    assert args == {"order_id": "abc123"}


def test_measure_for_top_products():
    m = measure_for_tool("top_products")
    assert m["id"] == "product_ranking"


def test_route_rank_best_product_perfumaria():
    tool, args = resolve_meta_call(
        "rank",
        {
            "entity": "products",
            "category": "perfumaria",
            "date_token": "last_year",
            "by": "revenue",
            "limit": 1,
        },
        "best product in perfumaria last year",
    )
    assert tool == "top_products"
    assert args["category"] == "perfumaria"
    assert args["date_token"] == "last_year"
    assert args["limit"] == 1
    assert args["by"] == "revenue"


def test_rank_defaults_best_sets_limit_one():
    args = apply_rank_defaults(
        "which one is the best product for last year",
        {"entity": "products", "date_token": "last_year"},
    )
    assert args["limit"] == 1
    assert args["by"] == "revenue"


def test_inherit_category_count_to_rank():
    prior = {
        "operation": "count",
        "args": {"entity": "products", "category": "perfumaria"},
    }
    cand = inherit_meta_filters(
        prior,
        {"tool": "rank", "args": {"date_token": "last_year", "by": "revenue", "limit": 1}},
    )
    assert cand["args"]["category"] == "perfumaria"
    assert cand["args"]["entity"] == "products"


def test_measure_for_count_products():
    m = measure_for_tool("count_products")
    assert m["id"] == "product_count"
    assert "catalog" in m["definition"].lower()


def test_route_sum_revenue_total():
    tool, args = resolve_meta_call(
        "sum",
        {"measure": "revenue", "date_token": "last_month"},
        "total revenue last month",
    )
    assert tool == "get_revenue"
    assert args["date_token"] == "last_month"


def test_route_sum_revenue_by_state():
    tool, args = resolve_meta_call(
        "sum",
        {"measure": "revenue", "group_by": "state", "date_token": "this_year"},
        "revenue by state this year",
    )
    assert tool == "revenue_by_state"


def test_route_list_orders():
    tool, args = resolve_meta_call(
        "list",
        {"entity": "orders", "city": "sao paulo", "status": "delivered"},
    )
    assert tool == "list_orders"
    assert args["city"] == "sao paulo"


def test_route_breakdown_order_status():
    tool, args = resolve_meta_call(
        "breakdown",
        {"dimension": "order_status"},
        "break down orders by status",
    )
    assert tool == "fulfillment_status_breakdown"


def test_route_compare_states():
    tool, args = resolve_meta_call(
        "compare",
        {"dimension": "state", "values": ["SP", "RJ"]},
    )
    assert tool == "state_comparison"
    assert args["states"] == ["SP", "RJ"]


def test_sum_defaults_detects_revenue():
    args = apply_sum_defaults("what was our total revenue last year", {})
    assert args["measure"] == "revenue"


def test_route_query_sql_escape(monkeypatch):
    import config

    monkeypatch.setattr(config.settings, "sql_escape_enabled", True)
    tool, args = resolve_meta_call(
        "query",
        {"sql": "SELECT order_id FROM olist_orders_dataset LIMIT 5"},
        "",
    )
    assert tool == "run_readonly_sql"
    assert "sql" in args
