"""Deterministic entity intent for count queries (meta-tool layer).

Detects whether the user means catalog products, orders sold, reviews,
or payments — without relying on the LLM to pick among 40+ function names.
"""
from __future__ import annotations

import re
from typing import Optional

# Catalog / inventory phrasing → count rows in products table.
_CATALOG_SIGNALS = re.compile(
    r"\b("
    r"we have|in the catalog|in catalog|product catalog|"
    r"skus?|stock keeping|listed products?"
    r")\b",
    re.IGNORECASE,
)

# Transactional phrasing → count orders / line items sold.
_ORDER_SIGNALS = re.compile(
    r"\b("
    r"ordered|sold|purchased|placed|shipped|delivered|"
    r"were bought|units sold|orders?\b"
    r")\b",
    re.IGNORECASE,
)

_REVIEW_SIGNALS = re.compile(
    r"\b(reviews?|stars?|rated|low.?scor|bad reviews?|1[- ]star|2[- ]star)\b",
    re.IGNORECASE,
)

_PAYMENT_SIGNALS = re.compile(
    r"\b(payments?|credit cards?|boleto|voucher|debit cards?|payment type)\b",
    re.IGNORECASE,
)

_PRODUCT_NOUN = re.compile(r"\bproducts?\b", re.IGNORECASE)


def has_catalog_signal(question: str) -> bool:
    return bool(_CATALOG_SIGNALS.search(question))


def has_order_signal(question: str) -> bool:
    return bool(_ORDER_SIGNALS.search(question))


def has_review_signal(question: str) -> bool:
    return bool(_REVIEW_SIGNALS.search(question))


def has_payment_signal(question: str) -> bool:
    return bool(_PAYMENT_SIGNALS.search(question))


def mentions_products(question: str) -> bool:
    return bool(_PRODUCT_NOUN.search(question))


def detect_count_ambiguity(question: str) -> bool:
    """True when 'products' could mean catalog size or orders sold."""
    if not mentions_products(question):
        return False
    if has_review_signal(question) or has_payment_signal(question):
        return False
    # Clear catalog-only or order-only phrasing → not ambiguous.
    if has_catalog_signal(question) and not has_order_signal(question):
        return False
    if has_order_signal(question) and not has_catalog_signal(question):
        return False
    # "how many products in X" with no other signal → ambiguous.
    return True


def detect_entity_for_count(question: str) -> Optional[str]:
    """Return entity slug for a count meta-tool, or None if unclear.

    Values: products | orders | reviews | payments
    """
    if has_review_signal(question):
        return "reviews"
    if has_payment_signal(question) and not mentions_products(question):
        return "payments"

    if mentions_products(question):
        if has_catalog_signal(question) and not has_order_signal(question):
            return "products"
        if has_order_signal(question) and not has_catalog_signal(question):
            return "orders"
        if detect_count_ambiguity(question):
            return None
        # Default bare "products" without order context → catalog (conservative
        # for "how many products in category X" analyst questions).
        return "products"

    # No product noun — default to orders (most common commerce count).
    if has_order_signal(question) or not has_catalog_signal(question):
        return "orders"
    return "orders"


def build_count_clarify(category: Optional[str] = None) -> dict:
    """Clarify payload when product count intent is ambiguous."""
    cat = f" in {category}" if category else ""
    return {
        "prompt": (
            "Do you mean products in the catalog, or orders that included "
            "those products?"
        ),
        "options": [
            {
                "label": "Products in catalog",
                "reply": f"How many products do we have in the catalog{cat}?",
            },
            {
                "label": "Orders sold",
                "reply": f"How many orders included products{cat}?",
            },
        ],
    }
