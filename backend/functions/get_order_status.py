"""get_order_status function — schema-aware.

Look up a single order's status + key dates by order_id. The column
list and the order/customers join are wired through the active config.
"""
import logging
from db import execute_query
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
    t_orders = cfg.get_table("orders")
    t_customers = cfg.get_table("customers")
    col_order_id = cfg.get_column("order_id")
    col_status = cfg.get_column("order_status")
    col_purchase = cfg.get_column("order_purchase_timestamp")
    col_delivered = cfg.get_column("order_delivered_date")
    col_estimated = cfg.get_column("order_estimated_delivery_date")
    col_city = cfg.get_column("customer_city")
    col_state = cfg.get_column("customer_state")
    cust_id_col = cfg.get_column("customer_id").column

    async def execute(order_id: str) -> dict:
        query = (
            f"SELECT "
            f"o.{col_order_id.column}, "
            f"o.{col_status.column}, "
            f"o.{col_purchase.column}, "
            f"o.{col_estimated.column}, "
            f"o.{col_delivered.column}, "
            f"c.{col_city.column}, "
            f"c.{col_state.column} "
            f"FROM {t_orders} o "
            f"LEFT JOIN {t_customers} c ON o.{cust_id_col} = c.{cust_id_col} "
            f"WHERE o.{col_order_id.column} = $1 "
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
            "order_id": row[col_order_id.column],
            "customer_city": row[col_city.column],
            "customer_state": row[col_state.column],
            "order_status": row[col_status.column],
            "order_purchase_timestamp": row[col_purchase.column].isoformat() if row[col_purchase.column] else None,
            "order_estimated_delivery_date": row[col_estimated.column].isoformat() if row[col_estimated.column] else None,
            "order_delivered_customer_date": row[col_delivered.column].isoformat() if row[col_delivered.column] else None,
        }

    return {"schema": SCHEMA, "execute": execute}
