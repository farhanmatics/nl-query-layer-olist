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
date) that are clearly present in the text but absent from the model's args. When
it can extract the value unambiguously, it repairs the args (the value then flows
through the normal validators in each function). When it detects a dimension but
cannot extract a safe value, it reports it as `unresolved` so the orchestrator
can ask the user instead of guessing.

It is intentionally high-precision: a false repair would *create* the very
failure mode we are guarding against, so every detector is conservative and gated
on whether the chosen tool even accepts that parameter.
"""
import re
from typing import Optional

# The 27 Brazilian federative units. Matched only when they appear UPPERCASE in
# the question (e.g. "SP", "RJ", "TO") — that uppercasing is what lets us safely
# treat ambiguous tokens like "TO"/"GO"/"AM"/"SE" as state codes rather than the
# English words "to"/"go"/"am"/"se".
BRAZIL_UF = {
    "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS",
    "MG", "PA", "PB", "PR", "PE", "PI", "RJ", "RN", "RO", "RR", "RS", "SC",
    "SP", "SE", "TO",
}

# Unambiguous relative-date phrases → the canonical token the date validator
# already understands. Longer phrases are checked first so "this month" is not
# shadowed by a hypothetical "month" rule.
_DATE_PHRASE_TOKENS = [
    ("yesterday", "yesterday"),
    ("today", "today"),
    ("last week", "last_week"),
    ("this week", "this_week"),
    ("last month", "last_month"),
    ("this month", "this_month"),
    ("last year", "last_year"),
    ("this year", "this_year"),
]

_UF_TOKEN_RE = re.compile(r"\b[A-Z]{2}\b")
_YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")


def _detect_state(question: str) -> Optional[str]:
    """Return a Brazilian UF code if one appears uppercase in the question."""
    for tok in _UF_TOKEN_RE.findall(question):
        if tok in BRAZIL_UF:
            return tok
    return None


def _detect_date(question: str):
    """Return a date value (token string or explicit {from,to} range) or None."""
    q = question.lower()
    for phrase, token in _DATE_PHRASE_TOKENS:
        if phrase in q:
            return token
    m = _YEAR_RE.search(question)
    if m:
        year = m.group(0)
        return {"from": f"{year}-01-01", "to": f"{year}-12-31"}
    return None


def _detect_city(question: str, known_cities: set) -> Optional[str]:
    """Return a known city named in the question, or None.

    Conservative: matches 1–3 word windows of the (accent-stripped, lowercased)
    question against the known-city set, accepts only multi-word names or single
    words of length >= 6, and prefers the longest match. This keeps short or
    common-word city names from triggering accidental repairs.
    """
    if not known_cities:
        return None
    # Local import avoids a cycle (cities.py would otherwise import this module's
    # consumers); normalize mirrors how the known set itself was built.
    from validation.cities import normalize

    norm = normalize(question)
    words = re.findall(r"[a-z0-9]+", norm)
    best = None
    for n in (3, 2, 1):
        for i in range(len(words) - n + 1):
            cand = " ".join(words[i : i + n])
            if cand in known_cities and (n > 1 or len(cand) >= 6):
                if best is None or len(cand) > len(best):
                    best = cand
    return best


def check_filter_faithfulness(
    question: str, supported_params: set, args: dict, known_cities: set
) -> dict:
    """Detect filters present in the question but missing from the model's args.

    Returns:
        {
            "repairs":    {param: value}   # safe to merge into args
            "applied":    [str, ...]       # human-readable notes (for auditing)
            "unresolved": [str, ...]       # detected but unsafe to auto-fill
        }
    Only dimensions the chosen tool actually accepts are considered.
    """
    args = args or {}
    repairs: dict = {}
    applied: list = []
    unresolved: list = []

    # Geography: if the question clearly names a place but the chosen tool can't
    # filter by that dimension, we must NOT answer (a place-less total dressed up
    # as a place-specific answer is the core failure mode). Repair when supported
    # and missing; flag as unresolved when unsupported so the caller declines.
    uf = _detect_state(question)
    if uf:
        if "state" in supported_params:
            if not args.get("state"):
                repairs["state"] = uf
                applied.append(f"state={uf}")
        else:
            unresolved.append(f"state '{uf}'")

    city = _detect_city(question, known_cities)
    if city:
        if "city" in supported_params:
            if not args.get("city"):
                repairs["city"] = city
                applied.append(f"city={city}")
        else:
            unresolved.append(f"city '{city}'")

    if "date_token" in supported_params and not args.get("date_token"):
        date_val = _detect_date(question)
        if date_val is not None:
            repairs["date_token"] = date_val
            applied.append(f"date={date_val if isinstance(date_val, str) else 'range'}")

    return {"repairs": repairs, "applied": applied, "unresolved": unresolved}
