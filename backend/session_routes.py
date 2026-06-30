"""Session routes (B3): durable conversations scoped to the authenticated
user. The IDOR-safe dependency `require_owned_session` is the main event
— every :id route loads the row and asserts `row.user_id == current_user.id`
before acting. Mismatch → 404 (not 403) so we don't confirm existence to
attackers guessing session ids.

Endpoints (all require auth; all enforce ownership):
  GET    /api/sessions                → [SessionMeta]  (current user only)
  POST   /api/sessions                → SessionMeta    (new conversation)
  PATCH  /api/sessions/:id {title}    → SessionMeta    (rename)
  DELETE /api/sessions/:id            → { ok }
  GET    /api/sessions/:id/messages   → [Message]
"""
import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel, Field

import appdb
from auth_routes import _resolve_session, require_csrf

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


# --- Response shapes ---------------------------------------------------------

class SessionMeta(BaseModel):
    id: str
    title: Optional[str] = None
    created_at: str
    last_active_at: str


class CreateSessionRequest(BaseModel):
    title: Optional[str] = Field(default=None, max_length=200)


class RenameSessionRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)


class MessageOut(BaseModel):
    id: str
    role: str
    question: Optional[str] = None
    response: Optional[dict] = None
    created_at: str


# --- Helpers -----------------------------------------------------------------

from fastapi import Cookie as _Cookie


async def require_user_id(
    nlq_session: Optional[str] = _Cookie(default=None),
) -> str:
    """Return the current user id or raise 401. Single auth check used by
    every session route below (and the IDOR-safe `require_owned_session`)."""
    user = await _resolve_session(nlq_session)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user["id"]


# --- IDOR-safe session guard --------------------------------------------------

async def require_owned_session(
    session_id: str = Path(..., min_length=1),
    user_id: str = Depends(require_user_id),
) -> dict:
    """Load the session, assert ownership, return the row. 404 on miss OR
    on cross-user access — never 403, never a leak.

    This is the single source of truth for IDOR safety on session-scoped
    routes. Every :id route below calls it; nothing reads a session row
    without it.
    """
    ok = await appdb.session_belongs_to_user(session_id, user_id)
    if not ok:
        # 404 (not 403) so an attacker can't distinguish "exists but not
        # yours" from "doesn't exist".
        raise HTTPException(status_code=404, detail="Session not found")
    session = await appdb.get_chat_session(session_id)
    # session_belongs_to_user just confirmed it exists; defensive assert.
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


# Title derivation lives in appdb.derive_session_title (single source of truth,
# used by the orchestrator to title an untitled session on its first message).


# --- Routes ------------------------------------------------------------------

@router.get("", response_model=list[SessionMeta])
async def list_sessions(user_id: str = Depends(require_user_id)):
    """Return the caller's sessions, newest activity first."""
    rows = await appdb.list_chat_sessions(user_id)
    return [SessionMeta(**r) for r in rows]


@router.post("", response_model=SessionMeta, status_code=201)
async def create_session(
    body: CreateSessionRequest,
    user_id: str = Depends(require_user_id),
    _csrf: None = Depends(require_csrf),
):
    """Create a new empty conversation. Used by the sidebar's "New chat" button."""
    title = body.title
    if title is not None:
        title = title.strip() or None
    row = await appdb.create_chat_session(user_id, title=title)
    return SessionMeta(**row)


@router.patch("/{session_id}", response_model=SessionMeta)
async def rename_session(
    body: RenameSessionRequest,
    session: dict = Depends(require_owned_session),
    user_id: str = Depends(require_user_id),
    _csrf: None = Depends(require_csrf),
):
    """Rename a session the caller owns. 404 on cross-user."""
    title = body.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="Title cannot be empty")
    ok = await appdb.rename_chat_session(session["id"], user_id, title)
    if not ok:
        # Defensive: require_owned_session already passed; this should be
        # impossible. But if a race deletes the row between the check and
        # the update, we'd rather 404 than 500.
        raise HTTPException(status_code=404, detail="Session not found")
    # Re-read for the updated timestamp.
    fresh = await appdb.get_chat_session(session["id"])
    return SessionMeta(**fresh)


@router.delete("/{session_id}")
async def delete_session(
    session: dict = Depends(require_owned_session),
    _csrf: None = Depends(require_csrf),
):
    """Delete a session the caller owns (and its messages via CASCADE). 404
    on cross-user."""
    ok = await appdb.delete_chat_session(session["id"], session["user_id"])
    if not ok:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"ok": True}


@router.get("/{session_id}/messages", response_model=list[MessageOut])
async def list_messages(
    session: dict = Depends(require_owned_session),
):
    """Return all messages in a session the caller owns. 404 on cross-user."""
    rows = await appdb.list_messages(session["id"])
    out: list[MessageOut] = []
    for r in rows:
        response_obj = None
        if r.get("response_json"):
            try:
                response_obj = json.loads(r["response_json"])
            except (ValueError, TypeError):
                response_obj = None
        out.append(
            MessageOut(
                id=r["id"],
                role=r["role"],
                question=r.get("question"),
                response=response_obj,
                created_at=r["created_at"],
            )
        )
    return out
