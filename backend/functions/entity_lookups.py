"""Entity lookup functions — schema-aware single-row lookups by ID.

get_customer_info, get_product_info, and get_seller_info return
aggregated metrics for one customer, product, or seller.
"""
import logging

from db import execute_query
from errors import client_error
from functions._helpers import col_name, table_for
from schemas.base import ColumnRef, SchemaConfig

logger = logging.getLogger(__name__)

COL_SELLER_CITY = ColumnRef("sellers", "seller_city")
COL_SELLER_STATE = ColumnRef("sellers", "seller_state")

GET_CUSTOMER_INFO_SCHEMA = {
    "name": "get_customer_info",
    "description": "Get customer location, order count, total spent, and average review score",
    "parameters": {
        "type": "object",
        "properties": {
            "customer_id": {
                "type": "string",
                "description": "The customer ID to look up",
            }
        },
        "required": ["customer_id"],
    },
}

GET_PRODUCT_INFO_SCHEMA = {
    "name": "get_product_info",
    "description": "Get product category, order count, total revenue, and average review score",
    "parameters": {
        "type": "object",
        "properties": {
            "product_id": {
                "type": "string",
                "description": "The product ID to look up",
            }
        },
        "required": ["product_id"],
    },
}

GET_SELLER_INFO_SCHEMA = {
    "name": "get_seller_info",
    "description": "Get seller location, product count, order count, revenue, and average review score",
    "parameters": {
        "type": "object",
        "properties": {
            "seller_id": {
                "type": "string",
                "description": "The seller ID to look up",
            }
        },
        "required": ["seller_id"],
    },
}


def make_get_customer_info(cfg: SchemaConfig) -> dict:
    cust_id = cfg.get_column("customer_id")
    col_city = cfg.get_column("customer_city")
    col_state = cfg.get_column("customer_state")
    col_order_id = cfg.get_column("order_id")
    col_pay_value = cfg.get_column("payment_value")
    col_review_score = cfg.get_column("review_score")

    t_customers = table_for(col_city, cfg)
    t_orders = table_for(col_order_id, cfg)
    t_payments = table_for(col_pay_value, cfg)
    t_reviews = table_for(col_review_score, cfg)

    async def execute(customer_id: str) -> dict:
        query = (
            f"SELECT "
            f"c.{col_name(col_city)} AS city, "
            f"c.{col_name(col_state)} AS state, "
            f"COUNT(DISTINCT o.{col_name(col_order_id)}) AS order_count, "
            f"COALESCE(SUM(p.{col_name(col_pay_value)}), 0) AS total_spent, "
            f"AVG(r.{col_name(col_review_score)}) AS avg_review_score "
            f"FROM {t_customers} c "
            f"LEFT JOIN {t_orders} o ON c.{col_name(cust_id)} = o.{col_name(cust_id)} "
            f"LEFT JOIN {t_payments} p ON o.{col_name(col_order_id)} = p.{col_name(col_order_id)} "
            f"LEFT JOIN {t_reviews} r ON o.{col_name(col_order_id)} = r.{col_name(col_order_id)} "
            f"WHERE c.{col_name(cust_id)} = $1 "
            f"GROUP BY c.{col_name(cust_id)}, c.{col_name(col_city)}, c.{col_name(col_state)} "
            f"LIMIT 1"
        )

        try:
            rows = await execute_query(query, customer_id)
        except Exception as e:
            logger.error(f"get_customer_info query failed: {e}")
            return {
                "error": client_error(e, "A database error occurred while running your query."),
                "customer_id": customer_id,
            }

        if not rows:
            return {
                "error": f"Customer {customer_id} not found",
                "customer_id": customer_id,
            }

        row = rows[0]
        avg_score = row["avg_review_score"]
        return {
            "customer_id": customer_id,
            "city": row["city"],
            "state": row["state"],
            "order_count": int(row["order_count"] or 0),
            "total_spent": float(row["total_spent"] or 0),
            "avg_review_score": float(avg_score) if avg_score is not None else None,
        }

    return {"schema": GET_CUSTOMER_INFO_SCHEMA, "execute": execute}


def make_get_product_info(cfg: SchemaConfig) -> dict:
    col_product_id = cfg.get_column("product_id")
    col_order_id = cfg.get_column("order_id")
    col_price = cfg.get_column("price")
    col_freight = cfg.get_column("freight_value")
    col_cat_pt = cfg.get_column("product_category_pt")
    col_cat_en = cfg.get_column("product_category_en")
    col_review_score = cfg.get_column("review_score")

    t_products = table_for(col_cat_pt, cfg)
    t_cat_translation = table_for(col_cat_en, cfg)
    t_items = table_for(col_price, cfg)
    t_orders = table_for(col_order_id, cfg)
    t_reviews = table_for(col_review_score, cfg)

    category_expr = (
        f"COALESCE(t.{col_name(col_cat_en)}, p.{col_name(col_cat_pt)})"
    )

    async def execute(product_id: str) -> dict:
        query = (
            f"SELECT "
            f"{category_expr} AS category_en, "
            f"COUNT(DISTINCT oi.{col_name(col_order_id)}) AS order_count, "
            f"COALESCE(SUM(oi.{col_name(col_price)} + oi.{col_name(col_freight)}), 0) AS total_revenue, "
            f"AVG(r.{col_name(col_review_score)}) AS avg_review_score "
            f"FROM {t_products} p "
            f"LEFT JOIN {t_cat_translation} t "
            f"ON p.{col_name(col_cat_pt)} = t.{col_name(col_cat_pt)} "
            f"LEFT JOIN {t_items} oi ON p.{col_name(col_product_id)} = oi.{col_name(col_product_id)} "
            f"LEFT JOIN {t_orders} o ON oi.{col_name(col_order_id)} = o.{col_name(col_order_id)} "
            f"LEFT JOIN {t_reviews} r ON o.{col_name(col_order_id)} = r.{col_name(col_order_id)} "
            f"WHERE p.{col_name(col_product_id)} = $1 "
            f"GROUP BY p.{col_name(col_product_id)}, {category_expr} "
            f"LIMIT 1"
        )

        try:
            rows = await execute_query(query, product_id)
        except Exception as e:
            logger.error(f"get_product_info query failed: {e}")
            return {
                "error": client_error(e, "A database error occurred while running your query."),
                "product_id": product_id,
            }

        if not rows:
            return {
                "error": f"Product {product_id} not found",
                "product_id": product_id,
            }

        row = rows[0]
        avg_score = row["avg_review_score"]
        return {
            "product_id": product_id,
            "category_en": row["category_en"],
            "order_count": int(row["order_count"] or 0),
            "total_revenue": float(row["total_revenue"] or 0),
            "avg_review_score": float(avg_score) if avg_score is not None else None,
        }

    return {"schema": GET_PRODUCT_INFO_SCHEMA, "execute": execute}


def make_get_seller_info(cfg: SchemaConfig) -> dict:
    col_seller_id = cfg.get_column("seller_id")
    col_order_id = cfg.get_column("order_id")
    col_product_id = cfg.get_column("product_id")
    col_price = cfg.get_column("price")
    col_freight = cfg.get_column("freight_value")
    col_review_score = cfg.get_column("review_score")

    t_sellers = table_for(COL_SELLER_CITY, cfg)
    t_items = table_for(col_price, cfg)
    t_orders = table_for(col_order_id, cfg)
    t_reviews = table_for(col_review_score, cfg)

    async def execute(seller_id: str) -> dict:
        query = (
            f"SELECT "
            f"s.{col_name(COL_SELLER_CITY)} AS seller_city, "
            f"s.{col_name(COL_SELLER_STATE)} AS seller_state, "
            f"COUNT(DISTINCT oi.{col_name(col_product_id)}) AS product_count, "
            f"COUNT(DISTINCT oi.{col_name(col_order_id)}) AS order_count, "
            f"COALESCE(SUM(oi.{col_name(col_price)} + oi.{col_name(col_freight)}), 0) AS revenue, "
            f"AVG(r.{col_name(col_review_score)}) AS avg_review_score "
            f"FROM {t_sellers} s "
            f"LEFT JOIN {t_items} oi ON s.{col_name(col_seller_id)} = oi.{col_name(col_seller_id)} "
            f"LEFT JOIN {t_orders} o ON oi.{col_name(col_order_id)} = o.{col_name(col_order_id)} "
            f"LEFT JOIN {t_reviews} r ON o.{col_name(col_order_id)} = r.{col_name(col_order_id)} "
            f"WHERE s.{col_name(col_seller_id)} = $1 "
            f"GROUP BY s.{col_name(col_seller_id)}, "
            f"s.{col_name(COL_SELLER_CITY)}, s.{col_name(COL_SELLER_STATE)} "
            f"LIMIT 1"
        )

        try:
            rows = await execute_query(query, seller_id)
        except Exception as e:
            logger.error(f"get_seller_info query failed: {e}")
            return {
                "error": client_error(e, "A database error occurred while running your query."),
                "seller_id": seller_id,
            }

        if not rows:
            return {
                "error": f"Seller {seller_id} not found",
                "seller_id": seller_id,
            }

        row = rows[0]
        avg_score = row["avg_review_score"]
        return {
            "seller_id": seller_id,
            "seller_city": row["seller_city"],
            "seller_state": row["seller_state"],
            "product_count": int(row["product_count"] or 0),
            "order_count": int(row["order_count"] or 0),
            "revenue": float(row["revenue"] or 0),
            "avg_review_score": float(avg_score) if avg_score is not None else None,
        }

    return {"schema": GET_SELLER_INFO_SCHEMA, "execute": execute}
