"""Quality and satisfaction metric functions — schema-aware.

Product, seller, and category ratings; review score distribution;
and satisfaction trends over time.
"""
import logging
from typing import Optional

from config import settings
from db import execute_query
from errors import client_error
from functions._filters import clamp_limit, resolve_order_filters, where_clause
from functions._helpers import col_name, table_for
from schemas.base import SchemaConfig
from validation.dates import parse_date_range

logger = logging.getLogger(__name__)

VALID_GRANULARITIES = {"month"}


def _parse_review_date_token(
    date_token: Optional[str], filters: dict
) -> tuple[Optional[tuple], Optional[dict]]:
    if not date_token:
        return None, None
    try:
        date_range = parse_date_range(date_token, settings.reference_datetime)
        if date_range:
            filters["date_range"] = [date_range[0].isoformat(), date_range[1].isoformat()]
        return date_range, None
    except Exception as e:
        return None, {"error": f"Date validation failed: {str(e)}", "filters": filters}


def _category_condition(col_cat_pt, col_cat_en, category: str, params: list) -> str:
    normalized = str(category).lower().strip().replace("_", " ")
    params.append(normalized)
    i = len(params)
    params.append(normalized)
    j = len(params)
    return (
        f"(lower(t.{col_name(col_cat_en)}) = ${i} "
        f"OR lower(p.{col_name(col_cat_pt)}) = ${j})"
    )


AVERAGE_RATING_BY_PRODUCT_SCHEMA = {
    "name": "average_rating_by_product",
    "description": (
        "Average review score grouped by product, with English category names. "
        "Only products with at least one review are included."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "category": {
                "type": "string",
                "description": "Product category in English (optional), e.g. 'health_beauty'",
            },
            "limit": {
                "type": "integer",
                "description": "Number of products to return (default 20, max 25)",
            },
        },
        "required": [],
    },
}


AVERAGE_RATING_BY_SELLER_SCHEMA = {
    "name": "average_rating_by_seller",
    "description": "Average review score grouped by seller, optionally filtered by seller state.",
    "parameters": {
        "type": "object",
        "properties": {
            "state": {"type": "string", "description": "Seller state/UF (optional, e.g., 'SP', 'RJ')"},
            "limit": {
                "type": "integer",
                "description": "Number of sellers to return (default 10, max 25)",
            },
        },
        "required": [],
    },
}


AVERAGE_RATING_BY_CATEGORY_SCHEMA = {
    "name": "average_rating_by_category",
    "description": "Average review score grouped by product category (English names where available).",
    "parameters": {
        "type": "object",
        "properties": {},
        "required": [],
    },
}


REVIEW_SCORE_DISTRIBUTION_SCHEMA = {
    "name": "review_score_distribution",
    "description": "Count of reviews grouped by review score (1 through 5).",
    "parameters": {
        "type": "object",
        "properties": {
            "date_token": {
                "type": "string",
                "description": "Date range token applied to review_creation_date",
            },
            "state": {"type": "string", "description": "Customer state/UF (optional, e.g., 'SP', 'RJ')"},
            "seller_id": {"type": "string", "description": "Seller ID (optional)"},
        },
        "required": [],
    },
}


REVIEW_SENTIMENT_TREND_SCHEMA = {
    "name": "review_sentiment_trend",
    "description": "Average review score over time, grouped by month from review_creation_date.",
    "parameters": {
        "type": "object",
        "properties": {
            "date_token": {
                "type": "string",
                "description": "Date range token applied to review_creation_date",
            },
            "granularity": {
                "type": "string",
                "enum": ["month"],
                "description": "Time bucket granularity (default 'month')",
            },
        },
        "required": [],
    },
}


def make_average_rating_by_product(cfg: SchemaConfig) -> dict:
    col_score = cfg.get_column("review_score")
    col_order_id = cfg.get_column("order_id")
    col_product_id = cfg.get_column("product_id")
    col_cat_pt = cfg.get_column("product_category_pt")
    col_cat_en = cfg.get_column("product_category_en")

    t_reviews = table_for(col_score, cfg)
    t_orders = table_for(col_order_id, cfg)
    t_items = table_for(col_product_id, cfg)
    t_products = table_for(col_cat_pt, cfg)
    t_cat_translation = table_for(col_cat_en, cfg)

    async def execute(category: Optional[str] = None, limit: int = 20) -> dict:
        filters: dict = {}
        limit = clamp_limit(limit, default=20)
        filters["limit"] = limit

        if category:
            filters["category"] = str(category).lower().strip().replace("_", " ")

        params: list = []
        conditions: list[str] = []

        if category:
            conditions.append(_category_condition(col_cat_pt, col_cat_en, category, params))

        where = where_clause(conditions)
        limit_idx = len(params) + 1
        params.append(limit)

        category_expr = f"COALESCE(t.{col_name(col_cat_en)}, p.{col_name(col_cat_pt)})"

        query = (
            f"SELECT oi.{col_name(col_product_id)} AS product_id, "
            f"{category_expr} AS category, "
            f"ROUND(AVG(r.{col_name(col_score)})::numeric, 2) AS avg_rating, "
            f"COUNT(*) AS review_count "
            f"FROM {t_reviews} r "
            f"JOIN {t_orders} o ON r.{col_name(col_order_id)} = o.{col_name(col_order_id)} "
            f"JOIN {t_items} oi ON o.{col_name(col_order_id)} = oi.{col_name(col_order_id)} "
            f"LEFT JOIN {t_products} p ON oi.{col_name(col_product_id)} = p.{col_name(col_product_id)} "
            f"LEFT JOIN {t_cat_translation} t ON p.{col_name(col_cat_pt)} = t.{col_name(col_cat_pt)} "
            f"WHERE {where} "
            f"GROUP BY oi.{col_name(col_product_id)}, {category_expr} "
            f"HAVING COUNT(*) >= 1 "
            f"ORDER BY avg_rating DESC NULLS LAST, review_count DESC "
            f"LIMIT ${limit_idx}"
        )

        try:
            rows = await execute_query(query, *params)
            products = [
                {
                    "product_id": r["product_id"],
                    "category": r["category"],
                    "avg_rating": float(r["avg_rating"] or 0),
                    "review_count": int(r["review_count"] or 0),
                }
                for r in rows
            ]
            return {"products": products, "filters": filters}
        except Exception as e:
            logger.error(f"Query failed: {e}")
            return {
                "error": client_error(e, "A database error occurred while running your query."),
                "filters": filters,
            }

    return {"schema": AVERAGE_RATING_BY_PRODUCT_SCHEMA, "execute": execute}


def make_average_rating_by_seller(cfg: SchemaConfig) -> dict:
    col_score = cfg.get_column("review_score")
    col_order_id = cfg.get_column("order_id")
    col_seller_id = cfg.get_column("seller_id")

    t_reviews = table_for(col_score, cfg)
    t_orders = table_for(col_order_id, cfg)
    t_items = table_for(col_seller_id, cfg)
    t_sellers = cfg.get_table("sellers")

    async def execute(state: Optional[str] = None, limit: int = 10) -> dict:
        filters: dict = {}
        limit = clamp_limit(limit, default=10)
        filters["limit"] = limit

        params: list = []
        conditions: list[str] = []

        if state:
            normalized_state = state.upper().strip()
            filters["state"] = normalized_state
            params.append(normalized_state)
            conditions.append(f"s.seller_state = ${len(params)}")

        where = where_clause(conditions)
        limit_idx = len(params) + 1
        params.append(limit)

        query = (
            f"SELECT oi.{col_name(col_seller_id)} AS seller_id, "
            f"ROUND(AVG(r.{col_name(col_score)})::numeric, 2) AS avg_rating, "
            f"COUNT(*) AS review_count "
            f"FROM {t_reviews} r "
            f"JOIN {t_orders} o ON r.{col_name(col_order_id)} = o.{col_name(col_order_id)} "
            f"JOIN {t_items} oi ON o.{col_name(col_order_id)} = oi.{col_name(col_order_id)} "
            f"LEFT JOIN {t_sellers} s ON oi.{col_name(col_seller_id)} = s.{col_name(col_seller_id)} "
            f"WHERE {where} "
            f"GROUP BY oi.{col_name(col_seller_id)} "
            f"HAVING COUNT(*) >= 1 "
            f"ORDER BY avg_rating DESC NULLS LAST, review_count DESC "
            f"LIMIT ${limit_idx}"
        )

        try:
            rows = await execute_query(query, *params)
            sellers = [
                {
                    "seller_id": r["seller_id"],
                    "avg_rating": float(r["avg_rating"] or 0),
                    "review_count": int(r["review_count"] or 0),
                }
                for r in rows
            ]
            return {"sellers": sellers, "filters": filters}
        except Exception as e:
            logger.error(f"Query failed: {e}")
            return {
                "error": client_error(e, "A database error occurred while running your query."),
                "filters": filters,
            }

    return {"schema": AVERAGE_RATING_BY_SELLER_SCHEMA, "execute": execute}


def make_average_rating_by_category(cfg: SchemaConfig) -> dict:
    col_score = cfg.get_column("review_score")
    col_order_id = cfg.get_column("order_id")
    col_product_id = cfg.get_column("product_id")
    col_cat_pt = cfg.get_column("product_category_pt")
    col_cat_en = cfg.get_column("product_category_en")

    t_reviews = table_for(col_score, cfg)
    t_orders = table_for(col_order_id, cfg)
    t_items = table_for(col_product_id, cfg)
    t_products = table_for(col_cat_pt, cfg)
    t_cat_translation = table_for(col_cat_en, cfg)

    category_expr = f"COALESCE(t.{col_name(col_cat_en)}, p.{col_name(col_cat_pt)})"

    async def execute() -> dict:
        filters: dict = {}

        query = (
            f"SELECT {category_expr} AS category, "
            f"ROUND(AVG(r.{col_name(col_score)})::numeric, 2) AS avg_rating, "
            f"COUNT(*) AS review_count "
            f"FROM {t_reviews} r "
            f"JOIN {t_orders} o ON r.{col_name(col_order_id)} = o.{col_name(col_order_id)} "
            f"JOIN {t_items} oi ON o.{col_name(col_order_id)} = oi.{col_name(col_order_id)} "
            f"LEFT JOIN {t_products} p ON oi.{col_name(col_product_id)} = p.{col_name(col_product_id)} "
            f"LEFT JOIN {t_cat_translation} t ON p.{col_name(col_cat_pt)} = t.{col_name(col_cat_pt)} "
            f"WHERE 1=1 "
            f"GROUP BY {category_expr} "
            f"HAVING COUNT(*) >= 1 "
            f"ORDER BY avg_rating DESC NULLS LAST, review_count DESC"
        )

        try:
            rows = await execute_query(query)
            categories = [
                {
                    "category": r["category"],
                    "avg_rating": float(r["avg_rating"] or 0),
                    "review_count": int(r["review_count"] or 0),
                }
                for r in rows
            ]
            return {"categories": categories, "filters": filters}
        except Exception as e:
            logger.error(f"Query failed: {e}")
            return {
                "error": client_error(e, "A database error occurred while running your query."),
                "filters": filters,
            }

    return {"schema": AVERAGE_RATING_BY_CATEGORY_SCHEMA, "execute": execute}


def make_review_score_distribution(cfg: SchemaConfig) -> dict:
    cust_id = cfg.get_column("customer_id")
    col_score = cfg.get_column("review_score")
    col_order_id = cfg.get_column("order_id")
    col_review_date = cfg.get_column("review_creation_date")
    col_city = cfg.get_column("customer_city")
    col_state = cfg.get_column("customer_state")
    col_status = cfg.get_column("order_status")
    col_purchase = cfg.get_column("order_purchase_timestamp")
    col_seller_id = cfg.get_column("seller_id")

    t_reviews = table_for(col_score, cfg)
    t_orders = table_for(col_order_id, cfg)
    t_customers = table_for(col_city, cfg)
    t_items = table_for(col_seller_id, cfg)

    async def execute(
        date_token: Optional[str] = None,
        state: Optional[str] = None,
        seller_id: Optional[str] = None,
    ) -> dict:
        filters: dict = {}
        params: list = []
        conditions: list[str] = []

        date_range, err = _parse_review_date_token(date_token, filters)
        if err:
            return err
        if date_range:
            params.append(date_range[0])
            conditions.append(f"r.{col_name(col_review_date)} >= ${len(params)}")
            params.append(date_range[1])
            conditions.append(f"r.{col_name(col_review_date)} <= ${len(params)}")

        fb = await resolve_order_filters(
            state=state,
            seller_id=seller_id,
            col_city=col_city,
            col_state=col_state,
            col_status=col_status,
            col_purchase=col_purchase,
            col_seller_id=col_seller_id,
            alias_o="o",
            alias_c="c",
            alias_oi="oi",
        )
        if fb.error:
            return fb.error
        filters.update(fb.filters)
        conditions.extend(fb.conditions)
        params.extend(fb.params)

        where = where_clause(conditions)

        query = (
            f"SELECT r.{col_name(col_score)} AS review_score, COUNT(*) AS count "
            f"FROM {t_reviews} r "
            f"JOIN {t_orders} o ON r.{col_name(col_order_id)} = o.{col_name(col_order_id)} "
            f"LEFT JOIN {t_customers} c ON o.{col_name(cust_id)} = c.{col_name(cust_id)} "
        )
        if seller_id:
            query += (
                f"JOIN {t_items} oi ON o.{col_name(col_order_id)} = oi.{col_name(col_order_id)} "
            )
        query += (
            f"WHERE {where} "
            f"GROUP BY r.{col_name(col_score)} "
            f"ORDER BY review_score ASC"
        )

        try:
            rows = await execute_query(query, *params)
            distribution = [
                {
                    "review_score": int(r["review_score"]),
                    "count": int(r["count"] or 0),
                }
                for r in rows
            ]
            return {"distribution": distribution, "filters": filters}
        except Exception as e:
            logger.error(f"Query failed: {e}")
            return {
                "error": client_error(e, "A database error occurred while running your query."),
                "filters": filters,
            }

    return {"schema": REVIEW_SCORE_DISTRIBUTION_SCHEMA, "execute": execute}


def make_review_sentiment_trend(cfg: SchemaConfig) -> dict:
    col_score = cfg.get_column("review_score")
    col_order_id = cfg.get_column("order_id")
    col_review_date = cfg.get_column("review_creation_date")

    t_reviews = table_for(col_score, cfg)
    t_orders = table_for(col_order_id, cfg)

    async def execute(
        date_token: Optional[str] = None,
        granularity: str = "month",
    ) -> dict:
        filters: dict = {}
        granularity = str(granularity).lower().strip() if granularity else "month"
        if granularity not in VALID_GRANULARITIES:
            return {
                "error": f"Invalid granularity '{granularity}'. Allowed: month",
                "filters": filters,
            }
        filters["granularity"] = granularity

        params: list = []
        conditions: list[str] = []

        date_range, err = _parse_review_date_token(date_token, filters)
        if err:
            return err
        if date_range:
            params.append(date_range[0])
            conditions.append(f"r.{col_name(col_review_date)} >= ${len(params)}")
            params.append(date_range[1])
            conditions.append(f"r.{col_name(col_review_date)} <= ${len(params)}")

        where = where_clause(conditions)
        period_expr = f"to_char(date_trunc('{granularity}', r.{col_name(col_review_date)}), 'YYYY-MM')"

        query = (
            f"SELECT {period_expr} AS period, "
            f"ROUND(AVG(r.{col_name(col_score)})::numeric, 2) AS avg_rating, "
            f"COUNT(*) AS review_count "
            f"FROM {t_reviews} r "
            f"JOIN {t_orders} o ON r.{col_name(col_order_id)} = o.{col_name(col_order_id)} "
            f"WHERE {where} "
            f"GROUP BY {period_expr} "
            f"ORDER BY period ASC"
        )

        try:
            rows = await execute_query(query, *params)
            trend = [
                {
                    "period": r["period"],
                    "avg_rating": float(r["avg_rating"] or 0),
                    "review_count": int(r["review_count"] or 0),
                }
                for r in rows
            ]
            return {"trend": trend, "granularity": granularity, "filters": filters}
        except Exception as e:
            logger.error(f"Query failed: {e}")
            return {
                "error": client_error(e, "A database error occurred while running your query."),
                "filters": filters,
            }

    return {"schema": REVIEW_SENTIMENT_TREND_SCHEMA, "execute": execute}
