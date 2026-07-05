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
from functions._helpers import col_name, table_for
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
            "category": {
                "type": "string",
                "description": "Optional product category (Portuguese or English), e.g. 'perfumaria', 'health_beauty'",
            },
        },
        "required": [],
    },
}


def make_top_products(cfg: SchemaConfig) -> dict:
    col_product_id = cfg.get_column("product_id")
    col_order_id = cfg.get_column("order_id")
    col_item_price = cfg.get_column("price")
    col_item_freight = cfg.get_column("freight_value")
    col_purchase = cfg.get_column("order_purchase_timestamp")
    col_cat_pt = cfg.get_column("product_category_pt")
    col_cat_en = cfg.get_column("product_category_en")

    t_items = table_for(col_item_price, cfg)
    t_orders = table_for(col_purchase, cfg)
    t_products = table_for(col_cat_pt, cfg)
    t_cat_translation = table_for(col_cat_en, cfg)

    async def execute(
        date_token: Optional[str] = None,
        limit: int = 10,
        by: str = "count",
        category: Optional[str] = None,
    ) -> dict:
        filters = {}

        by = str(by).lower().strip()
        if by not in ("count", "revenue"):
            return {"error": "Invalid 'by' value. Use 'count' or 'revenue'", "filters": {}}
        filters["by"] = by

        limit = int(limit)
        limit = max(1, min(25, limit))
        filters["limit"] = limit

        normalized_category = None
        if category:
            normalized_category = str(category).lower().strip()
            filters["category"] = normalized_category

        date_range = None
        if date_token:
            try:
                date_range = parse_date_range(date_token, settings.reference_datetime)
                if date_range:
                    filters["date_range"] = [date_range[0].isoformat(), date_range[1].isoformat()]
            except Exception as e:
                return {"error": f"Date validation failed: {str(e)}", "filters": filters}

        if by == "revenue":
            measure_sql = f"SUM(oi.{col_name(col_item_price)} + oi.{col_name(col_item_freight)})"
        else:
            measure_sql = "COUNT(*)"

        # Items join to orders by order_id; items join to products by
        # product_id. Two different columns, two different joins.
        query = (
            f"SELECT oi.{col_name(col_product_id)}, "
            f"COALESCE(t.{col_name(col_cat_en)}, p.{col_name(col_cat_pt)}) AS category, "
            f"{measure_sql} AS value "
            f"FROM {t_items} oi "
            f"JOIN {t_orders} o ON oi.{col_name(col_order_id)} = o.{col_name(col_order_id)} "
            f"LEFT JOIN {t_products} p ON oi.{col_name(col_product_id)} = p.{col_name(col_product_id)} "
            f"LEFT JOIN {t_cat_translation} t ON p.{col_name(col_cat_pt)} = t.{col_name(col_cat_pt)} "
            f"WHERE 1=1"
        )

        params = []

        if normalized_category:
            params.append(normalized_category)
            i = len(params)
            params.append(normalized_category)
            j = len(params)
            query += (
                f" AND (lower(t.{col_name(col_cat_en)}) = ${i} "
                f"OR lower(p.{col_name(col_cat_pt)}) = ${j})"
            )

        if date_range:
            query += f" AND o.{col_name(col_purchase)} >= ${len(params) + 1}"
            query += f" AND o.{col_name(col_purchase)} <= ${len(params) + 2}"
            params.extend([date_range[0], date_range[1]])

        query += (
            f" GROUP BY oi.{col_name(col_product_id)}, COALESCE(t.{col_name(col_cat_en)}, p.{col_name(col_cat_pt)})"
            f" ORDER BY value DESC"
            f" LIMIT ${len(params) + 1}"
        )
        params.append(limit)

        try:
            rows = await execute_query(query, *params)
            products = [
                {
                    "product_id": r[col_name(col_product_id)],
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
