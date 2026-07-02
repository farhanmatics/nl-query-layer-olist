"""Delivery and fulfillment metrics — schema-aware factory functions.

on_time_delivery_rate, average_delivery_days, late_deliveries, and
fulfillment_status_breakdown use order delivery/estimated dates and
order_status from the active SchemaConfig.
"""
import logging
from typing import Optional

from db import execute_query, execute_scalar
from errors import client_error
from functions._filters import resolve_order_filters, where_clause
from functions._helpers import col_name, table_for
from schemas.base import SchemaConfig

logger = logging.getLogger(__name__)

_DATE_TOKEN_DESC = (
    "Date range token: 'today', 'yesterday', 'this_week', 'last_week', "
    "'this_month', 'last_month', 'this_year', 'last_year'"
)

ON_TIME_DELIVERY_RATE_SCHEMA = {
    "name": "on_time_delivery_rate",
    "description": (
        "Percentage of delivered orders that arrived on or before the estimated "
        "delivery date, optionally filtered by customer state and purchase date range"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "state": {
                "type": "string",
                "description": "Customer state/UF (optional, e.g., 'SP', 'RJ')",
            },
            "date_token": {"type": "string", "description": _DATE_TOKEN_DESC},
        },
        "required": [],
    },
}

AVERAGE_DELIVERY_DAYS_SCHEMA = {
    "name": "average_delivery_days",
    "description": (
        "Average days from purchase to delivery for delivered orders, optionally "
        "filtered by state, product category, seller, and purchase date range"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "state": {
                "type": "string",
                "description": "Customer state/UF (optional, e.g., 'SP', 'RJ')",
            },
            "category": {
                "type": "string",
                "description": "Product category in English or Portuguese (optional)",
            },
            "seller_id": {
                "type": "string",
                "description": "Seller ID (optional)",
            },
            "date_token": {"type": "string", "description": _DATE_TOKEN_DESC},
        },
        "required": [],
    },
}

LATE_DELIVERIES_SCHEMA = {
    "name": "late_deliveries",
    "description": (
        "Count delivered orders where actual delivery was more than N days after "
        "the estimated delivery date, optionally filtered by state and date range"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "days_late": {
                "type": "integer",
                "description": "Minimum days past estimated delivery (default 5)",
            },
            "state": {
                "type": "string",
                "description": "Customer state/UF (optional, e.g., 'SP', 'RJ')",
            },
            "date_token": {"type": "string", "description": _DATE_TOKEN_DESC},
        },
        "required": [],
    },
}

FULFILLMENT_STATUS_BREAKDOWN_SCHEMA = {
    "name": "fulfillment_status_breakdown",
    "description": "Count orders grouped by order status, optionally filtered by purchase date range",
    "parameters": {
        "type": "object",
        "properties": {
            "date_token": {"type": "string", "description": _DATE_TOKEN_DESC},
        },
        "required": [],
    },
}


def _delivered_date_conditions(col_delivered, col_estimated, alias_o: str = "o") -> list[str]:
    """Require non-null delivery timestamps for on-time / late metrics."""
    return [
        f"{alias_o}.{col_name(col_delivered)} IS NOT NULL",
        f"{alias_o}.{col_name(col_estimated)} IS NOT NULL",
    ]


def make_on_time_delivery_rate(cfg: SchemaConfig) -> dict:
    cust_id = cfg.get_column("customer_id")
    col_city = cfg.get_column("customer_city")
    col_state = cfg.get_column("customer_state")
    col_status = cfg.get_column("order_status")
    col_purchase = cfg.get_column("order_purchase_timestamp")
    col_delivered = cfg.get_column("order_delivered_date")
    col_estimated = cfg.get_column("order_estimated_delivery_date")

    t_orders = table_for(col_status, cfg)
    t_customers = table_for(col_city, cfg)

    async def execute(
        state: Optional[str] = None,
        date_token: Optional[str] = None,
    ) -> dict:
        built = await resolve_order_filters(
            state=state,
            status="delivered",
            date_token=date_token,
            col_city=col_city,
            col_state=col_state,
            col_status=col_status,
            col_purchase=col_purchase,
        )
        if built.error:
            return built.error

        conditions = built.conditions + _delivered_date_conditions(
            col_delivered, col_estimated
        )
        on_time_expr = (
            f"{col_name(col_delivered)} <= {col_name(col_estimated)}"
        )

        query = (
            f"SELECT "
            f"COUNT(*) FILTER (WHERE o.{on_time_expr}) AS on_time_count, "
            f"COUNT(*) AS delivered_count "
            f"FROM {t_orders} o "
            f"LEFT JOIN {t_customers} c ON o.{col_name(cust_id)} = c.{col_name(cust_id)} "
            f"WHERE {where_clause(conditions)}"
        )

        try:
            rows = await execute_query(query, *built.params)
            row = rows[0]
            delivered_count = int(row["delivered_count"] or 0)
            on_time_count = int(row["on_time_count"] or 0)
            on_time_pct = (
                round(100.0 * on_time_count / delivered_count, 2)
                if delivered_count
                else 0.0
            )
            return {
                "on_time_pct": on_time_pct,
                "on_time_count": on_time_count,
                "delivered_count": delivered_count,
                "filters": built.filters,
            }
        except Exception as e:
            logger.error(f"on_time_delivery_rate query failed: {e}")
            return {
                "error": client_error(e, "A database error occurred while running your query."),
                "filters": built.filters,
            }

    return {"schema": ON_TIME_DELIVERY_RATE_SCHEMA, "execute": execute}


def make_average_delivery_days(cfg: SchemaConfig) -> dict:
    cust_id = cfg.get_column("customer_id")
    col_city = cfg.get_column("customer_city")
    col_state = cfg.get_column("customer_state")
    col_status = cfg.get_column("order_status")
    col_purchase = cfg.get_column("order_purchase_timestamp")
    col_delivered = cfg.get_column("order_delivered_date")
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
        state: Optional[str] = None,
        category: Optional[str] = None,
        seller_id: Optional[str] = None,
        date_token: Optional[str] = None,
    ) -> dict:
        built = await resolve_order_filters(
            state=state,
            seller_id=seller_id,
            status="delivered",
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

        conditions = built.conditions + [
            f"o.{col_name(col_delivered)} IS NOT NULL",
            f"o.{col_name(col_purchase)} IS NOT NULL",
        ]

        if category:
            normalized_category = built.filters["category"]
            built.params.append(normalized_category)
            i = len(built.params)
            built.params.append(normalized_category)
            j = len(built.params)
            conditions.append(
                f"(lower(t.{col_name(col_cat_en)}) = ${i} "
                f"OR lower(p.{col_name(col_cat_pt)}) = ${j})"
            )

        avg_expr = (
            f"AVG(EXTRACT(EPOCH FROM ("
            f"o.{col_name(col_delivered)} - o.{col_name(col_purchase)}"
            f")) / 86400.0)"
        )

        query = (
            f"SELECT {avg_expr} AS avg_days "
            f"FROM {t_orders} o "
            f"LEFT JOIN {t_customers} c ON o.{col_name(cust_id)} = c.{col_name(cust_id)} "
        )

        if category or seller_id:
            query += (
                f"JOIN {t_items} oi ON o.{col_name(col_order_id)} = oi.{col_name(col_order_id)} "
            )
            if category:
                query += (
                    f"JOIN {t_products} p ON oi.{col_name(col_product_id)} = p.{col_name(col_product_id)} "
                    f"LEFT JOIN {t_cat_translation} t "
                    f"ON p.{col_name(col_cat_pt)} = t.{col_name(col_cat_pt)} "
                )

        query += f"WHERE {where_clause(conditions)}"

        try:
            avg_days = await execute_scalar(query, *built.params)
            return {
                "avg_days": round(float(avg_days), 2) if avg_days is not None else None,
                "filters": built.filters,
            }
        except Exception as e:
            logger.error(f"average_delivery_days query failed: {e}")
            return {
                "error": client_error(e, "A database error occurred while running your query."),
                "filters": built.filters,
            }

    return {"schema": AVERAGE_DELIVERY_DAYS_SCHEMA, "execute": execute}


def make_late_deliveries(cfg: SchemaConfig) -> dict:
    cust_id = cfg.get_column("customer_id")
    col_city = cfg.get_column("customer_city")
    col_state = cfg.get_column("customer_state")
    col_status = cfg.get_column("order_status")
    col_purchase = cfg.get_column("order_purchase_timestamp")
    col_delivered = cfg.get_column("order_delivered_date")
    col_estimated = cfg.get_column("order_estimated_delivery_date")

    t_orders = table_for(col_status, cfg)
    t_customers = table_for(col_city, cfg)

    async def execute(
        days_late: int = 5,
        state: Optional[str] = None,
        date_token: Optional[str] = None,
    ) -> dict:
        try:
            days_late = int(days_late)
        except (TypeError, ValueError):
            days_late = 5
        days_late = max(1, min(365, days_late))

        built = await resolve_order_filters(
            state=state,
            status="delivered",
            date_token=date_token,
            col_city=col_city,
            col_state=col_state,
            col_status=col_status,
            col_purchase=col_purchase,
        )
        if built.error:
            return built.error
        built.filters["days_late"] = days_late

        conditions = built.conditions + _delivered_date_conditions(
            col_delivered, col_estimated
        )
        built.params.append(days_late)
        late_param = len(built.params)
        conditions.append(
            f"o.{col_name(col_delivered)} > "
            f"o.{col_name(col_estimated)} + make_interval(days => ${late_param})"
        )

        query = (
            f"SELECT COUNT(*) AS count "
            f"FROM {t_orders} o "
            f"LEFT JOIN {t_customers} c ON o.{col_name(cust_id)} = c.{col_name(cust_id)} "
            f"WHERE {where_clause(conditions)}"
        )

        try:
            count = await execute_scalar(query, *built.params)
            return {"count": count or 0, "filters": built.filters}
        except Exception as e:
            logger.error(f"late_deliveries query failed: {e}")
            return {
                "error": client_error(e, "A database error occurred while running your query."),
                "filters": built.filters,
            }

    return {"schema": LATE_DELIVERIES_SCHEMA, "execute": execute}


def make_fulfillment_status_breakdown(cfg: SchemaConfig) -> dict:
    col_status = cfg.get_column("order_status")
    col_purchase = cfg.get_column("order_purchase_timestamp")

    t_orders = table_for(col_status, cfg)

    async def execute(date_token: Optional[str] = None) -> dict:
        built = await resolve_order_filters(
            date_token=date_token,
            col_city=cfg.get_column("customer_city"),
            col_state=cfg.get_column("customer_state"),
            col_status=col_status,
            col_purchase=col_purchase,
        )
        if built.error:
            return built.error

        query = (
            f"SELECT o.{col_name(col_status)} AS status, COUNT(*) AS count "
            f"FROM {t_orders} o "
            f"WHERE {where_clause(built.conditions)} "
            f"GROUP BY o.{col_name(col_status)} "
            f"ORDER BY count DESC"
        )

        try:
            rows = await execute_query(query, *built.params)
            breakdown = [
                {"status": r["status"], "count": int(r["count"] or 0)} for r in rows
            ]
            return {"breakdown": breakdown, "filters": built.filters}
        except Exception as e:
            logger.error(f"fulfillment_status_breakdown query failed: {e}")
            return {
                "error": client_error(e, "A database error occurred while running your query."),
                "filters": built.filters,
            }

    return {"schema": FULFILLMENT_STATUS_BREAKDOWN_SCHEMA, "execute": execute}
