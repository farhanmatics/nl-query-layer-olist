"""list_low_reviews function — schema-aware.

Paginated list of low-scoring reviews (review_score <= score_max) with
optional city and date filters. Complements count_low_reviews by
returning the actual review rows, which is what "share me the last N"
follow-ups need after a count.

Order: most recent by review_creation_date, then review_id for stability.
Limit is clamped to [1, 50]; offset is clamped to [0, +inf).
"""
import logging
from typing import Optional

from db import execute_query, execute_scalar
from validation.cities import resolve_city
from validation.dates import parse_date_range
from config import settings
from errors import client_error
from functions._helpers import col_name, table_for
from schemas.base import SchemaConfig

logger = logging.getLogger(__name__)


SCHEMA = {
    "name": "list_low_reviews",
    "description": (
        "List individual low-scoring reviews (review_score <= score_max), "
        "paginated and ordered by review_creation_date DESC. Returns at most 50 "
        "rows per page. Use for follow-ups like 'share me the last 5' after a "
        "count_low_reviews turn."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "score_max": {
                "type": "integer",
                "description": "Maximum review score to include (default 2, clamped to 1..5)",
            },
            "city": {"type": "string", "description": "Customer city (optional, will be normalized)"},
            "date_token": {
                "type": "string",
                "description": (
                    "Date range token: 'today', 'yesterday', 'this_week', 'last_week', "
                    "'this_month', 'last_month', 'this_year', 'last_year'"
                ),
            },
            "limit": {
                "type": "integer",
                "description": "Max rows per page (default 5, max 50)",
            },
            "offset": {
                "type": "integer",
                "description": "Rows to skip for pagination (default 0)",
            },
        },
        "required": [],
    },
}


def make_list_low_reviews(cfg: SchemaConfig) -> dict:
    cust_id = cfg.get_column("customer_id")
    col_order_id = cfg.get_column("order_id")
    col_score = cfg.get_column("review_score")
    col_review_date = cfg.get_column("review_creation_date")
    col_review_id = cfg.get_column("review_id")
    col_city = cfg.get_column("customer_city")
    col_state = cfg.get_column("customer_state")

    async def execute(
        score_max: int = 2,
        city: Optional[str] = None,
        date_token: Optional[str] = None,
        limit: int = 5,
        offset: int = 0,
    ) -> dict:
        filters: dict = {}

        try:
            score_max = int(score_max)
        except (ValueError, TypeError):
            score_max = 2
        score_max = max(1, min(5, score_max))
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
                    filters["date_range"] = [
                        date_range[0].isoformat(),
                        date_range[1].isoformat(),
                    ]
            except Exception as e:
                return {"error": f"Date validation failed: {str(e)}", "filters": filters}

        try:
            limit = int(limit)
        except (TypeError, ValueError):
            limit = 5
        limit = max(1, min(50, limit))
        filters["limit"] = limit

        try:
            offset = int(offset)
        except (TypeError, ValueError):
            offset = 0
        offset = max(0, offset)
        filters["offset"] = offset

        t_reviews = table_for(col_score, cfg)
        t_orders = table_for(col_order_id, cfg)
        t_customers = table_for(col_city, cfg)

        where = f" WHERE r.{col_name(col_score)} <= $1"
        params: list = [score_max]

        if normalized_city:
            where += f" AND c.{col_name(col_city)} = ${len(params) + 1}"
            params.append(normalized_city)

        if date_range:
            where += f" AND r.{col_name(col_review_date)} >= ${len(params) + 1}"
            where += f" AND r.{col_name(col_review_date)} <= ${len(params) + 2}"
            params.extend([date_range[0], date_range[1]])

        count_query = (
            f"SELECT COUNT(*) "
            f"FROM {t_reviews} r "
            f"JOIN {t_orders} o ON r.{col_name(col_order_id)} = o.{col_name(col_order_id)} "
            f"LEFT JOIN {t_customers} c ON o.{col_name(cust_id)} = c.{col_name(cust_id)} "
            f"{where}"
        )

        rows_query = (
            f"SELECT r.{col_name(col_review_id)} AS review_id, "
            f"r.{col_name(col_order_id)} AS order_id, "
            f"r.{col_name(col_score)} AS review_score, "
            f"r.{col_name(col_review_date)} AS review_creation_date, "
            f"c.{col_name(col_city)} AS customer_city, "
            f"c.{col_name(col_state)} AS customer_state "
            f"FROM {t_reviews} r "
            f"JOIN {t_orders} o ON r.{col_name(col_order_id)} = o.{col_name(col_order_id)} "
            f"LEFT JOIN {t_customers} c ON o.{col_name(cust_id)} = c.{col_name(cust_id)} "
            f"{where} "
            f"ORDER BY r.{col_name(col_review_date)} DESC NULLS LAST, "
            f"r.{col_name(col_review_id)} DESC "
            f"LIMIT ${len(params) + 1} OFFSET ${len(params) + 2}"
        )

        rows_params = params + [limit, offset]

        try:
            total = await execute_scalar(count_query, *params)
            rows = await execute_query(rows_query, *rows_params)
            reviews = [
                {
                    "review_id": r["review_id"],
                    "order_id": r["order_id"],
                    "review_score": r["review_score"],
                    "review_creation_date": (
                        r["review_creation_date"].isoformat()
                        if r["review_creation_date"]
                        else None
                    ),
                    "customer_city": r["customer_city"],
                    "customer_state": r["customer_state"],
                }
                for r in rows
            ]
            return {
                "reviews": reviews,
                "total_count": total or 0,
                "limit": limit,
                "offset": offset,
                "filters": filters,
            }
        except Exception as e:
            logger.error(f"list_low_reviews query failed: {e}")
            return {
                "error": client_error(
                    e, "A database error occurred while running your query."
                ),
                "filters": filters,
            }

    return {"schema": SCHEMA, "execute": execute}
