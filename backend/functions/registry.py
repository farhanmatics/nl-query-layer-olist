"""Function registry: maps tool names to executable handlers.

The registry is SCHEMA-AWARE. It materializes function entries at
startup by calling each `SchemaConfig.function_factories` with the
active config. Switching `SCHEMA=shopify` rebuilds the registry with
the shopify factories.

Why not just import functions at module load?  Because the factories
need the active config, which itself is loaded lazily (so a process
can boot without env vars set, then pick the right schema based on
the first /api/query or startup hook).
"""
import logging
from typing import Optional

from schemas import get_active_config, SchemaConfig

logger = logging.getLogger(__name__)


# The active registry. Rebuilt when the schema changes (tests only; prod
# never swaps schemas in-process).
_FUNCTIONS: dict[str, dict] = {}


def _build_registry(config: SchemaConfig) -> dict[str, dict]:
    """Call every factory in the config and collect their registry entries."""
    reg: dict[str, dict] = {}
    for factory in config.function_factories:
        entry = factory(config)
        name = entry["schema"]["name"]
        reg[name] = entry
        logger.info(f"Registered function: {name} (schema={config.name})")
    return reg


def get_function(name: str) -> dict:
    """Get a function handler by name. Raises KeyError if not found."""
    if not _FUNCTIONS:
        _FUNCTIONS.update(_build_registry(get_active_config()))
    if name not in _FUNCTIONS:
        raise KeyError(f"Unknown function: {name}")
    return _FUNCTIONS[name]


def get_all_schemas() -> list[dict]:
    """Get JSON schemas for all registered functions (for the LLM)."""
    if not _FUNCTIONS:
        _FUNCTIONS.update(_build_registry(get_active_config()))
    return [_FUNCTIONS[name]["schema"] for name in sorted(_FUNCTIONS.keys())]


def list_functions() -> list[str]:
    """List all registered function names."""
    if not _FUNCTIONS:
        _FUNCTIONS.update(_build_registry(get_active_config()))
    return sorted(_FUNCTIONS.keys())


def reset_registry() -> None:
    """Drop the cached registry. Tests use this to force a rebuild
    after switching `SCHEMA` env var; production code should never
    need it (process restart for schema changes)."""
    _FUNCTIONS.clear()
