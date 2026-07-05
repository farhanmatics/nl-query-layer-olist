"""Integration test: planner chain demo with demo fallback (no LLM)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))


@pytest.mark.asyncio
async def test_planner_chain_demo_fallback(monkeypatch):
    monkeypatch.setattr("config.settings.meta_tools_enabled", True)
    monkeypatch.setattr("config.settings.planner_enabled", True)
    monkeypatch.setattr("config.settings.planner_demo_fallback", True)
    monkeypatch.setattr("config.settings.llm_cache_enabled", False)
    monkeypatch.setattr("orchestrator.settings.meta_tools_enabled", True)
    monkeypatch.setattr("orchestrator.settings.planner_enabled", True)
    monkeypatch.setattr("orchestrator.settings.planner_demo_fallback", True)
    monkeypatch.setattr("orchestrator.settings.llm_cache_enabled", False)

    from orchestrator import process_question

    question = (
        "Top category by revenue last year, then best product in that category"
    )
    response = await process_question(question)

    assert response.get("error") is None, response.get("error")
    assert response.get("meta_operation") == "chain"
    assert response.get("operation") == "top_products"
    chain = response.get("chain") or []
    assert len(chain) == 2
    assert chain[0]["operation"] == "top_categories"
    assert chain[1]["operation"] == "top_products"
    assert response.get("plan", {}).get("mode") == "chain"
    products = (response.get("result") or {}).get("products") or []
    assert len(products) >= 1
