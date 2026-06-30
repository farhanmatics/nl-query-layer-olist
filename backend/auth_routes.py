"""Auth routes (B2): register, login, logout, me.

Cookie model:
  - `nlq_session` (HttpOnly, SameSite=Lax): signed wrapper around the
    `auth_sessions` row id. The session row itself carries the user binding
    + expiry, so logout = delete the row.
  - `nlq_csrf` (NOT HttpOnly — JS must read it for the double-submit): a
    random per-session token. State-changing requests (POST/PATCH/DELETE)
    must echo it in the `X-CSRF-Token` header.

Error model:
  - Login: always "invalid email or password" — never reveal which is wrong
    (no user enumeration).
  - Register: may say "email taken" (accepted trade-off; plan says verify-flow
    later is optional).
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel, Field

import appdb
from auth import (
    CSRF_COOKIE,
    CSRF_HEADER,
    get_dummy_hash,
    make_csrf_token,
    make_session_token,
    hash_password,
    read_session_token,
    validate_csrf,
    validate_email,
    validate_password,
    verify_password,
)
from auth_rate_limit import auth_limiter
from config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])


# --- Request/response shapes -------------------------------------------------

class RegisterRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=254)
    password: str = Field(..., min_length=1)  # policy enforced server-side


class LoginRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=254)
    password: str = Field(..., min_length=1)


class UserOut(BaseModel):
    id: str
    email: str
    role: Optional[str] = None


# --- Cookie helpers ----------------------------------------------------------

def _set_session_cookies(response: Response, session_id: str, csrf_token: str) -> None:
    """Attach both cookies. HttpOnly on the session, NOT on the CSRF token."""
    secure = settings.cookie_secure
    token = make_session_token(session_id)
    response.set_cookie(
        key="nlq_session",
        value=token,
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/",
        max_age=settings.session_ttl_minutes * 60,
    )
    response.set_cookie(
        key=CSRF_COOKIE,
        value=csrf_token,
        httponly=False,  # JS must read this for the double-submit pattern
        secure=secure,
        samesite="lax",
        path="/",
        max_age=settings.session_ttl_minutes * 60,
    )


def _clear_session_cookies(response: Response) -> None:
    response.delete_cookie("nlq_session", path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")


# --- Auth dependency (the `current_user`) -----------------------------------

async def _resolve_session(
    nlq_session: Optional[str] = Cookie(default=None),
) -> Optional[dict]:
    """Return the user record for the current request, or None.

    Used both as a dependency (for `/me`) and as a guard (for any route
    that requires auth). B3 will swap "the row in auth_sessions" for
    "the most-recent assistant message" for conversation routes; this
    helper stays the same.
    """
    if not nlq_session:
        return None
    session_id = read_session_token(nlq_session)
    if not session_id:
        return None
    sess = await appdb.get_auth_session(session_id)
    if not sess:
        return None
    user = await appdb.get_user_by_id(sess["user_id"])
    return user


async def require_user(
    request: Request,
    nlq_session: Optional[str] = Cookie(default=None),
) -> dict:
    """FastAPI dependency: returns the user or raises 401."""
    user = await _resolve_session(nlq_session)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    # Stash the user on request.state for middleware/audit that want it.
    request.state.user = user
    return user


# --- CSRF dependency ---------------------------------------------------------

async def require_csrf(
    request: Request,
    nlq_csrf: Optional[str] = Cookie(default=None),
    x_csrf_token: Optional[str] = Header(default=None, alias=CSRF_HEADER),
) -> None:
    """Validate the double-submit CSRF token on state-changing routes."""
    if not validate_csrf(nlq_csrf, x_csrf_token):
        raise HTTPException(status_code=403, detail="Invalid or missing CSRF token")


# --- Routes ------------------------------------------------------------------

@router.post("/register", response_model=UserOut)
async def register(
    body: RegisterRequest,
    request: Request,
    response: Response,
    _csrf: None = Depends(require_csrf),
):
    """Create a new user and open a session.

    Email is normalized (lowercased, trimmed) before lookup/insert. Password
    is validated against the policy (min length + common-password denylist).
    On success, the response includes a Set-Cookie for both the session and
    the CSRF token. Register *may* reveal "email taken" — verify flow is
    optional per the plan. CSRF required (the dev-seed endpoint is the
    way to obtain a token before the user is logged in).
    """
    # Same per-(email, IP) throttle as login, so an open registration endpoint
    # can't be used for cheap mass account creation from one host.
    ip = request.client.host if request.client else "unknown"
    if not auth_limiter.is_allowed(body.email, ip):
        raise HTTPException(
            status_code=429,
            detail="Too many attempts. Please try again later.",
        )

    email_err = validate_email(body.email)
    if email_err:
        raise HTTPException(status_code=400, detail=email_err)
    pw_err = validate_password(body.password)
    if pw_err:
        raise HTTPException(status_code=400, detail=pw_err)

    # Hash BEFORE the unique check, so a duplicate email doesn't leak timing.
    pw_hash = await hash_password(body.password)

    try:
        user = await appdb.create_user(body.email, pw_hash)
    except ValueError as e:
        # Email already exists — accepted to reveal (plan Open Q).
        raise HTTPException(status_code=409, detail="Email already registered") from e

    # Open a session.
    expires_at = (
        datetime.now(timezone.utc) + timedelta(minutes=settings.session_ttl_minutes)
    ).isoformat()
    sid = await appdb.create_auth_session(user["id"], expires_at)
    csrf = make_csrf_token()
    _set_session_cookies(response, sid, csrf)
    return UserOut(**user)


@router.post("/login", response_model=UserOut)
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    _csrf: None = Depends(require_csrf),
):
    """Authenticate and open a session. Uniform error: never reveal which
    field is wrong (no user enumeration). CSRF required (seed via the
    dev endpoint before the user has a session)."""
    ip = request.client.host if request.client else "unknown"
    if not auth_limiter.is_allowed(body.email, ip):
        raise HTTPException(
            status_code=429,
            detail="Too many attempts. Please try again later.",
        )

    user = await appdb.get_user_by_email(body.email)
    if not user:
        # Verify against a dummy hash built with the SAME configured argon2
        # params so the not-found path costs the same as a real verify (no
        # timing-based user enumeration).
        await verify_password(body.password, get_dummy_hash())
        raise HTTPException(status_code=401, detail="Invalid email or password")

    if not await verify_password(body.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    expires_at = (
        datetime.now(timezone.utc) + timedelta(minutes=settings.session_ttl_minutes)
    ).isoformat()
    sid = await appdb.create_auth_session(user["id"], expires_at)
    csrf = make_csrf_token()
    _set_session_cookies(response, sid, csrf)
    return UserOut(**user)


@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    nlq_session: Optional[str] = Cookie(default=None),
    _csrf: None = Depends(require_csrf),
):
    """Invalidate the server-side session and clear the cookies.

    CSRF is required because logout is state-changing (in case an attacker
    can plant a logout via CSRF — annoying if they do). If no session is
    present, this is a no-op (idempotent).
    """
    if nlq_session:
        sid = read_session_token(nlq_session)
        if sid:
            await appdb.delete_auth_session(sid)
    _clear_session_cookies(response)
    return {"ok": True}


@router.get("/me", response_model=UserOut)
async def me(user: Optional[dict] = Depends(_resolve_session)):
    """Return the current user, or 401 if not authenticated. Used by the
    frontend to bootstrap the AuthContext on page load (cookie already
    present → silent login on refresh)."""
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return UserOut(**user)


# --- CSRF bootstrap endpoint -------------------------------------------------

@router.get("/csrf")
async def get_csrf(response: Response):
    """Issue a CSRF cookie for unauthenticated users so the register/login
    forms (which are state-changing) can echo it in the X-CSRF-Token header.
    The token is purely anti-CSRF; it grants no access by itself.

    GET is intentional: it only sets a random cookie (no state change), so it
    needs no CSRF protection of its own. This is the standard "get a token
    before you're logged in" bootstrap.
    """
    csrf = make_csrf_token()
    response.set_cookie(
        key=CSRF_COOKIE,
        value=csrf,
        httponly=False,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
        max_age=settings.session_ttl_minutes * 60,
    )
    return {"ok": True}
