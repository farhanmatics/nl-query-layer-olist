"""App-state store: SQLite + repo layer (B1 + B2).

This is a *separate* read-write connection from the Olist read-only pool in
`db.py`. The two never reach each other's tables.

Engine: SQLite (dev/single-tenant). A Postgres DSN is a drop-in for
multi-tenant later; the repo layer (placeholder dialect `?`) is the only place
that touches SQL.

PRAGMAs on connect:
- `journal_mode=WAL` — concurrent reads while a write is in progress
- `busy_timeout=5000` — wait, don't instantly fail, when a write lock is held
  (SQLite serializes writers; without this any concurrent request can fail)
- `foreign_keys=ON` — the `ON DELETE CASCADE` clauses are inert without it

Schema lives in `migrations_app/`. Migrations are applied by the app on
startup; the runner is `migrate_app.py` (mirrors `migrate.py` for Olist).
"""
import asyncio
import logging
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional

import aiosqlite
from config import settings

logger = logging.getLogger(__name__)

_conn: Optional[aiosqlite.Connection] = None

# Serializes multi-statement transactions on the single shared connection.
# Without it, two coroutines interleaving a transaction() block would have one
# coroutine's commit/rollback capture the other's pending writes. Created lazily
# so it binds to the running loop (Python 3.9-safe).
_write_lock: Optional[asyncio.Lock] = None


def _get_write_lock() -> asyncio.Lock:
    global _write_lock
    if _write_lock is None:
        _write_lock = asyncio.Lock()
    return _write_lock


def _path_from_url(url: str) -> str:
    """Convert a sqlite:///path URL to a filesystem path."""
    if url.startswith("sqlite:///"):
        return url[len("sqlite:///"):]
    if url.startswith("sqlite://"):
        return url[len("sqlite://"):]
    return url


def db_path() -> str:
    return _path_from_url(settings.app_db_url)


async def get_conn() -> aiosqlite.Connection:
    """Return the singleton app-state connection, opening it on first use.

    aiosqlite is async, so the connection itself is safe to share across
    concurrent requests. WAL + busy_timeout give us reasonable concurrency
    on the single-file SQLite backend.
    """
    global _conn
    if _conn is None:
        path = db_path()
        # Ensure parent directory exists (file: backend/app_state.db)
        parent = os.path.dirname(path)
        if parent and not os.path.exists(parent):
            os.makedirs(parent, exist_ok=True)
        _conn = await aiosqlite.connect(path)
        await _conn.execute("PRAGMA journal_mode=WAL")
        await _conn.execute("PRAGMA busy_timeout=5000")
        await _conn.execute("PRAGMA foreign_keys=ON")
        _conn.row_factory = aiosqlite.Row
        logger.info(f"App-state DB opened: {path}")
    return _conn


async def close_conn() -> None:
    global _conn
    if _conn is not None:
        await _conn.close()
        _conn = None
        logger.info("App-state DB closed")


@asynccontextmanager
async def transaction():
    """Commit on success, roll back on exception.

    Holds a process-wide write lock for the duration so concurrent multi-
    statement transactions on the shared connection can't interleave (one
    commit/rollback must not capture another coroutine's pending writes).
    """
    conn = await get_conn()
    async with _get_write_lock():
        try:
            yield conn
            await conn.commit()
        except Exception:
            await conn.rollback()
            raise


def _now_iso() -> str:
    """ISO timestamp in UTC. Stored as text (ISO 8601) for portability with
    any future Postgres migration."""
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return str(uuid.uuid4())


# --- User repo ---------------------------------------------------------------

USER_FIELDS = "id, email, password_hash, role, created_at"


async def create_user(email: str, password_hash: str) -> dict:
    """Create a user. Raises ValueError if email already exists."""
    user_id = _new_id()
    created_at = _now_iso()
    conn = await get_conn()
    try:
        await conn.execute(
            "INSERT INTO users (id, email, password_hash, role, created_at) "
            "VALUES (?, ?, ?, NULL, ?)",
            (user_id, email.lower().strip(), password_hash, created_at),
        )
        await conn.commit()
    except aiosqlite.IntegrityError as e:
        raise ValueError(f"email already exists: {email}") from e
    return {
        "id": user_id,
        "email": email.lower().strip(),
        "role": None,
        "created_at": created_at,
    }


async def get_user_by_email(email: str) -> Optional[dict]:
    conn = await get_conn()
    async with conn.execute(
        f"SELECT {USER_FIELDS} FROM users WHERE email = ?",
        (email.lower().strip(),),
    ) as cur:
        row = await cur.fetchone()
    return dict(row) if row else None


async def get_user_by_id(user_id: str) -> Optional[dict]:
    conn = await get_conn()
    async with conn.execute(
        f"SELECT {USER_FIELDS} FROM users WHERE id = ?",
        (user_id,),
    ) as cur:
        row = await cur.fetchone()
    return dict(row) if row else None


# --- Auth session repo --------------------------------------------------------

async def create_auth_session(user_id: str, expires_at: str) -> str:
    """Create a server-side auth session. Returns the opaque session id
    (the value sent in the cookie)."""
    sid = _new_id()
    created_at = _now_iso()
    conn = await get_conn()
    await conn.execute(
        "INSERT INTO auth_sessions (id, user_id, created_at, expires_at) "
        "VALUES (?, ?, ?, ?)",
        (sid, user_id, created_at, expires_at),
    )
    await conn.commit()
    return sid


async def get_auth_session(sid: str) -> Optional[dict]:
    """Return the session row, or None if missing/expired."""
    conn = await get_conn()
    async with conn.execute(
        "SELECT id, user_id, created_at, expires_at FROM auth_sessions "
        "WHERE id = ? AND expires_at > ?",
        (sid, _now_iso()),
    ) as cur:
        row = await cur.fetchone()
    return dict(row) if row else None


async def delete_auth_session(sid: str) -> None:
    """Invalidate a server-side session (logout). Idempotent."""
    conn = await get_conn()
    await conn.execute("DELETE FROM auth_sessions WHERE id = ?", (sid,))
    await conn.commit()


async def cleanup_expired_sessions() -> int:
    """Delete sessions whose expires_at is in the past. Called opportunistically
    on startup. Returns the number of rows deleted."""
    conn = await get_conn()
    cur = await conn.execute(
        "DELETE FROM auth_sessions WHERE expires_at <= ?", (_now_iso(),)
    )
    await conn.commit()
    return cur.rowcount or 0


# --- Chat session repo (B3) ---------------------------------------------------

SESSION_FIELDS = "id, user_id, title, created_at, last_active_at"


async def create_chat_session(user_id: str, title: Optional[str] = None) -> dict:
    """Create a chat session for the given user."""
    sid = _new_id()
    now = _now_iso()
    conn = await get_conn()
    await conn.execute(
        "INSERT INTO sessions (id, user_id, title, created_at, last_active_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (sid, user_id, title, now, now),
    )
    await conn.commit()
    return {
        "id": sid,
        "user_id": user_id,
        "title": title,
        "created_at": now,
        "last_active_at": now,
    }


async def list_chat_sessions(user_id: str) -> list[dict]:
    """Return all chat sessions for a user, newest activity first."""
    conn = await get_conn()
    async with conn.execute(
        f"SELECT {SESSION_FIELDS} FROM sessions "
        "WHERE user_id = ? ORDER BY last_active_at DESC",
        (user_id,),
    ) as cur:
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def get_chat_session(session_id: str) -> Optional[dict]:
    """Return a session row by id, regardless of owner. Callers MUST verify
    ownership via session_belongs_to_user() before returning to the client."""
    conn = await get_conn()
    async with conn.execute(
        f"SELECT {SESSION_FIELDS} FROM sessions WHERE id = ?",
        (session_id,),
    ) as cur:
        row = await cur.fetchone()
    return dict(row) if row else None


async def session_belongs_to_user(session_id: str, user_id: str) -> bool:
    """True iff the session exists AND belongs to the user. Single source of
    truth for IDOR checks — every :id route calls this before any action."""
    conn = await get_conn()
    async with conn.execute(
        "SELECT 1 FROM sessions WHERE id = ? AND user_id = ?",
        (session_id, user_id),
    ) as cur:
        row = await cur.fetchone()
    return row is not None


def derive_session_title(question: str, max_len: int = 60) -> str:
    """Backend-derived conversation title from the first user question:
    whitespace-collapsed and truncated. Used to title an untitled session on
    its first message (single source of truth — the frontend mirrors this)."""
    if not question:
        return "New chat"
    cleaned = " ".join(question.split())
    if len(cleaned) > max_len:
        cleaned = cleaned[: max_len - 1].rstrip() + "…"
    return cleaned or "New chat"


async def set_session_title_if_unset(session_id: str, user_id: str, title: str) -> bool:
    """Set the title ONLY if it's currently NULL — so the first message titles
    a "New chat" conversation, but an explicit title or a later rename is never
    clobbered. Ownership-scoped. Returns True iff a row was updated."""
    conn = await get_conn()
    cur = await conn.execute(
        "UPDATE sessions SET title = ? WHERE id = ? AND user_id = ? AND title IS NULL",
        (title, session_id, user_id),
    )
    await conn.commit()
    return (cur.rowcount or 0) > 0


async def rename_chat_session(session_id: str, user_id: str, title: str) -> bool:
    """Rename a session, but ONLY if the user owns it. Returns True iff a row
    was updated. No row → 404 from the caller (ownership is the boundary)."""
    conn = await get_conn()
    cur = await conn.execute(
        "UPDATE sessions SET title = ? WHERE id = ? AND user_id = ?",
        (title, session_id, user_id),
    )
    await conn.commit()
    return (cur.rowcount or 0) > 0


async def touch_chat_session(session_id: str, user_id: str) -> None:
    """Bump last_active_at. Caller must have already verified ownership."""
    conn = await get_conn()
    await conn.execute(
        "UPDATE sessions SET last_active_at = ? WHERE id = ? AND user_id = ?",
        (_now_iso(), session_id, user_id),
    )
    await conn.commit()


async def delete_chat_session(session_id: str, user_id: str) -> bool:
    """Delete a session (and its messages via ON DELETE CASCADE), but ONLY
    if the user owns it. Returns True iff a row was deleted."""
    conn = await get_conn()
    cur = await conn.execute(
        "DELETE FROM sessions WHERE id = ? AND user_id = ?",
        (session_id, user_id),
    )
    await conn.commit()
    return (cur.rowcount or 0) > 0


# --- Message repo (B3 / B4) --------------------------------------------------

async def insert_message(
    session_id: str,
    role: str,
    question: Optional[str] = None,
    response_json: Optional[str] = None,
    resolved_call: Optional[str] = None,
) -> dict:
    """Insert a message row. Caller MUST have already verified session ownership."""
    mid = _new_id()
    now = _now_iso()
    conn = await get_conn()
    await conn.execute(
        "INSERT INTO messages (id, session_id, role, question, response_json, "
        "resolved_call, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (mid, session_id, role, question, response_json, resolved_call, now),
    )
    await conn.commit()
    return {
        "id": mid,
        "session_id": session_id,
        "role": role,
        "question": question,
        "response_json": response_json,
        "resolved_call": resolved_call,
        "created_at": now,
    }


async def list_messages(session_id: str) -> list[dict]:
    """Return all messages in a session, oldest first. Ownership MUST be
    checked by the caller before this is invoked."""
    conn = await get_conn()
    async with conn.execute(
        "SELECT id, session_id, role, question, response_json, resolved_call, "
        "created_at FROM messages WHERE session_id = ? "
        "ORDER BY created_at ASC",
        (session_id,),
    ) as cur:
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def get_last_resolved_call(session_id: str) -> Optional[dict]:
    """Return the most recent assistant message with a non-null resolved_call,
    or None. Used by B4 to load prior state for follow-up resolution.

    Per the plan: "Most recent assistant whose resolved_call is non-null"
    is the right shape. Clarify/error turns have resolved_call=NULL and are
    correctly skipped.
    """
    conn = await get_conn()
    async with conn.execute(
        "SELECT resolved_call FROM messages "
        "WHERE session_id = ? AND role = 'assistant' AND resolved_call IS NOT NULL "
        "ORDER BY created_at DESC LIMIT 1",
        (session_id,),
    ) as cur:
        row = await cur.fetchone()
    if not row or not row[0]:
        return None
    import json as _json
    try:
        return _json.loads(row[0])
    except (ValueError, TypeError):
        return None
