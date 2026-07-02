"""Filtered count variants — schema-aware count functions with required dimensions.

count_by_status, count_by_payment_type, and count_by_category wrap
resolve_order_filters for shared validation and SQL condition building.
"""
import logging
from typing import Optional

from db import execute_scalar
from errors import client_error
from functions._filters import resolve_order_filters, where_clause
from functions._helpers import col_name, table_for
from schemas.base import SchemaConfig

logger = logging.getLogger(__name__)

COUNT_BY_STATUS_SCHEMA = {
    "name": "count_by_status",
    "description": "Count orders with a required status, optionally filtered by date range",
    "parameters": {
        "type": "object",
        "properties": {
            "status": {
                "type": "string",
                "description": "Order status (required, e.g., 'delivered', 'processing', 'canceled')",
            },
            "date_token": {
                "type": "string",
                "description": "Date range token: 'today', 'yesterday', 'this_week', 'last_week', 'this_month', 'last_month', 'this_year', 'last_year'",
            },
        },
        "required": ["status"],
    },
}

COUNT_BY_PAYMENT_TYPE_SCHEMA = {
    "name": "count_by_payment_type",
    "description": "Count distinct orders paid with a given payment type, optionally filtered by state and date range",
    "parameters": {
        "type": "object",
        "properties": {
            "payment_type": {
                "type": "string",
                "description": "Payment type (required, e.g., 'credit_card', 'boleto', 'voucher')",
            },
            "state": {
                "type": "string",
                "description": "Customer state/UF (optional, e.g., 'SP', 'RJ')",
            },
            "date_token": {
                "type": "string",
                "description": "Date range token: 'today', 'yesterday', 'this_week', 'last_week', 'this_month', 'last_month', 'this_year', 'last_year'",
            },
        },
        "required": ["payment_type"],
    },
}

COUNT_BY_CATEGORY_SCHEMA = {
    "name": "count_by_category",
    "description": "Count distinct orders that include at least one product in the given category (orders sold, not catalog size). Optionally filtered by state, seller, and date range",
    "parameters": {
        "type": "object",
        "properties": {
            "category": {
                "type": "string",
                "description": "Product category in English or Portuguese (required, e.g., 'health_beauty')",
            },
            "state": {
                "type": "string",
                "description": "Customer state/UF (optional, e.g., 'SP', 'RJ')",
            },
            "seller_id": {
                "type": "string",
                "description": "Seller ID (optional)",
            },
            "date_token": {
                "type": "string",
                "description": "Date range token: 'today', 'yesterday', 'this_week', 'last_week', 'this_month', 'last_month', 'this_year', 'last_year'",
            },
        },
        "required": ["category"],
    },
}


def make_count_by_status(cfg: SchemaConfig) -> dict:
    cust_id = cfg.get_column("customer_id")
    col_city = cfg.get_column("customer_city")
    col_state = cfg.get_column("customer_state")
    col_status = cfg.get_column("order_status")
    col_purchase = cfg.get_column("order_purchase_timestamp")

    t_orders = table_for(col_status, cfg)
    t_customers = table_for(col_city, cfg)

    async def execute(
        status: str,
        date_token: Optional[str] = None,
    ) -> dict:
        built = await resolve_order_filters(
            status=status,
            date_token=date_token,
            col_city=col_city,
            col_state=col_state,
            col_status=col_status,
            col_purchase=col_purchase,
            require_status=True,
        )
        if built.error:
            return built.error

        query = (
            f"SELECT COUNT(*) AS count "
            f"FROM {t_orders} o "
            f"LEFT JOIN {t_customers} c ON o.{col_name(cust_id)} = c.{col_name(cust_id)} "
            f"WHERE {where_clause(built.conditions)}"
        )

        try:
            count = await execute_scalar(query, *built.params)
            return {"count": count or 0, "filters": built.filters}
        except Exception as e:
            logger.error(f"count_by_status query failed: {e}")
            return {
                "error": client_error(e, "A database error occurred while running your query."),
                "filters": built.filters,
            }

    return {"schema": COUNT_BY_STATUS_SCHEMA, "execute": execute}


def make_count_by_payment_type(cfg: SchemaConfig) -> dict:
    cust_id = cfg.get_column("customer_id")
    col_city = cfg.get_column("customer_city")
    col_state = cfg.get_column("customer_state")
    col_status = cfg.get_column("order_status")
    col_purchase = cfg.get_column("order_purchase_timestamp")
    col_order_id = cfg.get_column("order_id")
    col_payment_type = cfg.get_column("payment_type")

    t_payments = table_for(col_payment_type, cfg)
    t_orders = table_for(col_order_id, cfg)
    t_customers = table_for(col_city, cfg)

    async def execute(
        payment_type: str,
        state: Optional[str] = None,
        date_token: Optional[str] = None,
    ) -> dict:
        if not payment_type or not str(payment_type).strip():
            return {"error": "payment_type is required for this query", "filters": {}}

        built = await resolve_order_filters(
            state=state,
            date_token=date_token,
            payment_type=payment_type,
            col_city=col_city,
            col_state=col_state,
            col_status=col_status,
            col_purchase=col_purchase,
            col_payment_type=col_payment_type,
            alias_p="p",
        )
        if built.error:
            return built.error

        query = (
            f"SELECT COUNT(DISTINCT p.{col_name(col_order_id)}) AS count "
            f"FROM {t_payments} p "
            f"JOIN {t_orders} o ON p.{col_name(col_order_id)} = o.{col_name(col_order_id)} "
            f"LEFT JOIN {t_customers} c ON o.{col_name(cust_id)} = c.{col_name(cust_id)} "
            f"WHERE {where_clause(built.conditions)}"
        )

        try:
            count = await execute_scalar(query, *built.params)
            return {"count": count or 0, "filters": built.filters}
        except Exception as e:
            logger.error(f"count_by_payment_type query failed: {e}")
            return {
                "error": client_error(e, "A database error occurred while running your query."),
                "filters": built.filters,
            }

    return {"schema": COUNT_BY_PAYMENT_TYPE_SCHEMA, "execute": execute}


def make_count_by_category(cfg: SchemaConfig) -> dict:
    cust_id = cfg.get_column("customer_id")
    col_city = cfg.get_column("customer_city")
    col_state = cfg.get_column("customer_state")
    col_status = cfg.get_column("order_status")
    col_purchase = cfg.get_column("order_purchase_timestamp")
    col_order_id = cfg.get_column("order_id")
    col_product_id = cfg.get_column("product_id")
    col_seller_id = cfg.get_column("seller_id")
    col_cat_pt = cfg.get_column("product_category_pt")
    col_cat_en = cfg.get_column("product_category_en")

    t_orders = table_for(col_order_id, cfg)
    t_customers = table_for(col_city, cfg)
    t_items = table_for(col_product_id, cfg)
    t_products = table_for(col_cat_pt, cfg)
    t_cat_translation = table_for(col_cat_en, cfg)

    async def execute(
        category: str,
        state: Optional[str] = None,
        seller_id: Optional[str] = None,
        date_token: Optional[str] = None,
    ) -> dict:
        if not category or not str(category).strip():
            return {"error": "category is required for this query", "filters": {}}

        built = await resolve_order_filters(
            state=state,
            seller_id=seller_id,
            date_token=date_token,
            category=category,
            col_city=col_city,
            col_state=col_state,
            col_status=col_status,
            col_purchase=col_purchase,
            col_seller_id=col_seller_id,
            alias_oi="oi",
        )
        if built.error:
            return built.error

        normalized_category = built.filters["category"]
        built.params.append(normalized_category)
        i = len(built.params)
        built.params.append(normalized_category)
        j = len(built.params)
        built.conditions.append(
            f"(lower(t.{col_name(col_cat_en)}) = ${i} "
            f"OR lower(p.{col_name(col_cat_pt)}) = ${j})"
        )

        query = (
            f"SELECT COUNT(DISTINCT o.{col_name(col_order_id)}) AS count "
            f"FROM {t_orders} o "
            f"JOIN {t_customers} c ON o.{col_name(cust_id)} = c.{col_name(cust_id)} "
            f"JOIN {t_items} oi ON o.{col_name(col_order_id)} = oi.{col_name(col_order_id)} "
            f"JOIN {t_products} p ON oi.{col_name(col_product_id)} = p.{col_name(col_product_id)} "
            f"LEFT JOIN {t_cat_translation} t "
            f"ON p.{col_name(col_cat_pt)} = t.{col_name(col_cat_pt)} "
            f"WHERE {where_clause(built.conditions)}"
        )

        try:
            count = await execute_scalar(query, *built.params)
            return {"count": count or 0, "filters": built.filters}
        except Exception as e:
            logger.error(f"count_by_category query failed: {e}")
            return {
                "error": client_error(e, "A database error occurred while running your query."),
                "filters": built.filters,
            }

    return {"schema": COUNT_BY_CATEGORY_SCHEMA, "execute": execute}
