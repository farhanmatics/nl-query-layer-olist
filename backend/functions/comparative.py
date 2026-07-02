"""Comparative and dimensional breakdown functions — schema-aware factories.

seller_comparison, category_comparison, state_comparison, and
payment_type_breakdown compare entities or group orders by payment method.
"""
import logging
from typing import Optional

from db import execute_query
from errors import client_error
from functions._filters import resolve_order_filters, where_clause
from functions._helpers import col_name, table_for
from schemas.base import SchemaConfig

logger = logging.getLogger(__name__)

MAX_COMPARE_ITEMS = 5

_DATE_TOKEN_DESC = (
    "Date range token: 'today', 'yesterday', 'this_week', 'last_week', "
    "'this_month', 'last_month', 'this_year', 'last_year'"
)

SELLER_COMPARISON_SCHEMA = {
    "name": "seller_comparison",
    "description": (
        "Compare up to 5 sellers side-by-side: order count, revenue, and average review score"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "seller_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Seller IDs to compare (required, 1-5 items)",
            },
            "date_token": {"type": "string", "description": _DATE_TOKEN_DESC},
        },
        "required": ["seller_ids"],
    },
}

CATEGORY_COMPARISON_SCHEMA = {
    "name": "category_comparison",
    "description": (
        "Compare up to 5 product categories side-by-side: order count, revenue, "
        "and average review score"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "categories": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Categories in English or Portuguese (required, 1-5 items)",
            },
            "date_token": {"type": "string", "description": _DATE_TOKEN_DESC},
        },
        "required": ["categories"],
    },
}

STATE_COMPARISON_SCHEMA = {
    "name": "state_comparison",
    "description": (
        "Compare up to 5 customer states side-by-side: order count, revenue, "
        "and average review score"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "states": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Brazilian UF codes to compare (required, 1-5 items)",
            },
            "date_token": {"type": "string", "description": _DATE_TOKEN_DESC},
        },
        "required": ["states"],
    },
}

PAYMENT_TYPE_BREAKDOWN_SCHEMA = {
    "name": "payment_type_breakdown",
    "description": (
        "Count distinct orders and sum revenue grouped by payment type, "
        "optionally filtered by purchase date range"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "date_token": {"type": "string", "description": _DATE_TOKEN_DESC},
        },
        "required": [],
    },
}


def _validate_compare_list(values, param_name: str) -> tuple[Optional[list[str]], Optional[dict]]:
    """Validate a non-empty list with at most MAX_COMPARE_ITEMS string entries."""
    if not isinstance(values, list) or not values:
        return None, {
            "error": f"{param_name} must be a non-empty list",
            "filters": {},
        }

    normalized = [str(v).strip() for v in values if str(v).strip()]
    if not normalized:
        return None, {
            "error": f"{param_name} must be a non-empty list",
            "filters": {},
        }
    if len(normalized) > MAX_COMPARE_ITEMS:
        return None, {
            "error": f"{param_name} may contain at most {MAX_COMPARE_ITEMS} items",
            "filters": {},
        }
    return normalized, None


def _float_or_none(value) -> Optional[float]:
    return float(value) if value is not None else None


def make_seller_comparison(cfg: SchemaConfig) -> dict:
    col_order_id = cfg.get_column("order_id")
    col_purchase = cfg.get_column("order_purchase_timestamp")
    col_seller_id = cfg.get_column("seller_id")
    col_price = cfg.get_column("price")
    col_freight = cfg.get_column("freight_value")
    col_review_score = cfg.get_column("review_score")

    t_items = table_for(col_price, cfg)
    t_orders = table_for(col_order_id, cfg)
    t_reviews = table_for(col_review_score, cfg)

    async def execute(
        seller_ids: list,
        date_token: Optional[str] = None,
    ) -> dict:
        normalized_ids, list_error = _validate_compare_list(seller_ids, "seller_ids")
        if list_error:
            return list_error

        built = await resolve_order_filters(
            date_token=date_token,
            col_city=cfg.get_column("customer_city"),
            col_state=cfg.get_column("customer_state"),
            col_status=cfg.get_column("order_status"),
            col_purchase=col_purchase,
        )
        if built.error:
            return built.error
        built.filters["seller_ids"] = normalized_ids

        built.params.append(normalized_ids)
        id_param = len(built.params)
        built.conditions.append(
            f"oi.{col_name(col_seller_id)} = ANY(${id_param})"
        )

        query = (
            f"SELECT "
            f"oi.{col_name(col_seller_id)} AS seller_id, "
            f"COUNT(DISTINCT o.{col_name(col_order_id)}) AS orders, "
            f"COALESCE(SUM(oi.{col_name(col_price)} + oi.{col_name(col_freight)}), 0) AS revenue, "
            f"AVG(r.{col_name(col_review_score)}) AS avg_rating "
            f"FROM {t_items} oi "
            f"JOIN {t_orders} o ON oi.{col_name(col_order_id)} = o.{col_name(col_order_id)} "
            f"LEFT JOIN {t_reviews} r ON o.{col_name(col_order_id)} = r.{col_name(col_order_id)} "
            f"WHERE {where_clause(built.conditions)} "
            f"GROUP BY oi.{col_name(col_seller_id)} "
            f"ORDER BY revenue DESC"
        )

        try:
            rows = await execute_query(query, *built.params)
            comparison = [
                {
                    "seller_id": r["seller_id"],
                    "orders": int(r["orders"] or 0),
                    "revenue": float(r["revenue"] or 0),
                    "avg_rating": _float_or_none(r["avg_rating"]),
                }
                for r in rows
            ]
            return {"comparison": comparison, "filters": built.filters}
        except Exception as e:
            logger.error(f"seller_comparison query failed: {e}")
            return {
                "error": client_error(e, "A database error occurred while running your query."),
                "filters": built.filters,
            }

    return {"schema": SELLER_COMPARISON_SCHEMA, "execute": execute}


def make_category_comparison(cfg: SchemaConfig) -> dict:
    col_order_id = cfg.get_column("order_id")
    col_purchase = cfg.get_column("order_purchase_timestamp")
    col_product_id = cfg.get_column("product_id")
    col_price = cfg.get_column("price")
    col_freight = cfg.get_column("freight_value")
    col_cat_pt = cfg.get_column("product_category_pt")
    col_cat_en = cfg.get_column("product_category_en")
    col_review_score = cfg.get_column("review_score")

    t_items = table_for(col_price, cfg)
    t_orders = table_for(col_order_id, cfg)
    t_products = table_for(col_cat_pt, cfg)
    t_cat_translation = table_for(col_cat_en, cfg)
    t_reviews = table_for(col_review_score, cfg)

    category_expr = f"COALESCE(t.{col_name(col_cat_en)}, p.{col_name(col_cat_pt)})"

    async def execute(
        categories: list,
        date_token: Optional[str] = None,
    ) -> dict:
        normalized_cats, list_error = _validate_compare_list(categories, "categories")
        if list_error:
            return list_error

        built = await resolve_order_filters(
            date_token=date_token,
            col_city=cfg.get_column("customer_city"),
            col_state=cfg.get_column("customer_state"),
            col_status=cfg.get_column("order_status"),
            col_purchase=col_purchase,
        )
        if built.error:
            return built.error

        normalized_lookup = [
            c.lower().strip().replace("_", " ") for c in normalized_cats
        ]
        built.filters["categories"] = normalized_lookup

        built.params.append(normalized_lookup)
        cat_param = len(built.params)
        built.conditions.append(
            f"(lower(t.{col_name(col_cat_en)}) = ANY(${cat_param}) "
            f"OR lower(p.{col_name(col_cat_pt)}) = ANY(${cat_param}))"
        )

        query = (
            f"SELECT "
            f"{category_expr} AS category, "
            f"COUNT(DISTINCT o.{col_name(col_order_id)}) AS orders, "
            f"COALESCE(SUM(oi.{col_name(col_price)} + oi.{col_name(col_freight)}), 0) AS revenue, "
            f"AVG(r.{col_name(col_review_score)}) AS avg_rating "
            f"FROM {t_items} oi "
            f"JOIN {t_orders} o ON oi.{col_name(col_order_id)} = o.{col_name(col_order_id)} "
            f"JOIN {t_products} p ON oi.{col_name(col_product_id)} = p.{col_name(col_product_id)} "
            f"LEFT JOIN {t_cat_translation} t "
            f"ON p.{col_name(col_cat_pt)} = t.{col_name(col_cat_pt)} "
            f"LEFT JOIN {t_reviews} r ON o.{col_name(col_order_id)} = r.{col_name(col_order_id)} "
            f"WHERE {where_clause(built.conditions)} "
            f"GROUP BY {category_expr} "
            f"ORDER BY revenue DESC"
        )

        try:
            rows = await execute_query(query, *built.params)
            comparison = [
                {
                    "category": r["category"],
                    "orders": int(r["orders"] or 0),
                    "revenue": float(r["revenue"] or 0),
                    "avg_rating": _float_or_none(r["avg_rating"]),
                }
                for r in rows
            ]
            return {"comparison": comparison, "filters": built.filters}
        except Exception as e:
            logger.error(f"category_comparison query failed: {e}")
            return {
                "error": client_error(e, "A database error occurred while running your query."),
                "filters": built.filters,
            }

    return {"schema": CATEGORY_COMPARISON_SCHEMA, "execute": execute}


def make_state_comparison(cfg: SchemaConfig) -> dict:
    cust_id = cfg.get_column("customer_id")
    col_city = cfg.get_column("customer_city")
    col_state = cfg.get_column("customer_state")
    col_status = cfg.get_column("order_status")
    col_purchase = cfg.get_column("order_purchase_timestamp")
    col_order_id = cfg.get_column("order_id")
    col_pay_value = cfg.get_column("payment_value")
    col_review_score = cfg.get_column("review_score")

    t_orders = table_for(col_order_id, cfg)
    t_customers = table_for(col_city, cfg)
    t_payments = table_for(col_pay_value, cfg)
    t_reviews = table_for(col_review_score, cfg)

    async def execute(
        states: list,
        date_token: Optional[str] = None,
    ) -> dict:
        normalized_states, list_error = _validate_compare_list(states, "states")
        if list_error:
            return list_error

        normalized_states = [s.upper() for s in normalized_states]

        built = await resolve_order_filters(
            date_token=date_token,
            col_city=col_city,
            col_state=col_state,
            col_status=col_status,
            col_purchase=col_purchase,
        )
        if built.error:
            return built.error
        built.filters["states"] = normalized_states

        built.params.append(normalized_states)
        state_param = len(built.params)
        built.conditions.append(
            f"c.{col_name(col_state)} = ANY(${state_param})"
        )

        query = (
            f"SELECT "
            f"c.{col_name(col_state)} AS state, "
            f"COUNT(DISTINCT o.{col_name(col_order_id)}) AS orders, "
            f"COALESCE(SUM(p.{col_name(col_pay_value)}), 0) AS revenue, "
            f"AVG(r.{col_name(col_review_score)}) AS avg_rating "
            f"FROM {t_orders} o "
            f"JOIN {t_customers} c ON o.{col_name(cust_id)} = c.{col_name(cust_id)} "
            f"LEFT JOIN {t_payments} p ON o.{col_name(col_order_id)} = p.{col_name(col_order_id)} "
            f"LEFT JOIN {t_reviews} r ON o.{col_name(col_order_id)} = r.{col_name(col_order_id)} "
            f"WHERE {where_clause(built.conditions)} "
            f"GROUP BY c.{col_name(col_state)} "
            f"ORDER BY revenue DESC"
        )

        try:
            rows = await execute_query(query, *built.params)
            comparison = [
                {
                    "state": r["state"],
                    "orders": int(r["orders"] or 0),
                    "revenue": float(r["revenue"] or 0),
                    "avg_rating": _float_or_none(r["avg_rating"]),
                }
                for r in rows
            ]
            return {"comparison": comparison, "filters": built.filters}
        except Exception as e:
            logger.error(f"state_comparison query failed: {e}")
            return {
                "error": client_error(e, "A database error occurred while running your query."),
                "filters": built.filters,
            }

    return {"schema": STATE_COMPARISON_SCHEMA, "execute": execute}


def make_payment_type_breakdown(cfg: SchemaConfig) -> dict:
    cust_id = cfg.get_column("customer_id")
    col_city = cfg.get_column("customer_city")
    col_state = cfg.get_column("customer_state")
    col_status = cfg.get_column("order_status")
    col_purchase = cfg.get_column("order_purchase_timestamp")
    col_order_id = cfg.get_column("order_id")
    col_payment_type = cfg.get_column("payment_type")
    col_pay_value = cfg.get_column("payment_value")

    t_payments = table_for(col_payment_type, cfg)
    t_orders = table_for(col_order_id, cfg)
    t_customers = table_for(col_city, cfg)

    async def execute(date_token: Optional[str] = None) -> dict:
        built = await resolve_order_filters(
            date_token=date_token,
            col_city=col_city,
            col_state=col_state,
            col_status=col_status,
            col_purchase=col_purchase,
        )
        if built.error:
            return built.error

        query = (
            f"SELECT "
            f"p.{col_name(col_payment_type)} AS payment_type, "
            f"COUNT(DISTINCT p.{col_name(col_order_id)}) AS orders, "
            f"COALESCE(SUM(p.{col_name(col_pay_value)}), 0) AS revenue "
            f"FROM {t_payments} p "
            f"JOIN {t_orders} o ON p.{col_name(col_order_id)} = o.{col_name(col_order_id)} "
            f"LEFT JOIN {t_customers} c ON o.{col_name(cust_id)} = c.{col_name(cust_id)} "
            f"WHERE {where_clause(built.conditions)} "
            f"GROUP BY p.{col_name(col_payment_type)} "
            f"ORDER BY revenue DESC"
        )

        try:
            rows = await execute_query(query, *built.params)
            breakdown = [
                {
                    "payment_type": r["payment_type"],
                    "orders": int(r["orders"] or 0),
                    "revenue": float(r["revenue"] or 0),
                }
                for r in rows
            ]
            return {"breakdown": breakdown, "filters": built.filters}
        except Exception as e:
            logger.error(f"payment_type_breakdown query failed: {e}")
            return {
                "error": client_error(e, "A database error occurred while running your query."),
                "filters": built.filters,
            }

    return {"schema": PAYMENT_TYPE_BREAKDOWN_SCHEMA, "execute": execute}
