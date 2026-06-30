"""list_orders function — schema-aware.

Paginated list of orders with optional filters (city, state, status,
date range). Limit is clamped to [1, 50]; offset is clamped to [0, ∞).
"""
import logging
from typing import Optional
from db import execute_query, execute_scalar
from validation.cities import resolve_city
from validation.dates import parse_date_range
from validation.enums import validate_order_status, ValidationError
from config import settings
from errors import client_error
from functions._helpers import col_name, table_for
from schemas.base import SchemaConfig

logger = logging.getLogger(__name__)


SCHEMA = {
    "name": "list_orders",
    "description": "List individual orders matching optional filters (city, state, status, date range), paginated. Returns at most 50 rows per page.",
    "parameters": {
        "type": "object",
        "properties": {
            "city": {"type": "string", "description": "Customer city (optional, will be normalized)"},
            "state": {"type": "string", "description": "Customer state/UF (optional, e.g., 'SP', 'RJ')"},
            "status": {"type": "string", "description": "Order status (optional, e.g., 'delivered', 'shipped', 'canceled')"},
            "date_token": {
                "type": "string",
                "description": "Date range token: 'today', 'yesterday', 'this_week', 'last_week', 'this_month', 'last_month', 'this_year', 'last_year'",
            },
            "limit": {"type": "integer", "description": "Maximum number of rows to return per page (default 20, max 50)"},
            "offset": {"type": "integer", "description": "Number of rows to skip for pagination (default 0)"},
        },
        "required": [],
    },
}


def make_list_orders(cfg: SchemaConfig) -> dict:
    cust_id = cfg.get_column("customer_id")
    col_order_id = cfg.get_column("order_id")
    col_status = cfg.get_column("order_status")
    col_purchase = cfg.get_column("order_purchase_timestamp")
    col_city = cfg.get_column("customer_city")
    col_state = cfg.get_column("customer_state")

    t_orders = table_for(col_order_id, cfg)
    t_customers = table_for(col_city, cfg)

    async def execute(
        city: Optional[str] = None,
        state: Optional[str] = None,
        status: Optional[str] = None,
        date_token: Optional[str] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> dict:
        filters = {}

        normalized_city = None
        if city:
            try:
                normalized_city = await resolve_city(city)
                if not normalized_city:
                    return {
                        "error": f"City '{city}' not found in database",
                        "filters": {"city": city},
                    }
                filters["city"] = normalized_city
            except Exception as e:
                return {"error": f"City validation failed: {str(e)}", "filters": {}}

        normalized_state = None
        if state:
            normalized_state = state.upper().strip()
            filters["state"] = normalized_state

        normalized_status = None
        if status:
            try:
                normalized_status = validate_order_status(status)
                filters["status"] = normalized_status
            except ValidationError as e:
                return {"error": str(e), "filters": filters}

        date_range = None
        if date_token:
            try:
                date_range = parse_date_range(date_token, settings.reference_datetime)
                if date_range:
                    filters["date_range"] = [date_range[0].isoformat(), date_range[1].isoformat()]
            except Exception as e:
                return {"error": f"Date validation failed: {str(e)}", "filters": filters}

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

        where = " WHERE 1=1"
        params = []

        if normalized_city:
            where += f" AND c.{col_name(col_city)} = ${len(params) + 1}"
            params.append(normalized_city)

        if normalized_state:
            where += f" AND c.{col_name(col_state)} = ${len(params) + 1}"
            params.append(normalized_state)

        if normalized_status:
            where += f" AND o.{col_name(col_status)} = ${len(params) + 1}"
            params.append(normalized_status)

        if date_range:
            where += f" AND o.{col_name(col_purchase)} >= ${len(params) + 1}"
            where += f" AND o.{col_name(col_purchase)} <= ${len(params) + 2}"
            params.extend([date_range[0], date_range[1]])

        count_query = (
            f"SELECT COUNT(*) "
            f"FROM {t_orders} o "
            f"LEFT JOIN {t_customers} c ON o.{col_name(cust_id)} = c.{col_name(cust_id)}"
            f"{where}"
        )

        rows_query = (
            f"SELECT o.{col_name(col_order_id)}, o.{col_name(col_status)}, o.{col_name(col_purchase)}, c.{col_name(col_city)}, c.{col_name(col_state)} "
            f"FROM {t_orders} o "
            f"LEFT JOIN {t_customers} c ON o.{col_name(cust_id)} = c.{col_name(cust_id)}"
            f"{where} "
            f"ORDER BY o.{col_name(col_purchase)} DESC NULLS LAST "
            f"LIMIT ${len(params) + 1} "
            f"OFFSET ${len(params) + 2}"
        )

        rows_params = params + [limit, offset]

        try:
            total = await execute_scalar(count_query, *params)
            rows = await execute_query(rows_query, *rows_params)

            orders = []
            for r in rows:
                orders.append(
                    {
                        "order_id": r[col_name(col_order_id)],
                        "order_status": r[col_name(col_status)],
                        "order_purchase_timestamp": r[col_name(col_purchase)].isoformat()
                        if r[col_name(col_purchase)]
                        else None,
                        "customer_city": r[col_name(col_city)],
                        "customer_state": r[col_name(col_state)],
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

    return {"schema": SCHEMA, "execute": execute}
