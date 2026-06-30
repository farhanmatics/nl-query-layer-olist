"""Client-facing error text sanitization.

Raw exception strings (especially from the DB driver) can embed schema names,
SQL fragments, or connection details. For regulated customers we must not leak
those to the API client. Callers still log the full exception server-side; this
helper only decides what the *response* may say.
"""
from config import settings


def client_error(exc: Exception, fallback: str) -> str:
    """Return safe error text for the client.

    Returns the raw exception text only when ``expose_internal_errors`` is on
    (dev), otherwise the generic ``fallback`` message. Does no logging itself.
    """
    if settings.expose_internal_errors:
        return str(exc)
    return fallback
