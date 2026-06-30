"""Schema registry: load the active SchemaConfig by name.

The active schema is selected at startup from the `SCHEMA` env var
(default: `olist`). To add a new schema:

  1. Create `backend/schemas/<name>/config.py` exporting `CONFIG: SchemaConfig`
  2. Add a case in `_BUILTIN` below (or wire it as a plugin if you
     don't want to touch this file)
  3. Set `SCHEMA=<name>` in the environment

The active config is cached on first call to `get_active_config()`.
Tests that need an isolated config can use `set_active_config(...)`
to inject a different one (and reset to None when done).
"""
import importlib
import logging
import os
import threading
from typing import Optional

from schemas.base import SchemaConfig

logger = logging.getLogger(__name__)


# Built-in schemas shipped in this repo. Add new ones by importing
# their config module here and adding a name -> module entry.
def _load_olist() -> SchemaConfig:
    from schemas.olist.config import CONFIG
    return CONFIG


def _load_shopify() -> SchemaConfig:
    from schemas.shopify.config import CONFIG
    return CONFIG


_BUILTIN = {
    "olist": _load_olist,
    "shopify": _load_shopify,
}


_lock = threading.Lock()
_active: Optional[SchemaConfig] = None


def get_active_config() -> SchemaConfig:
    """Return the active SchemaConfig, loading it on first call.

    Selection order: explicit override (set via `set_active_config`,
    used by tests) → `SCHEMA` env var (or `settings.schema` if not set
    in env) → 'olist' default.
    """
    global _active
    if _active is not None:
        return _active
    with _lock:
        if _active is not None:
            return _active
        # Read from env first (lets operators override at runtime), then
        # fall back to settings.schema_name (which defaults to "olist").
        name = (
            os.environ.get("SCHEMA_NAME")
            or _settings_schema_default()
            or "olist"
        ).strip().lower()
        loader = _BUILTIN.get(name)
        if loader is None:
            available = ", ".join(sorted(_BUILTIN.keys()))
            raise RuntimeError(
                f"Unknown schema {name!r}. Available: {available}. "
                f"Add a new schema under backend/schemas/<name>/config.py "
                f"and register it in _BUILTIN."
            )
        config = loader()
        logger.info(
            f"Loaded schema config: name={config.name!r} "
            f"display_name={config.display_name!r} "
            f"tables={len(config.tables)} columns={len(config.columns)} "
            f"enums={len(config.enums)} functions={len(config.function_factories)}"
        )
        _active = config
        return _active


def _settings_schema_default() -> Optional[str]:
    """Return settings.schema_name, importing lazily to avoid a circular
    import at module load (settings → pydantic → ?). Returns None if
    the settings module isn't importable yet."""
    try:
        from config import settings
        return settings.schema_name
    except Exception:  # noqa: BLE001
        return None


def set_active_config(config: Optional[SchemaConfig]) -> None:
    """Override the active config (for tests). Pass None to reset."""
    global _active
    _active = config


def list_available_schemas() -> list[str]:
    """Return the names of every schema this build knows about."""
    return sorted(_BUILTIN.keys())


def reload_active_config() -> SchemaConfig:
    """Drop the cache and re-load from env. Used after SCHEMA env changes
    in tests. Production code should never need this — restart the
    process to pick up a new schema."""
    global _active
    with _lock:
        _active = None
    return get_active_config()
