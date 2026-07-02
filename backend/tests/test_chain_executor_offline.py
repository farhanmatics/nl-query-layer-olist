"""Offline tests for chain_executor bindings and plan execution."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

_BACKEND = Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from chain_executor import resolve_bindings, execute_plan  # noqa: E402


def test_resolve_bindings_category_from_prior_step():
    step_results = [{"categories": [{"category": "perfumaria", "value": 1000}]}]
    args = resolve_bindings(
        {"entity": "products", "category": "$step0.category", "limit": 1},
        step_results,
    )
    assert args["category"] == "perfumaria"


@pytest.mark.asyncio
async def test_execute_single_step_plan():
    from meta_router import resolve_meta_call
    from orchestrator import apply_filter_guard, dispatch_function

    plan = {
        "mode": "single",
        "steps": [
            {
                "kind": "meta",
                "tool": "count",
                "args": {
                    "entity": "orders",
                    "status": "delivered",
                    "date_token": "last_month",
                },
            }
        ],
    }
    mock_dispatch = AsyncMock(
        return_value={"count": 42, "filters": {"status": "delivered"}}
    )
    out = await execute_plan(
        plan,
        question="How many delivered orders last month?",
        resolve_meta_call=resolve_meta_call,
        dispatch_function=mock_dispatch,
        apply_filter_guard=apply_filter_guard,
    )
    assert out["final_operation"] in ("count_orders", "count_by_status")
    assert out["final_result"]["count"] == 42
    mock_dispatch.assert_awaited_once()


def test_chain_eval_set_loads():
    path = _BACKEND / "tests" / "chain_eval_set.json"
    data = json.loads(path.read_text())
    assert len(data["cases"]) >= 2
    for case in data["cases"]:
        assert "expected_plan" in case
        assert case["expected_plan"]["steps"]
