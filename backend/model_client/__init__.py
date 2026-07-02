"""Model client singleton — DashScope for cloud inference."""
from __future__ import annotations

from typing import Optional

from model_client.dashscope_client import DashScopeClient

_client: Optional[DashScopeClient] = None


def get_model_client() -> DashScopeClient:
    global _client
    if _client is None:
        _client = DashScopeClient()
    return _client


def reset_model_client() -> None:
    """Drop the singleton (tests only)."""
    global _client
    _client = None
