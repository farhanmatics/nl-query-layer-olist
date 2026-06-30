"""Shared pytest fixtures.

The asyncpg pool in db.py is a process-global singleton bound to the event loop
that first created it. pytest-asyncio creates a fresh loop per test by default,
which invalidates the pool ("Event loop is closed") on the second test. Using a
single session-scoped event loop keeps the pool valid across the whole run.

We also expose a `schema` fixture so tests that exercise schema-switching
behavior can do so without the manual `set_active_config + reload + try/
finally` dance. The fixture uses `monkeypatch` (pytest's per-test env
mutator) so the env is restored automatically.
"""
import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import schemas  # noqa: E402
from db import close_pool  # noqa: E402


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.run_until_complete(close_pool())
    loop.close()


@pytest.fixture(autouse=True)
def _default_schema_for_session(monkeypatch):
    """Per-test autouse fixture: ensure the active schema is olist.

    Tests that want a different schema call the `schema` fixture to
    activate it (and monkeypatch.setenv() restores the env after the
    test). The session-level `_active` cache in `schemas` is reset on
    every test so a stale shopify config from a prior test never leaks.

    Without this, tests that exercise only the function SQL path (and
    never call the `schema` fixture) inherit whatever schema the last
    `schema()` call set — usually shopify, which then fails to find
    `shopify_orders` against the live Olist DB.
    """
    monkeypatch.delenv("SCHEMA_NAME", raising=False)
    schemas.set_active_config(None)
    schemas.reload_active_config()
    yield


@pytest.fixture
def schema(monkeypatch):
    """Fixture that activates a named schema for the duration of one test.

    Usage::

        def test_x(schema):
            schema("shopify")
            # ... the active config is now Shopify
            # cleanup is automatic; the env is restored after this test

    The fixture uses pytest's `monkeypatch` (passed in by name) so the
    SCHEMA_NAME env var is restored even if the test raises. After the
    test, the schemas module's cached config is also cleared, so the
    next test starts from a clean slate.
    """
    activated: list[str] = []

    def activate(name: str) -> schemas.SchemaConfig:
        monkeypatch.setenv("SCHEMA_NAME", name)
        schemas.set_active_config(None)
        cfg = schemas.reload_active_config()
        activated.append(name)
        return cfg

    yield activate

    # Cleanup: reset the schemas cache so the next test sees a fresh
    # load. monkeypatch restores the env var automatically.
    schemas.set_active_config(None)
    schemas.reload_active_config()
