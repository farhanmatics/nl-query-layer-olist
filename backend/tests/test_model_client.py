"""Offline unit tests for the DashScope model client.

Mocks MultiModalConversation.call — no API key or network required.

Run:
    cd backend && ../venv/bin/python -m pytest tests/test_model_client.py -v
"""
import sys
from http import HTTPStatus
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from model_client.dashscope_client import (  # noqa: E402
    DashScopeClient,
    DashScopeError,
    _extract_text,
    _text_messages,
)


def test_text_messages_shape():
    msgs = _text_messages("system prompt", "user question")
    assert msgs == [
        {"role": "system", "content": [{"text": "system prompt"}]},
        {"role": "user", "content": [{"text": "user question"}]},
    ]


def test_text_messages_omits_empty_system():
    msgs = _text_messages("", "only user")
    assert len(msgs) == 1
    assert msgs[0]["role"] == "user"


def test_extract_text_from_list_content():
    response = SimpleNamespace(
        status_code=HTTPStatus.OK,
        output=SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=[{"text": '{"tool": "count_orders"}'}]
                    )
                )
            ]
        ),
    )
    assert _extract_text(response) == '{"tool": "count_orders"}'


def test_extract_text_raises_on_error_status():
    response = SimpleNamespace(status_code=400, message="bad request")
    with pytest.raises(DashScopeError, match="bad request"):
        _extract_text(response)


@pytest.mark.asyncio
async def test_complete_json_passes_response_format(monkeypatch):
    monkeypatch.setattr(
        "model_client.dashscope_client.settings.dashscope_api_key", "sk-test"
    )
    mock_response = SimpleNamespace(
        status_code=HTTPStatus.OK,
        output=SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=[{"text": '{"tool": "count_orders", "args": {}}'}]
                    )
                )
            ]
        ),
    )
    client = DashScopeClient()
    with patch(
        "model_client.dashscope_client.MultiModalConversation.call",
        return_value=mock_response,
    ) as mock_call:
        text = await client.complete_json("Return JSON.", "How many orders?")
        assert '"tool"' in text
        kwargs = mock_call.call_args.kwargs
        assert kwargs["response_format"] == {"type": "json_object"}
        assert kwargs["enable_thinking"] is False
        assert kwargs["messages"][0]["content"] == [{"text": "Return JSON."}]


@pytest.mark.asyncio
async def test_complete_text_no_response_format(monkeypatch):
    monkeypatch.setattr(
        "model_client.dashscope_client.settings.dashscope_api_key", "sk-test"
    )
    mock_response = SimpleNamespace(
        status_code=HTTPStatus.OK,
        output=SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=[{"text": "There were 42 orders."}])
                )
            ]
        ),
    )
    client = DashScopeClient()
    with patch(
        "model_client.dashscope_client.MultiModalConversation.call",
        return_value=mock_response,
    ) as mock_call:
        text = await client.complete_text("Format answer.", '{"count": 42}')
        assert text == "There were 42 orders."
        kwargs = mock_call.call_args.kwargs
        assert "response_format" not in kwargs


@pytest.mark.asyncio
async def test_health_check_returns_false_on_error():
    client = DashScopeClient()
    with patch.object(client, "complete_text", side_effect=DashScopeError("down")):
        assert await client.health_check() is False
