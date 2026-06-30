"""Offline unit tests for the filter-faithfulness guard.

Pure Python — no DB, no LLM. These pin the exact failure modes the guard exists
to catch (filters the 2B model silently drops) plus the false-positive cases it
must NOT trigger on. Run:

    cd backend && ../venv/bin/python -m pytest tests/test_faithfulness.py -v
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from validation.faithfulness import check_filter_faithfulness  # noqa: E402

KNOWN = {"sao paulo", "rio de janeiro", "campinas", "curitiba", "brasilia"}
REVENUE_PARAMS = {"date_token", "state", "category", "group_by"}
COUNT_PARAMS = {"city", "state", "status", "date_token"}


def guard(question, supported, args):
    return check_filter_faithfulness(question, supported, args or {}, KNOWN)


# --- the three real eval failures the guard must repair ---------------------

def test_repairs_dropped_state_uppercase():
    r = guard("How much revenue came from SP?", REVENUE_PARAMS, {})
    assert r["repairs"] == {"state": "SP"}


def test_repairs_dropped_relative_date():
    r = guard("Total revenue this year", REVENUE_PARAMS, {})
    assert r["repairs"] == {"date_token": "this_year"}


def test_repairs_dropped_state_keeps_model_date():
    # Model kept last_year but dropped RJ; guard fills only the gap.
    r = guard("Total revenue in RJ last year", REVENUE_PARAMS, {"date_token": "last_year"})
    assert r["repairs"] == {"state": "RJ"}


# --- must NOT over-repair ----------------------------------------------------

def test_no_repair_when_model_already_has_state():
    r = guard("Revenue in SP this year", REVENUE_PARAMS, {"state": "SP", "date_token": "this_year"})
    assert r["repairs"] == {}


def test_lowercase_uf_homographs_are_not_states():
    # "to", "go", "am" are UF codes only when uppercased; lowercase = English.
    r = guard("How many orders do we have to ship?", COUNT_PARAMS, {})
    assert "state" not in r["repairs"]


def test_unknown_city_not_invented():
    r = guard("How many orders in Nowhereville?", COUNT_PARAMS, {})
    assert r["repairs"] == {}


def test_unsupported_param_not_added():
    # get_order_status accepts only order_id — never inject state/date.
    r = guard("status of order in SP this year", {"order_id"}, {})
    assert r["repairs"] == {}


# --- unsupported geography must be refused, not silently dropped -------------

def test_unsupported_state_is_unresolved():
    # top_products can't filter by location → flag, don't ignore.
    r = guard("top products in SP", {"date_token", "limit", "by"}, {})
    assert r["repairs"] == {}
    assert any("SP" in u for u in r["unresolved"])


def test_unsupported_city_is_unresolved():
    r = guard("top products in Campinas", {"date_token", "limit", "by"}, {})
    assert r["repairs"] == {}
    assert any("campinas" in u for u in r["unresolved"])


def test_city_supported_is_repaired_not_unresolved():
    # get_revenue now supports city → repair it, no refusal.
    r = guard("revenue for Sao Paulo", {"date_token", "city", "state", "category"}, {})
    assert r["repairs"].get("city") == "sao paulo"
    assert r["unresolved"] == []


# --- detectors in isolation --------------------------------------------------

def test_known_city_detected():
    r = guard("revenue from Campinas", COUNT_PARAMS, {})
    assert r["repairs"].get("city") == "campinas"


def test_bare_year_becomes_explicit_range():
    r = guard("Total revenue in 2017", REVENUE_PARAMS, {})
    assert r["repairs"]["date_token"] == {"from": "2017-01-01", "to": "2017-12-31"}


def test_group_by_month_not_mistaken_for_date():
    # "by month" is a breakdown, not a date filter — no this/last qualifier.
    r = guard("Break down revenue by month", REVENUE_PARAMS, {"group_by": "month"})
    assert "date_token" not in r["repairs"]


def test_invalid_status_qualifier_is_unresolved():
    """Status-shaped word the schema doesn't track → refuse, not whole-dataset count."""
    r = guard("How many completed orders?", COUNT_PARAMS, {})
    assert r["repairs"] == {}
    assert any("completed" in u for u in r["unresolved"])


def test_invalid_status_not_flagged_when_model_supplied_status():
    r = guard("How many delivered orders?", COUNT_PARAMS, {"status": "delivered"})
    assert not any("delivered" in u for u in r["unresolved"])
