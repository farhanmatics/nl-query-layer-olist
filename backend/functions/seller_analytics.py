"""Seller analytics functions — schema-aware.

Seller rankings, per-seller metrics, concentration, and state-level
distribution. Seller-attributed revenue uses item-level (price + freight)
to avoid order-level payment fan-out across multiple sellers.
"""
import logging
from typing import Optional

from config import settings
from db import execute_query, execute_scalar
from errors import client_error
from functions._filters import clamp_limit, where_clause
from functions._helpers import col_name, table_for
from schemas.base import ColumnRef, SchemaConfig
from validation.dates import parse_date_range

logger = logging.getLogger(__name__)

COL_SELLER_CITY = ColumnRef("sellers", "seller_city")
COL_SELLER_STATE = ColumnRef("sellers", "seller_state")


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


def _seller_item_parts(cfg: SchemaConfig) -> dict:
    col_item_price = cfg.get_column("price")
    col_item_freight = cfg.get_column("freight_value")
    col_order_id = cfg.get_column("order_id")
    col_purchase = cfg.get_column("order_purchase_timestamp")
    col_seller_id = cfg.get_column("seller_id")
    cust_id = cfg.get_column("customer_id")
    col_city = cfg.get_column("customer_city")
    col_score = cfg.get_column("review_score")
    col_product_id = cfg.get_column("product_id")

    t_items = table_for(col_item_price, cfg)
    t_orders = table_for(col_purchase, cfg)
    t_sellers = cfg.get_table("sellers")
    t_customers = table_for(col_city, cfg)
    t_reviews = table_for(col_score, cfg)

    return {
        "col_item_price": col_item_price,
        "col_item_freight": col_item_freight,
        "col_order_id": col_order_id,
        "col_purchase": col_purchase,
        "col_seller_id": col_seller_id,
        "col_city": col_city,
        "col_score": col_score,
        "col_product_id": col_product_id,
        "cust_id": cust_id,
        "t_items": t_items,
        "t_orders": t_orders,
        "t_sellers": t_sellers,
        "t_customers": t_customers,
        "t_reviews": t_reviews,
        "revenue_measure": (
            f"SUM(oi.{col_name(col_item_price)} + oi.{col_name(col_item_freight)})"
        ),
    }


def _append_date_filter(conditions: list[str], params: list, date_range, col_purchase) -> None:
    if date_range:
        params.append(date_range[0])
        conditions.append(f"o.{col_name(col_purchase)} >= ${len(params)}")
        params.append(date_range[1])
        conditions.append(f"o.{col_name(col_purchase)} <= ${len(params)}")


def make_top_sellers(cfg: SchemaConfig) -> dict:
    schema = {
        "name": "top_sellers",
        "description": (
            "Top sellers ranked by revenue or order count, optionally filtered "
            "by seller state and date range. Includes seller location."
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
                "by": {
                    "type": "string",
                    "description": "Ranking measure: 'revenue' or 'orders'",
                },
            },
            "required": [],
        },
    }

    parts = _seller_item_parts(cfg)

    async def execute(
        date_token: Optional[str] = None,
        state: Optional[str] = None,
        limit: int = 10,
        by: str = "revenue",
    ) -> dict:
        filters: dict = {}
        by = str(by).lower().strip()
        if by not in ("revenue", "orders"):
            return {"error": "Invalid 'by' value. Use 'revenue' or 'orders'", "filters": {}}
        filters["by"] = by

        limit = clamp_limit(limit, default=10)
        filters["limit"] = limit

        date_range, err = _parse_date_token(date_token, filters)
        if err:
            return err

        normalized_state = None
        if state:
            normalized_state = state.upper().strip()
            filters["state"] = normalized_state

        params: list = []
        conditions: list[str] = []
        _append_date_filter(conditions, params, date_range, parts["col_purchase"])

        if normalized_state:
            params.append(normalized_state)
            conditions.append(f"s.{col_name(COL_SELLER_STATE)} = ${len(params)}")

        measure = (
            parts["revenue_measure"]
            if by == "revenue"
            else f"COUNT(DISTINCT o.{col_name(parts['col_order_id'])})"
        )

        params.append(limit)
        query = (
            f"SELECT oi.{col_name(parts['col_seller_id'])} AS seller_id, "
            f"s.{col_name(COL_SELLER_CITY)} AS seller_city, "
            f"s.{col_name(COL_SELLER_STATE)} AS seller_state, "
            f"{measure} AS value "
            f"FROM {parts['t_items']} oi "
            f"JOIN {parts['t_orders']} o ON oi.{col_name(parts['col_order_id'])} = o.{col_name(parts['col_order_id'])} "
            f"JOIN {parts['t_sellers']} s ON oi.{col_name(parts['col_seller_id'])} = s.{col_name(parts['col_seller_id'])} "
            f"WHERE {where_clause(conditions)} "
            f"GROUP BY oi.{col_name(parts['col_seller_id'])}, "
            f"s.{col_name(COL_SELLER_CITY)}, s.{col_name(COL_SELLER_STATE)} "
            f"ORDER BY value DESC NULLS LAST "
            f"LIMIT ${len(params)}"
        )

        try:
            rows = await execute_query(query, *params)
            sellers = [
                {
                    "seller_id": r["seller_id"],
                    "seller_city": r["seller_city"],
                    "seller_state": r["seller_state"],
                    "value": (float(r["value"] or 0) if by == "revenue" else int(r["value"])),
                }
                for r in rows
            ]
            return {"sellers": sellers, "by": by, "filters": filters}
        except Exception as e:
            logger.error(f"top_sellers query failed: {e}")
            return {
                "error": client_error(e, "A database error occurred while running your query."),
                "filters": filters,
            }

    return {"schema": schema, "execute": execute}


def make_seller_metrics(cfg: SchemaConfig) -> dict:
    schema = {
        "name": "seller_metrics",
        "description": (
            "Performance metrics for a single seller: order count, revenue, "
            "product count, average rating, and distinct customer cities served."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "seller_id": {
                    "type": "string",
                    "description": "Seller ID to look up",
                },
                "date_token": {
                    "type": "string",
                    "description": (
                        "Date range token: today, yesterday, this_week, last_week, "
                        "this_month, last_month, this_year, last_year"
                    ),
                },
            },
            "required": ["seller_id"],
        },
    }

    parts = _seller_item_parts(cfg)

    async def execute(
        seller_id: str,
        date_token: Optional[str] = None,
    ) -> dict:
        filters: dict = {}
        sid = str(seller_id).strip()
        if not sid:
            return {"error": "seller_id is required", "filters": {}}
        filters["seller_id"] = sid

        date_range, err = _parse_date_token(date_token, filters)
        if err:
            return err

        params: list = [sid]
        conditions = [f"oi.{col_name(parts['col_seller_id'])} = $1"]
        _append_date_filter(conditions, params, date_range, parts["col_purchase"])

        where = where_clause(conditions)

        orders_query = (
            f"SELECT COUNT(DISTINCT o.{col_name(parts['col_order_id'])}) "
            f"FROM {parts['t_items']} oi "
            f"JOIN {parts['t_orders']} o ON oi.{col_name(parts['col_order_id'])} = o.{col_name(parts['col_order_id'])} "
            f"WHERE {where}"
        )
        revenue_query = (
            f"SELECT {parts['revenue_measure']} "
            f"FROM {parts['t_items']} oi "
            f"JOIN {parts['t_orders']} o ON oi.{col_name(parts['col_order_id'])} = o.{col_name(parts['col_order_id'])} "
            f"WHERE {where}"
        )
        products_query = (
            f"SELECT COUNT(DISTINCT oi.{col_name(parts['col_product_id'])}) "
            f"FROM {parts['t_items']} oi "
            f"JOIN {parts['t_orders']} o ON oi.{col_name(parts['col_order_id'])} = o.{col_name(parts['col_order_id'])} "
            f"WHERE {where}"
        )
        rating_query = (
            f"SELECT AVG(r.{col_name(parts['col_score'])}) "
            f"FROM {parts['t_reviews']} r "
            f"JOIN {parts['t_orders']} o ON r.{col_name(parts['col_order_id'])} = o.{col_name(parts['col_order_id'])} "
            f"JOIN {parts['t_items']} oi ON o.{col_name(parts['col_order_id'])} = oi.{col_name(parts['col_order_id'])} "
            f"WHERE {where}"
        )
        cities_query = (
            f"SELECT COUNT(DISTINCT c.{col_name(parts['col_city'])}) "
            f"FROM {parts['t_items']} oi "
            f"JOIN {parts['t_orders']} o ON oi.{col_name(parts['col_order_id'])} = o.{col_name(parts['col_order_id'])} "
            f"JOIN {parts['t_customers']} c ON o.{col_name(parts['cust_id'])} = c.{col_name(parts['cust_id'])} "
            f"WHERE {where}"
        )

        try:
            orders = await execute_scalar(orders_query, *params)
            revenue = await execute_scalar(revenue_query, *params)
            products = await execute_scalar(products_query, *params)
            avg_rating = await execute_scalar(rating_query, *params)
            cities_served = await execute_scalar(cities_query, *params)

            return {
                "seller_id": sid,
                "orders": int(orders or 0),
                "revenue": float(revenue or 0),
                "products": int(products or 0),
                "avg_rating": float(avg_rating) if avg_rating is not None else None,
                "cities_served": int(cities_served or 0),
                "filters": filters,
            }
        except Exception as e:
            logger.error(f"seller_metrics query failed: {e}")
            return {
                "error": client_error(e, "A database error occurred while running your query."),
                "filters": filters,
            }

    return {"schema": schema, "execute": execute}


def make_seller_concentration(cfg: SchemaConfig) -> dict:
    schema = {
        "name": "seller_concentration",
        "description": (
            "Marketplace concentration: share of total revenue held by the "
            "top 10 sellers, plus total seller count and total revenue."
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

    parts = _seller_item_parts(cfg)

    async def execute(date_token: Optional[str] = None) -> dict:
        filters: dict = {}
        date_range, err = _parse_date_token(date_token, filters)
        if err:
            return err

        params: list = []
        conditions: list[str] = []
        _append_date_filter(conditions, params, date_range, parts["col_purchase"])

        query = (
            f"WITH seller_rev AS ( "
            f"  SELECT oi.{col_name(parts['col_seller_id'])} AS seller_id, "
            f"  {parts['revenue_measure']} AS revenue "
            f"  FROM {parts['t_items']} oi "
            f"  JOIN {parts['t_orders']} o ON oi.{col_name(parts['col_order_id'])} = o.{col_name(parts['col_order_id'])} "
            f"  WHERE {where_clause(conditions)} "
            f"  GROUP BY oi.{col_name(parts['col_seller_id'])} "
            f"), ranked AS ( "
            f"  SELECT seller_id, revenue, "
            f"  SUM(revenue) OVER () AS total_revenue, "
            f"  COUNT(*) OVER () AS total_sellers, "
            f"  ROW_NUMBER() OVER (ORDER BY revenue DESC NULLS LAST) AS rn "
            f"  FROM seller_rev "
            f") "
            f"SELECT "
            f"  COALESCE(SUM(CASE WHEN rn <= 10 THEN revenue ELSE 0 END), 0) AS top_10_revenue, "
            f"  MAX(total_revenue) AS total_revenue, "
            f"  MAX(total_sellers) AS total_sellers "
            f"FROM ranked"
        )

        try:
            rows = await execute_query(query, *params)
            row = rows[0] if rows else {}
            total_revenue = float(row.get("total_revenue") or 0)
            top_10_revenue = float(row.get("top_10_revenue") or 0)
            total_sellers = int(row.get("total_sellers") or 0)
            share_pct = (top_10_revenue / total_revenue * 100) if total_revenue else 0.0

            return {
                "top_10_revenue_share_pct": round(share_pct, 2),
                "total_sellers": total_sellers,
                "total_revenue": total_revenue,
                "filters": filters,
            }
        except Exception as e:
            logger.error(f"seller_concentration query failed: {e}")
            return {
                "error": client_error(e, "A database error occurred while running your query."),
                "filters": filters,
            }

    return {"schema": schema, "execute": execute}


def make_sellers_by_state(cfg: SchemaConfig) -> dict:
    schema = {
        "name": "sellers_by_state",
        "description": (
            "Seller activity broken down by seller state (UF), ranked by "
            "revenue or order count."
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
                "by": {
                    "type": "string",
                    "description": "Ranking measure: 'revenue' or 'orders'",
                },
            },
            "required": [],
        },
    }

    parts = _seller_item_parts(cfg)

    async def execute(
        date_token: Optional[str] = None,
        by: str = "revenue",
    ) -> dict:
        filters: dict = {}
        by = str(by).lower().strip()
        if by not in ("revenue", "orders"):
            return {"error": "Invalid 'by' value. Use 'revenue' or 'orders'", "filters": {}}
        filters["by"] = by

        date_range, err = _parse_date_token(date_token, filters)
        if err:
            return err

        params: list = []
        conditions: list[str] = []
        _append_date_filter(conditions, params, date_range, parts["col_purchase"])

        measure = (
            parts["revenue_measure"]
            if by == "revenue"
            else f"COUNT(DISTINCT o.{col_name(parts['col_order_id'])})"
        )
        group_expr = f"s.{col_name(COL_SELLER_STATE)}"

        query = (
            f"SELECT {group_expr} AS seller_state, {measure} AS value "
            f"FROM {parts['t_items']} oi "
            f"JOIN {parts['t_orders']} o ON oi.{col_name(parts['col_order_id'])} = o.{col_name(parts['col_order_id'])} "
            f"JOIN {parts['t_sellers']} s ON oi.{col_name(parts['col_seller_id'])} = s.{col_name(parts['col_seller_id'])} "
            f"WHERE {where_clause(conditions)} "
            f"GROUP BY {group_expr} "
            f"ORDER BY value DESC NULLS LAST"
        )

        try:
            rows = await execute_query(query, *params)
            breakdown = [
                {
                    "seller_state": r["seller_state"],
                    "value": (float(r["value"] or 0) if by == "revenue" else int(r["value"])),
                }
                for r in rows
            ]
            return {"breakdown": breakdown, "by": by, "filters": filters}
        except Exception as e:
            logger.error(f"sellers_by_state query failed: {e}")
            return {
                "error": client_error(e, "A database error occurred while running your query."),
                "filters": filters,
            }

    return {"schema": schema, "execute": execute}
