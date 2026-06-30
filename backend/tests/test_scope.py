"""Tests for the out-of-scope concept guard (validation/scope.py)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from validation.scope import detect_unsupported_concept


@pytest.mark.parametrize(
    "question,concept",
    [
        ("are there any returns in Sao Paulo yesterday?", "returns"),
        ("how many returned orders?", "returns"),
        ("show me refunds last month", "refunds"),
        ("any chargebacks this year?", "chargebacks"),
        ("what was our profit last month?", "profit or margin"),
        ("revenue margin by category", "profit or margin"),
        ("how much inventory do we have?", "inventory or stock levels"),
        ("what's in stock?", "inventory or stock levels"),
        ("total discounts given", "discounts or coupons"),
    ],
)
def test_detects_unsupported(question, concept):
    result = detect_unsupported_concept(question)
    assert result is not None, f"expected to flag: {question!r}"
    assert result["concept"] == concept
    assert result["suggestion"]


@pytest.mark.parametrize(
    "question",
    [
        "how many delivered orders in Sao Paulo last month?",
        "total revenue this year",
        "how many returning customers do we have?",  # 'returning' must NOT match
        "top 5 products by revenue",
        "list canceled orders",
        "how many low reviews last week?",
    ],
)
def test_allows_supported(question):
    assert detect_unsupported_concept(question) is None, f"false positive: {question!r}"
