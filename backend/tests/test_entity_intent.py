"""Tests for entity_intent detectors (meta-tool P0)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from validation.entity_intent import (  # noqa: E402
    detect_count_ambiguity,
    detect_entity_for_count,
    has_catalog_signal,
)


def test_perfumaria_we_have_is_catalog():
    q = "how many products do we have in perfumaria category"
    assert has_catalog_signal(q)
    assert detect_entity_for_count(q) == "products"
    assert not detect_count_ambiguity(q)


def test_perfumaria_orders_sold_is_orders():
    q = "how many perfumaria orders were placed last year"
    assert detect_entity_for_count(q) == "orders"


def test_bare_products_in_category_is_ambiguous():
    q = "how many products in perfumaria"
    assert detect_count_ambiguity(q)
    assert detect_entity_for_count(q) is None


def test_delivered_orders_is_orders():
    q = "how many delivered orders in sao paulo last month"
    assert detect_entity_for_count(q) == "orders"


def test_low_reviews_is_reviews():
    q = "how many low reviews last month"
    assert detect_entity_for_count(q) == "reviews"
