"""Auth helpers (B2): password hashing, session token, CSRF.

Hashing is argon2id (memory-hard, OWASP-recommended). Verification is
constant-time. Both run in a threadpool so they don't block the async
event loop — argon2 is deliberately CPU/memory heavy (tens to hundreds
of ms at the default cost) and a stalled loop would serialize every
concurrent request.

Session token: a signed `itsdangerous` value wrapping the auth_sessions row
id. The cookie carries the token; the row carries the user binding + expiry.
This way:
  - Logout = delete the row; the token is now unresolvable.
  - Rolling expiry = update the row, keep the same token.
  - Token tampering (changed id) = signature mismatch → 401.

CSRF: double-submit cookie. A random `csrf_token` (NOT signed, not
session-bound) is sent in a non-HttpOnly cookie (so the JS can read it) AND
must appear in a custom header on every state-changing request; the server
compares them constant-time. The real protection is SameSite=Lax (cross-site
POST withholds the session cookie) with this as defense-in-depth. A
session-bound HMAC token is the upgrade path if stronger CSRF is needed.
"""
import hashlib
import hmac
import logging
import secrets
import time
from typing import Optional

import anyio
from argon2 import PasswordHasher, Type
from argon2.exceptions import VerifyMismatchError, InvalidHashError
from itsdangerous import BadSignature, URLSafeTimedSerializer

from config import settings

logger = logging.getLogger(__name__)

# --- Argon2id ----------------------------------------------------------------

_hasher: Optional[PasswordHasher] = None


def _get_hasher() -> PasswordHasher:
    global _hasher
    if _hasher is None:
        _hasher = PasswordHasher(
            time_cost=settings.argon2_time_cost,
            memory_cost=settings.argon2_memory_cost,
            parallelism=settings.argon2_parallelism,
            hash_len=32,
            salt_len=16,
            type=Type.ID,
        )
    return _hasher


async def hash_password(password: str) -> str:
    """Hash a password with argon2id in a worker thread (off the event loop)."""
    hasher = _get_hasher()
    return await anyio.to_thread.run_sync(hasher.hash, password)


_dummy_hash: Optional[str] = None


def get_dummy_hash() -> str:
    """A real argon2id hash (configured params) of a fixed constant, used to
    equalize timing on the login not-found path. Built lazily and cached so the
    not-found branch costs the same as a genuine verify — no enumeration via
    timing, and it tracks the configured cost knobs automatically."""
    global _dummy_hash
    if _dummy_hash is None:
        _dummy_hash = _get_hasher().hash("nlq-timing-equalizer-constant")
    return _dummy_hash


async def verify_password(password: str, encoded: str) -> bool:
    """Constant-time verify. Returns True on match, False on mismatch OR
    malformed hash (never raises)."""
    hasher = _get_hasher()
    def _verify() -> bool:
        try:
            hasher.verify(encoded, password)
            return True
        except (VerifyMismatchError, InvalidHashError):
            return False
    return await anyio.to_thread.run_sync(_verify)


# --- Password policy ---------------------------------------------------------

# Conservative: min length 10, reject very common passwords. Plan says
# "min length (e.g. 10), reject common passwords; validated server-side."
MIN_PASSWORD_LENGTH = 10

# A tiny denylist of the most common passwords. Anything in this set is
# rejected. (Real systems would use a larger list; this is a sane floor.)
COMMON_PASSWORDS = frozenset({
    "password", "password1", "password123", "1234567890",
    "qwertyuiop", "letmein123", "iloveyou123", "admin12345",
    "welcome123", "monkey1234", "dragon1234", "sunshine1",
})


def validate_password(password: str) -> Optional[str]:
    """Return None if acceptable, or a user-facing error message."""
    if not isinstance(password, str) or len(password) < MIN_PASSWORD_LENGTH:
        return (
            f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
        )
    if password.lower() in COMMON_PASSWORDS:
        return "That password is too common; please choose another."
    return None


def validate_email(email: str) -> Optional[str]:
    """Return None if acceptable, or a user-facing error message."""
    if not isinstance(email, str):
        return "Email is required."
    e = email.strip()
    if "@" not in e or "." not in e.split("@")[-1]:
        return "Please enter a valid email address."
    if len(e) > 254:  # RFC 5321
        return "Email is too long."
    return None


# --- Session token (signed) -------------------------------------------------

# Itsdangerous serializer for cookie values. The session_secret comes from
# env; default is for dev only (the production boot path refuses to start
# with the default).
def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(settings.session_secret, salt="nlq-auth")


def make_session_token(session_id: str) -> str:
    """Wrap the auth_sessions row id in a signed token for the cookie."""
    return _serializer().dumps(session_id)


def read_session_token(token: str) -> Optional[str]:
    """Return the session id from a signed token, or None if invalid/expired."""
    if not token:
        return None
    try:
        return _serializer().loads(token, max_age=settings.session_ttl_minutes * 60)
    except BadSignature:
        return None
    except Exception:  # noqa: BLE001 - itsdangerous raises generic on expiry
        return None


# --- CSRF (double-submit) ----------------------------------------------------

CSRF_HEADER = "X-CSRF-Token"
CSRF_COOKIE = "nlq_csrf"
CSRF_MAX_AGE_SECONDS = settings.session_ttl_minutes * 60


def make_csrf_token() -> str:
    """Return a fresh CSRF token (random URL-safe string)."""
    return secrets.token_urlsafe(32)


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def validate_csrf(cookie_value: Optional[str], header_value: Optional[str]) -> bool:
    """Constant-time compare. Both must be present and equal."""
    if not cookie_value or not header_value:
        return False
    if len(cookie_value) != len(header_value):
        return False
    return constant_time_equals(cookie_value, header_value)
