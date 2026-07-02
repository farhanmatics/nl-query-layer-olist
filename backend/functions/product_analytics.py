"""Product analytics functions — schema-aware.

Category rankings and product ratings derived from order items,
products, and reviews.
"""
import logging
from typing import Optional

from config import settings
from db import execute_query, execute_scalar
from errors import client_error
from functions._filters import clamp_limit, where_clause
from functions._helpers import col_name, table_for
from schemas.base import SchemaConfig
from validation.dates import parse_date_range

logger = logging.getLogger(__name__)


def _parse_date_token(date_token: Optional[str], filters: dict) -> tuple[Optional[tuple], Optional[dict]]:
    if not date_token:
        return None, None
    try:
        date_range = parse_date_range(date_token, settings.reference_datetime)
        if date_range:
            filters["date_range"] = [
                date_range[0].isoformat(),
                date_range[1].isoformat(),
            ]
        return date_range, None
    except Exception as e:
        return None, {"error": f"Date validation failed: {str(e)}", "filters": filters}


def _category_condition(
    category: str,
    params: list,
    col_cat_en,
    col_cat_pt,
) -> str:
    normalized = str(category).lower().strip()
    params.append(normalized)
    i = len(params)
    params.append(normalized)
    j = len(params)
    return (
        f"(lower(t.{col_name(col_cat_en)}) = ${i} "
        f"OR lower(p.{col_name(col_cat_pt)}) = ${j})"
    )


def make_count_products(cfg: SchemaConfig) -> dict:
    """Count products in the catalog (products table), not orders or line items."""
    schema = {
        "name": "count_products",
        "description": (
            "Count products in the product catalog, optionally filtered by category. "
            "Use this when the user asks how many products exist or 'we have' in a "
            "category — NOT for orders sold (use count_by_category for that)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "description": (
                        "Product category in Portuguese or English "
                        "(optional, e.g., 'perfumaria', 'health_beauty')"
                    ),
                },
            },
            "required": [],
        },
    }

    col_cat_pt = cfg.get_column("product_category_pt")
    col_cat_en = cfg.get_column("product_category_en")
    t_products = table_for(col_cat_pt, cfg)
    t_cat_translation = table_for(col_cat_en, cfg)

    async def execute(category: Optional[str] = None) -> dict:
        filters: dict = {}
        params: list = []
        conditions: list[str] = []

        if category:
            normalized = str(category).lower().strip().replace("_", " ")
            filters["category"] = normalized
            params.append(normalized)
            i = len(params)
            params.append(normalized)
            j = len(params)
            conditions.append(
                f"(lower(t.{col_name(col_cat_en)}) = ${i} "
                f"OR lower(p.{col_name(col_cat_pt)}) = ${j})"
            )

        where = where_clause(conditions)
        from_clause = (
            f"FROM {t_products} p "
            f"LEFT JOIN {t_cat_translation} t "
            f"ON p.{col_name(col_cat_pt)} = t.{col_name(col_cat_pt)}"
        )

        query = f"SELECT COUNT(*) AS count {from_clause} WHERE {where}"

        try:
            count = await execute_scalar(query, *params)
            return {"count": count or 0, "filters": filters}
        except Exception as e:
            logger.error(f"count_products query failed: {e}")
            return {
                "error": client_error(e, "A database error occurred while running your query."),
                "filters": filters,
            }

    return {"schema": schema, "execute": execute}


def make_top_categories(cfg: SchemaConfig) -> dict:
    schema = {
        "name": "top_categories",
        "description": (
            "Top product categories ranked by units sold (count) or revenue, "
            "optionally within a date range. Returns English category names."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "date_token": {
                    "type": "string",
                    "description": (
                        "Date range token: today, yesterday, this_week, last_week, "
                        "this_month, last_month, this_year, last_year"
                    ),
                },
                "limit": {
                    "type": "integer",
                    "description": "Number of categories to return (default 10, clamped to 1..25)",
                },
                "by": {
                    "type": "string",
                    "description": "Ranking measure: 'count' (units sold) or 'revenue'",
                },
            },
            "required": [],
        },
    }

    col_item_price = cfg.get_column("price")
    col_item_freight = cfg.get_column("freight_value")
    col_order_id = cfg.get_column("order_id")
    col_purchase = cfg.get_column("order_purchase_timestamp")
    col_product_id = cfg.get_column("product_id")
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
    ) -> dict:
        filters: dict = {}
        by = str(by).lower().strip()
        if by not in ("count", "revenue"):
            return {"error": "Invalid 'by' value. Use 'count' or 'revenue'", "filters": {}}
        filters["by"] = by

        limit = clamp_limit(limit, default=10)
        filters["limit"] = limit

        date_range, err = _parse_date_token(date_token, filters)
        if err:
            return err

        if by == "revenue":
            measure_sql = f"SUM(oi.{col_name(col_item_price)} + oi.{col_name(col_item_freight)})"
        else:
            measure_sql = "COUNT(*)"

        group_expr = f"COALESCE(t.{col_name(col_cat_en)}, p.{col_name(col_cat_pt)})"
        params: list = []
        conditions: list[str] = []

        if date_range:
            params.extend([date_range[0], date_range[1]])
            conditions.append(f"o.{col_name(col_purchase)} >= $1")
            conditions.append(f"o.{col_name(col_purchase)} <= $2")

        params.append(limit)
        query = (
            f"SELECT {group_expr} AS category, {measure_sql} AS value "
            f"FROM {t_items} oi "
            f"JOIN {t_orders} o ON oi.{col_name(col_order_id)} = o.{col_name(col_order_id)} "
            f"LEFT JOIN {t_products} p ON oi.{col_name(col_product_id)} = p.{col_name(col_product_id)} "
            f"LEFT JOIN {t_cat_translation} t ON p.{col_name(col_cat_pt)} = t.{col_name(col_cat_pt)} "
            f"WHERE {where_clause(conditions)} "
            f"GROUP BY {group_expr} "
            f"ORDER BY value DESC "
            f"LIMIT ${len(params)}"
        )

        try:
            rows = await execute_query(query, *params)
            categories = [
                {
                    "category": r["category"],
                    "value": (int(r["value"]) if by == "count" else float(r["value"] or 0)),
                }
                for r in rows
            ]
            return {"categories": categories, "by": by, "filters": filters}
        except Exception as e:
            logger.error(f"top_categories query failed: {e}")
            return {
                "error": client_error(e, "A database error occurred while running your query."),
                "filters": filters,
            }

    return {"schema": schema, "execute": execute}


def make_products_by_rating(cfg: SchemaConfig) -> dict:
    schema = {
        "name": "products_by_rating",
        "description": (
            "Products ranked by average review score. Only includes products with "
            "at least min_reviews reviews to reduce noise."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "description": "Optional product category in English, e.g. 'health_beauty'",
                },
                "limit": {
                    "type": "integer",
                    "description": "Number of products to return (default 20, clamped to 1..25)",
                },
                "min_reviews": {
                    "type": "integer",
                    "description": "Minimum review count per product (default 10, clamped to 1..100)",
                },
                "sort": {
                    "type": "string",
                    "description": "Sort order: 'best' (highest rating first) or 'worst' (lowest first)",
                },
            },
            "required": [],
        },
    }

    col_order_id = cfg.get_column("order_id")
    col_product_id = cfg.get_column("product_id")
    col_score = cfg.get_column("review_score")
    col_item_price = cfg.get_column("price")
    col_cat_pt = cfg.get_column("product_category_pt")
    col_cat_en = cfg.get_column("product_category_en")

    t_reviews = table_for(col_score, cfg)
    t_orders = table_for(col_order_id, cfg)
    t_items = table_for(col_item_price, cfg)
    t_products = table_for(col_cat_pt, cfg)
    t_cat_translation = table_for(col_cat_en, cfg)

    async def execute(
        category: Optional[str] = None,
        limit: int = 20,
        min_reviews: int = 10,
        sort: str = "best",
    ) -> dict:
        filters: dict = {}

        sort = str(sort).lower().strip()
        if sort not in ("best", "worst"):
            return {"error": "Invalid 'sort' value. Use 'best' or 'worst'", "filters": {}}
        filters["sort"] = sort

        limit = clamp_limit(limit, default=20)
        filters["limit"] = limit

        try:
            min_reviews = int(min_reviews)
        except (TypeError, ValueError):
            min_reviews = 10
        min_reviews = max(1, min(100, min_reviews))
        filters["min_reviews"] = min_reviews

        params: list = []
        conditions: list[str] = []

        if category:
            filters["category"] = str(category).lower().strip()
            conditions.append(
                _category_condition(category, params, col_cat_en, col_cat_pt)
            )

        params.append(min_reviews)
        min_reviews_param = len(params)
        params.append(limit)
        limit_param = len(params)

        order_dir = "DESC" if sort == "best" else "ASC"
        category_expr = f"COALESCE(t.{col_name(col_cat_en)}, p.{col_name(col_cat_pt)})"

        query = (
            f"SELECT oi.{col_name(col_product_id)} AS product_id, "
            f"{category_expr} AS category, "
            f"AVG(r.{col_name(col_score)}) AS avg_rating, "
            f"COUNT(*) AS review_count "
            f"FROM {t_reviews} r "
            f"JOIN {t_orders} o ON r.{col_name(col_order_id)} = o.{col_name(col_order_id)} "
            f"JOIN {t_items} oi ON o.{col_name(col_order_id)} = oi.{col_name(col_order_id)} "
            f"LEFT JOIN {t_products} p ON oi.{col_name(col_product_id)} = p.{col_name(col_product_id)} "
            f"LEFT JOIN {t_cat_translation} t ON p.{col_name(col_cat_pt)} = t.{col_name(col_cat_pt)} "
            f"WHERE {where_clause(conditions)} "
            f"GROUP BY oi.{col_name(col_product_id)}, {category_expr} "
            f"HAVING COUNT(*) >= ${min_reviews_param} "
            f"ORDER BY avg_rating {order_dir} "
            f"LIMIT ${limit_param}"
        )

        try:
            rows = await execute_query(query, *params)
            products = [
                {
                    "product_id": r["product_id"],
                    "category": r["category"],
                    "avg_rating": float(r["avg_rating"] or 0),
                    "review_count": int(r["review_count"]),
                }
                for r in rows
            ]
            return {"products": products, "filters": filters}
        except Exception as e:
            logger.error(f"products_by_rating query failed: {e}")
            return {
                "error": client_error(e, "A database error occurred while running your query."),
                "filters": filters,
            }

    return {"schema": schema, "execute": execute}
