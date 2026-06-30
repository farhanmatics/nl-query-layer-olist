"""Shopify schema config (stub) — proves the abstraction generalizes.

Shopify-shaped entity names (orders, customers, products) but in a
hypothetical `shopify_*` table space with English/US domain conventions.
This is a CONFIGURATION-ONLY stub: the table names exist in the config
but no real Shopify DB is loaded. Functions that try to execute will
return a clear "not wired" error.

Why include it at all?  Three reasons:
  1. Proves the abstraction is not Olist-shaped: different state codes
     (US), different statuses (financial_status, fulfillment_status),
     different scope (refunds ARE tracked), different prompt examples
     (New York, not São Paulo).
  2. Forces the test suite to exercise the loader (not just the
     olist config inline).
  3. Gives a real starting point for a future "real Shopify adapter"
     — only the table names + SQL strings need to change; the
     SchemaConfig shape and the rest of the backend are already
     schema-agnostic.
"""
from schemas.base import (
    ColumnRef,
    PromptConfig,
    SchemaConfig,
    ScopePattern,
)


# --- Table names (hypothetical; no real Shopify DB) -------------------------

T_ORDERS = "shopify_orders"
T_CUSTOMERS = "shopify_customers"
T_ORDER_ITEMS = "shopify_line_items"
T_PRODUCTS = "shopify_products"
T_PRODUCT_CATEGORY_TRANSLATION = "shopify_collections"
T_REFUNDS = "shopify_refunds"


# --- Column references -------------------------------------------------------
#
# Same convention as Olist: ColumnRef stores the LOGICAL table name
# (key into `tables` below). The factory's `table_for()` resolves it.

COL_ORDER_ID = ColumnRef("orders", "id")
COL_ORDER_STATUS = ColumnRef("orders", "financial_status")
COL_ORDER_PURCHASE_TS = ColumnRef("orders", "processed_at")
COL_ORDER_DELIVERED_DATE = ColumnRef("orders", "fulfilled_at")
COL_ORDER_ESTIMATED_DATE = ColumnRef("orders", "estimated_delivery_at")

COL_CUSTOMER_ID = ColumnRef("orders", "customer_id")
COL_CUSTOMER_CITY = ColumnRef("customers", "default_address_city")
COL_CUSTOMER_STATE = ColumnRef("customers", "default_address_province_code")
COL_CUSTOMER_UNIQUE_ID = ColumnRef("customers", "id")

COL_PRODUCT_ID = ColumnRef("order_items", "product_id")
COL_PRICE = ColumnRef("order_items", "price")
COL_FREIGHT_VALUE = ColumnRef("order_items", "shipping_lines_price")

COL_PRODUCT_CATEGORY_PT = ColumnRef("products", "product_type")
COL_PRODUCT_CATEGORY_EN = ColumnRef("product_category_translation", "title")

COL_PAYMENT_TYPE = ColumnRef("orders", "gateway")
COL_PAYMENT_VALUE = ColumnRef("orders", "total_price")

COL_REVIEW_SCORE = ColumnRef("orders", "customer_satisfaction_score")


# --- Enum values (US Shopify conventions) -----------------------------------

ORDER_STATUSES = frozenset({
    "pending", "authorized", "partially_paid", "paid",
    "partially_refunded", "refunded", "voided", "fulfilled",
    "partially_fulfilled", "unfulfilled", "cancelled",
})


# --- US state codes (subset; full set lives in the loader) -----------------

US_STATES = frozenset({
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID",
    "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS",
    "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK",
    "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV",
    "WI", "WY", "DC",
})


# --- Out-of-scope lexicon ----------------------------------------------------
#
# IMPORTANT: Shopify DOES track returns/refunds (unlike Olist). The
# scope patterns here drop "returns/refunds" from the decline list —
# they would be a real signal on this schema. The scope stays only for
# things Shopify doesn't have: inventory quantities, profit/cost
# (Shopify doesn't know the merchant's cost basis).

SCOPE_PATTERNS = (
    ScopePattern(
        pattern=r"\b(inventory|stock|stocklevel)\b",
        concept="inventory or stock levels",
        suggestion=(
            "Shopify tracks product availability per variant, but not "
            "warehouse quantities. Ask about a specific product's status "
            "instead."
        ),
    ),
    ScopePattern(
        pattern=r"\b(profit|profits|profitability|margin|margins)\b",
        concept="profit or margin",
        suggestion=(
            "Order totals exist, but Shopify doesn't know your cost basis, "
            "so margin can't be computed."
        ),
    ),
)


# --- Prompt config ----------------------------------------------------------

PROMPT = PromptConfig(
    dataset_description=(
        "You translate a natural-language question into a single JSON function call "
        "against a Shopify-shaped dataset (orders, customers, line items, products, "
        "refunds)."
    ),
    city_rule=(
        'pass the city name as the user typed it (case insensitive). '
        'Examples: "New York", "San Francisco", "Austin".'
    ),
    state_rule='use 2-letter US state codes (e.g., "CA", "NY", "TX", "WA").',
    status_rule=(
        f'valid order statuses are {", ".join(sorted(ORDER_STATUSES))}. '
        'Pass the status verbatim from this list.'
    ),
    group_by_rule=(
        'when a question says "by X" / "broken down by X" / "grouped by X" / "per X" '
        '(X = state, category, or month), set group_by to that dimension.'
    ),
    few_shot_examples=(
        ('How many fulfilled orders did we have in New York last month?',
         '{"tool": "count_orders", "args": {"city": "New York", "status": "fulfilled", "date_token": "last_month"}}'),
        ('How many refunded orders this year?',
         '{"tool": "count_orders", "args": {"status": "refunded", "date_token": "this_year"}}'),
        ('How many orders in San Francisco last week?',
         '{"tool": "count_orders", "args": {"city": "San Francisco", "date_token": "last_week"}}'),
        ('What is the status of order 12345?',
         '{"tool": "get_order_status", "args": {"order_id": "12345"}}'),
        ('Total revenue in CA last month?',
         '{"tool": "get_revenue", "args": {"state": "CA", "date_token": "last_month"}}'),
        ('Revenue by state this year',
         '{"tool": "get_revenue", "args": {"date_token": "this_year", "group_by": "state"}}'),
    ),
    source_citations={
        "get_order_status": "shopify_orders JOIN shopify_customers",
        "count_orders": "shopify_orders JOIN shopify_customers",
        "get_revenue": "shopify_orders",
        "count_low_reviews": "shopify_orders (satisfaction score)",
        "top_products": "shopify_line_items JOIN shopify_products",
        "list_orders": "shopify_orders JOIN shopify_customers",
    },
)


# --- Function factories ------------------------------------------------------
#
# Shopify functions are NOT wired to a real DB. The factory returns a
# registry entry whose `execute` immediately reports "not wired" — so
# the schema is selectable for prompt/formatting tests but cannot
# actually answer questions until a real adapter lands. This is the
# shape a future "shopify" adapter would follow: drop in a real loader
# and a real function SQL module, leaving CONFIG / PromptConfig / scope
# alone.

async def _shopify_not_wired(*args, **kwargs):
    return {
        "error": (
            "The shopify schema is a configuration stub. "
            "Connect a real Shopify data source to run queries."
        ),
        "filters": {},
    }


def _make_count_orders(cfg):
    schema = {
        "name": "count_orders",
        "description": "Count orders with optional filters by city, state, status, and date range",
        "parameters": {
            "type": "object",
            "properties": {
                "city": {"type": "string", "description": "Customer city (optional)"},
                "state": {"type": "string", "description": "Customer state/region (optional)"},
                "status": {"type": "string", "description": "Order status (optional)"},
                "date_token": {"type": "string", "description": "Date range token"},
            },
            "required": [],
        },
    }
    async def execute(city=None, state=None, status=None, date_token=None):
        return await _shopify_not_wired()
    return {"schema": schema, "execute": execute}


def _make_count_low_reviews(cfg):
    schema = {
        "name": "count_low_reviews",
        "description": "Count low-satisfaction orders (satisfaction <= score_max).",
        "parameters": {
            "type": "object",
            "properties": {
                "score_max": {"type": "integer", "description": "Maximum score (default 2)"},
                "city": {"type": "string", "description": "Customer city (optional)"},
                "date_token": {"type": "string", "description": "Date range token"},
            },
            "required": [],
        },
    }
    async def execute(score_max=2, city=None, date_token=None):
        return await _shopify_not_wired()
    return {"schema": schema, "execute": execute}


def _make_get_order_status(cfg):
    schema = {
        "name": "get_order_status",
        "description": "Look up a single order's status and key dates",
        "parameters": {
            "type": "object",
            "properties": {"order_id": {"type": "string", "description": "Order ID"}},
            "required": ["order_id"],
        },
    }
    async def execute(order_id):
        return await _shopify_not_wired()
    return {"schema": schema, "execute": execute}


def _make_get_revenue(cfg):
    schema = {
        "name": "get_revenue",
        "description": "Total revenue, optionally filtered by date / state / category / group_by",
        "parameters": {
            "type": "object",
            "properties": {
                "date_token": {"type": "string", "description": "Date range token"},
                "state": {"type": "string", "description": "Customer state (optional)"},
                "category": {"type": "string", "description": "Product category (optional)"},
                "group_by": {"type": "string", "enum": ["state", "category", "month"]},
            },
            "required": [],
        },
    }
    async def execute(date_token=None, state=None, category=None, group_by=None):
        return await _shopify_not_wired()
    return {"schema": schema, "execute": execute}


def _make_list_orders(cfg):
    schema = {
        "name": "list_orders",
        "description": "List individual orders, paginated, with optional filters",
        "parameters": {
            "type": "object",
            "properties": {
                "city": {"type": "string", "description": "Customer city (optional)"},
                "state": {"type": "string", "description": "Customer state (optional)"},
                "status": {"type": "string", "description": "Order status (optional)"},
                "date_token": {"type": "string", "description": "Date range token"},
                "limit": {"type": "integer", "description": "Max rows (default 20, max 50)"},
                "offset": {"type": "integer", "description": "Rows to skip (default 0)"},
            },
            "required": [],
        },
    }
    async def execute(city=None, state=None, status=None, date_token=None, limit=20, offset=0):
        return await _shopify_not_wired()
    return {"schema": schema, "execute": execute}


def _make_top_products(cfg):
    schema = {
        "name": "top_products",
        "description": "Top-N products by units sold or revenue, optionally within a date range",
        "parameters": {
            "type": "object",
            "properties": {
                "date_token": {"type": "string", "description": "Date range token"},
                "limit": {"type": "integer", "description": "Top N (default 10, max 25)"},
                "by": {"type": "string", "description": '"count" or "revenue"'},
            },
            "required": [],
        },
    }
    async def execute(date_token=None, limit=10, by="count"):
        return await _shopify_not_wired()
    return {"schema": schema, "execute": execute}


# --- The config -------------------------------------------------------------

CONFIG = SchemaConfig(
    name="shopify",
    display_name="Shopify",
    tables={
        "orders": T_ORDERS,
        "customers": T_CUSTOMERS,
        "order_items": T_ORDER_ITEMS,
        "products": T_PRODUCTS,
        "product_category_translation": T_PRODUCT_CATEGORY_TRANSLATION,
        "sellers": T_CUSTOMERS,  # Shopify has no separate sellers concept
        "order_payments": T_ORDERS,  # payments are columns on orders
        "order_reviews": T_ORDERS,  # satisfaction is a column on orders
        "refunds": T_REFUNDS,
    },
    columns={
        "order_id": COL_ORDER_ID,
        "order_status": COL_ORDER_STATUS,
        "order_purchase_timestamp": COL_ORDER_PURCHASE_TS,
        "order_delivered_date": COL_ORDER_DELIVERED_DATE,
        "order_estimated_delivery_date": COL_ORDER_ESTIMATED_DATE,
        "customer_id": COL_CUSTOMER_ID,
        "customer_city": COL_CUSTOMER_CITY,
        "customer_state": COL_CUSTOMER_STATE,
        "customer_unique_id": COL_CUSTOMER_UNIQUE_ID,
        "product_id": COL_PRODUCT_ID,
        "seller_id": COL_CUSTOMER_UNIQUE_ID,  # seller ~= customer in Shopify
        "price": COL_PRICE,
        "freight_value": COL_FREIGHT_VALUE,
        "product_category_pt": COL_PRODUCT_CATEGORY_PT,
        "product_category_en": COL_PRODUCT_CATEGORY_EN,
        "payment_type": COL_PAYMENT_TYPE,
        "payment_value": COL_PAYMENT_VALUE,
        "review_id": COL_ORDER_ID,
        "review_score": COL_REVIEW_SCORE,
        "review_creation_date": COL_ORDER_PURCHASE_TS,
    },
    enums={
        "status": ORDER_STATUSES,
        "payment_type": None,  # freeform in Shopify
    },
    states=US_STATES,
    scope=SCOPE_PATTERNS,
    prompt=PROMPT,
    function_factories=(
        _make_count_orders,
        _make_count_low_reviews,
        _make_get_order_status,
        _make_get_revenue,
        _make_list_orders,
        _make_top_products,
    ),
)
