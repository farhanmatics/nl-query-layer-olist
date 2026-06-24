import logging
from typing import Optional
from datetime import datetime
from db import execute_scalar
from validation.cities import resolve_city
from validation.dates import parse_date_range
from validation.enums import validate_order_status, ValidationError
from config import settings

logger = logging.getLogger(__name__)

SCHEMA = {
    "name": "count_orders",
    "description": "Count orders with optional filters by city, state, status, and date range",
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
        },
        "required": [],
    },
}


async def execute(
    city: Optional[str] = None,
    state: Optional[str] = None,
    status: Optional[str] = None,
    date_token: Optional[str] = None,
) -> dict:
    """
    Count orders with optional filters.

    Returns:
        {
            "count": int,
            "filters": {
                "city": str | None,
                "state": str | None,
                "status": str | None,
                "date_range": [start_iso, end_iso] | None,
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

    query = """
    SELECT COUNT(*) as count
    FROM olist_orders_dataset o
    LEFT JOIN olist_customers_dataset c ON o.customer_id = c.customer_id
    WHERE 1=1
    """

    params = []

    if normalized_city:
        query += " AND c.customer_city = $" + str(len(params) + 1)
        params.append(normalized_city)

    if normalized_state:
        query += " AND c.customer_state = $" + str(len(params) + 1)
        params.append(normalized_state)

    if normalized_status:
        query += " AND o.order_status = $" + str(len(params) + 1)
        params.append(normalized_status)

    if date_range:
        query += " AND o.order_purchase_timestamp >= $" + str(len(params) + 1)
        query += " AND o.order_purchase_timestamp <= $" + str(len(params) + 2)
        params.extend([date_range[0], date_range[1]])

    try:
        count = await execute_scalar(query, *params)
        return {
            "count": count or 0,
            "filters": filters,
        }
    except Exception as e:
        logger.error(f"Query failed: {e}")
        return {
            "error": f"Database query failed: {str(e)}",
            "filters": filters,
        }
