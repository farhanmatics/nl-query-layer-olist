"""Tests for MCP tool helpers."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from mcp_server.tools import eval_dataset_summary  # noqa: E402
from planner_schemas import lookup_demo_plan  # noqa: E402


def test_eval_dataset_summary_counts_cases():
    summary = eval_dataset_summary()
    assert summary["total_cases"] >= 50
    assert "eval_set.json" in summary["datasets"]
    assert summary["pass_threshold"] == 0.85


def test_lookup_demo_plan_chain_question(monkeypatch):
    monkeypatch.setattr("config.settings.planner_demo_fallback", True)
    monkeypatch.setattr("planner_schemas.settings.planner_demo_fallback", True)
    plan = lookup_demo_plan(
        "Top category by revenue last year, then best product in that category"
    )
    assert plan is not None
    assert plan["mode"] == "chain"
    assert len(plan["steps"]) == 2
    assert plan["steps"][1]["args"]["category"] == "$step0.category"


@pytest.mark.asyncio
async def test_count_orders_tool_smoke():
    from mcp_server.tools import count_orders_tool

    result = await count_orders_tool(status="delivered", date_token="last_month")
    assert result.get("error") is None
    assert result["operation"] in ("count_orders", "count_by_status")
    assert "count" in (result.get("result") or {})
