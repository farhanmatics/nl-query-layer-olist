"""get_order_status function — schema-aware.

Look up a single order's status + key dates by order_id. The column
list and the order/customers join are wired through the active config.
"""
import logging
from db import execute_query
from functions._helpers import col_name, table_for
from schemas.base import SchemaConfig

logger = logging.getLogger(__name__)


SCHEMA = {
    "name": "get_order_status",
    "description": "Get the status and key dates for a single order",
    "parameters": {
        "type": "object",
        "properties": {
            "order_id": {
                "type": "string",
                "description": "The order ID to look up",
            }
        },
        "required": ["order_id"],
    },
}


def make_get_order_status(cfg: SchemaConfig) -> dict:
    col_order_id = cfg.get_column("order_id")
    col_status = cfg.get_column("order_status")
    col_purchase = cfg.get_column("order_purchase_timestamp")
    col_delivered = cfg.get_column("order_delivered_date")
    col_estimated = cfg.get_column("order_estimated_delivery_date")
    col_city = cfg.get_column("customer_city")
    col_state = cfg.get_column("customer_state")
    cust_id = cfg.get_column("customer_id")

    t_orders = table_for(col_order_id, cfg)
    t_customers = table_for(col_city, cfg)

    async def execute(order_id: str) -> dict:
        query = (
            f"SELECT "
            f"o.{col_name(col_order_id)}, "
            f"o.{col_name(col_status)}, "
            f"o.{col_name(col_purchase)}, "
            f"o.{col_name(col_estimated)}, "
            f"o.{col_name(col_delivered)}, "
            f"c.{col_name(col_city)}, "
            f"c.{col_name(col_state)} "
            f"FROM {t_orders} o "
            f"LEFT JOIN {t_customers} c ON o.{col_name(cust_id)} = c.{col_name(cust_id)} "
            f"WHERE o.{col_name(col_order_id)} = $1 "
            f"LIMIT 1"
        )

        rows = await execute_query(query, order_id)

        if not rows:
            return {
                "error": f"Order {order_id} not found",
                "order_id": order_id,
            }

        row = rows[0]
        return {
            "order_id": row[col_name(col_order_id)],
            "customer_city": row[col_name(col_city)],
            "customer_state": row[col_name(col_state)],
            "order_status": row[col_name(col_status)],
            "order_purchase_timestamp": row[col_name(col_purchase)].isoformat() if row[col_name(col_purchase)] else None,
            "order_estimated_delivery_date": row[col_name(col_estimated)].isoformat() if row[col_name(col_estimated)] else None,
            "order_delivered_customer_date": row[col_name(col_delivered)].isoformat() if row[col_name(col_delivered)] else None,
        }

    return {"schema": SCHEMA, "execute": execute}
