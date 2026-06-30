"""get_revenue function — schema-aware.

Total revenue, with optional filters and an optional breakdown
(grouped) by state, category, or month. When category is involved
(filter or group_by=category) the measure runs at the item level
(price + freight) to avoid the payments<->items fan-out — this
concern is identical across schemas, so the branch is the same.
The table/column names come from the active config.
"""
import logging
from typing import Optional
from db import execute_scalar, execute_query
from validation.dates import parse_date_range
from validation.cities import resolve_city
from config import settings
from errors import client_error
from schemas.base import SchemaConfig

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


def make_get_revenue(cfg: SchemaConfig) -> dict:
    t_payments = cfg.get_table("order_payments")
    t_items = cfg.get_table("order_items")
    t_orders = cfg.get_table("orders")
    t_customers = cfg.get_table("customers")
    t_products = cfg.get_table("products")
    t_cat_translation = cfg.get_table("product_category_translation")

    col_pay_value = cfg.get_column("payment_value")
    col_item_price = cfg.get_column("price")
    col_item_freight = cfg.get_column("freight_value")
    col_pay_type = cfg.get_column("payment_type")
    col_order_id = cfg.get_column("order_id").column
    col_product_id = cfg.get_column("product_id").column
    cust_id_col = cfg.get_column("customer_id").column
    col_purchase = cfg.get_column("order_purchase_timestamp").column
    col_city = cfg.get_column("customer_city").column
    col_state = cfg.get_column("customer_state").column
    col_cat_pt = cfg.get_column("product_category_pt").column
    col_cat_en = cfg.get_column("product_category_en").column

    async def execute(
        date_token: Optional[str] = None,
        city: Optional[str] = None,
        state: Optional[str] = None,
        category: Optional[str] = None,
        group_by: Optional[str] = None,
    ) -> dict:
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

        # Category involved → measure at item level (price+freight) to
        # avoid the payments<->items fan-out. Otherwise measure at the
        # payment level (the truest revenue).
        use_items = normalized_category is not None or group_by == "category"

        params = []
        conditions = []

        if use_items:
            measure = f"SUM(oi.{col_item_price.column} + oi.{col_item_freight.column})"
            from_clause = (
                f"FROM {t_items} oi "
                f"JOIN {t_orders} o ON oi.{col_order_id} = o.{col_order_id} "
                f"LEFT JOIN {t_customers} c ON o.{cust_id_col} = c.{cust_id_col} "
                f"LEFT JOIN {t_products} p ON oi.{col_product_id} = p.{col_product_id} "
                f"LEFT JOIN {t_cat_translation} t ON p.{col_cat_pt} = t.{col_cat_pt}"
            )
            if normalized_category:
                params.append(normalized_category)
                i = len(params)
                params.append(normalized_category)
                j = len(params)
                conditions.append(
                    f"(lower(t.{col_cat_en}) = ${i} "
                    f"OR lower(p.{col_cat_pt}) = ${j})"
                )
        else:
            measure = f"SUM(p.{col_pay_value.column})"
            from_clause = (
                f"FROM {t_payments} p "
                f"JOIN {t_orders} o ON p.{col_order_id} = o.{col_order_id} "
                f"LEFT JOIN {t_customers} c ON o.{cust_id_col} = c.{cust_id_col} "
            )

        if normalized_city:
            params.append(normalized_city)
            conditions.append(f"c.{col_city} = ${len(params)}")

        if normalized_state:
            params.append(normalized_state)
            conditions.append(f"c.{col_state} = ${len(params)}")

        if date_range:
            params.append(date_range[0])
            conditions.append(f"o.{col_purchase} >= ${len(params)}")
            params.append(date_range[1])
            conditions.append(f"o.{col_purchase} <= ${len(params)}")

        where_clause = " AND ".join(["1=1"] + conditions)

        try:
            if group_by is None:
                query = f"SELECT {measure} AS revenue {from_clause} WHERE {where_clause}"
                value = await execute_scalar(query, *params)
                return {"revenue": float(value or 0), "filters": filters}

            if group_by == "state":
                group_expr = f"c.{col_state}"  # col_state is already the string
                label = "state"
                order_clause = "revenue DESC NULLS LAST"
                limit_clause = "LIMIT 15"
            elif group_by == "month":
                group_expr = f"to_char(date_trunc('month', o.{col_purchase}), 'YYYY-MM')"
                label = "month"
                order_clause = "grp ASC"
                limit_clause = ""
            else:  # category
                group_expr = f"COALESCE(t.{col_cat_en}, p.{col_cat_pt})"
                label = "category"
                order_clause = "revenue DESC NULLS LAST"
                limit_clause = "LIMIT 15"

            query = (
                f"SELECT {group_expr} AS grp, {measure} AS revenue "
                f"{from_clause} "
                f"WHERE {where_clause} "
                f"GROUP BY {group_expr} "
                f"ORDER BY {order_clause} "
                f"{limit_clause}"
            )
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

    return {"schema": SCHEMA, "execute": execute}
