"""Filter-faithfulness guard (backend-owned, deterministic).

Why this exists
---------------
The model translates a question into a tool call. Small models (our 2B dev model)
are brittle: they reliably capture a filter only when the phrasing closely matches
a memorised few-shot. So "Total revenue in MG last year" keeps state=MG, but
"Total revenue in RJ last year" silently drops it — and the backend then returns
the *national* total labelled as if it answered the question. That confidently
wrong number is exactly the failure mode this product exists to prevent.

This guard is the deterministic safety net. After the model picks a tool, it
scans the ORIGINAL question for filter dimensions the tool supports (state, city,
date, status, category) that are clearly present in the text but absent from
the model's args. When it can extract the value unambiguously, it repairs the
args (the value then flows through the normal validators in each function).
When it detects a dimension but the chosen tool can't filter by it, it reports
it as `unresolved` so the orchestrator declines rather than answering with a
proxy.

It is intentionally high-precision: a false repair would *create* the very
failure mode we are guarding against, so every detector is conservative and gated
on whether the chosen tool even accepts that parameter. The detector
implementations live in `validation/detectors.py` (shared with the B0
conversational resolver) so the two can't drift.
"""
from validation.detectors import (
    detect_state,
    detect_date,
    detect_city,
    detect_status,
    detect_invalid_status_qualifier,
    detect_category,
    get_known_categories,
)


def _maybe_repair_or_flag(
    args: dict,
    repairs: dict,
    applied: list,
    unresolved: list,
    supported: set,
    key: str,
    value,
    label: str,
) -> None:
    """Add `key=value` to `args` if the tool supports it; flag as unresolved otherwise.

    Conservative: never repairs when the model already supplied the key.
    Never adds a key the tool doesn't accept (would silently filter on a
    parameter the function ignores — exactly the failure mode the guard exists
    to prevent).
    """
    if value is None or value == "" or value == []:
        return
    if key in supported:
        if not args.get(key):
            repairs[key] = value
            applied.append(f"{label}={value}")
    else:
        unresolved.append(f"{label} '{value}'")


def check_filter_faithfulness(
    question: str, supported_params: set, args: dict, known_cities: set
) -> dict:
    """Detect filters present in the question but missing from the model's args.

    Returns:
        {
            "repairs":    {param: value}   # safe to merge into args
            "applied":    [str, ...]       # human-readable notes (for auditing)
            "unresolved": [str, ...]       # detected but the tool can't filter
                                            # by it — caller must decline, not drop
        }
    Only dimensions the chosen tool actually accepts are considered for repair;
    unsupported ones are reported as unresolved so the orchestrator refuses.

    `known_cities` is the set of canonical city names to match against. The
    legacy signature takes it as an argument (for test isolation); at runtime
    the orchestrator passes the module-level set populated at startup. If the
    caller passes an empty set, we fall back to the module-level set so the
    startup-loaded cities are still used.
    """
    args = args or {}
    repairs: dict = {}
    applied: list = []
    unresolved: list = []

    # City source: prefer the caller's set if non-empty (test override or
    # explicit override), else fall back to the module-level set populated at
    # startup.
    cities = known_cities if known_cities else None

    _maybe_repair_or_flag(
        args, repairs, applied, unresolved, supported_params,
        "state", detect_state(question), "state",
    )
    _maybe_repair_or_flag(
        args, repairs, applied, unresolved, supported_params,
        "date_token", detect_date(question), "date",
    )
    # City detection always runs; detect_city falls back to the module-level
    # set populated at startup when `cities` is None.
    _maybe_repair_or_flag(
        args, repairs, applied, unresolved, supported_params,
        "city", detect_city(question, cities), "city",
    )
    _maybe_repair_or_flag(
        args, repairs, applied, unresolved, supported_params,
        "status", detect_status(question), "status",
    )
    _maybe_repair_or_flag(
        args, repairs, applied, unresolved, supported_params,
        "category", detect_category(question, get_known_categories() or None), "category",
    )

    # Status-shaped word the schema doesn't track → fail closed. Catches
    # "how many completed orders?" when the model omits status and would
    # otherwise return the whole-dataset count.
    if "status" in supported_params and not args.get("status"):
        invalid = detect_invalid_status_qualifier(question)
        if invalid:
            unresolved.append(f"status '{invalid}'")

    return {"repairs": repairs, "applied": applied, "unresolved": unresolved}
