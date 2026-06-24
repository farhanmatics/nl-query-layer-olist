import logging
from db import execute_query

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


async def execute(order_id: str) -> dict:
    """
    Look up a single order and return its status + key dates.

    Returns:
        {
            "order_id": str,
            "customer_city": str,
            "customer_state": str,
            "order_status": str,
            "order_purchase_timestamp": datetime,
            "order_estimated_delivery_date": datetime,
            "order_delivered_customer_date": datetime | None,
        }
    """
    query = """
    SELECT
        o.order_id,
        o.order_status,
        o.order_purchase_timestamp,
        o.order_estimated_delivery_date,
        o.order_delivered_customer_date,
        c.customer_city,
        c.customer_state
    FROM olist_orders_dataset o
    LEFT JOIN olist_customers_dataset c ON o.customer_id = c.customer_id
    WHERE o.order_id = $1
    LIMIT 1
    """

    rows = await execute_query(query, order_id)

    if not rows:
        return {
            "error": f"Order {order_id} not found",
            "order_id": order_id,
        }

    row = rows[0]
    return {
        "order_id": row["order_id"],
        "customer_city": row["customer_city"],
        "customer_state": row["customer_state"],
        "order_status": row["order_status"],
        "order_purchase_timestamp": row["order_purchase_timestamp"].isoformat() if row["order_purchase_timestamp"] else None,
        "order_estimated_delivery_date": row["order_estimated_delivery_date"].isoformat() if row["order_estimated_delivery_date"] else None,
        "order_delivered_customer_date": row["order_delivered_customer_date"].isoformat() if row["order_delivered_customer_date"] else None,
    }
