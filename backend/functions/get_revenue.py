import logging
from typing import Optional
from db import execute_scalar, execute_query
from validation.dates import parse_date_range
from validation.cities import resolve_city
from config import settings
from errors import client_error

logger = logging.getLogger(__name__)

VALID_GROUP_BY = {"state", "category", "month"}

SCHEMA = {
    "name": "get_revenue",
    "description": (
        "Total revenue, optionally filtered by date range, customer city, "
        "customer state, or product category, and optionally broken down "
        "(grouped) by state, category, or month."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "date_token": {
                "type": "string",
                "description": "Date range token: today, yesterday, this_week, last_week, this_month, last_month, this_year, last_year",
            },
            "city": {
                "type": "string",
                "description": "Customer city, e.g. 'sao paulo', 'rio de janeiro' (will be normalized)",
            },
            "state": {
                "type": "string",
                "description": "Customer state/UF, e.g. 'SP', 'RJ'",
            },
            "category": {
                "type": "string",
                "description": "Product category in English, e.g. 'health_beauty', 'bed_bath_table'",
            },
            "group_by": {
                "type": "string",
                "enum": ["state", "category", "month"],
                "description": "Optional breakdown dimension",
            },
        },
        "required": [],
    },
}


async def execute(
    date_token: Optional[str] = None,
    city: Optional[str] = None,
    state: Optional[str] = None,
    category: Optional[str] = None,
    group_by: Optional[str] = None,
) -> dict:
    """
    Sum revenue with optional filters and an optional breakdown.

    Revenue source note: payments give the truest revenue (SUM(payment_value)),
    but payment_value is per-ORDER and cannot be attributed to a product
    category. Whenever a category is involved (filter or group_by=category) we
    measure at the item level (price + freight) to avoid the payments<->items
    fan-out that would otherwise inflate the sum.
    """
    filters = {}

    if group_by is not None:
        group_by = str(group_by).lower().strip()
        if group_by not in VALID_GROUP_BY:
            return {
                "error": f"Invalid group_by '{group_by}'. Allowed: state, category, month",
                "filters": filters,
            }
        filters["group_by"] = group_by

    normalized_city = None
    if city:
        normalized_city = await resolve_city(city)
        if not normalized_city:
            return {
                "error": f"City '{city}' not found in database",
                "filters": {"city": city},
            }
        filters["city"] = normalized_city

    normalized_state = None
    if state:
        normalized_state = state.upper().strip()
        filters["state"] = normalized_state

    normalized_category = None
    if category:
        normalized_category = str(category).lower().strip()
        filters["category"] = normalized_category

    date_range = None
    if date_token:
        try:
            date_range = parse_date_range(date_token, settings.reference_datetime)
            if date_range:
                filters["date_range"] = [
                    date_range[0].isoformat(),
                    date_range[1].isoformat(),
                ]
        except Exception as e:
            return {"error": f"Date validation failed: {str(e)}", "filters": filters}

    use_items = normalized_category is not None or group_by == "category"

    params = []
    conditions = []

    if use_items:
        measure = "SUM(oi.price + oi.freight_value)"
        from_clause = """
        FROM olist_order_items_dataset oi
        JOIN olist_orders_dataset o ON oi.order_id = o.order_id
        LEFT JOIN olist_customers_dataset c ON o.customer_id = c.customer_id
        LEFT JOIN olist_products_dataset p ON oi.product_id = p.product_id
        LEFT JOIN product_category_name_translation t
            ON p.product_category_name = t.product_category_name
        """
        if normalized_category:
            params.append(normalized_category)
            i = len(params)
            params.append(normalized_category)
            j = len(params)
            conditions.append(
                f"(lower(t.product_category_name_english) = ${i} "
                f"OR lower(p.product_category_name) = ${j})"
            )
    else:
        measure = "SUM(p.payment_value)"
        from_clause = """
        FROM olist_order_payments_dataset p
        JOIN olist_orders_dataset o ON p.order_id = o.order_id
        LEFT JOIN olist_customers_dataset c ON o.customer_id = c.customer_id
        """

    if normalized_city:
        params.append(normalized_city)
        conditions.append(f"c.customer_city = ${len(params)}")

    if normalized_state:
        params.append(normalized_state)
        conditions.append(f"c.customer_state = ${len(params)}")

    if date_range:
        params.append(date_range[0])
        conditions.append(f"o.order_purchase_timestamp >= ${len(params)}")
        params.append(date_range[1])
        conditions.append(f"o.order_purchase_timestamp <= ${len(params)}")

    where_clause = " AND ".join(["1=1"] + conditions)

    try:
        if group_by is None:
            query = f"SELECT {measure} AS revenue {from_clause} WHERE {where_clause}"
            value = await execute_scalar(query, *params)
            return {"revenue": float(value or 0), "filters": filters}

        if group_by == "state":
            group_expr = "c.customer_state"
            label = "state"
            order_clause = "revenue DESC NULLS LAST"
            limit_clause = "LIMIT 15"
        elif group_by == "month":
            group_expr = "to_char(date_trunc('month', o.order_purchase_timestamp), 'YYYY-MM')"
            label = "month"
            order_clause = "grp ASC"
            limit_clause = ""
        else:  # category
            group_expr = "COALESCE(t.product_category_name_english, p.product_category_name)"
            label = "category"
            order_clause = "revenue DESC NULLS LAST"
            limit_clause = "LIMIT 15"

        query = f"""
        SELECT {group_expr} AS grp, {measure} AS revenue
        {from_clause}
        WHERE {where_clause}
        GROUP BY {group_expr}
        ORDER BY {order_clause}
        {limit_clause}
        """
        rows = await execute_query(query, *params)
        breakdown = [
            {label: r["grp"], "revenue": float(r["revenue"] or 0)} for r in rows
        ]
        return {"breakdown": breakdown, "group_by": group_by, "filters": filters}

    except Exception as e:
        logger.error(f"Revenue query failed: {e}")
        return {
            "error": client_error(e, "A database error occurred while running your query."),
            "filters": filters,
        }
