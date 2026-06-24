import logging
import unicodedata
import difflib
from typing import Optional
from db import execute_query

logger = logging.getLogger(__name__)

_known_cities = None


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
    """Load all known cities from database on startup."""
    global _known_cities
    if _known_cities is not None:
        return _known_cities

    try:
        rows = await execute_query(
            "SELECT DISTINCT customer_city FROM olist_customers_dataset WHERE customer_city IS NOT NULL"
        )
        _known_cities = {normalize(row["customer_city"]) for row in rows}
        logger.info(f"Loaded {len(_known_cities)} unique cities from database")
        return _known_cities
    except Exception as e:
        logger.error(f"Failed to load cities: {e}")
        _known_cities = set()
        return _known_cities


async def resolve_city(city_input: str) -> Optional[str]:
    """
    Resolve a user-input city name to a canonical normalized city name.

    Returns:
    - Normalized city name if found
    - None if not found (and suggest closest match in error)
    """
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
