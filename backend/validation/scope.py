"""Out-of-scope concept guard (backend-owned, deterministic).

Why this exists
---------------
The dataset has no notion of returns, refunds, profit, inventory, etc. A small
model, asked "how many returns did we have?", will happily route to the nearest
function (e.g. low-reviews) and return a confident number — which a manager may
read as an actual returns count. That silent substitution is precisely the
faithfulness failure this product exists to prevent.

So before we ever consult the model, we scan the question for concepts the schema
provably cannot answer and decline explicitly, naming the nearest real signal so
the user can rephrase. Declining honestly beats answering with a proxy.

It is intentionally high-precision: each pattern is word-boundaried and targets
terms with no representation in the Olist schema, so legitimate questions
("returning customers", "delivered orders") are not caught.
"""
import re
from typing import Optional

# (compiled pattern, concept label, what the data *does* have instead)
_UNSUPPORTED = [
    (
        re.compile(r"\brefund(s|ed)?\b", re.IGNORECASE),
        "refunds",
        "Payments are recorded, but there are no refund or chargeback records.",
    ),
    (
        re.compile(r"\bchargeback(s)?\b", re.IGNORECASE),
        "chargebacks",
        "Payments are recorded, but there are no chargeback records.",
    ),
    (
        re.compile(r"\breturn(s|ed)?\b", re.IGNORECASE),
        "returns",
        "The closest available signals are canceled orders (order_status) and "
        "low review scores.",
    ),
    (
        re.compile(r"\b(profit|profits|profitability|margin|margins)\b", re.IGNORECASE),
        "profit or margin",
        "Revenue and item prices exist, but product/unit cost is not in the data, "
        "so profit cannot be computed.",
    ),
    (
        re.compile(r"\b(inventory|stock)\b", re.IGNORECASE),
        "inventory or stock levels",
        "The dataset has orders and products but no warehouse/stock quantities.",
    ),
    (
        re.compile(r"\b(discount|discounts|coupon|coupons)\b", re.IGNORECASE),
        "discounts or coupons",
        "There is a 'voucher' payment type, but no discount or coupon amounts.",
    ),
]


def detect_unsupported_concept(question: str) -> Optional[dict]:
    """Return {'concept', 'suggestion'} if the question targets a concept the
    schema cannot answer, else None."""
    if not question:
        return None
    for pattern, concept, suggestion in _UNSUPPORTED:
        if pattern.search(question):
            return {"concept": concept, "suggestion": suggestion}
    return None
