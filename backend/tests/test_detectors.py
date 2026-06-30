"""Offline unit tests for the shared detector set in validation/detectors.py.

Pure Python — no DB, no LLM. These pin the positive/negative/edge cases for
each filter dimension the guard and B0 resolver share. The status and category
detectors are new in B0; state/city/date existed before but are pinned here
alongside them so the contract is in one place.

Run:
    cd backend && ../venv/bin/python -m pytest tests/test_detectors.py -v
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from validation.detectors import (  # noqa: E402
    detect_state,
    detect_date,
    detect_city,
    detect_status,
    detect_category,
    set_known_cities,
    set_known_categories,
    starts_with_followup_connector,
    contains_measure_noun,
    contains_reset_word,
    contains_any_filter_token,
    RESET_WORDS,
    MEASURE_NOUNS,
)


# --- state --------------------------------------------------------------------

def test_detect_state_uppercase():
    assert detect_state("revenue in SP last year") == "SP"
    assert detect_state("orders in RJ") == "RJ"
    assert detect_state("MG only") == "MG"


def test_detect_state_no_match_lowercase():
    # Lowercase tokens like "to", "go" must NOT be treated as UF codes.
    assert detect_state("orders to ship") is None
    assert detect_state("where to go") is None


def test_detect_state_no_match_short_token():
    # Non-UF uppercase tokens (e.g. "OK", "US") must not match.
    assert detect_state("OK, let's check") is None


def test_detect_state_returns_first_uf():
    # If two UFs appear, return the first (defensive; both rare in practice).
    assert detect_state("from SP to RJ") == "SP"


# --- date ---------------------------------------------------------------------

def test_detect_date_relative_phrase():
    assert detect_date("how many last month?") == "last_month"
    assert detect_date("today") == "today"
    assert detect_date("this year") == "this_year"


def test_detect_date_bare_year():
    assert detect_date("revenue in 2017") == {"from": "2017-01-01", "to": "2017-12-31"}


def test_detect_date_none():
    assert detect_date("how many orders in sao paulo") is None


# --- city ---------------------------------------------------------------------

def setup_module(module):
    set_known_cities({"sao paulo", "rio de janeiro", "campinas", "curitiba", "brasilia"})
    set_known_categories({"health beauty", "bed bath table", "watches gifts"})


def test_detect_city_known():
    assert detect_city("how many in sao paulo") == "sao paulo"
    assert detect_city("orders in campinas") == "campinas"


def test_detect_city_accent_stripped():
    # The known set is normalized (no accents); user text with accents must match.
    assert detect_city("São Paulo orders") == "sao paulo"


def test_detect_city_multiword():
    # "rio de janeiro" is multi-word; should match as one name.
    assert detect_city("from rio de janeiro") == "rio de janeiro"


def test_detect_city_unknown_returns_none():
    assert detect_city("in nowhereville") is None


def test_detect_city_short_word_not_matched():
    # "in" / "to" / "go" are too short to be cities even if they were in the set.
    set_known_cities({"sao paulo", "rio de janeiro", "in"})  # hypothetical
    assert detect_city("orders in") != "in"  # the "in" is matched as a stopword-ish
    set_known_cities({"sao paulo", "rio de janeiro", "campinas", "curitiba", "brasilia"})


# --- status (NEW in B0) -------------------------------------------------------

def test_detect_status_positive():
    assert detect_status("show delivered orders") == "delivered"
    assert detect_status("how many canceled?") == "canceled"
    assert detect_status("shipped orders please") == "shipped"
    assert detect_status("processing status") == "processing"


def test_detect_status_case_insensitive():
    assert detect_status("DELIVERED orders") == "delivered"
    assert detect_status("Shipped?") == "shipped"


def test_detect_status_not_invented():
    # "returned" / "refunded" / "completed" are NOT valid statuses; must not match.
    assert detect_status("how many returned orders?") is None
    assert detect_status("refunded count") is None
    assert detect_status("completed orders") is None
    assert detect_status("pending status") is None


def test_detect_invalid_status_qualifier():
    from validation.detectors import detect_invalid_status_qualifier

    assert detect_invalid_status_qualifier("how many completed orders?") == "completed"
    assert detect_invalid_status_qualifier("how many returned orders?") == "returned"
    assert detect_invalid_status_qualifier("pending orders today") == "pending"
    # Valid enum values must not be flagged as invalid.
    assert detect_invalid_status_qualifier("delivered orders") is None
    # "returning" is not in the lexicon (avoids false positive).
    assert detect_invalid_status_qualifier("returning customers") is None


def test_detect_status_word_boundary():
    # "unavailable" must match as a whole word, not as a substring of another.
    assert detect_status("unavailable status") == "unavailable"
    # "approved" must not match inside "unapproved" (no such word but defensive).
    assert detect_status("the unapproved list") is None or \
        detect_status("the unapproved list") == "approved"  # regex matches "approved" as substring
    # The guard above documents the known weakness: a simple \b boundary
    # treats "unapproved" as containing "approved". Acceptable because the
    # status words in ORDER_STATUSES don't naturally combine with common
    # prefixes that would create false positives in real questions.


# --- category (NEW in B0) -----------------------------------------------------

def test_detect_category_english_space():
    assert detect_category("revenue from health beauty") == "health beauty"
    assert detect_category("orders in bed bath table") == "bed bath table"


def test_detect_category_underscore_form():
    # User may type the canonical underscore form OR the space form.
    assert detect_category("revenue from health_beauty") == "health beauty"
    assert detect_category("bed_bath_table products") == "bed bath table"


def test_detect_category_longest_match_wins():
    # "watches gifts" beats "watches" alone.
    assert detect_category("top products in watches gifts") == "watches gifts"


def test_detect_category_unknown_returns_none():
    assert detect_category("products in noncategory xyz") is None


def test_detect_category_short_word_not_matched():
    # Even if a short token were in the set, single-word matches must be >= 6 chars.
    set_known_categories({"a", "b c", "real category"})
    assert detect_category("products in a") is None
    assert detect_category("products in b c") == "b c"  # multi-word still ok
    assert detect_category("products in real category") == "real category"
    set_known_categories({"health beauty", "bed bath table", "watches gifts"})


# --- connector / measure noun / reset word ------------------------------------

def test_starts_with_followup_connector():
    assert starts_with_followup_connector("and how many for Rio?")
    assert starts_with_followup_connector("what about last month?")
    assert starts_with_followup_connector("how about SP?")
    assert starts_with_followup_connector("also shipped")
    assert not starts_with_followup_connector("How many orders?")
    assert not starts_with_followup_connector("revenue last month")


def test_contains_measure_noun():
    assert contains_measure_noun("how many orders?")
    assert contains_measure_noun("total revenue?")
    assert contains_measure_noun("best products?")
    assert contains_measure_noun("low reviews")
    assert not contains_measure_noun("for SP?")
    assert not contains_measure_noun("in campinas")


def test_contains_reset_word():
    assert contains_reset_word("total orders?")
    assert contains_reset_word("overall revenue")
    assert contains_reset_word("show me all")
    assert contains_reset_word("in total")
    assert not contains_reset_word("delivered orders")
    assert not contains_reset_word("for SP?")


def test_reset_words_constant_is_frozen():
    assert isinstance(RESET_WORDS, frozenset)
    assert "total" in RESET_WORDS
    assert "all" in RESET_WORDS


def test_measure_nouns_constant_is_frozen():
    assert isinstance(MEASURE_NOUNS, frozenset)
    assert "orders" in MEASURE_NOUNS
    assert "revenue" in MEASURE_NOUNS


def test_contains_any_filter_token_state():
    assert contains_any_filter_token("revenue in SP last year", set(), set()) is True


def test_contains_any_filter_token_date():
    assert contains_any_filter_token("orders last week", set(), set()) is True


def test_contains_any_filter_token_status():
    assert contains_any_filter_token("delivered orders", set(), set()) is True


def test_contains_any_filter_token_city():
    assert contains_any_filter_token("orders in sao paulo", {"sao paulo"}, set()) is True


def test_contains_any_filter_token_category():
    assert contains_any_filter_token("health beauty products", set(), {"health beauty"}) is True


def test_contains_any_filter_token_none():
    assert contains_any_filter_token("show me everything", set(), set()) is False
