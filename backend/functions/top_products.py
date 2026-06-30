import logging
from typing import Optional
from db import execute_query
from validation.dates import parse_date_range
from config import settings
from errors import client_error

logger = logging.getLogger(__name__)

SCHEMA = {
    "name": "top_products",
    "description": "Top-N products ranked by units sold (count) or revenue, optionally within a date range. Returns English category names.",
    "parameters": {
        "type": "object",
        "properties": {
            "date_token": {
                "type": "string",
                "description": "Date range token: 'today', 'yesterday', 'this_week', 'last_week', 'this_month', 'last_month', 'this_year', 'last_year'",
            },
            "limit": {
                "type": "integer",
                "description": "Number of products to return (default 10, clamped to 1..25)",
            },
            "by": {
                "type": "string",
                "description": "Ranking measure: 'count' (units sold) or 'revenue' (sum of price + freight)",
            },
        },
        "required": [],
    },
}


async def execute(
    date_token: Optional[str] = None,
    limit: int = 10,
    by: str = "count",
) -> dict:
    """
    Return the top-N products ranked by units sold or revenue.

    Returns:
        {
            "products": [
                {"product_id": str, "category": str | None, "value": int | float},
                ...
            ],
            "by": str,
            "filters": {
                "by": str,
                "limit": int,
                "date_range": [start_iso, end_iso] | None,
            }
        }
    """
    filters = {}

    by = str(by).lower().strip()
    if by not in ("count", "revenue"):
        return {"error": "Invalid 'by' value. Use 'count' or 'revenue'", "filters": {}}
    filters["by"] = by

    limit = int(limit)
    limit = max(1, min(25, limit))
    filters["limit"] = limit

    date_range = None
    if date_token:
        try:
            date_range = parse_date_range(date_token, settings.reference_datetime)
            if date_range:
                filters["date_range"] = [date_range[0].isoformat(), date_range[1].isoformat()]
        except Exception as e:
            return {"error": f"Date validation failed: {str(e)}", "filters": filters}

    if by == "revenue":
        measure_sql = "SUM(oi.price + oi.freight_value)"
    else:
        measure_sql = "COUNT(*)"

    query = """
    SELECT oi.product_id,
           COALESCE(t.product_category_name_english, p.product_category_name) AS category,
           """ + measure_sql + """ AS value
    FROM olist_order_items_dataset oi
    JOIN olist_orders_dataset o ON oi.order_id = o.order_id
    LEFT JOIN olist_products_dataset p ON oi.product_id = p.product_id
    LEFT JOIN product_category_name_translation t ON p.product_category_name = t.product_category_name
    WHERE 1=1
    """

    params = []

    if date_range:
        query += " AND o.order_purchase_timestamp >= $" + str(len(params) + 1)
        query += " AND o.order_purchase_timestamp <= $" + str(len(params) + 2)
        params.extend([date_range[0], date_range[1]])

    query += """
    GROUP BY oi.product_id, COALESCE(t.product_category_name_english, p.product_category_name)
    ORDER BY value DESC
    LIMIT $""" + str(len(params) + 1)
    params.append(limit)

    try:
        rows = await execute_query(query, *params)
        products = [
            {
                "product_id": r["product_id"],
                "category": r["category"],
                "value": (int(r["value"]) if by == "count" else float(r["value"] or 0)),
            }
            for r in rows
        ]
        return {
            "products": products,
            "by": by,
            "filters": filters,
        }
    except Exception as e:
        logger.error(f"Query failed: {e}")
        return {
            "error": client_error(e, "A database error occurred while running your query."),
            "filters": filters,
        }
