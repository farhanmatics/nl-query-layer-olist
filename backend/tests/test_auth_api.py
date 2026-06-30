"""End-to-end auth flow tests via FastAPI TestClient.

Exercises the HTTP layer (cookie setting, 401/403 status codes, CSRF header
enforcement) without requiring a live Olist database. Uses an in-memory
SQLite app-state DB so each test is isolated.

Run:
    cd backend && ../venv/bin/python -m pytest tests/test_auth_api.py -v
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

# Configure the app BEFORE importing main so the app-state DB URL is set.
import os  # noqa: E402

# Use an in-memory SQLite for tests; each connection sees its own DB so
# the singleton pool would normally get a fresh DB. Use a temp file so the
# connection is shared.
import tempfile  # noqa: E402

_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["APP_DB_URL"] = f"sqlite:///{_tmp.name}"
os.environ["SESSION_SECRET"] = "test-secret-please-ignore"
os.environ["AUTH_RATE_LIMIT"] = "3/60"  # tighter for tests

# Reload config to pick up the env vars.
import importlib  # noqa: E402
import config as _config  # noqa: E402
importlib.reload(_config)


# Now import the rest of the app (config is now test-aware).
import appdb  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture
def client():
    # Per-test temp DB so tests don't collide on email uniqueness.
    import importlib as _il
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    os.environ["APP_DB_URL"] = f"sqlite:///{tmp.name}"
    os.environ["SESSION_SECRET"] = "test-secret-please-ignore"
    os.environ["AUTH_RATE_LIMIT"] = "3/60"
    _il.reload(_config)
    _il.reload(appdb)
    import auth_rate_limit as _arl
    _il.reload(_arl)  # parse auth_rate_limit re-reads settings
    import auth_routes as _ar
    _il.reload(_ar)  # so it picks up the new auth_limiter instance
    import main as _main
    _il.reload(_main)
    # Reset the auth rate limiter between tests (it holds global state).
    _arl.auth_limiter.reset()
    import asyncio as _aio
    from migrate_app import cmd_up
    _aio.run(cmd_up())
    with TestClient(_main.app) as c:
        yield c
    try:
        os.unlink(tmp.name)
    except Exception:
        pass


def _register_and_get_csrf(client: TestClient, email="alice@example.com", password="correct horse battery staple"):
    """Helper: register a user and return the CSRF token from the cookie jar."""
    # Get a CSRF token first (the dev-seed endpoint sets the cookie).
    r = client.get("/api/auth/csrf")
    assert r.status_code == 200, r.text
    csrf = client.cookies.get("nlq_csrf")
    r = client.post(
        "/api/auth/register",
        json={"email": email, "password": password},
        headers={"X-CSRF-Token": csrf},
    )
    assert r.status_code == 200, r.text
    return csrf


# --- /me ---------------------------------------------------------------------

def test_me_unauthenticated_returns_401(client):
    r = client.get("/api/auth/me")
    assert r.status_code == 401


def test_me_authenticated_returns_user(client):
    _register_and_get_csrf(client, email="bob@example.com")
    r = client.get("/api/auth/me")
    assert r.status_code == 200
    body = r.json()
    assert body["email"] == "bob@example.com"
    assert "id" in body
    assert "role" in body


# --- register ---------------------------------------------------------------

def test_register_succeeds_with_valid_input(client):
    r_csrf = client.get("/api/auth/csrf")
    csrf = client.cookies.get("nlq_csrf")
    r = client.post(
        "/api/auth/register",
        json={"email": "carol@example.com", "password": "correct horse battery staple"},
        headers={"X-CSRF-Token": csrf},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["email"] == "carol@example.com"


def test_register_rejects_short_password(client):
    r_csrf = client.get("/api/auth/csrf")
    csrf = client.cookies.get("nlq_csrf")
    r = client.post(
        "/api/auth/register",
        json={"email": "dave@example.com", "password": "short"},
        headers={"X-CSRF-Token": csrf},
    )
    assert r.status_code == 400
    assert "10" in r.json()["detail"]


def test_register_rejects_duplicate_email(client):
    _register_and_get_csrf(client, email="eve@example.com")
    # Re-seed CSRF since register response rotated it.
    client.get("/api/auth/csrf")
    csrf = client.cookies.get("nlq_csrf")
    r = client.post(
        "/api/auth/register",
        json={"email": "eve@example.com", "password": "another good password"},
        headers={"X-CSRF-Token": csrf},
    )
    assert r.status_code == 409


def test_register_requires_csrf(client):
    r = client.post(
        "/api/auth/register",
        json={"email": "frank@example.com", "password": "another good password"},
    )
    assert r.status_code == 403


# --- login ------------------------------------------------------------------

def test_login_succeeds_after_register(client):
    _register_and_get_csrf(client, email="grace@example.com", password="correct horse battery staple")
    # Clear cookies (logout by removing session)
    client.cookies.clear()
    # Now login
    client.get("/api/auth/csrf")
    csrf = client.cookies.get("nlq_csrf")
    r = client.post(
        "/api/auth/login",
        json={"email": "grace@example.com", "password": "correct horse battery staple"},
        headers={"X-CSRF-Token": csrf},
    )
    assert r.status_code == 200
    assert r.json()["email"] == "grace@example.com"


def test_login_rejects_wrong_password_uniformly(client):
    _register_and_get_csrf(client, email="henry@example.com", password="correct horse battery staple")
    client.cookies.clear()
    client.get("/api/auth/csrf")
    csrf = client.cookies.get("nlq_csrf")
    r = client.post(
        "/api/auth/login",
        json={"email": "henry@example.com", "password": "wrong password here"},
        headers={"X-CSRF-Token": csrf},
    )
    assert r.status_code == 401
    # Uniform error: no user enumeration.
    assert r.json()["detail"] == "Invalid email or password"


def test_login_rejects_unknown_email_uniformly(client):
    client.get("/api/auth/csrf")
    csrf = client.cookies.get("nlq_csrf")
    r = client.post(
        "/api/auth/login",
        json={"email": "nobody@example.com", "password": "correct horse battery staple"},
        headers={"X-CSRF-Token": csrf},
    )
    assert r.status_code == 401
    assert r.json()["detail"] == "Invalid email or password"


def test_login_requires_csrf(client):
    r = client.post(
        "/api/auth/login",
        json={"email": "x@y.com", "password": "correct horse battery staple"},
    )
    assert r.status_code == 403


# --- logout -----------------------------------------------------------------

def test_logout_invalidates_session(client):
    _register_and_get_csrf(client, email="ivan@example.com")
    # We are now logged in.
    assert client.get("/api/auth/me").status_code == 200
    # Rotate CSRF after register — fetch a new one (the dev endpoint sets it).
    client.get("/api/auth/csrf")
    csrf = client.cookies.get("nlq_csrf")
    r = client.post("/api/auth/logout", headers={"X-CSRF-Token": csrf})
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    # /me should now be 401.
    assert client.get("/api/auth/me").status_code == 401


def test_logout_requires_csrf(client):
    _register_and_get_csrf(client, email="judy@example.com")
    r = client.post("/api/auth/logout")
    assert r.status_code == 403


# --- rate limit -------------------------------------------------------------

def test_login_rate_limit_kicks_in(client):
    # The fixture sets AUTH_RATE_LIMIT=3/60.
    # Pre-create the user. Register now shares the per-(email, IP) limiter with
    # login, so reset afterwards to measure login throttling in isolation.
    _register_and_get_csrf(client, email="kate@example.com", password="correct horse battery staple")
    import auth_rate_limit as _arl
    _arl.auth_limiter.reset()
    client.cookies.clear()
    # 3 failed attempts should still work, the 4th should 429.
    for i in range(3):
        client.get("/api/auth/csrf")
        csrf = client.cookies.get("nlq_csrf")
        r = client.post(
            "/api/auth/login",
            json={"email": "kate@example.com", "password": "wrong password here"},
            headers={"X-CSRF-Token": csrf},
        )
        assert r.status_code == 401, f"attempt {i} unexpected: {r.status_code}"
    # 4th: rate limited.
    client.get("/api/auth/csrf")
    csrf = client.cookies.get("nlq_csrf")
    r = client.post(
        "/api/auth/login",
        json={"email": "kate@example.com", "password": "wrong password here"},
        headers={"X-CSRF-Token": csrf},
    )
    assert r.status_code == 429


# --- /api/query is still accessible anon (back-compat) --------------------

def test_query_endpoint_still_works_anon(client):
    # Auth is opt-in for /api/query in this phase; ensure anon still works.
    r = client.post("/api/query", json={"question": "are there any returns in sao paulo?"})
    # The scope guard kicks in, but the endpoint is reachable.
    assert r.status_code == 200
    body = r.json()
    assert "error" in body or "operation" in body
