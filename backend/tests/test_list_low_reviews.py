"""Unit + integration tests for list_low_reviews and the reviews list route."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))


@pytest.mark.asyncio
async def test_list_low_reviews_returns_rows_and_total():
    from functions.registry import get_function

    execute = get_function("list_low_reviews")["execute"]
    out = await execute(score_max=2, date_token="last_month", limit=5)
    assert out.get("error") is None, out.get("error")
    assert "reviews" in out
    reviews = out["reviews"]
    assert isinstance(reviews, list)
    assert len(reviews) <= 5
    assert out.get("total_count", 0) >= len(reviews)
    for r in reviews:
        assert r["review_score"] <= 2
        assert "review_id" in r
        assert "order_id" in r
        assert "review_creation_date" in r


def test_meta_router_list_reviews_maps_to_list_low_reviews():
    from meta_router import resolve_meta_call

    tool, args = resolve_meta_call(
        "list",
        {"entity": "reviews", "date_token": "last_month", "limit": 5},
        "share me the last 5",
    )
    assert tool == "list_low_reviews"
    assert args["limit"] == 5
    assert args["score_max"] == 2
    assert args["date_token"] == "last_month"


def test_entity_for_op_covers_reviews_and_products():
    from meta_router import entity_for_op

    assert entity_for_op("count_low_reviews") == "reviews"
    assert entity_for_op("list_low_reviews") == "reviews"
    assert entity_for_op("top_products") == "products"
    assert entity_for_op("count_orders") == "orders"
    assert entity_for_op("does_not_exist") is None


@pytest.mark.asyncio
async def test_followup_deixis_review_context_rewrites_to_list_reviews():
    """Regression: 'of that share me last five' after count_low_reviews must
    return the list of low reviews, not top_products (the observed bug)."""
    from resolver import clear_session, store_state
    from orchestrator import process_question
    from meta_router import resolve_meta_call

    session_id = "test-deixis-reviews"
    clear_session(session_id)
    # Seed the prior turn as the orchestrator would after a successful count.
    store_state(
        session_id,
        "count_low_reviews",
        {"entity": "reviews", "date_token": "last_month", "score_max": 2},
    )

    # Force the "wrong" LLM tool choice by seeding the translation cache with a
    # rank call — exactly what happened in the observed log. The entity guard
    # must catch this and rewrite it to list_low_reviews.
    from cache import translation_cache, translation_key
    from meta_schemas import get_meta_tool_schemas
    from orchestrator import build_meta_system_prompt

    question = "of that share me last five"
    system_prompt = build_meta_system_prompt(get_meta_tool_schemas())
    translation_cache.set(
        translation_key(question, system_prompt),
        {
            "tool": "rank",
            "args": {"entity": "products", "by": "revenue", "limit": 5},
        },
    )

    try:
        response = await process_question(question, session_id=session_id)
    finally:
        translation_cache.delete(translation_key(question, system_prompt))
        clear_session(session_id)

    assert response.get("error") is None, response.get("error")
    # The guard must land us on the reviews list, not top_products.
    assert response.get("operation") == "list_low_reviews", response
    assert isinstance((response.get("result") or {}).get("reviews"), list)
    assert response.get("context", {}).get("from_operation") == "count_low_reviews"
