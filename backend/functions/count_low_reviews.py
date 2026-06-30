"""count_low_reviews function — schema-aware.

Count reviews with `review_score <= score_max`, optionally filtered
by city and date range. The schema for Olist has a separate
`order_reviews` table; for Shopify it's a column on orders. The factory
emits the right SQL for the active schema.
"""
import logging
from typing import Optional
from db import execute_scalar
from validation.cities import resolve_city
from validation.dates import parse_date_range
from config import settings
from errors import client_error
from functions._helpers import col_name, table_for
from schemas.base import SchemaConfig

logger = logging.getLogger(__name__)


SCHEMA = {
    "name": "count_low_reviews",
    "description": "Count low-scoring reviews (review_score <= score_max), optionally filtered by city and date range. Used as the disputes/complaints analog.",
    "parameters": {
        "type": "object",
        "properties": {
            "score_max": {"type": "integer", "description": "Maximum review score to count (default 2, clamped to 1..5)"},
            "city": {"type": "string", "description": "Customer city (optional, will be normalized)"},
            "date_token": {
                "type": "string",
                "description": "Date range token: 'today', 'yesterday', 'this_week', 'last_week', 'this_month', 'last_month', 'this_year', 'last_year'",
            },
        },
        "required": [],
    },
}


def make_count_low_reviews(cfg: SchemaConfig) -> dict:
    cust_id = cfg.get_column("customer_id")
    col_order_id = cfg.get_column("order_id")
    col_score = cfg.get_column("review_score")
    col_review_date = cfg.get_column("review_creation_date")
    col_city = cfg.get_column("customer_city")

    async def execute(
        score_max: int = 2,
        city: Optional[str] = None,
        date_token: Optional[str] = None,
    ) -> dict:
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

        # The review row joins to the order by order_id; the order joins
        # to the customer by customer_id. The config wires both columns
        # so the SQL is identical across schemas.
        # The review table is whichever table the `review_score` column
        # lives in (order_reviews in Olist, orders in Shopify).
        t_reviews = table_for(col_score, cfg)
        t_orders = table_for(col_order_id, cfg)
        t_customers = table_for(col_city, cfg)
        query = (
            f"SELECT COUNT(*) AS count "
            f"FROM {t_reviews} r "
            f"JOIN {t_orders} o ON r.{col_name(col_order_id)} = o.{col_name(col_order_id)} "
            f"LEFT JOIN {t_customers} c ON o.{col_name(cust_id)} = c.{col_name(cust_id)} "
            f"WHERE r.{col_name(col_score)} <= $1"
        )

        params = [score_max]

        if normalized_city:
            query += f" AND c.{col_name(col_city)} = ${len(params) + 1}"
            params.append(normalized_city)

        if date_range:
            query += f" AND r.{col_name(col_review_date)} >= ${len(params) + 1}"
            query += f" AND r.{col_name(col_review_date)} <= ${len(params) + 2}"
            params.extend([date_range[0], date_range[1]])

        try:
            count = await execute_scalar(query, *params)
            return {"count": count or 0, "filters": filters}
        except Exception as e:
            logger.error(f"Query failed: {e}")
            return {
                "error": client_error(e, "A database error occurred while running your query."),
                "filters": filters,
            }

    return {"schema": SCHEMA, "execute": execute}
