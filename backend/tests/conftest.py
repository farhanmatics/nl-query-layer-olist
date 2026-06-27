"""Shared pytest fixtures.

The asyncpg pool in db.py is a process-global singleton bound to the event loop
that first created it. pytest-asyncio creates a fresh loop per test by default,
which invalidates the pool ("Event loop is closed") on the second test. Using a
single session-scoped event loop keeps the pool valid across the whole run.
"""
import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db import close_pool  # noqa: E402


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.run_until_complete(close_pool())
    loop.close()
