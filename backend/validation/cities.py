"""City normalization + lookup — schema-aware.

The known-city set is loaded from the active schema's `customers`
table on startup, normalized (lowercase + accent-stripped), and exposed
synchronously via `get_known_cities()`. Resolution of a user-typed
city name uses difflib to suggest the closest match.
"""
import logging
import unicodedata
import difflib
from typing import Optional

from db import execute_query
from schemas import get_active_config

logger = logging.getLogger(__name__)

_known_cities: Optional[set[str]] = None


class ValidationError(Exception):
    pass


def normalize(city: str) -> str:
    """Normalize city name: lowercase + strip accents."""
    if not city:
        return ""
    city = city.lower().strip()
    nfkd = unicodedata.normalize("NFKD", city)
    return "".join(c for c in nfkd if unicodedata.category(c) != "Mn")


async def load_known_cities() -> set[str]:
    """Load all known cities from the active schema's customers table.

    The query is built from the active config so it works against
    `olist_customers_dataset` (Olist) or `shopify_customers` (Shopify)
    or any future schema with the same `customer_city` logical key.
    """
    global _known_cities
    if _known_cities is not None:
        return _known_cities

    cfg = get_active_config()
    t_customers = cfg.get_table("customers")
    col_city = cfg.get_column("customer_city").column
    query = (
        f"SELECT DISTINCT {col_city} FROM {t_customers} "
        f"WHERE {col_city} IS NOT NULL"
    )
    try:
        rows = await execute_query(
            query,
            enforce_cap=False,  # trusted internal dictionary load
        )
        _known_cities = {normalize(row[col_city]) for row in rows}
        logger.info(
            f"Loaded {len(_known_cities)} unique cities from {cfg.name} customers"
        )
        return _known_cities
    except Exception as e:
        logger.error(f"Failed to load cities: {e}")
        _known_cities = set()
        return _known_cities


def get_known_cities() -> set[str]:
    """Synchronous accessor; used by the faithfulness guard which must
    not block on the DB during a request."""
    return _known_cities or set()


async def resolve_city(city_input: str) -> Optional[str]:
    """Resolve a user-input city name to a canonical normalized form, or
    None if no reasonable match exists."""
    known_cities = await load_known_cities()
    if not known_cities:
        raise ValidationError("City database not loaded")

    normalized = normalize(city_input)
    if normalized in known_cities:
        return normalized

    closest = difflib.get_close_matches(normalized, known_cities, n=1, cutoff=0.85)
    if closest:
        logger.warning(
            f"City '{city_input}' not exact match, using suggestion '{closest[0]}'"
        )
        return closest[0]

    logger.warning(f"City '{city_input}' not found and no close matches")
    return None
