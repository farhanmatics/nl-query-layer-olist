"""Revenue breakdown functions — schema-aware.

Grouped revenue views: by state, category, seller, payment type, and
monthly trend. Payment-level SUM(payment_value) is used except for
category and seller breakdowns, where item-level (price + freight)
avoids the payments↔items fan-out.
"""
import logging
from typing import Optional

from config import settings
from db import execute_query
from errors import client_error
from functions._filters import clamp_limit, where_clause
from functions._helpers import col_name, table_for
from schemas.base import ColumnRef, SchemaConfig
from validation.dates import parse_date_range

logger = logging.getLogger(__name__)

VALID_GRANULARITY = {"month"}


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


def _payment_revenue_parts(cfg: SchemaConfig) -> dict:
    col_pay_value = cfg.get_column("payment_value")
    col_order_id = cfg.get_column("order_id")
    col_purchase = cfg.get_column("order_purchase_timestamp")
    cust_id = cfg.get_column("customer_id")
    col_state = cfg.get_column("customer_state")

    return {
        "measure": f"SUM(p.{col_name(col_pay_value)})",
        "from_clause": (
            f"FROM {table_for(col_pay_value, cfg)} p "
            f"JOIN {table_for(col_purchase, cfg)} o "
            f"ON p.{col_name(col_order_id)} = o.{col_name(col_order_id)} "
            f"LEFT JOIN {table_for(col_state, cfg)} c "
            f"ON o.{col_name(cust_id)} = c.{col_name(cust_id)}"
        ),
        "col_purchase": col_purchase,
        "alias_o": "o",
    }


def _item_revenue_parts(cfg: SchemaConfig) -> dict:
    col_item_price = cfg.get_column("price")
    col_item_freight = cfg.get_column("freight_value")
    col_order_id = cfg.get_column("order_id")
    col_purchase = cfg.get_column("order_purchase_timestamp")
    col_product_id = cfg.get_column("product_id")
    col_cat_pt = cfg.get_column("product_category_pt")
    col_cat_en = cfg.get_column("product_category_en")
    col_seller_id = cfg.get_column("seller_id")

    return {
        "measure": f"SUM(oi.{col_name(col_item_price)} + oi.{col_name(col_item_freight)})",
        "from_clause": (
            f"FROM {table_for(col_item_price, cfg)} oi "
            f"JOIN {table_for(col_purchase, cfg)} o ON oi.{col_name(col_order_id)} = o.{col_name(col_order_id)} "
            f"LEFT JOIN {table_for(col_cat_pt, cfg)} p "
            f"ON oi.{col_name(col_product_id)} = p.{col_name(col_product_id)} "
            f"LEFT JOIN {table_for(col_cat_en, cfg)} t "
            f"ON p.{col_name(col_cat_pt)} = t.{col_name(col_cat_pt)}"
        ),
        "col_purchase": col_purchase,
        "alias_o": "o",
        "col_seller_id": col_seller_id,
        "col_cat_pt": col_cat_pt,
        "col_cat_en": col_cat_en,
    }


def _append_date_filter(
    conditions: list[str],
    params: list,
    date_range: Optional[tuple],
    col_purchase,
    alias_o: str = "o",
) -> None:
    if date_range:
        params.append(date_range[0])
        conditions.append(f"{alias_o}.{col_name(col_purchase)} >= ${len(params)}")
        params.append(date_range[1])
        conditions.append(f"{alias_o}.{col_name(col_purchase)} <= ${len(params)}")


def make_revenue_by_state(cfg: SchemaConfig) -> dict:
    schema = {
        "name": "revenue_by_state",
        "description": (
            "Revenue broken down by customer state (UF), ranked highest first. "
            "Returns the top 15 states."
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
            },
            "required": [],
        },
    }

    parts = _payment_revenue_parts(cfg)
    col_state = cfg.get_column("customer_state")

    async def execute(date_token: Optional[str] = None) -> dict:
        filters: dict = {}
        date_range, err = _parse_date_token(date_token, filters)
        if err:
            return err

        params: list = []
        conditions: list[str] = []
        _append_date_filter(conditions, params, date_range, parts["col_purchase"])

        group_expr = f"c.{col_name(col_state)}"
        query = (
            f"SELECT {group_expr} AS state, {parts['measure']} AS revenue "
            f"{parts['from_clause']} "
            f"WHERE {where_clause(conditions)} "
            f"GROUP BY {group_expr} "
            f"ORDER BY revenue DESC NULLS LAST "
            f"LIMIT 15"
        )

        try:
            rows = await execute_query(query, *params)
            breakdown = [
                {"state": r["state"], "revenue": float(r["revenue"] or 0)} for r in rows
            ]
            return {"breakdown": breakdown, "filters": filters}
        except Exception as e:
            logger.error(f"revenue_by_state query failed: {e}")
            return {
                "error": client_error(e, "A database error occurred while running your query."),
                "filters": filters,
            }

    return {"schema": schema, "execute": execute}


def make_revenue_by_category(cfg: SchemaConfig) -> dict:
    schema = {
        "name": "revenue_by_category",
        "description": (
            "Revenue broken down by product category (English names), ranked highest first."
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
            },
            "required": [],
        },
    }

    parts = _item_revenue_parts(cfg)

    async def execute(
        date_token: Optional[str] = None,
        limit: int = 10,
    ) -> dict:
        filters: dict = {}
        date_range, err = _parse_date_token(date_token, filters)
        if err:
            return err

        limit = clamp_limit(limit, default=10)
        filters["limit"] = limit

        params: list = []
        conditions: list[str] = []
        _append_date_filter(conditions, params, date_range, parts["col_purchase"])

        group_expr = (
            f"COALESCE(t.{col_name(parts['col_cat_en'])}, p.{col_name(parts['col_cat_pt'])})"
        )
        params.append(limit)
        query = (
            f"SELECT {group_expr} AS category, {parts['measure']} AS revenue "
            f"{parts['from_clause']} "
            f"WHERE {where_clause(conditions)} "
            f"GROUP BY {group_expr} "
            f"ORDER BY revenue DESC NULLS LAST "
            f"LIMIT ${len(params)}"
        )

        try:
            rows = await execute_query(query, *params)
            breakdown = [
                {"category": r["category"], "revenue": float(r["revenue"] or 0)} for r in rows
            ]
            return {"breakdown": breakdown, "filters": filters}
        except Exception as e:
            logger.error(f"revenue_by_category query failed: {e}")
            return {
                "error": client_error(e, "A database error occurred while running your query."),
                "filters": filters,
            }

    return {"schema": schema, "execute": execute}


def make_revenue_by_seller(cfg: SchemaConfig) -> dict:
    col_seller_city = ColumnRef("sellers", "seller_city")
    col_seller_state = ColumnRef("sellers", "seller_state")

    schema = {
        "name": "revenue_by_seller",
        "description": (
            "Revenue broken down by seller, ranked highest first. "
            "Includes seller city and state."
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
                "state": {
                    "type": "string",
                    "description": "Optional seller state/UF filter, e.g. 'SP', 'RJ'",
                },
                "limit": {
                    "type": "integer",
                    "description": "Number of sellers to return (default 10, clamped to 1..25)",
                },
            },
            "required": [],
        },
    }

    parts = _item_revenue_parts(cfg)
    t_sellers = cfg.get_table("sellers")

    async def execute(
        date_token: Optional[str] = None,
        state: Optional[str] = None,
        limit: int = 10,
    ) -> dict:
        filters: dict = {}
        date_range, err = _parse_date_token(date_token, filters)
        if err:
            return err

        limit = clamp_limit(limit, default=10)
        filters["limit"] = limit

        normalized_state = None
        if state:
            normalized_state = state.upper().strip()
            filters["state"] = normalized_state

        params: list = []
        conditions: list[str] = []
        _append_date_filter(conditions, params, date_range, parts["col_purchase"])

        if normalized_state:
            params.append(normalized_state)
            conditions.append(f"s.{col_name(col_seller_state)} = ${len(params)}")

        from_clause = (
            f"{parts['from_clause']} "
            f"JOIN {t_sellers} s ON oi.{col_name(parts['col_seller_id'])} = s.{col_name(parts['col_seller_id'])}"
        )
        group_expr = f"oi.{col_name(parts['col_seller_id'])}"
        params.append(limit)
        query = (
            f"SELECT {group_expr} AS seller_id, "
            f"s.{col_name(col_seller_city)} AS seller_city, "
            f"s.{col_name(col_seller_state)} AS seller_state, "
            f"{parts['measure']} AS revenue "
            f"{from_clause} "
            f"WHERE {where_clause(conditions)} "
            f"GROUP BY {group_expr}, s.{col_name(col_seller_city)}, s.{col_name(col_seller_state)} "
            f"ORDER BY revenue DESC NULLS LAST "
            f"LIMIT ${len(params)}"
        )

        try:
            rows = await execute_query(query, *params)
            breakdown = [
                {
                    "seller_id": r["seller_id"],
                    "seller_city": r["seller_city"],
                    "seller_state": r["seller_state"],
                    "revenue": float(r["revenue"] or 0),
                }
                for r in rows
            ]
            return {"breakdown": breakdown, "filters": filters}
        except Exception as e:
            logger.error(f"revenue_by_seller query failed: {e}")
            return {
                "error": client_error(e, "A database error occurred while running your query."),
                "filters": filters,
            }

    return {"schema": schema, "execute": execute}


def make_revenue_by_payment_type(cfg: SchemaConfig) -> dict:
    schema = {
        "name": "revenue_by_payment_type",
        "description": "Revenue broken down by payment type (credit_card, boleto, etc.).",
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
            },
            "required": [],
        },
    }

    col_pay_value = cfg.get_column("payment_value")
    col_payment_type = cfg.get_column("payment_type")
    col_order_id = cfg.get_column("order_id")
    col_purchase = cfg.get_column("order_purchase_timestamp")

    async def execute(date_token: Optional[str] = None) -> dict:
        filters: dict = {}
        date_range, err = _parse_date_token(date_token, filters)
        if err:
            return err

        params: list = []
        conditions: list[str] = []
        _append_date_filter(conditions, params, date_range, col_purchase)

        group_expr = f"p.{col_name(col_payment_type)}"
        query = (
            f"SELECT {group_expr} AS payment_type, SUM(p.{col_name(col_pay_value)}) AS revenue "
            f"FROM {table_for(col_pay_value, cfg)} p "
            f"JOIN {table_for(col_purchase, cfg)} o "
            f"ON p.{col_name(col_order_id)} = o.{col_name(col_order_id)} "
            f"WHERE {where_clause(conditions)} "
            f"GROUP BY {group_expr} "
            f"ORDER BY revenue DESC NULLS LAST"
        )

        try:
            rows = await execute_query(query, *params)
            breakdown = [
                {"payment_type": r["payment_type"], "revenue": float(r["revenue"] or 0)}
                for r in rows
            ]
            return {"breakdown": breakdown, "filters": filters}
        except Exception as e:
            logger.error(f"revenue_by_payment_type query failed: {e}")
            return {
                "error": client_error(e, "A database error occurred while running your query."),
                "filters": filters,
            }

    return {"schema": schema, "execute": execute}


def make_revenue_by_trend(cfg: SchemaConfig) -> dict:
    schema = {
        "name": "revenue_trend",
        "description": (
            "Monthly revenue time series, ordered chronologically. "
            "Granularity is month only for now."
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
                "granularity": {
                    "type": "string",
                    "enum": ["month"],
                    "description": "Time bucket granularity (month only for now)",
                },
            },
            "required": [],
        },
    }

    parts = _payment_revenue_parts(cfg)

    async def execute(
        date_token: Optional[str] = None,
        granularity: str = "month",
    ) -> dict:
        filters: dict = {}
        date_range, err = _parse_date_token(date_token, filters)
        if err:
            return err

        granularity = str(granularity).lower().strip()
        if granularity not in VALID_GRANULARITY:
            return {
                "error": f"Invalid granularity '{granularity}'. Allowed: month",
                "filters": filters,
            }
        filters["granularity"] = granularity

        params: list = []
        conditions: list[str] = []
        _append_date_filter(conditions, params, date_range, parts["col_purchase"])

        group_expr = (
            f"to_char(date_trunc('month', o.{col_name(parts['col_purchase'])}), 'YYYY-MM')"
        )
        query = (
            f"SELECT {group_expr} AS month, {parts['measure']} AS revenue "
            f"{parts['from_clause']} "
            f"WHERE {where_clause(conditions)} "
            f"GROUP BY {group_expr} "
            f"ORDER BY month ASC"
        )

        try:
            rows = await execute_query(query, *params)
            series = [
                {"month": r["month"], "revenue": float(r["revenue"] or 0)} for r in rows
            ]
            return {"series": series, "granularity": granularity, "filters": filters}
        except Exception as e:
            logger.error(f"revenue_trend query failed: {e}")
            return {
                "error": client_error(e, "A database error occurred while running your query."),
                "filters": filters,
            }

    return {"schema": schema, "execute": execute}
