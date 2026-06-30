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

COL_ORDER_ID = ColumnRef(T_ORDERS, "order_id")
COL_ORDER_STATUS = ColumnRef(T_ORDERS, "order_status")
COL_ORDER_PURCHASE_TS = ColumnRef(T_ORDERS, "order_purchase_timestamp")
COL_ORDER_DELIVERED_DATE = ColumnRef(T_ORDERS, "order_delivered_customer_date")
COL_ORDER_ESTIMATED_DATE = ColumnRef(T_ORDERS, "order_estimated_delivery_date")

COL_CUSTOMER_ID = ColumnRef(T_ORDERS, "customer_id")
COL_CUSTOMER_CITY = ColumnRef(T_CUSTOMERS, "customer_city")
COL_CUSTOMER_STATE = ColumnRef(T_CUSTOMERS, "customer_state")
COL_CUSTOMER_UNIQUE_ID = ColumnRef(T_CUSTOMERS, "customer_unique_id")

COL_PRODUCT_ID = ColumnRef(T_ORDER_ITEMS, "product_id")
COL_SELLER_ID = ColumnRef(T_ORDER_ITEMS, "seller_id")
COL_PRICE = ColumnRef(T_ORDER_ITEMS, "price")
COL_FREIGHT_VALUE = ColumnRef(T_ORDER_ITEMS, "freight_value")

COL_PRODUCT_CATEGORY_PT = ColumnRef(T_PRODUCTS, "product_category_name")
COL_PRODUCT_CATEGORY_EN = ColumnRef(T_PRODUCT_CATEGORY_TRANSLATION, "product_category_name_english")

COL_PAYMENT_TYPE = ColumnRef(T_ORDER_PAYMENTS, "payment_type")
COL_PAYMENT_VALUE = ColumnRef(T_ORDER_PAYMENTS, "payment_value")

COL_REVIEW_ID = ColumnRef(T_ORDER_REVIEWS, "review_id")
COL_REVIEW_SCORE = ColumnRef(T_ORDER_REVIEWS, "review_score")
COL_REVIEW_CREATION_DATE = ColumnRef(T_ORDER_REVIEWS, "review_creation_date")


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

PROMPT = PromptConfig(
    dataset_description=(
        "You translate a natural-language question into a single JSON function call "
        "against the Olist Brazilian e-commerce dataset (orders, customers, items, "
        "products, payments, reviews)."
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
        '(X = state, category, or month), set group_by to that dimension.'
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
         '{"tool": "get_revenue", "args": {"date_token": "this_year", "group_by": "state"}}'),
        ('Show revenue broken down by category',
         '{"tool": "get_revenue", "args": {"group_by": "category"}}'),
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
    ),
    source_citations={
        "get_order_status": "olist_orders_dataset JOIN olist_customers_dataset",
        "count_orders": "olist_orders_dataset JOIN olist_customers_dataset",
        "get_revenue": "olist_order_payments_dataset / olist_order_items_dataset JOIN olist_orders_dataset",
        "count_low_reviews": "olist_order_reviews_dataset JOIN olist_orders_dataset",
        "top_products": "olist_order_items_dataset JOIN olist_products_dataset, product_category_name_translation",
        "list_orders": "olist_orders_dataset JOIN olist_customers_dataset",
    },
)


# --- Function factories ------------------------------------------------------

# Imported lazily to avoid a circular import: functions/*.py build SQL
# using the config we hand them, and the config builds them via these
# factories. We resolve at factory-call time.
def _factories() -> tuple:
    from functions.count_orders import make_count_orders
    from functions.count_low_reviews import make_count_low_reviews
    from functions.get_order_status import make_get_order_status
    from functions.get_revenue import make_get_revenue
    from functions.list_orders import make_list_orders
    from functions.top_products import make_top_products
    return (
        make_count_orders,
        make_count_low_reviews,
        make_get_order_status,
        make_get_revenue,
        make_list_orders,
        make_top_products,
    )


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
