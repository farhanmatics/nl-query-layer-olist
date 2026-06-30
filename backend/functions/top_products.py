"""top_products function — schema-aware.

Top-N products by units sold (`by='count'`) or revenue
(`by='revenue'`, measured as price + freight), with English category
names where the schema has a translation table. Limit is clamped to
[1, 25].
"""
import logging
from typing import Optional
from db import execute_query
from validation.dates import parse_date_range
from config import settings
from errors import client_error
from schemas.base import SchemaConfig

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
            "limit": {"type": "integer", "description": "Number of products to return (default 10, clamped to 1..25)"},
            "by": {"type": "string", "description": "Ranking measure: 'count' (units sold) or 'revenue' (sum of price + freight)"},
        },
        "required": [],
    },
}


def make_top_products(cfg: SchemaConfig) -> dict:
    t_items = cfg.get_table("order_items")
    t_orders = cfg.get_table("orders")
    t_products = cfg.get_table("products")
    t_cat_translation = cfg.get_table("product_category_translation")

    col_item_price = cfg.get_column("price")
    col_item_freight = cfg.get_column("freight_value")
    col_order_id = cfg.get_column("order_id").column
    col_product_id = cfg.get_column("product_id").column
    col_purchase = cfg.get_column("order_purchase_timestamp").column
    col_cat_pt = cfg.get_column("product_category_pt").column
    col_cat_en = cfg.get_column("product_category_en").column

    async def execute(
        date_token: Optional[str] = None,
        limit: int = 10,
        by: str = "count",
    ) -> dict:
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
            measure_sql = f"SUM(oi.{col_item_price.column} + oi.{col_item_freight.column})"
        else:
            measure_sql = "COUNT(*)"

        query = (
            f"SELECT oi.{col_product_id}, "
            f"COALESCE(t.{col_cat_en}, p.{col_cat_pt}) AS category, "
            f"{measure_sql} AS value "
            f"FROM {t_items} oi "
            f"JOIN {t_orders} o ON oi.{col_order_id} = o.{col_order_id} "
            f"LEFT JOIN {t_products} p ON oi.{col_product_id} = p.{col_product_id} "
            f"LEFT JOIN {t_cat_translation} t ON p.{col_cat_pt} = t.{col_cat_pt} "
            f"WHERE 1=1"
        )

        params = []

        if date_range:
            query += f" AND o.{col_purchase} >= ${len(params) + 1}"
            query += f" AND o.{col_purchase} <= ${len(params) + 2}"
            params.extend([date_range[0], date_range[1]])

        query += (
            f" GROUP BY oi.{col_product_id}, COALESCE(t.{col_cat_en}, p.{col_cat_pt})"
            f" ORDER BY value DESC"
            f" LIMIT ${len(params) + 1}"
        )
        params.append(limit)

        try:
            rows = await execute_query(query, *params)
            products = [
                {
                    "product_id": r[col_product_id],
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

    return {"schema": SCHEMA, "execute": execute}
