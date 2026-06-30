"""B0 — Conversational resolution (deterministic, backend-owned).

Why this exists
---------------
The live defect is *"and how many for Rio de Janeiro?"* returning the
all-time order count instead of inheriting the previous turn's
`count_low_reviews` + `last_month` and overlaying `city=rio de janeiro`.
Small models will happily route a follow-up to whatever tool feels closest
and silently drop the inheritance — a confidently-wrong answer.

This module is the deterministic, backend-owned fix:

  1. **Storage** — a TTL'd, bounded in-memory map `session_id →
     ConversationState` (reuses `cache.TTLCache` so the eviction + LRU +
     thread-safety story stays in one place). B4 swaps this for the
     persisted `messages.resolved_call` row in SQLite; the shape is
     identical so the swap is local.

  2. **Classification** — `classify_turn` decides FRESH vs FOLLOW-UP
     deterministically (connector + no-measure-noun + filter-present).
     The model's tool choice is a tie-breaker signal, never the sole basis.

  3. **Resolution** — `resolve` takes the candidate `{operation, args}` and
     (if FOLLOW-UP) the prior state, and produces the final
     `{operation, args, context}`: either the merged call, or a fail-closed
     `clarify` payload when an inherited operation can't be safely applied.

  4. **Gating** — every overlay dimension is checked against the inherited
     tool's supported params. `top_products` + "for Rio" → clarify, not a
     silent drop, because the inherited tool can't filter by city.

  5. **Storage discipline** — only *successful* turns are stored. An errored
     or declined turn never overwrites the prior state. A clarify turn
     also does not overwrite state (nothing was resolved).
"""
from typing import Optional
import copy

from cache import TTLCache
from config import settings
from validation.detectors import (
    detect_state,
    detect_date,
    detect_city,
    detect_status,
    detect_category,
    starts_with_followup_connector,
    contains_measure_noun,
    contains_reset_word,
    contains_any_filter_token,
    get_known_cities,
    get_known_categories,
)


# --- Storage -----------------------------------------------------------------

# ConversationState: {operation: str, args: dict, at: float}
_context_store: Optional[TTLCache] = None


def _get_store() -> TTLCache:
    global _context_store
    if _context_store is None:
        _context_store = TTLCache(
            max_entries=settings.context_max_entries,
            default_ttl=settings.context_ttl_minutes * 60,
        )
    return _context_store


def get_prior_state(session_id: Optional[str]) -> Optional[dict]:
    """Return the prior ConversationState for this session, or None."""
    if not session_id:
        return None
    state = _get_store().get(session_id)
    if state is None:
        return None
    return copy.deepcopy(state)


def store_state(session_id: Optional[str], operation: str, args: dict) -> None:
    """Persist a successful turn's resolved call for future follow-ups.

    Only successful turns are stored (the orchestrator decides not to call
    this on errors/clarifies). Bounded by the TTLCache's TTL and LRU.
    """
    if not session_id:
        return
    _get_store().set(
        session_id,
        {"operation": operation, "args": dict(args or {})},
    )


def clear_session(session_id: Optional[str]) -> None:
    """Drop a session's state (used by tests, and by future logout)."""
    if not session_id:
        return
    _get_store().delete(session_id)


# --- Classification ----------------------------------------------------------

def classify_turn(
    question: str,
    model_says_tool: Optional[str],
) -> str:
    """Return 'FRESH' or 'FOLLOW_UP'.

    Deterministic and unit-tested. The model's tool choice is a tie-breaker
    signal: a model that picked the SAME tool as the prior turn makes a
    follow-up more likely; a model that picked a different tool makes a
    fresh turn more likely. But the textual rules (connector, no measure
    noun, filter present) are the primary basis.

    The plan's rule is: FOLLOW_UP iff (connector or filter-only) AND
    no measure noun AND filter present. Reset words are an additional
    follow-up signal regardless of measure noun presence, because they
    express scope-reset intent (drop inherited filters, keep operation).
    """
    q = question.strip()
    if not q:
        return "FOLLOW_UP"  # empty → can't be a fresh, self-contained question

    has_connector = starts_with_followup_connector(q)
    has_measure = contains_measure_noun(q)
    has_filter = contains_any_filter_token(
        q, get_known_cities(), get_known_categories()
    )
    has_reset = contains_reset_word(q)

    # Reset words: the user is signalling a scope reset. Strong follow-up
    # signal regardless of measure noun — "overall revenue" inherits the
    # prior op and drops the prior filters.
    if has_reset:
        return "FOLLOW_UP"

    # Connector + filter + no measure noun → classic follow-up.
    if has_connector and not has_measure and has_filter:
        return "FOLLOW_UP"

    # No connector, no measure noun, has filter → filter-only fragment
    # ("for Rio?", "in SP?") — classic follow-up shape.
    if not has_connector and not has_measure and has_filter:
        return "FOLLOW_UP"

    # Otherwise: fresh. This includes:
    #   - self-contained questions ("how many orders...")
    #   - "and revenue last year?" (connector + measure noun → fresh)
    #   - "and for SP?" with no other signal handled above
    return "FRESH"


# --- Resolution --------------------------------------------------------------

# The dimensions a follow-up can overlay. Each is gated on whether the
# inherited tool supports it (see resolve()).
OVERLAY_DIMS = ("city", "state", "date_token", "status", "category")


def _detect_overlay_values(question: str) -> dict:
    """Return a dict of any overlay values detected in the question."""
    out: dict = {}
    s = detect_state(question)
    if s:
        out["state"] = s
    d = detect_date(question)
    if d is not None:
        out["date_token"] = d
    c = detect_city(question)
    if c:
        out["city"] = c
    st = detect_status(question)
    if st:
        out["status"] = st
    cat = detect_category(question)
    if cat:
        out["category"] = cat
    return out


def _supported_params_for(tool_name: str) -> set:
    """Return the set of param names the given tool accepts."""
    from functions.registry import get_function

    try:
        schema = get_function(tool_name)["schema"]
    except KeyError:
        return set()
    return set(schema.get("parameters", {}).get("properties", {}).keys())


def resolve(
    question: str,
    candidate: dict,
    prior: Optional[dict],
    classification: str,
) -> dict:
    """Apply the resolution algorithm to produce a final call.

    Inputs:
      question:      the raw user text
      candidate:     the model's tool call: {tool: str, args: dict}
      prior:         the prior ConversationState, or None
      classification: 'FRESH' or 'FOLLOW_UP'

    Returns:
      {
        "operation":   str | None,    # final tool to dispatch
        "args":        dict,          # final args
        "context":     {
            "inherited": bool,
            "from_operation": str | None,
            "carried": dict,         # filters carried from prior (only for FOLLOW_UP)
            "clarify":  dict | None, # {prompt, options} if declining
        }
      }
    """
    if classification == "FRESH" or prior is None:
        return {
            "operation": candidate.get("tool"),
            "args": dict(candidate.get("args") or {}),
            "context": {
                "inherited": False,
                "from_operation": None,
                "carried": {},
                "clarify": None,
            },
        }

    # FOLLOW_UP with prior state: start from prior, overlay only what the
    # new turn specifies.
    prior_op = prior["operation"]
    prior_args = dict(prior.get("args") or {})
    supported = _supported_params_for(prior_op)
    if not supported:
        # The prior tool is no longer registered (defensive) — treat as fresh.
        return {
            "operation": candidate.get("tool"),
            "args": dict(candidate.get("args") or {}),
            "context": {
                "inherited": False,
                "from_operation": None,
                "carried": {},
                "clarify": None,
            },
        }

    # Build the overlay. Reset words → drop filters (keep operation).
    is_reset = contains_reset_word(question)
    if is_reset:
        overlay: dict = {}
        carried: dict = {}  # nothing carried on a reset
    else:
        detected = _detect_overlay_values(question)
        overlay = {k: v for k, v in detected.items() if k in supported}
        # carried = filters the user did NOT name this turn; these are the
        # ones we're inheriting from the prior state. Restricted to params the
        # inherited tool actually accepts — defense-in-depth so a wrongly-shaped
        # stored state (e.g. a resolved date_range instead of a date_token)
        # can never leak through as a non-kwarg and crash dispatch.
        carried = {
            k: v for k, v in prior_args.items()
            if k not in overlay and k in supported
        }

    # Gate: if the user named a filter the inherited tool can't accept,
    # clarify (e.g. inherited `top_products` + "for Rio" → top_products
    # has no city param).
    if not is_reset:
        unfilterable = set(detected.keys()) - set(supported)
        if unfilterable:
            return {
                "operation": None,
                "args": {},
                "context": {
                    "inherited": True,
                    "from_operation": prior_op,
                    "carried": carried,
                    "clarify": {
                        "prompt": (
                            f"The previous answer was a {prior_op.replace('_', ' ')}. "
                            f"It can't be filtered by {', '.join(sorted(unfilterable))}. "
                            f"Try a different operation, or narrow the question."
                        ),
                        "options": [
                            f"{prior_op.replace('_', ' ')} without that filter",
                            "a different question",
                        ],
                    },
                },
            }

    # Final args = carried (prior filters not overlaid) + overlay (new ones).
    final_args = {**carried, **overlay}

    return {
        "operation": prior_op,
        "args": final_args,
        "context": {
            "inherited": True,
            "from_operation": prior_op,
            "carried": carried,
            "clarify": None,
        },
    }
