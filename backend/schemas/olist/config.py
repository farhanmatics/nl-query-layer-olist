"""Olist schema config — the default and reference implementation.

Everything Olist-specific lives here. The rest of the backend reads
from this (via `schemas.get_active_config()`) instead of hardcoding
`olist_*` strings.

If you're adding a second schema, copy this directory to
`backend/schemas/<name>/`, edit the constants below, and register the
loader in `schemas/__init__.py::_BUILTIN`. That's the whole onboarding
flow.
"""
from schemas.base import (
    ColumnRef,
    FunctionFactory,
    PromptConfig,
    SchemaConfig,
    ScopePattern,
)


# --- Table names -------------------------------------------------------------

T_ORDERS = "olist_orders_dataset"
T_CUSTOMERS = "olist_customers_dataset"
T_ORDER_ITEMS = "olist_order_items_dataset"
T_PRODUCTS = "olist_products_dataset"
T_PRODUCT_CATEGORY_TRANSLATION = "product_category_name_translation"
T_SELLERS = "olist_sellers_dataset"
T_ORDER_PAYMENTS = "olist_order_payments_dataset"
T_ORDER_REVIEWS = "olist_order_reviews_dataset"


# --- Column references -------------------------------------------------------
#
# Each ColumnRef stores the LOGICAL table name (a key into `tables` below).
# The factory's `table_for()` helper resolves it to the physical name at
# SQL-emit time. This indirection is the whole point: a future schema
# can change the physical table name without touching any function code.

COL_ORDER_ID = ColumnRef("orders", "order_id")
COL_ORDER_STATUS = ColumnRef("orders", "order_status")
COL_ORDER_PURCHASE_TS = ColumnRef("orders", "order_purchase_timestamp")
COL_ORDER_DELIVERED_DATE = ColumnRef("orders", "order_delivered_customer_date")
COL_ORDER_ESTIMATED_DATE = ColumnRef("orders", "order_estimated_delivery_date")

COL_CUSTOMER_ID = ColumnRef("orders", "customer_id")
COL_CUSTOMER_CITY = ColumnRef("customers", "customer_city")
COL_CUSTOMER_STATE = ColumnRef("customers", "customer_state")
COL_CUSTOMER_UNIQUE_ID = ColumnRef("customers", "customer_unique_id")

COL_PRODUCT_ID = ColumnRef("order_items", "product_id")
COL_SELLER_ID = ColumnRef("order_items", "seller_id")
COL_SELLER_CITY = ColumnRef("sellers", "seller_city")
COL_SELLER_STATE = ColumnRef("sellers", "seller_state")
COL_PRICE = ColumnRef("order_items", "price")
COL_FREIGHT_VALUE = ColumnRef("order_items", "freight_value")

COL_PRODUCT_CATEGORY_PT = ColumnRef("products", "product_category_name")
COL_PRODUCT_CATEGORY_EN = ColumnRef("product_category_translation", "product_category_name_english")

COL_PAYMENT_TYPE = ColumnRef("order_payments", "payment_type")
COL_PAYMENT_VALUE = ColumnRef("order_payments", "payment_value")

COL_REVIEW_ID = ColumnRef("order_reviews", "review_id")
COL_REVIEW_SCORE = ColumnRef("order_reviews", "review_score")
COL_REVIEW_CREATION_DATE = ColumnRef("order_reviews", "review_creation_date")


# --- Enum values (logical name -> allowed values) ----------------------------

ORDER_STATUSES = frozenset({
    "delivered", "shipped", "canceled", "processing",
    "invoiced", "unavailable", "approved", "created",
})

PAYMENT_TYPES = frozenset({
    "credit_card", "boleto", "voucher", "debit_card", "not_defined",
})


# --- Geographic state codes -------------------------------------------------

BRAZIL_UF = frozenset({
    "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS",
    "MG", "PA", "PB", "PR", "PE", "PI", "RJ", "RN", "RO", "RR", "RS", "SC",
    "SP", "SE", "TO",
})


# --- Out-of-scope lexicon ---------------------------------------------------

# Each entry: (regex, human label, "but you could ask X instead" hint).
# Order matters: we decline on the first match.
SCOPE_PATTERNS = (
    ScopePattern(
        pattern=r"\brefund(s|ed)?\b",
        concept="refunds",
        suggestion="Payments are recorded, but there are no refund or chargeback records.",
    ),
    ScopePattern(
        pattern=r"\bchargeback(s)?\b",
        concept="chargebacks",
        suggestion="Payments are recorded, but there are no chargeback records.",
    ),
    ScopePattern(
        pattern=r"\breturn(s|ed)?\b",
        concept="returns",
        suggestion=(
            "The closest available signals are canceled orders (order_status) "
            "and low review scores."
        ),
    ),
    ScopePattern(
        pattern=r"\b(profit|profits|profitability|margin|margins)\b",
        concept="profit or margin",
        suggestion=(
            "Revenue and item prices exist, but product/unit cost is not in the "
            "data, so profit cannot be computed."
        ),
    ),
    ScopePattern(
        pattern=r"\b(inventory|stock)\b",
        concept="inventory or stock levels",
        suggestion="The dataset has orders and products but no warehouse/stock quantities.",
    ),
    ScopePattern(
        pattern=r"\b(discount|discounts|coupon|coupons)\b",
        concept="discounts or coupons",
        suggestion=(
            "There is a 'voucher' payment type, but no discount or coupon amounts."
        ),
    ),
)


# --- Prompt config ----------------------------------------------------------

SOURCE_CITATIONS = {
    "get_order_status": "olist_orders_dataset JOIN olist_customers_dataset",
    "count_orders": "olist_orders_dataset JOIN olist_customers_dataset",
    "get_revenue": "olist_order_payments_dataset JOIN olist_orders_dataset",
    "count_low_reviews": "olist_order_reviews_dataset JOIN olist_orders_dataset",
    "top_products": "olist_order_items_dataset JOIN olist_products_dataset",
    "list_orders": "olist_orders_dataset JOIN olist_customers_dataset",
    "get_customer_info": "olist_customers_dataset JOIN olist_orders_dataset JOIN olist_order_payments_dataset",
    "get_product_info": "olist_products_dataset JOIN olist_order_items_dataset",
    "get_seller_info": "olist_sellers_dataset JOIN olist_order_items_dataset",
    "count_by_status": "olist_orders_dataset",
    "count_by_payment_type": "olist_order_payments_dataset JOIN olist_orders_dataset",
    "count_by_category": "olist_order_items_dataset JOIN olist_products_dataset",
    "revenue_by_state": "olist_order_payments_dataset JOIN olist_orders_dataset JOIN olist_customers_dataset",
    "revenue_by_category": "olist_order_items_dataset JOIN olist_products_dataset",
    "revenue_by_seller": "olist_order_items_dataset JOIN olist_sellers_dataset",
    "revenue_by_payment_type": "olist_order_payments_dataset",
    "revenue_trend": "olist_order_payments_dataset JOIN olist_orders_dataset",
    "top_categories": "olist_order_items_dataset JOIN olist_products_dataset",
    "count_products": "olist_products_dataset",
    "products_by_rating": "olist_order_reviews_dataset JOIN olist_order_items_dataset",
    "top_sellers": "olist_order_items_dataset JOIN olist_sellers_dataset",
    "seller_metrics": "olist_sellers_dataset JOIN olist_order_items_dataset",
    "seller_concentration": "olist_order_items_dataset",
    "sellers_by_state": "olist_sellers_dataset JOIN olist_order_items_dataset",
    "customer_lifetime_value": "olist_order_payments_dataset JOIN olist_orders_dataset",
    "repeat_customer_rate": "olist_orders_dataset",
    "customers_by_city": "olist_orders_dataset JOIN olist_customers_dataset",
    "customer_order_history": "olist_orders_dataset JOIN olist_order_payments_dataset",
    "customer_cohort_analysis": "olist_orders_dataset JOIN olist_order_payments_dataset",
    "average_rating_by_product": "olist_order_reviews_dataset JOIN olist_order_items_dataset",
    "average_rating_by_seller": "olist_order_reviews_dataset JOIN olist_order_items_dataset",
    "average_rating_by_category": "olist_order_reviews_dataset JOIN olist_products_dataset",
    "review_score_distribution": "olist_order_reviews_dataset",
    "review_sentiment_trend": "olist_order_reviews_dataset",
    "on_time_delivery_rate": "olist_orders_dataset",
    "average_delivery_days": "olist_orders_dataset",
    "late_deliveries": "olist_orders_dataset",
    "fulfillment_status_breakdown": "olist_orders_dataset",
    "seller_comparison": "olist_order_items_dataset JOIN olist_sellers_dataset",
    "category_comparison": "olist_order_items_dataset JOIN olist_products_dataset",
    "state_comparison": "olist_orders_dataset JOIN olist_customers_dataset",
    "payment_type_breakdown": "olist_order_payments_dataset",
}

PROMPT = PromptConfig(
    dataset_description=(
        "You translate a natural-language question into a single JSON function call "
        "against the Olist Brazilian e-commerce dataset (orders, customers, items, "
        "products, payments, reviews, sellers)."
    ),
    city_rule=(
        'normalize to lowercase without accents (e.g., "São Paulo" → "sao paulo", '
        '"Rio de Janeiro" → "rio de janeiro").'
    ),
    state_rule='use 2-letter Brazilian UF codes (e.g., "SP", "RJ", "MG").',
    status_rule=(
        f'valid order statuses are {", ".join(sorted(ORDER_STATUSES))}. '
        'Pass the status verbatim from this list.'
    ),
    group_by_rule=(
        'when a question says "by X" / "broken down by X" / "grouped by X" / "per X" '
        '(X = state, category, or month), set group_by to that dimension on get_revenue, '
        'or pick the dedicated breakdown tool (revenue_by_state, revenue_by_category, '
        'revenue_trend, fulfillment_status_breakdown, etc.) when one exists.'
    ),
    few_shot_examples=(
        ('How many delivered orders did we have in São Paulo last month?',
         '{"tool": "count_orders", "args": {"city": "sao paulo", "status": "delivered", "date_token": "last_month"}}'),
        ('How many canceled orders this year?',
         '{"tool": "count_orders", "args": {"status": "canceled", "date_token": "this_year"}}'),
        ('How many orders in Rio de Janeiro last week?',
         '{"tool": "count_orders", "args": {"city": "rio de janeiro", "date_token": "last_week"}}'),
        ('What is the status of order abc123?',
         '{"tool": "get_order_status", "args": {"order_id": "abc123"}}'),
        ('How many shipped orders do we have?',
         '{"tool": "count_orders", "args": {"status": "shipped"}}'),
        ('Total orders in SP this month?',
         '{"tool": "count_orders", "args": {"state": "SP", "date_token": "this_month"}}'),
        ('What was our total revenue last month?',
         '{"tool": "get_revenue", "args": {"date_token": "last_month"}}'),
        ('Revenue by state this year',
         '{"tool": "revenue_by_state", "args": {"date_token": "this_year"}}'),
        ('Show revenue broken down by category',
         '{"tool": "revenue_by_category", "args": {}}'),
        ('Total revenue in MG last year',
         '{"tool": "get_revenue", "args": {"state": "MG", "date_token": "last_year"}}'),
        ('How much revenue did the health_beauty category make?',
         '{"tool": "get_revenue", "args": {"category": "health_beauty"}}'),
        ('How many approved orders last year?',
         '{"tool": "count_orders", "args": {"status": "approved", "date_token": "last_year"}}'),
        ('How many low reviews did we get last month?',
         '{"tool": "count_low_reviews", "args": {"date_token": "last_month"}}'),
        ('How many 1-star or 2-star reviews in Sao Paulo?',
         '{"tool": "count_low_reviews", "args": {"score_max": 2, "city": "sao paulo"}}'),
        ('What are our best-selling products?',
         '{"tool": "top_products", "args": {"by": "count", "limit": 10}}'),
        ('Top 5 products by revenue this year',
         '{"tool": "top_products", "args": {"by": "revenue", "limit": 5, "date_token": "this_year"}}'),
        ('Show me delivered orders in Sao Paulo',
         '{"tool": "list_orders", "args": {"city": "sao paulo", "status": "delivered"}}'),
        ('List the next 20 canceled orders',
         '{"tool": "list_orders", "args": {"status": "canceled", "limit": 20}}'),
        ('List 30 shipped orders in MG',
         '{"tool": "list_orders", "args": {"status": "shipped", "state": "MG", "limit": 30}}'),
        ('Who are our top sellers by revenue?',
         '{"tool": "top_sellers", "args": {"by": "revenue", "limit": 10}}'),
        ('What percent of orders are delivered on time?',
         '{"tool": "on_time_delivery_rate", "args": {}}'),
        ('Break down orders by status',
         '{"tool": "fulfillment_status_breakdown", "args": {}}'),
        ('How many products do we have in the perfumaria category?',
         '{"tool": "count_products", "args": {"category": "perfumaria"}}'),
        ('How many perfumaria orders were placed last year?',
         '{"tool": "count_by_category", "args": {"category": "perfumaria", "date_token": "last_year"}}'),
    ),
    source_citations=SOURCE_CITATIONS,
)


# --- Function factories ------------------------------------------------------

# Imported lazily to avoid a circular import: functions/*.py build SQL
# using the config we hand them, and the config builds them via these
# factories. We resolve at factory-call time.
def _factories() -> tuple:
    from functions.all_factories import all_factories
    return all_factories()


# --- The config -------------------------------------------------------------

CONFIG = SchemaConfig(
    name="olist",
    display_name="Olist Brazilian e-commerce",
    tables={
        "orders": T_ORDERS,
        "customers": T_CUSTOMERS,
        "order_items": T_ORDER_ITEMS,
        "products": T_PRODUCTS,
        "product_category_translation": T_PRODUCT_CATEGORY_TRANSLATION,
        "sellers": T_SELLERS,
        "order_payments": T_ORDER_PAYMENTS,
        "order_reviews": T_ORDER_REVIEWS,
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
        "seller_id": COL_SELLER_ID,
        "seller_city": COL_SELLER_CITY,
        "seller_state": COL_SELLER_STATE,
        "price": COL_PRICE,
        "freight_value": COL_FREIGHT_VALUE,
        "product_category_pt": COL_PRODUCT_CATEGORY_PT,
        "product_category_en": COL_PRODUCT_CATEGORY_EN,
        "payment_type": COL_PAYMENT_TYPE,
        "payment_value": COL_PAYMENT_VALUE,
        "review_id": COL_REVIEW_ID,
        "review_score": COL_REVIEW_SCORE,
        "review_creation_date": COL_REVIEW_CREATION_DATE,
    },
    enums={
        "status": ORDER_STATUSES,
        "payment_type": PAYMENT_TYPES,
    },
    states=BRAZIL_UF,
    scope=SCOPE_PATTERNS,
    prompt=PROMPT,
    function_factories=_factories(),
)
