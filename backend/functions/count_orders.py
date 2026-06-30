"""count_orders function — schema-aware.

Returns the number of orders matching optional filters (city, state,
status, date range). Parameter names are domain-neutral; the SQL
emitter reads table/column names from the active SchemaConfig.

This file is config-driven: the active `SchemaConfig` provides the
physical table and column names. Switching schemas (e.g. SCHEMA=shopify)
is what makes this query run against a different DB.
"""
import logging
from typing import Optional
from datetime import datetime
from db import execute_scalar
from validation.cities import resolve_city
from validation.dates import parse_date_range
from validation.enums import validate_order_status, ValidationError
from config import settings
from errors import client_error
from schemas.base import SchemaConfig

logger = logging.getLogger(__name__)


# Parameter schema is the SAME across schemas (the LLM is told the
# parameter names; only the SQL emitter differs per schema).
SCHEMA = {
    "name": "count_orders",
    "description": "Count orders with optional filters by city, state, status, and date range",
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
        },
        "required": [],
    },
}


def make_count_orders(cfg: SchemaConfig) -> dict:
    """Factory: build a registry entry bound to the given config.

    The `execute` returned here closes over `cfg`, so callers don't
    need to thread the config through. The SQL is emitted against the
    config's tables/columns.
    """
    t_orders = cfg.get_table("orders")
    t_customers = cfg.get_table("customers")
    col_city = cfg.get_column("customer_city")
    col_state = cfg.get_column("customer_state")
    col_status = cfg.get_column("order_status")
    col_purchase = cfg.get_column("order_purchase_timestamp")

    async def execute(
        city: Optional[str] = None,
        state: Optional[str] = None,
        status: Optional[str] = None,
        date_token: Optional[str] = None,
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

        # Build the SQL against the active schema's table/column names.
        # Note: we use simple string interpolation here for table/column
        # identifiers (safe — these come from a frozen SchemaConfig, not
        # user input). User values are parameterized via $1, $2, ...
        cust_id_col = cfg.get_column("customer_id").column
        query = (
            f"SELECT COUNT(*) as count "
            f"FROM {t_orders} o "
            f"LEFT JOIN {t_customers} c ON o.{cust_id_col} = c.{cust_id_col} "
            f"WHERE 1=1"
        )

        params = []

        if normalized_city:
            query += f" AND c.{col_city.column} = ${len(params) + 1}"
            params.append(normalized_city)

        if normalized_state:
            query += f" AND c.{col_state.column} = ${len(params) + 1}"
            params.append(normalized_state)

        if normalized_status:
            query += f" AND o.{col_status.column} = ${len(params) + 1}"
            params.append(normalized_status)

        if date_range:
            query += f" AND o.{col_purchase.column} >= ${len(params) + 1}"
            query += f" AND o.{col_purchase.column} <= ${len(params) + 2}"
            params.extend([date_range[0], date_range[1]])

        try:
            count = await execute_scalar(query, *params)
            return {"count": count or 0, "filters": filters}
        except Exception as e:
            logger.error(f"Query failed: {e}")
            return {
                "error": client_error(e, "A database error occurred while running your query."),
                "filters": filters,
            }

    return {"schema": SCHEMA, "execute": execute}
