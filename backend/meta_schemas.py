"""Meta-tool JSON schemas exposed to the LLM.

P0: count + lookup. P1 adds rank (top-N / best / worst).
"""
from __future__ import annotations

META_TOOL_SCHEMAS = [
    {
        "name": "count",
        "description": (
            "Count how many of something match filters. REQUIRED: set 'entity' to "
            "what is being counted — products (catalog SKUs), orders (transactions), "
            "reviews (low scores), or payments. "
            "'products' = rows in the product catalog. "
            "'orders' = distinct orders (e.g. sold in a category). "
            "Do NOT use orders when the user asks how many products we have or in the catalog."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "entity": {
                    "type": "string",
                    "enum": ["products", "orders", "reviews", "payments"],
                    "description": "What is being counted (required)",
                },
                "city": {"type": "string"},
                "state": {"type": "string"},
                "status": {"type": "string"},
                "category": {"type": "string"},
                "date_token": {"type": "string"},
                "payment_type": {"type": "string"},
                "seller_id": {"type": "string"},
                "score_max": {
                    "type": "integer",
                    "description": "For reviews: max score to include (default 2)",
                },
            },
            "required": ["entity"],
        },
    },
    {
        "name": "rank",
        "description": (
            "Rank or find the top/best/worst N by sales, revenue, or rating. "
            "Use for 'best product', 'top sellers', 'highest rated'. "
            "entity=products ranks individual products (by units sold or revenue). "
            "Set limit=1 for 'the best' single answer. "
            "Supports category and date_token filters on products."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "entity": {
                    "type": "string",
                    "enum": ["products", "categories", "sellers", "customers"],
                    "description": "What to rank (required)",
                },
                "by": {
                    "type": "string",
                    "enum": ["count", "revenue", "rating"],
                    "description": "Ranking measure (default revenue for best-seller questions)",
                },
                "sort": {
                    "type": "string",
                    "enum": ["best", "worst"],
                    "description": "best = highest first (default), worst = lowest first",
                },
                "limit": {
                    "type": "integer",
                    "description": "How many rows to return (use 1 for 'the best')",
                },
                "category": {"type": "string", "description": "Filter products to a category"},
                "state": {"type": "string"},
                "city": {"type": "string"},
                "date_token": {"type": "string"},
            },
            "required": ["entity"],
        },
    },
    {
        "name": "sum",
        "description": (
            "Totals, rates, and aggregates (not rankings). Use for total revenue, "
            "revenue broken down by dimension, on-time delivery %, repeat customer rate, "
            "average delivery days, or seller concentration. "
            "Set measure=revenue for 'how much revenue/total sales'. "
            "Set group_by when user asks 'by state/category/month/seller/payment type'."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "measure": {
                    "type": "string",
                    "enum": [
                        "revenue",
                        "on_time_delivery_rate",
                        "repeat_customer_rate",
                        "avg_delivery_days",
                        "seller_concentration",
                    ],
                    "description": "Aggregate to compute (required)",
                },
                "group_by": {
                    "type": "string",
                    "enum": ["state", "category", "month", "seller", "payment_type"],
                    "description": "Optional breakdown dimension (revenue only)",
                },
                "city": {"type": "string"},
                "state": {"type": "string"},
                "category": {"type": "string"},
                "date_token": {"type": "string"},
            },
            "required": ["measure"],
        },
    },
    {
        "name": "list",
        "description": (
            "Paginated list of rows. entity=orders lists matching orders; "
            "entity=reviews lists low-scoring reviews (use after count_low_reviews); "
            "entity=customer_orders lists orders for one customer (requires customer_id)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "entity": {
                    "type": "string",
                    "enum": ["orders", "reviews", "customer_orders"],
                    "description": "What to list (required)",
                },
                "customer_id": {"type": "string", "description": "Required when entity=customer_orders"},
                "city": {"type": "string"},
                "state": {"type": "string"},
                "status": {"type": "string"},
                "date_token": {"type": "string"},
                "score_max": {"type": "integer", "description": "Max review score when entity=reviews (default 2)"},
                "limit": {"type": "integer", "description": "Max rows (default 20, max 50)"},
                "offset": {"type": "integer", "description": "Pagination offset (default 0)"},
            },
            "required": ["entity"],
        },
    },
    {
        "name": "breakdown",
        "description": (
            "Histogram or grouped distribution — counts or revenue per bucket. "
            "Use for 'orders by status', 'reviews by score', 'payment mix', "
            "'revenue by state', 'satisfaction trend by month'."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "dimension": {
                    "type": "string",
                    "enum": [
                        "order_status",
                        "review_score",
                        "payment_type",
                        "seller_state",
                        "review_trend",
                        "revenue_state",
                        "revenue_category",
                        "revenue_month",
                        "category_rating",
                    ],
                    "description": "What to group by (required)",
                },
                "by": {
                    "type": "string",
                    "enum": ["count", "revenue", "orders"],
                    "description": "For seller_state: revenue or orders",
                },
                "date_token": {"type": "string"},
                "state": {"type": "string"},
                "seller_id": {"type": "string"},
                "limit": {"type": "integer"},
            },
            "required": ["dimension"],
        },
    },
    {
        "name": "compare",
        "description": (
            "Side-by-side comparison of 2-5 sellers, categories, or states "
            "(orders, revenue, avg rating each)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "dimension": {
                    "type": "string",
                    "enum": ["seller", "category", "state"],
                    "description": "What to compare (required)",
                },
                "values": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "IDs or names to compare (2-5 items, required)",
                },
                "date_token": {"type": "string"},
            },
            "required": ["dimension", "values"],
        },
    },
    {
        "name": "lookup",
        "description": "Look up a single entity by ID (order, customer, product, or seller).",
        "parameters": {
            "type": "object",
            "properties": {
                "entity": {
                    "type": "string",
                    "enum": ["order", "customer", "product", "seller"],
                },
                "id": {"type": "string", "description": "Entity ID"},
            },
            "required": ["entity", "id"],
        },
    },
]

QUERY_META_TOOL_SCHEMA = {
    "name": "query",
    "description": (
        "LAST RESORT: run a read-only SELECT when no other meta-tool fits. "
        "The backend validates SQL (SELECT only, allowlisted tables, mandatory LIMIT). "
        "Use for ad-hoc aggregates not covered by count/rank/sum/list/breakdown/compare. "
        "Never use for writes. Always include LIMIT (max 100)."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "sql": {
                "type": "string",
                "description": (
                    "Single PostgreSQL SELECT. Only these tables: "
                    "olist_orders_dataset, olist_customers_dataset, olist_order_items_dataset, "
                    "olist_products_dataset, product_category_name_translation, "
                    "olist_sellers_dataset, olist_order_payments_dataset, olist_order_reviews_dataset."
                ),
            },
        },
        "required": ["sql"],
    },
}

META_FEW_SHOT_EXAMPLES = (
    (
        "How many delivered orders in Sao Paulo last month?",
        '{"tool": "count", "args": {"entity": "orders", "city": "sao paulo", '
        '"status": "delivered", "date_token": "last_month"}}',
    ),
    (
        "How many products do we have in the perfumaria category?",
        '{"tool": "count", "args": {"entity": "products", "category": "perfumaria"}}',
    ),
    (
        "How many perfumaria orders were placed last year?",
        '{"tool": "count", "args": {"entity": "orders", "category": "perfumaria", '
        '"date_token": "last_year"}}',
    ),
    (
        "Which is the best product in perfumaria last year?",
        '{"tool": "rank", "args": {"entity": "products", "category": "perfumaria", '
        '"date_token": "last_year", "by": "revenue", "limit": 1}}',
    ),
    (
        "Top 5 products by revenue this year",
        '{"tool": "rank", "args": {"entity": "products", "by": "revenue", '
        '"limit": 5, "date_token": "this_year"}}',
    ),
    (
        "Who are our top sellers by revenue?",
        '{"tool": "rank", "args": {"entity": "sellers", "by": "revenue", "limit": 10}}',
    ),
    (
        "What was our total revenue last month?",
        '{"tool": "sum", "args": {"measure": "revenue", "date_token": "last_month"}}',
    ),
    (
        "Revenue by state this year",
        '{"tool": "sum", "args": {"measure": "revenue", "group_by": "state", '
        '"date_token": "this_year"}}',
    ),
    (
        "Show me delivered orders in Sao Paulo",
        '{"tool": "list", "args": {"entity": "orders", "city": "sao paulo", '
        '"status": "delivered"}}',
    ),
    (
        "Break down orders by status",
        '{"tool": "breakdown", "args": {"dimension": "order_status"}}',
    ),
    (
        "Compare SP and RJ revenue",
        '{"tool": "compare", "args": {"dimension": "state", "values": ["SP", "RJ"]}}',
    ),
    (
        "How many low reviews last month?",
        '{"tool": "count", "args": {"entity": "reviews", "date_token": "last_month"}}',
    ),
    (
        "Share me the last 5 low reviews last month",
        '{"tool": "list", "args": {"entity": "reviews", "date_token": "last_month", "limit": 5}}',
    ),
    (
        "Of those, share me the last five (after a low-reviews count)",
        '{"tool": "list", "args": {"entity": "reviews", "limit": 5}}',
    ),
    (
        "What is the status of order abc123?",
        '{"tool": "lookup", "args": {"entity": "order", "id": "abc123"}}',
    ),
)


def get_meta_tool_schemas() -> list[dict]:
    from config import settings

    schemas = list(META_TOOL_SCHEMAS)
    if settings.sql_escape_enabled:
        schemas.append(QUERY_META_TOOL_SCHEMA)
    return schemas
