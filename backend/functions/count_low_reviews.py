import logging
from typing import Optional
from db import execute_scalar
from validation.cities import resolve_city
from validation.dates import parse_date_range
from config import settings
from errors import client_error

logger = logging.getLogger(__name__)

SCHEMA = {
    "name": "count_low_reviews",
    "description": "Count low-scoring reviews (review_score <= score_max), optionally filtered by city and date range. Used as the disputes/complaints analog.",
    "parameters": {
        "type": "object",
        "properties": {
            "score_max": {
                "type": "integer",
                "description": "Maximum review score to count (default 2, clamped to 1..5)",
            },
            "city": {
                "type": "string",
                "description": "Customer city (optional, will be normalized)",
            },
            "date_token": {
                "type": "string",
                "description": "Date range token: 'today', 'yesterday', 'this_week', 'last_week', 'this_month', 'last_month', 'this_year', 'last_year'",
            },
        },
        "required": [],
    },
}


async def execute(
    score_max: int = 2,
    city: Optional[str] = None,
    date_token: Optional[str] = None,
) -> dict:
    """
    Count low-scoring reviews with optional filters.

    Returns:
        {
            "count": int,
            "filters": {
                "score_max": int,
                "city": str | None,
                "date_range": [start_iso, end_iso] | None,
            }
        }
    """
    filters = {}

    try:
        score_max = int(score_max)
    except (ValueError, TypeError):
        score_max = 2
    if score_max < 1:
        score_max = 1
    elif score_max > 5:
        score_max = 5
    filters["score_max"] = score_max

    normalized_city = None
    if city:
        try:
            normalized_city = await resolve_city(city)
            if not normalized_city:
                return {
                    "error": f"City '{city}' not found in database",
                    "filters": {"city": city},
                }
            filters["city"] = normalized_city
        except Exception as e:
            return {"error": f"City validation failed: {str(e)}", "filters": {}}

    date_range = None
    if date_token:
        try:
            date_range = parse_date_range(date_token, settings.reference_datetime)
            if date_range:
                filters["date_range"] = [date_range[0].isoformat(), date_range[1].isoformat()]
        except Exception as e:
            return {"error": f"Date validation failed: {str(e)}", "filters": filters}

    query = """
    SELECT COUNT(*) AS count
    FROM olist_order_reviews_dataset r
    JOIN olist_orders_dataset o ON r.order_id = o.order_id
    LEFT JOIN olist_customers_dataset c ON o.customer_id = c.customer_id
    WHERE r.review_score <= $1
    """

    params = [score_max]

    if normalized_city:
        query += " AND c.customer_city = $" + str(len(params) + 1)
        params.append(normalized_city)

    if date_range:
        query += " AND r.review_creation_date >= $" + str(len(params) + 1)
        query += " AND r.review_creation_date <= $" + str(len(params) + 2)
        params.extend([date_range[0], date_range[1]])

    try:
        count = await execute_scalar(query, *params)
        return {
            "count": count or 0,
            "filters": filters,
        }
    except Exception as e:
        logger.error(f"Query failed: {e}")
        return {
            "error": client_error(e, "A database error occurred while running your query."),
            "filters": filters,
        }
