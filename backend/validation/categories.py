"""Category loader — schema-aware.

The known-category set is loaded from the active schema's
`product_category_translation` table on startup (PT name + English
name). The detector normalizes underscores to spaces so the
known-set's space-separated form matches the user's "health_beauty"
typing.
"""
import logging
import unicodedata
from typing import Optional

from db import execute_query
from schemas import get_active_config

logger = logging.getLogger(__name__)

_known_categories: Optional[set[str]] = None


def _normalize_for_set(name: str) -> str:
    """Lowercase, strip accents, underscores→spaces. Mirrors the
    detector's normalization so the known set matches user input."""
    if not name:
        return ""
    s = name.lower().strip().replace("_", " ")
    nfkd = unicodedata.normalize("NFKD", s)
    return " ".join("".join(c for c in nfkd if unicodedata.category(c) != "Mn").split())


async def load_known_categories() -> set[str]:
    """Load categories from the active schema's translation table."""
    global _known_categories
    if _known_categories is not None:
        return _known_categories

    cfg = get_active_config()
    t = cfg.get_table("product_category_translation")
    col_pt = cfg.get_column("product_category_pt").column
    col_en = cfg.get_column("product_category_en").column

    query = (
        f"SELECT {col_pt}, {col_en} FROM {t} "
        f"WHERE {col_pt} IS NOT NULL"
    )
    try:
        rows = await execute_query(query, enforce_cap=False)
    except Exception as e:
        logger.error(f"Failed to load categories: {e}")
        _known_categories = set()
        return _known_categories

    names: set[str] = set()
    for row in rows:
        for col in (col_pt, col_en):
            v = row.get(col)
            if v:
                names.add(_normalize_for_set(v))
    _known_categories = names
    logger.info(
        f"Loaded {len(_known_categories)} unique categories from {cfg.name}"
    )
    return _known_categories


def get_loaded_categories() -> set[str]:
    """Synchronous accessor for the already-loaded category set."""
    return _known_categories or set()
