"""Stricter per-email+IP rate limiter for /api/auth/* (B2).

Distinct from the global per-IP limiter on /api/* because:
  - brute force is email-scoped (one attacker, many emails vs one email,
    many passwords), and
  - a generous global limit lets an attacker probe a single user.

The key is `(email_lower, ip)` so the same attacker IP can't burn a
victim's budget *and* the same email can't be probed from many IPs without
tripping the limit. The format `max/window` is read from settings.
"""
import logging
import time
from collections import defaultdict
from typing import Optional

from config import settings

logger = logging.getLogger(__name__)


def parse_rate_limit(spec: str) -> tuple:
    """Parse '5/900' → (5, 900). '0' → (0, 0) (disabled)."""
    if spec in ("0", "0/0", ""):
        return (0, 0)
    try:
        max_str, window_str = spec.split("/", 1)
        return (int(max_str), int(window_str))
    except Exception:  # noqa: BLE001
        logger.warning("Invalid auth rate limit spec %r; disabling", spec)
        return (0, 0)


class AuthRateLimiter:
    """In-memory sliding-window limiter keyed on (email, ip)."""

    def __init__(self, max_attempts: int, window_seconds: int):
        self.max = max_attempts
        self.window = window_seconds
        self.attempts: dict[tuple, list[float]] = defaultdict(list)

    def is_allowed(self, email: str, ip: str) -> bool:
        if self.max <= 0:
            return True
        key = (email.lower().strip(), ip)
        now = time.time()
        cutoff = now - self.window
        # Drop expired entries (sliding window).
        self.attempts[key] = [t for t in self.attempts[key] if t > cutoff]
        if len(self.attempts[key]) >= self.max:
            return False
        self.attempts[key].append(now)
        return True

    def reset(self) -> None:
        self.attempts.clear()


_max, _window = parse_rate_limit(settings.auth_rate_limit)
auth_limiter = AuthRateLimiter(max_attempts=_max, window_seconds=_window)
