"""Offline unit tests for the B0 conversational resolver.

Pure Python — no DB, no LLM. These pin the exact resolution behaviour for the
two-turn Rio regression and its variants:
  - classification (FRESH vs FOLLOW_UP)
  - slot overlay (new city keeps prior op+date)
  - status overlay ("…and the canceled ones?")
  - category overlay ("…what about electronics?")
  - reset words ("total", "overall", "all")
  - fragment-with-no-prior → clarify
  - inherited op can't filter by a named place → clarify

Run:
    cd backend && ../venv/bin/python -m pytest tests/test_context_resolution.py -v
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from resolver import (  # noqa: E402
    classify_turn,
    resolve,
    get_prior_state,
    store_state,
    clear_session,
    _supported_params_for,
)
from validation.detectors import (  # noqa: E402
    set_known_cities,
    set_known_categories,
)


# Module-level setup: load the same kind of dictionary the runtime uses.
KNOWN_CITIES = {"sao paulo", "rio de janeiro", "campinas", "curitiba", "brasilia"}
KNOWN_CATEGORIES = {"health beauty", "bed bath table", "watches gifts", "electronics"}


def setup_module(module):
    set_known_cities(KNOWN_CITIES)
    set_known_categories(KNOWN_CATEGORIES)


# --- classification ----------------------------------------------------------

def test_classify_fresh_self_contained():
    assert classify_turn("How many delivered orders last month?", "count_orders") == "FRESH"


def test_classify_fresh_with_measure_noun():
    # Even starting with "and", if a measure noun is present, it's a fresh turn.
    assert classify_turn("and what was the revenue last year?", "get_revenue") == "FRESH"


def test_classify_followup_connector_plus_filter():
    assert classify_turn("and how many for Rio de Janeiro?", "count_low_reviews") == "FOLLOW_UP"


def test_classify_followup_filter_only_fragment():
    # No connector, no measure noun, has filter — classic follow-up.
    assert classify_turn("for SP?", "count_orders") == "FOLLOW_UP"
    assert classify_turn("in campinas", "count_orders") == "FOLLOW_UP"


def test_classify_followup_connector_with_filter():
    # Connector + no measure noun + filter → classic follow-up.
    assert classify_turn("and for SP?", "count_orders") == "FOLLOW_UP"


def test_classify_reset_word_is_followup():
    assert classify_turn("total", "count_orders") == "FOLLOW_UP"
    assert classify_turn("overall revenue", "get_revenue") == "FOLLOW_UP"
    assert classify_turn("show me all", "count_orders") == "FOLLOW_UP"


def test_classify_empty_is_followup():
    assert classify_turn("", "count_orders") == "FOLLOW_UP"


def test_classify_deixis_with_measure_noun_is_followup():
    """'about those orders…' refers back; measure noun must not force FRESH."""
    q = "about those orders how many have cancelled"
    assert classify_turn(q, "count_orders") == "FOLLOW_UP"


# --- resolution: FRESH path --------------------------------------------------

def test_resolve_fresh_no_prior():
    r = resolve(
        "How many delivered orders in Sao Paulo last month?",
        {"tool": "count_orders", "args": {"city": "sao paulo", "status": "delivered", "date_token": "last_month"}},
        prior=None,
        classification="FRESH",
    )
    assert r["operation"] == "count_orders"
    assert r["args"] == {"city": "sao paulo", "status": "delivered", "date_token": "last_month"}
    assert r["context"]["inherited"] is False
    assert r["context"]["from_operation"] is None
    assert r["context"]["carried"] == {}
    assert r["context"]["clarify"] is None


# --- resolution: FOLLOW-UP slot overlay --------------------------------------

def test_resolve_followup_city_overlay_keeps_op_and_date():
    """The Rio regression: prior was count_low_reviews+last_month; follow-up
    'and how many for Rio de Janeiro?' must inherit op+date, overlay city."""
    prior = {
        "operation": "count_low_reviews",
        "args": {"date_token": "last_month", "score_max": 2},
    }
    r = resolve(
        "and how many for Rio de Janeiro?",
        # The model's candidate (what it would have picked alone — wrong for this
        # turn): a generic count_orders. The resolver should IGNORE this and
        # return the inherited tool.
        {"tool": "count_orders", "args": {}},
        prior=prior,
        classification="FOLLOW_UP",
    )
    assert r["operation"] == "count_low_reviews"
    assert r["args"]["city"] == "rio de janeiro"
    assert r["args"]["date_token"] == "last_month"  # carried
    assert r["args"]["score_max"] == 2  # carried
    assert r["context"]["inherited"] is True
    assert r["context"]["from_operation"] == "count_low_reviews"
    assert r["context"]["carried"] == {"date_token": "last_month", "score_max": 2}
    assert r["context"]["clarify"] is None


def test_resolve_followup_status_overlay_swaps_status():
    """'…and the canceled ones?' must keep op+city+date, swap status."""
    prior = {
        "operation": "count_orders",
        "args": {"city": "sao paulo", "status": "delivered", "date_token": "last_month"},
    }
    r = resolve(
        "and the canceled ones?",
        {"tool": "count_orders", "args": {}},
        prior=prior,
        classification="FOLLOW_UP",
    )
    assert r["operation"] == "count_orders"
    assert r["args"]["status"] == "canceled"  # overlaid
    assert r["args"]["city"] == "sao paulo"   # carried
    assert r["args"]["date_token"] == "last_month"  # carried


def test_resolve_deixis_status_overlay_keeps_city_and_date():
    """'about those orders how many cancelled' keeps SP + last_month, swaps status."""
    prior = {
        "operation": "count_orders",
        "args": {"city": "sao paulo", "status": "delivered", "date_token": "last_month"},
    }
    r = resolve(
        "about those orders how many have cancelled",
        {"tool": "count_orders", "args": {}},
        prior=prior,
        classification="FOLLOW_UP",
    )
    assert r["operation"] == "count_orders"
    assert r["args"]["status"] == "canceled"
    assert r["args"]["city"] == "sao paulo"
    assert r["args"]["date_token"] == "last_month"
    assert r["context"]["inherited"] is True


def test_resolve_followup_category_overlay():
    """'what about electronics?' overlays category, keeps op+date."""
    prior = {
        "operation": "get_revenue",
        "args": {"date_token": "this_year", "state": "SP"},
    }
    r = resolve(
        "what about electronics?",
        {"tool": "get_revenue", "args": {}},
        prior=prior,
        classification="FOLLOW_UP",
    )
    assert r["operation"] == "get_revenue"
    assert r["args"]["category"] == "electronics"  # overlaid (space form)
    assert r["args"]["state"] == "SP"  # carried
    assert r["args"]["date_token"] == "this_year"  # carried


def test_resolve_followup_state_overlay():
    """'and in MG?' overlays state on a revenue query."""
    prior = {
        "operation": "get_revenue",
        "args": {"date_token": "last_year"},
    }
    r = resolve(
        "and in MG?",
        {"tool": "get_revenue", "args": {}},
        prior=prior,
        classification="FOLLOW_UP",
    )
    assert r["args"]["state"] == "MG"
    assert r["args"]["date_token"] == "last_year"


def test_resolve_followup_date_overlay():
    """'what about this month?' overlays date, keeps city+status."""
    prior = {
        "operation": "count_orders",
        "args": {"city": "sao paulo", "status": "delivered", "date_token": "last_month"},
    }
    r = resolve(
        "what about this month?",
        {"tool": "count_orders", "args": {}},
        prior=prior,
        classification="FOLLOW_UP",
    )
    assert r["args"]["date_token"] == "this_month"  # overlaid
    assert r["args"]["city"] == "sao paulo"
    assert r["args"]["status"] == "delivered"


def test_resolve_followup_multiple_overlays():
    """A turn can overlay more than one dim (e.g. city + date)."""
    prior = {
        "operation": "count_low_reviews",
        "args": {"date_token": "last_month", "score_max": 2},
    }
    r = resolve(
        "and how many in campinas last week?",
        {"tool": "count_orders", "args": {}},
        prior=prior,
        classification="FOLLOW_UP",
    )
    assert r["operation"] == "count_low_reviews"
    assert r["args"]["city"] == "campinas"
    assert r["args"]["date_token"] == "last_week"
    assert r["args"]["score_max"] == 2  # carried


# --- resolution: reset words -------------------------------------------------

def test_resolve_reset_drops_filters_keeps_op():
    prior = {
        "operation": "count_orders",
        "args": {"city": "sao paulo", "status": "delivered", "date_token": "last_month"},
    }
    r = resolve(
        "show me all",
        {"tool": "count_orders", "args": {}},
        prior=prior,
        classification="FOLLOW_UP",
    )
    assert r["operation"] == "count_orders"
    assert r["args"] == {}  # all filters dropped
    assert r["context"]["inherited"] is True
    assert r["context"]["carried"] == {}


# --- resolution: clarify paths -----------------------------------------------

def test_resolve_unfilterable_place_triggers_clarify():
    """Inherited top_products + 'for Rio' → top_products has no city → clarify."""
    prior = {
        "operation": "top_products",
        "args": {"by": "count", "limit": 10},
    }
    r = resolve(
        "and how many for Rio de Janeiro?",
        {"tool": "top_products", "args": {}},
        prior=prior,
        classification="FOLLOW_UP",
    )
    assert r["operation"] is None
    assert r["context"]["inherited"] is True
    assert r["context"]["from_operation"] == "top_products"
    assert r["context"]["clarify"] is not None
    assert "city" in r["context"]["clarify"]["prompt"]


def test_resolve_unfilterable_status_triggers_clarify():
    """Inherited top_products + 'canceled ones?' → no status param → clarify."""
    prior = {
        "operation": "top_products",
        "args": {"by": "count", "limit": 10},
    }
    r = resolve(
        "and the canceled ones?",
        {"tool": "top_products", "args": {}},
        prior=prior,
        classification="FOLLOW_UP",
    )
    assert r["operation"] is None
    assert r["context"]["clarify"] is not None
    assert "status" in r["context"]["clarify"]["prompt"]


# --- storage discipline ------------------------------------------------------

def test_get_prior_state_empty_session():
    assert get_prior_state("never-seen") is None


def test_store_and_get_state_round_trip():
    sid = "test-session-1"
    try:
        store_state(sid, "count_orders", {"city": "sao paulo", "date_token": "last_month"})
        prior = get_prior_state(sid)
        assert prior is not None
        assert prior["operation"] == "count_orders"
        assert prior["args"] == {"city": "sao paulo", "date_token": "last_month"}
    finally:
        clear_session(sid)


def test_clear_session_removes_state():
    sid = "test-session-2"
    store_state(sid, "count_orders", {"city": "sao paulo"})
    assert get_prior_state(sid) is not None
    clear_session(sid)
    assert get_prior_state(sid) is None


def test_get_prior_state_isolates_caller_from_store():
    """get_prior_state must return a copy, not a live reference to the cache."""
    sid = "test-session-3"
    try:
        store_state(sid, "count_orders", {"city": "sao paulo"})
        prior = get_prior_state(sid)
        prior["args"]["city"] = "tampered"
        # Re-read: the stored state must be unaffected.
        prior2 = get_prior_state(sid)
        assert prior2["args"]["city"] == "sao paulo"
    finally:
        clear_session(sid)


# --- dispatch-safety invariant -----------------------------------------------

def test_followup_carried_args_are_valid_kwargs():
    """Every key in the resolved args must be a real parameter of the inherited
    tool, so re-dispatching a carried follow-up can never raise TypeError.

    This is the invariant that the live two-turn path violated when the
    orchestrator stored result.filters (date_range) instead of input args
    (date_token). Even given a wrongly-shaped prior, resolve() must not leak a
    non-kwarg through to dispatch.
    """
    # Deliberately feed a wrongly-shaped prior (resolved date_range, as the old
    # orchestrator would have stored) to prove the defense-in-depth holds.
    prior = {
        "operation": "count_low_reviews",
        "args": {"date_range": ["2018-07-01T00:00:00", "2018-07-31T23:59:59"], "score_max": 2},
    }
    r = resolve(
        "and how many for Rio de Janeiro?",
        {"tool": "count_orders", "args": {}},
        prior=prior,
        classification="FOLLOW_UP",
    )
    supported = _supported_params_for(r["operation"])
    leaked = set(r["args"]) - supported
    assert not leaked, f"carried args not accepted by {r['operation']}: {leaked}"


# --- end-to-end two-turn replay (the B0 exit check) --------------------------

def test_two_turn_rio_replay():
    """Reproduce the plan's exit check: 'low reviews last month?' then
    'and how many for Rio de Janeiro?' → second answer is count_low_reviews
    with city=rio de janeiro, date_token=last_month, context.inherited=true."""
    sid = "rio-test"
    try:
        # Turn 1: fresh
        candidate1 = {
            "tool": "count_low_reviews",
            "args": {"date_token": "last_month", "score_max": 2},
        }
        r1 = resolve(
            "How many low reviews last month?",
            candidate1,
            prior=None,
            classification="FRESH",
        )
        assert r1["operation"] == "count_low_reviews"
        assert r1["args"]["date_token"] == "last_month"
        # Persist (the orchestrator does this on success).
        store_state(sid, r1["operation"], {"date_token": "last_month", "score_max": 2})

        # Turn 2: follow-up, prior state is now present
        prior = get_prior_state(sid)
        assert prior is not None
        r2 = resolve(
            "and how many for Rio de Janeiro?",
            {"tool": "count_orders", "args": {}},  # model picked the wrong tool
            prior=prior,
            classification="FOLLOW_UP",
        )
        assert r2["operation"] == "count_low_reviews", \
            "must inherit count_low_reviews, not the model's wrong pick"
        assert r2["args"]["city"] == "rio de janeiro"
        assert r2["args"]["date_token"] == "last_month"
        assert r2["args"]["score_max"] == 2
        assert r2["context"]["inherited"] is True
        assert r2["context"]["from_operation"] == "count_low_reviews"
        assert r2["context"]["carried"]["date_token"] == "last_month"
    finally:
        clear_session(sid)
