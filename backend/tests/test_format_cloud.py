"""Offline unit tests for cloud answer formatting with deterministic fallback.

Mocks DashScope — no API key or network required.

Run:
    cd backend && ../venv/bin/python -m pytest tests/test_format_cloud.py -v
"""
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from orchestrator import (  # noqa: E402
    _sanitize_result_for_llm,
    format_answer,
)


def test_sanitize_list_orders_caps_rows():
    result = {
        "total_count": 100,
        "offset": 0,
        "orders": [{"order_id": f"o{i}"} for i in range(10)],
        "filters": {"status": "delivered"},
    }
    sanitized = _sanitize_result_for_llm("list_orders", result)
    assert sanitized["total_count"] == 100
    assert sanitized["showing"] == 10
    assert len(sanitized["sample"]) == 3
    assert "filters" not in sanitized


@pytest.mark.asyncio
async def test_format_answer_uses_cloud_on_success():
    with patch(
        "orchestrator.call_llm_for_format",
        new_callable=AsyncMock,
        return_value="Cloud wrote this sentence.",
    ):
        answer = await format_answer(
            "How many orders?",
            "count_orders",
            {"status": "delivered"},
            {"count": 42, "filters": {"status": "delivered"}},
        )
        assert answer == "Cloud wrote this sentence."


@pytest.mark.asyncio
async def test_format_answer_falls_back_on_cloud_failure():
    with patch(
        "orchestrator.call_llm_for_format",
        new_callable=AsyncMock,
        side_effect=RuntimeError("API down"),
    ):
        answer = await format_answer(
            "How many orders?",
            "count_orders",
            {"status": "delivered"},
            {"count": 42},
        )
        assert "42" in answer
        assert "orders" in answer.lower()
