"""Customer analytics functions — schema-aware.

Lifetime value, repeat rate, geographic distribution, order history,
and simplified cohort analysis. Each factory closes over SchemaConfig
and emits SQL via col_name()/table_for().
"""
import logging
from typing import Optional

from config import settings
from db import execute_query, execute_scalar
from errors import client_error
from functions._filters import clamp_limit, resolve_order_filters, where_clause
from functions._helpers import col_name, table_for
from schemas.base import SchemaConfig
from validation.dates import parse_date_range

logger = logging.getLogger(__name__)

VALID_COHORT_METRICS = {"revenue", "retention"}


def _parse_date_token(date_token: Optional[str], filters: dict) -> tuple[Optional[tuple], Optional[dict]]:
    if not date_token:
        return None, None
    try:
        date_range = parse_date_range(date_token, settings.reference_datetime)
        if date_range:
            filters["date_range"] = [date_range[0].isoformat(), date_range[1].isoformat()]
        return date_range, None
    except Exception as e:
        return None, {"error": f"Date validation failed: {str(e)}", "filters": filters}


CUSTOMER_LIFETIME_VALUE_SCHEMA = {
    "name": "customer_lifetime_value",
    "description": (
        "Top customers ranked by lifetime value (sum of payment_value), "
        "optionally filtered by customer city or state."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "city": {"type": "string", "description": "Customer city (optional, will be normalized)"},
            "state": {"type": "string", "description": "Customer state/UF (optional, e.g., 'SP', 'RJ')"},
            "min_orders": {
                "type": "integer",
                "description": "Minimum number of orders a customer must have (default 1)",
            },
            "limit": {
                "type": "integer",
                "description": "Number of top customers to return (default 10, max 25)",
            },
        },
        "required": [],
    },
}


REPEAT_CUSTOMER_RATE_SCHEMA = {
    "name": "repeat_customer_rate",
    "description": (
        "Repeat customer rate: percentage of customers with more than one order, "
        "plus total customers and average orders per customer."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "date_token": {
                "type": "string",
                "description": "Date range token: 'today', 'yesterday', 'this_week', 'last_week', 'this_month', 'last_month', 'this_year', 'last_year'",
            },
        },
        "required": [],
    },
}


CUSTOMERS_BY_CITY_SCHEMA = {
    "name": "customers_by_city",
    "description": "Count distinct customers grouped by city, ordered by count descending.",
    "parameters": {
        "type": "object",
        "properties": {
            "date_token": {
                "type": "string",
                "description": "Date range token: 'today', 'yesterday', 'this_week', 'last_week', 'this_month', 'last_month', 'this_year', 'last_year'",
            },
            "limit": {
                "type": "integer",
                "description": "Number of cities to return (default 10, max 25)",
            },
        },
        "required": [],
    },
}


CUSTOMER_ORDER_HISTORY_SCHEMA = {
    "name": "customer_order_history",
    "description": (
        "Paginated order history for a single customer: status, purchase date, "
        "and total payment per order."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "customer_id": {"type": "string", "description": "Customer ID (required)"},
            "limit": {"type": "integer", "description": "Maximum rows per page (default 20, max 50)"},
            "offset": {"type": "integer", "description": "Rows to skip for pagination (default 0)"},
        },
        "required": ["customer_id"],
    },
}


CUSTOMER_COHORT_ANALYSIS_SCHEMA = {
    "name": "customer_cohort_analysis",
    "description": (
        "Simplified cohort analysis: customers whose first order falls in the "
        "cohort date window, with revenue or retention stats in that same window."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "cohort_date_token": {
                "type": "string",
                "description": "Date range token defining the cohort window (first-order month window)",
            },
            "metric": {
                "type": "string",
                "enum": ["revenue", "retention"],
                "description": "Cohort metric: 'revenue' (sum of payments) or 'retention' (repeat rate within window)",
            },
        },
        "required": ["cohort_date_token"],
    },
}


def make_customer_lifetime_value(cfg: SchemaConfig) -> dict:
    cust_id = cfg.get_column("customer_id")
    col_unique_id = cfg.get_column("customer_unique_id")
    col_pay_value = cfg.get_column("payment_value")
    col_order_id = cfg.get_column("order_id")
    col_city = cfg.get_column("customer_city")
    col_state = cfg.get_column("customer_state")

    t_payments = table_for(col_pay_value, cfg)
    t_orders = table_for(col_order_id, cfg)
    t_customers = table_for(col_city, cfg)

    async def execute(
        city: Optional[str] = None,
        state: Optional[str] = None,
        min_orders: int = 1,
        limit: int = 10,
    ) -> dict:
        filters: dict = {}

        try:
            min_orders = int(min_orders)
        except (TypeError, ValueError):
            min_orders = 1
        min_orders = max(1, min_orders)
        filters["min_orders"] = min_orders

        limit = clamp_limit(limit, default=10)
        filters["limit"] = limit

        fb = await resolve_order_filters(
            city=city,
            state=state,
            col_city=col_city,
            col_state=col_state,
            col_status=cfg.get_column("order_status"),
            col_purchase=cfg.get_column("order_purchase_timestamp"),
        )
        if fb.error:
            return fb.error
        filters.update(fb.filters)

        where = where_clause(fb.conditions)
        params = list(fb.params)
        having_idx = len(params) + 1
        params.append(min_orders)
        limit_idx = len(params) + 1
        params.append(limit)

        query = (
            f"SELECT o.{col_name(cust_id)} AS customer_id, "
            f"c.{col_name(col_unique_id)} AS customer_unique_id, "
            f"SUM(p.{col_name(col_pay_value)}) AS lifetime_value, "
            f"COUNT(DISTINCT o.{col_name(col_order_id)}) AS order_count "
            f"FROM {t_payments} p "
            f"JOIN {t_orders} o ON p.{col_name(col_order_id)} = o.{col_name(col_order_id)} "
            f"LEFT JOIN {t_customers} c ON o.{col_name(cust_id)} = c.{col_name(cust_id)} "
            f"WHERE {where} "
            f"GROUP BY o.{col_name(cust_id)}, c.{col_name(col_unique_id)} "
            f"HAVING COUNT(DISTINCT o.{col_name(col_order_id)}) >= ${having_idx} "
            f"ORDER BY lifetime_value DESC NULLS LAST "
            f"LIMIT ${limit_idx}"
        )

        try:
            rows = await execute_query(query, *params)
            customers = [
                {
                    "customer_id": r["customer_id"],
                    "customer_unique_id": r["customer_unique_id"],
                    "lifetime_value": float(r["lifetime_value"] or 0),
                    "order_count": int(r["order_count"] or 0),
                }
                for r in rows
            ]
            return {"customers": customers, "filters": filters}
        except Exception as e:
            logger.error(f"Query failed: {e}")
            return {
                "error": client_error(e, "A database error occurred while running your query."),
                "filters": filters,
            }

    return {"schema": CUSTOMER_LIFETIME_VALUE_SCHEMA, "execute": execute}


def make_repeat_customer_rate(cfg: SchemaConfig) -> dict:
    cust_id = cfg.get_column("customer_id")
    col_order_id = cfg.get_column("order_id")
    col_purchase = cfg.get_column("order_purchase_timestamp")
    col_status = cfg.get_column("order_status")

    t_orders = table_for(col_order_id, cfg)

    async def execute(date_token: Optional[str] = None) -> dict:
        filters: dict = {}

        fb = await resolve_order_filters(
            date_token=date_token,
            col_city=cfg.get_column("customer_city"),
            col_state=cfg.get_column("customer_state"),
            col_status=col_status,
            col_purchase=col_purchase,
            alias_o="o",
        )
        if fb.error:
            return fb.error
        filters.update(fb.filters)

        where = where_clause(fb.conditions)
        params = list(fb.params)

        query = (
            f"WITH customer_orders AS ("
            f"  SELECT o.{col_name(cust_id)} AS customer_id, COUNT(*) AS order_count "
            f"  FROM {t_orders} o "
            f"  WHERE {where} "
            f"  GROUP BY o.{col_name(cust_id)}"
            f") "
            f"SELECT "
            f"  COUNT(*) AS total_customers, "
            f"  COUNT(*) FILTER (WHERE order_count > 1) AS customers_with_multiple_orders, "
            f"  ROUND("
            f"    100.0 * COUNT(*) FILTER (WHERE order_count > 1) / NULLIF(COUNT(*), 0), "
            f"    2"
            f"  ) AS repeat_rate_pct, "
            f"  ROUND(AVG(order_count)::numeric, 2) AS avg_orders_per_customer "
            f"FROM customer_orders"
        )

        try:
            rows = await execute_query(query, *params)
            row = rows[0] if rows else {}
            return {
                "repeat_rate_pct": float(row.get("repeat_rate_pct") or 0),
                "customers_with_multiple_orders": int(row.get("customers_with_multiple_orders") or 0),
                "total_customers": int(row.get("total_customers") or 0),
                "avg_orders_per_customer": float(row.get("avg_orders_per_customer") or 0),
                "filters": filters,
            }
        except Exception as e:
            logger.error(f"Query failed: {e}")
            return {
                "error": client_error(e, "A database error occurred while running your query."),
                "filters": filters,
            }

    return {"schema": REPEAT_CUSTOMER_RATE_SCHEMA, "execute": execute}


def make_customers_by_city(cfg: SchemaConfig) -> dict:
    cust_id = cfg.get_column("customer_id")
    col_order_id = cfg.get_column("order_id")
    col_purchase = cfg.get_column("order_purchase_timestamp")
    col_city = cfg.get_column("customer_city")
    col_status = cfg.get_column("order_status")

    t_orders = table_for(col_order_id, cfg)
    t_customers = table_for(col_city, cfg)

    async def execute(date_token: Optional[str] = None, limit: int = 10) -> dict:
        filters: dict = {}
        limit = clamp_limit(limit, default=10)
        filters["limit"] = limit

        fb = await resolve_order_filters(
            date_token=date_token,
            col_city=col_city,
            col_state=cfg.get_column("customer_state"),
            col_status=col_status,
            col_purchase=col_purchase,
        )
        if fb.error:
            return fb.error
        filters.update(fb.filters)

        where = where_clause(fb.conditions)
        params = list(fb.params)
        limit_idx = len(params) + 1
        params.append(limit)

        query = (
            f"SELECT c.{col_name(col_city)} AS city, "
            f"COUNT(DISTINCT o.{col_name(cust_id)}) AS customer_count "
            f"FROM {t_orders} o "
            f"JOIN {t_customers} c ON o.{col_name(cust_id)} = c.{col_name(cust_id)} "
            f"WHERE {where} "
            f"GROUP BY c.{col_name(col_city)} "
            f"ORDER BY customer_count DESC NULLS LAST "
            f"LIMIT ${limit_idx}"
        )

        try:
            rows = await execute_query(query, *params)
            cities = [
                {"city": r["city"], "customer_count": int(r["customer_count"] or 0)}
                for r in rows
            ]
            return {"cities": cities, "filters": filters}
        except Exception as e:
            logger.error(f"Query failed: {e}")
            return {
                "error": client_error(e, "A database error occurred while running your query."),
                "filters": filters,
            }

    return {"schema": CUSTOMERS_BY_CITY_SCHEMA, "execute": execute}


def make_customer_order_history(cfg: SchemaConfig) -> dict:
    cust_id = cfg.get_column("customer_id")
    col_order_id = cfg.get_column("order_id")
    col_status = cfg.get_column("order_status")
    col_purchase = cfg.get_column("order_purchase_timestamp")
    col_pay_value = cfg.get_column("payment_value")

    t_orders = table_for(col_order_id, cfg)
    t_payments = table_for(col_pay_value, cfg)

    async def execute(
        customer_id: str,
        limit: int = 20,
        offset: int = 0,
    ) -> dict:
        filters: dict = {}

        customer_id = str(customer_id).strip() if customer_id is not None else ""
        if not customer_id:
            return {"error": "customer_id is required", "filters": filters}
        filters["customer_id"] = customer_id

        try:
            limit = int(limit)
        except (TypeError, ValueError):
            limit = 20
        limit = max(1, min(50, limit))
        filters["limit"] = limit

        try:
            offset = int(offset)
        except (TypeError, ValueError):
            offset = 0
        offset = max(0, offset)
        filters["offset"] = offset

        count_query = (
            f"SELECT COUNT(*) "
            f"FROM {t_orders} o "
            f"WHERE o.{col_name(cust_id)} = $1"
        )

        rows_query = (
            f"SELECT o.{col_name(col_order_id)} AS order_id, "
            f"o.{col_name(col_status)} AS order_status, "
            f"o.{col_name(col_purchase)} AS order_purchase_timestamp, "
            f"COALESCE(pay.payment_total, 0) AS payment_total "
            f"FROM {t_orders} o "
            f"LEFT JOIN ("
            f"  SELECT {col_name(col_order_id)} AS order_id, "
            f"         SUM({col_name(col_pay_value)}) AS payment_total "
            f"  FROM {t_payments} "
            f"  GROUP BY {col_name(col_order_id)}"
            f") pay ON o.{col_name(col_order_id)} = pay.order_id "
            f"WHERE o.{col_name(cust_id)} = $1 "
            f"ORDER BY o.{col_name(col_purchase)} DESC NULLS LAST "
            f"LIMIT $2 OFFSET $3"
        )

        try:
            total = await execute_scalar(count_query, customer_id)
            rows = await execute_query(rows_query, customer_id, limit, offset)
            orders = []
            for r in rows:
                ts = r["order_purchase_timestamp"]
                orders.append(
                    {
                        "order_id": r["order_id"],
                        "order_status": r["order_status"],
                        "order_purchase_timestamp": ts.isoformat() if ts else None,
                        "payment_total": float(r["payment_total"] or 0),
                    }
                )
            return {
                "orders": orders,
                "total_count": total or 0,
                "limit": limit,
                "offset": offset,
                "filters": filters,
            }
        except Exception as e:
            logger.error(f"Query failed: {e}")
            return {
                "error": client_error(e, "A database error occurred while running your query."),
                "filters": filters,
            }

    return {"schema": CUSTOMER_ORDER_HISTORY_SCHEMA, "execute": execute}


def make_customer_cohort_analysis(cfg: SchemaConfig) -> dict:
    cust_id = cfg.get_column("customer_id")
    col_order_id = cfg.get_column("order_id")
    col_purchase = cfg.get_column("order_purchase_timestamp")
    col_pay_value = cfg.get_column("payment_value")

    t_orders = table_for(col_order_id, cfg)
    t_payments = table_for(col_pay_value, cfg)

    async def execute(
        cohort_date_token: str,
        metric: str = "revenue",
    ) -> dict:
        filters: dict = {}

        if not cohort_date_token:
            return {"error": "cohort_date_token is required", "filters": filters}

        metric = str(metric).lower().strip() if metric else "revenue"
        if metric not in VALID_COHORT_METRICS:
            return {
                "error": f"Invalid metric '{metric}'. Allowed: revenue, retention",
                "filters": filters,
            }
        filters["metric"] = metric
        filters["cohort_date_token"] = cohort_date_token

        date_range, err = _parse_date_token(cohort_date_token, filters)
        if err:
            return err
        if not date_range:
            return {
                "error": "Could not resolve cohort_date_token to a date range",
                "filters": filters,
            }

        start, end = date_range
        params = [start, end]

        cohort_cte = (
            f"WITH first_orders AS ("
            f"  SELECT o.{col_name(cust_id)} AS customer_id, "
            f"         MIN(o.{col_name(col_purchase)}) AS first_order_at "
            f"  FROM {t_orders} o "
            f"  GROUP BY o.{col_name(cust_id)}"
            f"), "
            f"cohort_customers AS ("
            f"  SELECT fo.customer_id, "
            f"         date_trunc('month', fo.first_order_at) AS cohort_month "
            f"  FROM first_orders fo "
            f"  WHERE fo.first_order_at >= $1 AND fo.first_order_at <= $2"
            f")"
        )

        if metric == "revenue":
            query = (
                f"{cohort_cte} "
                f"SELECT to_char(cc.cohort_month, 'YYYY-MM') AS cohort_month, "
                f"COUNT(DISTINCT cc.customer_id) AS cohort_size, "
                f"COALESCE(SUM(p.{col_name(col_pay_value)}), 0) AS revenue "
                f"FROM cohort_customers cc "
                f"JOIN {t_orders} o ON o.{col_name(cust_id)} = cc.customer_id "
                f"JOIN {t_payments} p ON p.{col_name(col_order_id)} = o.{col_name(col_order_id)} "
                f"WHERE o.{col_name(col_purchase)} >= $1 AND o.{col_name(col_purchase)} <= $2 "
                f"GROUP BY cc.cohort_month "
                f"ORDER BY cc.cohort_month ASC"
            )
        else:
            query = (
                f"{cohort_cte}, "
                f"window_orders AS ("
                f"  SELECT o.{col_name(cust_id)} AS customer_id, COUNT(*) AS order_count "
                f"  FROM {t_orders} o "
                f"  WHERE o.{col_name(col_purchase)} >= $1 AND o.{col_name(col_purchase)} <= $2 "
                f"  GROUP BY o.{col_name(cust_id)}"
                f") "
                f"SELECT to_char(cc.cohort_month, 'YYYY-MM') AS cohort_month, "
                f"COUNT(DISTINCT cc.customer_id) AS cohort_size, "
                f"COUNT(DISTINCT CASE WHEN wo.order_count > 1 THEN cc.customer_id END) AS repeat_customers, "
                f"ROUND("
                f"  100.0 * COUNT(DISTINCT CASE WHEN wo.order_count > 1 THEN cc.customer_id END) "
                f"  / NULLIF(COUNT(DISTINCT cc.customer_id), 0), "
                f"  2"
                f") AS retention_pct "
                f"FROM cohort_customers cc "
                f"LEFT JOIN window_orders wo ON wo.customer_id = cc.customer_id "
                f"GROUP BY cc.cohort_month "
                f"ORDER BY cc.cohort_month ASC"
            )

        try:
            rows = await execute_query(query, *params)
            cohorts = []
            for r in rows:
                entry = {
                    "cohort_month": r["cohort_month"],
                    "cohort_size": int(r["cohort_size"] or 0),
                }
                if metric == "revenue":
                    entry["revenue"] = float(r["revenue"] or 0)
                else:
                    entry["repeat_customers"] = int(r["repeat_customers"] or 0)
                    entry["retention_pct"] = float(r["retention_pct"] or 0)
                cohorts.append(entry)
            return {"cohorts": cohorts, "metric": metric, "filters": filters}
        except Exception as e:
            logger.error(f"Query failed: {e}")
            return {
                "error": client_error(e, "A database error occurred while running your query."),
                "filters": filters,
            }

    return {"schema": CUSTOMER_COHORT_ANALYSIS_SCHEMA, "execute": execute}
