import logging
from typing import Optional
from datetime import datetime
from db import execute_query, execute_scalar
from validation.cities import resolve_city
from validation.dates import parse_date_range
from validation.enums import validate_order_status, ValidationError
from config import settings

logger = logging.getLogger(__name__)

SCHEMA = {
    "name": "list_orders",
    "description": "List individual orders matching optional filters (city, state, status, date range), paginated. Returns at most 50 rows per page.",
    "parameters": {
        "type": "object",
        "properties": {
            "city": {
                "type": "string",
                "description": "Customer city (optional, will be normalized)",
            },
            "state": {
                "type": "string",
                "description": "Customer state/UF (optional, e.g., 'SP', 'RJ')",
            },
            "status": {
                "type": "string",
                "description": "Order status (optional, e.g., 'delivered', 'shipped', 'canceled')",
            },
            "date_token": {
                "type": "string",
                "description": "Date range token: 'today', 'yesterday', 'this_week', 'last_week', 'this_month', 'last_month', 'this_year', 'last_year'",
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of rows to return per page (default 20, max 50)",
            },
            "offset": {
                "type": "integer",
                "description": "Number of rows to skip for pagination (default 0)",
            },
        },
        "required": [],
    },
}


async def execute(
    city: Optional[str] = None,
    state: Optional[str] = None,
    status: Optional[str] = None,
    date_token: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
) -> dict:
    """
    List orders with optional filters, paginated.

    Returns:
        {
            "orders": [
                {
                    "order_id": str,
                    "order_status": str,
                    "order_purchase_timestamp": str | None,
                    "customer_city": str | None,
                    "customer_state": str | None,
                },
                ...
            ],
            "total_count": int,
            "limit": int,
            "offset": int,
            "filters": {
                "city": str | None,
                "state": str | None,
                "status": str | None,
                "date_range": [start_iso, end_iso] | None,
                "limit": int,
                "offset": int,
            }
        }
    """
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
        where += " AND c.customer_city = $" + str(len(params) + 1)
        params.append(normalized_city)

    if normalized_state:
        where += " AND c.customer_state = $" + str(len(params) + 1)
        params.append(normalized_state)

    if normalized_status:
        where += " AND o.order_status = $" + str(len(params) + 1)
        params.append(normalized_status)

    if date_range:
        where += " AND o.order_purchase_timestamp >= $" + str(len(params) + 1)
        where += " AND o.order_purchase_timestamp <= $" + str(len(params) + 2)
        params.extend([date_range[0], date_range[1]])

    count_query = (
        """
    SELECT COUNT(*)
    FROM olist_orders_dataset o
    LEFT JOIN olist_customers_dataset c ON o.customer_id = c.customer_id
    """
        + where
    )

    rows_query = (
        """
    SELECT o.order_id, o.order_status, o.order_purchase_timestamp, c.customer_city, c.customer_state
    FROM olist_orders_dataset o
    LEFT JOIN olist_customers_dataset c ON o.customer_id = c.customer_id
    """
        + where
        + " ORDER BY o.order_purchase_timestamp DESC NULLS LAST"
        + " LIMIT $" + str(len(params) + 1)
        + " OFFSET $" + str(len(params) + 2)
    )

    rows_params = params + [limit, offset]

    try:
        total = await execute_scalar(count_query, *params)
        rows = await execute_query(rows_query, *rows_params)

        orders = []
        for r in rows:
            orders.append(
                {
                    "order_id": r["order_id"],
                    "order_status": r["order_status"],
                    "order_purchase_timestamp": r["order_purchase_timestamp"].isoformat()
                    if r["order_purchase_timestamp"]
                    else None,
                    "customer_city": r["customer_city"],
                    "customer_state": r["customer_state"],
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
            "error": f"Database query failed: {str(e)}",
            "filters": filters,
        }
