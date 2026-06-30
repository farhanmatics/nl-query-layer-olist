"""End-to-end B3 tests: IDOR-safe ownership + session/message lifecycle.

The critical control: every :id route must 404 (not 403) on cross-user
access. This is the test that protects the multi-tenant boundary.

Run:
    cd backend && ../venv/bin/python -m pytest tests/test_sessions.py -v
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import os  # noqa: E402
import tempfile  # noqa: E402
import importlib as _il  # noqa: E402

# Module-level setup: a single fresh app-state DB. The schema is applied
# lazily by the first request (via the migration runner at startup), so
# we don't need to run anything here.
_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["APP_DB_URL"] = f"sqlite:///{_tmp.name}"
os.environ["SESSION_SECRET"] = "test-secret-please-ignore"
os.environ["AUTH_RATE_LIMIT"] = "0/0"  # disable for these tests

import config as _config  # noqa: E402
_il.reload(_config)
import appdb  # noqa: E402
_il.reload(appdb)
import auth_routes  # noqa: E402
_il.reload(auth_routes)
import session_routes  # noqa: E402
_il.reload(session_routes)
import main as _main  # noqa: E402
_il.reload(_main)


import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


async def _wipe():
    conn = await appdb.get_conn()
    await conn.execute("DELETE FROM messages")
    await conn.execute("DELETE FROM sessions")
    await conn.execute("DELETE FROM auth_sessions")
    await conn.execute("DELETE FROM users")
    await conn.commit()


def _seed_csrf(client: TestClient) -> str:
    r = client.get("/api/auth/csrf")
    assert r.status_code == 200
    return client.cookies.get("nlq_csrf")


def _register(client: TestClient, email: str, password: str = "correct horse battery staple") -> None:
    csrf = _seed_csrf(client)
    r = client.post(
        "/api/auth/register",
        json={"email": email, "password": password},
        headers={"X-CSRF-Token": csrf},
    )
    assert r.status_code == 200, r.text


def _login(client: TestClient, email: str, password: str = "correct horse battery staple") -> None:
    client.cookies.clear()
    _seed_csrf(client)
    csrf = client.cookies.get("nlq_csrf")
    r = client.post(
        "/api/auth/login",
        json={"email": email, "password": password},
        headers={"X-CSRF-Token": csrf},
    )
    assert r.status_code == 200, r.text


@pytest.fixture
def client():
    """A clean client per test. The TestClient context manager triggers
    FastAPI's startup hook (which applies app-state migrations). Wipe
    between tests via a fresh aiosqlite connection (independent of the
    appdb singleton loop)."""
    with TestClient(_main.app) as c:
        # The startup hook runs on context enter. Now wipe for isolation.
        import asyncio as _aio
        import aiosqlite
        import auth_rate_limit as _arl
        # Reload to pick up AUTH_RATE_LIMIT=0/0 (parse_rate_limit reads
        # settings at import time).
        _il.reload(_arl)
        import auth_routes as _ar
        _il.reload(_ar)
        _il.reload(_main)
        _arl.auth_limiter.reset()
        async def _wipe():
            path = appdb.db_path()
            async with aiosqlite.connect(path) as conn:
                await conn.execute("DELETE FROM messages")
                await conn.execute("DELETE FROM sessions")
                await conn.execute("DELETE FROM auth_sessions")
                await conn.execute("DELETE FROM users")
                await conn.commit()
        _aio.run(_wipe())
        yield c


# --- Auth: who am I -----------------------------------------------------------

def test_list_sessions_unauth_returns_401(client):
    r = client.get("/api/sessions")
    assert r.status_code == 401


def test_list_sessions_authed_empty(client):
    _register(client, email="alice@example.com")
    r = client.get("/api/sessions")
    assert r.status_code == 200
    assert r.json() == []


# --- Create + list ------------------------------------------------------------

def test_create_session_returns_row(client):
    _register(client, email="bob@example.com")
    csrf = _seed_csrf(client)
    r = client.post("/api/sessions", json={}, headers={"X-CSRF-Token": csrf})
    assert r.status_code == 201
    body = r.json()
    assert "id" in body
    assert "created_at" in body
    assert "last_active_at" in body


def test_create_session_requires_csrf(client):
    _register(client, email="carl@example.com")
    r = client.post("/api/sessions", json={})
    assert r.status_code == 403


def test_list_only_returns_caller_s_sessions(client):
    _register(client, email="dave@example.com")
    # Create one session as dave.
    csrf = _seed_csrf(client)
    r = client.post("/api/sessions", json={"title": "Dave's chat"}, headers={"X-CSRF-Token": csrf})
    dave_sid = r.json()["id"]
    # Register eve.
    client.cookies.clear()
    _register(client, email="eve@example.com")
    # Eve's list is empty.
    r = client.get("/api/sessions")
    assert r.json() == []
    # Dave's list has his one.
    client.cookies.clear()
    _login(client, email="dave@example.com")
    r = client.get("/api/sessions")
    assert [s["id"] for s in r.json()] == [dave_sid]


# --- IDOR-safe: the main event ------------------------------------------------

def test_get_messages_on_other_users_session_returns_404(client):
    """The headline IDOR test: alice can see her own session's messages,
    but accessing eve's session id is 404 — never 403, never a leak."""
    _register(client, email="alice@example.com")
    csrf = _seed_csrf(client)
    r = client.post("/api/sessions", json={}, headers={"X-CSRF-Token": csrf})
    alice_sid = r.json()["id"]
    # Register eve.
    client.cookies.clear()
    _register(client, email="eve@example.com")
    csrf = _seed_csrf(client)
    # Eve tries to read alice's session → 404.
    r = client.get(f"/api/sessions/{alice_sid}/messages")
    assert r.status_code == 404, f"expected 404 (no leak), got {r.status_code}: {r.text}"


def test_rename_other_users_session_returns_404(client):
    _register(client, email="frank@example.com")
    csrf = _seed_csrf(client)
    r = client.post("/api/sessions", json={}, headers={"X-CSRF-Token": csrf})
    frank_sid = r.json()["id"]
    # Register grace.
    client.cookies.clear()
    _register(client, email="grace@example.com")
    csrf = _seed_csrf(client)
    r = client.patch(
        f"/api/sessions/{frank_sid}",
        json={"title": "Grace hijacks"},
        headers={"X-CSRF-Token": csrf},
    )
    assert r.status_code == 404
    # Verify frank's title was NOT touched.
    client.cookies.clear()
    _login(client, email="frank@example.com")
    r = client.get("/api/sessions")
    assert r.json()[0]["title"] is None


def test_delete_other_users_session_returns_404(client):
    _register(client, email="henry@example.com")
    csrf = _seed_csrf(client)
    r = client.post("/api/sessions", json={}, headers={"X-CSRF-Token": csrf})
    henry_sid = r.json()["id"]
    # Register ivy.
    client.cookies.clear()
    _register(client, email="ivy@example.com")
    csrf = _seed_csrf(client)
    r = client.delete(f"/api/sessions/{henry_sid}", headers={"X-CSRF-Token": csrf})
    assert r.status_code == 404
    # Henry's session must still exist.
    client.cookies.clear()
    _login(client, email="henry@example.com")
    r = client.get("/api/sessions")
    assert any(s["id"] == henry_sid for s in r.json())


def test_get_messages_on_nonexistent_session_returns_404(client):
    """Same code path as cross-user — attacker can't distinguish."""
    _register(client, email="jack@example.com")
    r = client.get("/api/sessions/00000000-0000-0000-0000-000000000000/messages")
    assert r.status_code == 404


# --- Cascade delete -----------------------------------------------------------

def test_delete_session_cascades_messages(client):
    _register(client, email="kim@example.com")
    csrf = _seed_csrf(client)
    r = client.post("/api/sessions", json={}, headers={"X-CSRF-Token": csrf})
    sid = r.json()["id"]
    # Insert a message directly via a fresh connection (avoids the
    # appdb-singleton-loop issue).
    import asyncio as _aio
    import aiosqlite
    async def _insert():
        path = appdb.db_path()
        async with aiosqlite.connect(path) as conn:
            await conn.execute(
                "INSERT INTO messages (id, session_id, role, question, "
                "response_json, resolved_call, created_at) "
                "VALUES (?, ?, ?, ?, NULL, NULL, ?)",
                ("test-msg-id", sid, "user", "hi", "2024-01-01T00:00:00+00:00"),
            )
            await conn.commit()
    _aio.run(_insert())
    # Sanity: list sees it.
    r = client.get(f"/api/sessions/{sid}/messages")
    assert len(r.json()) == 1
    # Delete the session.
    csrf = _seed_csrf(client)
    r = client.delete(f"/api/sessions/{sid}", headers={"X-CSRF-Token": csrf})
    assert r.status_code == 200
    # Messages should be gone via ON DELETE CASCADE.
    async def _count():
        path = appdb.db_path()
        async with aiosqlite.connect(path) as conn:
            async with conn.execute(
                "SELECT COUNT(*) FROM messages WHERE session_id = ?", (sid,)
            ) as cur:
                row = await cur.fetchone()
                return row[0] if row else 0
    import asyncio as _aio
    assert _aio.run(_count()) == 0


def test_delete_user_cascades_sessions(client):
    """Sanity: when an auth session is deleted, the chat sessions survive
    (we only delete the auth_sessions row in logout, not the user)."""
    _register(client, email="lara@example.com")
    csrf = _seed_csrf(client)
    r = client.post("/api/sessions", json={}, headers={"X-CSRF-Token": csrf})
    sid = r.json()["id"]
    # Verify it exists.
    r = client.get("/api/sessions")
    assert any(s["id"] == sid for s in r.json())


# --- Auth / ownership combo --------------------------------------------------

def test_anonymous_user_cannot_list_sessions(client):
    # No login at all.
    r = client.get("/api/sessions")
    assert r.status_code == 401


def test_query_with_cross_user_session_id_returns_error(client):
    """The /api/query route must also enforce ownership. A logged-in user
    cannot use another user's session id (would let them see history)."""
    _register(client, email="mia@example.com")
    csrf = _seed_csrf(client)
    r = client.post("/api/sessions", json={}, headers={"X-CSRF-Token": csrf})
    mia_sid = r.json()["id"]
    # Register nina.
    client.cookies.clear()
    _register(client, email="nina@example.com")
    # Nina tries to use mia's session id.
    r = client.post(
        "/api/query",
        json={"question": "anything", "session_id": mia_sid},
    )
    assert r.status_code == 200  # not 401/403
    body = r.json()
    assert body.get("error") == "Session not found"


def test_query_with_own_session_id_succeeds(client):
    """The same user's session id is accepted (and the orchestrator will
    resolve the follow-up against persisted state)."""
    _register(client, email="olive@example.com")
    csrf = _seed_csrf(client)
    r = client.post("/api/sessions", json={}, headers={"X-CSRF-Token": csrf})
    sid = r.json()["id"]
    # Use scope-guard question so the orchestrator returns a known shape
    # without needing the LLM.
    r = client.post(
        "/api/query",
        json={"question": "are there any returns?", "session_id": sid},
    )
    assert r.status_code == 200
    body = r.json()
    # The scope guard should have declined with the standard "not tracked" error.
    assert "returns" in (body.get("error") or "")


def test_query_persists_turn_in_owned_session(client):
    """After a query in an owned session, the message list shows the pair."""
    _register(client, email="paul@example.com")
    csrf = _seed_csrf(client)
    r = client.post("/api/sessions", json={}, headers={"X-CSRF-Token": csrf})
    sid = r.json()["id"]
    # Run a query.
    client.post(
        "/api/query",
        json={"question": "are there any returns?", "session_id": sid},
    )
    # The session should have at least 1 user + 1 assistant row.
    r = client.get(f"/api/sessions/{sid}/messages")
    assert r.status_code == 200
    msgs = r.json()
    assert len(msgs) >= 2
    roles = [m["role"] for m in msgs]
    assert "user" in roles
    assert "assistant" in roles


def test_query_does_not_persist_turn_for_cross_user_session(client):
    """If a cross-user session id is rejected, no rows are written for that
    session. Verify the cross-user's session still has 0 messages."""
    _register(client, email="quinn@example.com")
    csrf = _seed_csrf(client)
    r = client.post("/api/sessions", json={}, headers={"X-CSRF-Token": csrf})
    quinn_sid = r.json()["id"]
    # Register rita.
    client.cookies.clear()
    _register(client, email="rita@example.com")
    # Rita tries to write to quinn's session.
    client.post(
        "/api/query",
        json={"question": "are there any returns?", "session_id": quinn_sid},
    )
    # Switch back to quinn; her session must have 0 messages.
    client.cookies.clear()
    _login(client, email="quinn@example.com")
    r = client.get(f"/api/sessions/{quinn_sid}/messages")
    assert r.json() == []


# --- Rename ------------------------------------------------------------------

def test_rename_own_session(client):
    _register(client, email="sara@example.com")
    csrf = _seed_csrf(client)
    r = client.post("/api/sessions", json={}, headers={"X-CSRF-Token": csrf})
    sid = r.json()["id"]
    csrf = _seed_csrf(client)
    r = client.patch(
        f"/api/sessions/{sid}",
        json={"title": "My new title"},
        headers={"X-CSRF-Token": csrf},
    )
    assert r.status_code == 200
    assert r.json()["title"] == "My new title"


def test_rename_requires_csrf(client):
    _register(client, email="tara@example.com")
    csrf = _seed_csrf(client)
    r = client.post("/api/sessions", json={}, headers={"X-CSRF-Token": csrf})
    sid = r.json()["id"]
    r = client.patch(f"/api/sessions/{sid}", json={"title": "no csrf"})
    assert r.status_code == 403


# --- First-message auto-titling ----------------------------------------------

def test_first_message_titles_untitled_session(client):
    """A button-created session starts untitled ("New chat"); its first
    message must title it server-side (single source of truth)."""
    _register(client, email="ulm@example.com")
    csrf = _seed_csrf(client)
    # Button-created session: no title.
    r = client.post("/api/sessions", json={}, headers={"X-CSRF-Token": csrf})
    sid = r.json()["id"]
    assert r.json()["title"] is None
    # First message (scope-guard question persists durably without the LLM).
    client.post("/api/query", json={"question": "are there any returns?", "session_id": sid})
    # The session is now titled from that question.
    r = client.get("/api/sessions")
    row = next(s for s in r.json() if s["id"] == sid)
    assert row["title"] == "are there any returns?"


def test_second_message_does_not_retitle(client):
    """Only the FIRST message titles; a later message must not overwrite it."""
    _register(client, email="vera@example.com")
    csrf = _seed_csrf(client)
    r = client.post("/api/sessions", json={}, headers={"X-CSRF-Token": csrf})
    sid = r.json()["id"]
    client.post("/api/query", json={"question": "are there any returns?", "session_id": sid})
    client.post("/api/query", json={"question": "what about refunds?", "session_id": sid})
    r = client.get("/api/sessions")
    row = next(s for s in r.json() if s["id"] == sid)
    assert row["title"] == "are there any returns?"


def test_explicit_title_not_overwritten_by_first_message(client):
    """A session created WITH a title keeps it after the first message."""
    _register(client, email="walt@example.com")
    csrf = _seed_csrf(client)
    r = client.post(
        "/api/sessions",
        json={"title": "Quarterly review"},
        headers={"X-CSRF-Token": csrf},
    )
    sid = r.json()["id"]
    client.post("/api/query", json={"question": "are there any returns?", "session_id": sid})
    r = client.get("/api/sessions")
    row = next(s for s in r.json() if s["id"] == sid)
    assert row["title"] == "Quarterly review"


# --- resolved_call shape (B4-prep regression) --------------------------------

def test_persist_turn_stores_input_shaped_resolved_call(monkeypatch):
    """Durable resolved_call MUST be the input shape (date_token), never the
    resolved result.filters (date_range). Otherwise a follow-up turn loses the
    date (the resolver drops date_range as a non-param) and answers all-time —
    the exact confidently-wrong failure this whole feature prevents."""
    import asyncio as _aio
    import json as _json
    import orchestrator as _orch

    captured = {}

    async def _fake_insert(session_id, role, question=None, response_json=None, resolved_call=None):
        if role == "assistant":
            captured["resolved_call"] = resolved_call
        return {}

    async def _fake_touch(session_id, user_id):
        return None

    async def _fake_title(session_id, user_id, title):
        return True

    monkeypatch.setattr(appdb, "insert_message", _fake_insert)
    monkeypatch.setattr(appdb, "touch_chat_session", _fake_touch)
    monkeypatch.setattr(appdb, "set_session_title_if_unset", _fake_title)

    # Response carries RESULT-shaped filters (date_range, normalized city) ...
    response = {
        "operation": "count_low_reviews",
        "filters": {"score_max": 2, "date_range": ["2018-07-01T00:00:00", "2018-07-31T23:59:59"]},
        "error": None,
        "context": {"inherited": False, "clarify": None},
    }
    # ... but the input-shaped args (what the resolver needs) use date_token.
    resolved_args = {"score_max": 2, "date_token": "last_month"}

    _aio.run(_orch._persist_turn("sid", "uid", "low reviews last month?", response, resolved_args=resolved_args))

    stored = _json.loads(captured["resolved_call"])
    assert stored["operation"] == "count_low_reviews"
    assert stored["args"] == {"score_max": 2, "date_token": "last_month"}
    assert "date_range" not in stored["args"], "must store input shape, not the resolved date_range"


def test_persist_turn_null_resolved_call_for_clarify(monkeypatch):
    """Clarify/error turns store resolved_call=NULL so get_last_resolved_call
    skips them and a later follow-up inherits the last *real* turn."""
    import asyncio as _aio
    import orchestrator as _orch

    captured = {}

    async def _fake_insert(session_id, role, question=None, response_json=None, resolved_call=None):
        if role == "assistant":
            captured["resolved_call"] = resolved_call
        return {}

    async def _fake_touch(session_id, user_id):
        return None

    async def _fake_title(session_id, user_id, title):
        return True

    monkeypatch.setattr(appdb, "insert_message", _fake_insert)
    monkeypatch.setattr(appdb, "touch_chat_session", _fake_touch)
    monkeypatch.setattr(appdb, "set_session_title_if_unset", _fake_title)

    response = {
        "operation": None,
        "filters": None,
        "error": None,
        "context": {"inherited": True, "clarify": {"prompt": "which?", "options": ["a", "b"]}},
    }
    _aio.run(_orch._persist_turn("sid", "uid", "and for Rio?", response, resolved_args=None))
    assert captured["resolved_call"] is None


# --- Cleanup -----------------------------------------------------------------

@pytest.fixture(autouse=True)
def cleanup_db():
    """Remove the temp DB after the test module exits."""
    yield
    try:
        os.unlink(_tmp.name)
    except Exception:
        pass
