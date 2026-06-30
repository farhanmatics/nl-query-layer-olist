"""Offline unit tests for the rate limiter.

Pure Python — no DB, no LLM, no network. These pin that the RateLimiter
correctly enforces the sliding-window request limit. Run:

    cd backend && ../venv/bin/python -m pytest tests/test_rate_limit.py -v
"""
import sys
from pathlib import Path
import time

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from main import RateLimiter  # noqa: E402


def test_allows_under_limit():
    limiter = RateLimiter(max_requests=5, window_seconds=60)
    for _ in range(5):
        assert limiter.is_allowed("127.0.0.1") is True


def test_blocks_over_limit():
    limiter = RateLimiter(max_requests=3, window_seconds=60)
    assert limiter.is_allowed("127.0.0.1") is True
    assert limiter.is_allowed("127.0.0.1") is True
    assert limiter.is_allowed("127.0.0.1") is True
    assert limiter.is_allowed("127.0.0.1") is False


def test_separate_keys_tracked_independently():
    limiter = RateLimiter(max_requests=2, window_seconds=60)
    assert limiter.is_allowed("ip1") is True
    assert limiter.is_allowed("ip1") is True
    assert limiter.is_allowed("ip1") is False
    assert limiter.is_allowed("ip2") is True
    assert limiter.is_allowed("ip2") is True
    assert limiter.is_allowed("ip2") is False


def test_window_expiry_allows_new_requests():
    limiter = RateLimiter(max_requests=2, window_seconds=1)
    assert limiter.is_allowed("127.0.0.1") is True
    assert limiter.is_allowed("127.0.0.1") is True
    assert limiter.is_allowed("127.0.0.1") is False
    time.sleep(1.1)
    assert limiter.is_allowed("127.0.0.1") is True


def test_disabled_when_max_is_zero():
    limiter = RateLimiter(max_requests=0, window_seconds=60)
    for _ in range(100):
        assert limiter.is_allowed("127.0.0.1") is True


def test_reset_clears_all():
    limiter = RateLimiter(max_requests=2, window_seconds=60)
    assert limiter.is_allowed("127.0.0.1") is True
    assert limiter.is_allowed("127.0.0.1") is True
    assert limiter.is_allowed("127.0.0.1") is False
    limiter.reset()
    assert limiter.is_allowed("127.0.0.1") is True
