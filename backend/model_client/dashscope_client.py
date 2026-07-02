"""DashScope model client for qwen3.7-plus (MultiModalConversation API).

qwen3.7-plus is a multimodal-series model: even text-only requests must use
MultiModalConversation.call() with content shaped as [{"text": "..."}].

The dashscope SDK is synchronous; all calls run in a threadpool via anyio so
the FastAPI event loop is not blocked.
"""
from __future__ import annotations

import logging
from http import HTTPStatus
from typing import Any, Optional

import anyio
import dashscope
from dashscope import MultiModalConversation

from config import settings

logger = logging.getLogger(__name__)

_configured = False


class DashScopeError(Exception):
    """Raised when DashScope returns a non-success response."""

    def __init__(self, message: str, *, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


def _configure_dashscope() -> None:
    global _configured
    if _configured:
        return
    dashscope.base_http_api_url = settings.dashscope_base_url
    _configured = True


def _text_messages(system: str, user: str) -> list[dict]:
    """Build multimodal-format messages for text-only content."""
    messages: list[dict] = []
    if system:
        messages.append({"role": "system", "content": [{"text": system}]})
    messages.append({"role": "user", "content": [{"text": user}]})
    return messages


def _extract_text(response: Any) -> str:
    """Parse text from a MultiModalConversation response."""
    if response is None:
        raise DashScopeError("Empty response from DashScope")

    status = getattr(response, "status_code", None)
    if status is not None and status != HTTPStatus.OK:
        msg = getattr(response, "message", None) or f"HTTP {status}"
        raise DashScopeError(str(msg), status_code=status)

    try:
        content = response.output.choices[0].message.content
    except (AttributeError, IndexError, KeyError, TypeError) as e:
        raise DashScopeError(f"Unexpected response shape: {e!r}") from e

    if isinstance(content, list):
        for part in content:
            if isinstance(part, dict) and part.get("text"):
                return str(part["text"]).strip()
        raise DashScopeError("No text part in response content")

    if isinstance(content, str):
        return content.strip()

    raise DashScopeError(f"Unsupported content type: {type(content)!r}")


def _sync_call(
    *,
    system: str,
    user: str,
    temperature: float,
    response_format: Optional[dict] = None,
) -> str:
    _configure_dashscope()
    if not settings.dashscope_api_key:
        raise DashScopeError("DASHSCOPE_API_KEY is not configured")

    kwargs: dict[str, Any] = {
        "api_key": settings.dashscope_api_key,
        "model": settings.dashscope_model,
        "messages": _text_messages(system, user),
        "result_format": "message",
        "temperature": temperature,
    }
    if response_format is not None:
        kwargs["response_format"] = response_format
    if not settings.dashscope_enable_thinking:
        kwargs["enable_thinking"] = False

    response = MultiModalConversation.call(**kwargs)
    return _extract_text(response)


class DashScopeClient:
    """Async wrapper around the native dashscope SDK."""

    async def complete_json(
        self, system: str, user: str, *, temperature: float = 0
    ) -> str:
        return await anyio.to_thread.run_sync(
            lambda: _sync_call(
                system=system,
                user=user,
                temperature=temperature,
                response_format={"type": "json_object"},
            )
        )

    async def complete_text(
        self, system: str, user: str, *, temperature: float = 0.3
    ) -> str:
        return await anyio.to_thread.run_sync(
            lambda: _sync_call(
                system=system,
                user=user,
                temperature=temperature,
                response_format=None,
            )
        )

    async def health_check(self) -> bool:
        try:
            text = await self.complete_text(
                "Reply with the single word: ok",
                "health check",
                temperature=0,
            )
            return bool(text)
        except Exception as e:
            logger.error("DashScope health check failed: %s", e)
            return False
