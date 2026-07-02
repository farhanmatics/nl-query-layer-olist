"""Shared detector set for filter dimensions (state, city, date, status, category).

Single source of truth for both the filter-faithfulness guard
(`validation/faithfulness.py`) and the B0 conversational resolver
(`resolver.py`). Putting the detectors in one module means the two
consumers can't drift.

Schema-awareness:
  * `detect_state` reads its state-code set from the active config
    (Brazilian UFs for Olist, US states for Shopify, etc).
  * `detect_status` reads its allowed values from the active config
    enum.
  * City + category detectors use module-level sets populated at
    startup by the schema-specific loaders (which themselves read
    table/column names from the config).
"""
import re
import unicodedata
from typing import Optional

from schemas import get_active_config


# --- State (geographic codes from the active schema) ------------------------

_UF_TOKEN_RE = re.compile(r"\b[A-Z]{2}\b")


def _active_states() -> Optional[frozenset[str]]:
    """Return the active schema's geographic state codes, or None
    if the schema has no state dimension."""
    return get_active_config().states


def detect_state(question: str) -> Optional[str]:
    """Return a state code if one appears uppercase in the question.

    Matched only when it appears UPPERCASE — that uppercasing is what
    lets us safely treat ambiguous tokens like "TO"/"GO"/"AM"/"SE"
    as state codes rather than the English words "to"/"go"/"am"/"se".
    """
    states = _active_states()
    if not states:
        return None
    for tok in _UF_TOKEN_RE.findall(question):
        if tok in states:
            return tok
    return None


# --- Date (relative phrases + bare years) -----------------------------------

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

_YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")


def detect_date(question: str):
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


# --- City (loaded at startup by the active schema's loader) -----------------

_known_cities: set[str] = set()


def set_known_cities(cities: set[str]) -> None:
    """Inject the known-cities set (called once at startup by
    `validation.cities.load_known_cities`)."""
    global _known_cities
    _known_cities = set(cities)


def get_known_cities() -> set[str]:
    return _known_cities


def detect_city(question: str, known_cities: Optional[set] = None) -> Optional[str]:
    """Return a known city named in the question, or None.

    Conservative: matches 1–3 word windows, multi-word names or single
    words of length >= 6, prefers the longest match. If `known_cities`
    is not given, falls back to the module-level set populated at startup.
    """
    cities = known_cities if known_cities is not None else _known_cities
    if not cities:
        return None
    from validation.cities import normalize

    norm = normalize(question)
    words = re.findall(r"[a-z0-9]+", norm)
    best = None
    for n in (3, 2, 1):
        for i in range(len(words) - n + 1):
            cand = " ".join(words[i : i + n])
            if cand in cities and (n > 1 or len(cand) >= 6):
                if best is None or len(cand) > len(best):
                    best = cand
    return best


# --- Status (order_status enum from the active schema) ---------------------

_STATUS_RE: Optional[re.Pattern] = None

# Common user spellings that map to schema enum values (British → US, etc.).
_STATUS_ALIASES = {
    "cancelled": "canceled",
}


def _normalize_status_aliases(question: str) -> str:
    q = question.lower()
    for alias, canonical in _STATUS_ALIASES.items():
        q = re.sub(r"\b" + re.escape(alias) + r"\b", canonical, q)
    return q


def _build_status_pattern() -> re.Pattern:
    """Compile a regex over the active schema's allowed status values.

    If the schema marks status as freeform (None), we match any
    non-trivial word — but to keep the guard high-precision, the
    guard only acts on *known* statuses. Unknown freeform tokens are
    passed through to the function and validated there.
    """
    values = get_active_config().get_enum("status")
    if not values:
        # Freeform: no pattern (the guard should not auto-detect).
        return re.compile(r"(?!)")  # matches nothing
    alts = sorted(values, key=len, reverse=True)
    return re.compile(
        r"\b(" + "|".join(re.escape(s) for s in alts) + r")\b",
        re.IGNORECASE,
    )


def detect_status(question: str) -> Optional[str]:
    """Return a valid order_status if one appears in the question, else None."""
    global _STATUS_RE
    if _STATUS_RE is None:
        _STATUS_RE = _build_status_pattern()
    m = _STATUS_RE.search(_normalize_status_aliases(question))
    if m:
        return m.group(1).lower()
    return None


# High-precision lexicon of status-*shaped* words users ask about that are
# commonly NOT valid order_status values. Word-boundaried; any token that IS
# a valid enum for the active schema is skipped (detect_status handles those).
# Catches "how many completed orders?" → fail closed instead of returning the
# whole-dataset count with no status filter.
_STATUS_QUALIFIER_LEXICON = (
    "returned",
    "returns",
    "refund",
    "refunds",
    "refunded",
    "completed",
    "pending",
    "dispatched",
    "approved",
    "rejected",
    "failed",
    "finished",
    "closed",
)


def detect_invalid_status_qualifier(question: str) -> Optional[str]:
    """Return a status-like word in the question that is NOT a valid enum
    value for the active schema, or None."""
    if not question:
        return None
    valid = get_active_config().get_enum("status")
    if valid is None:
        return None
    q = question.lower()
    for word in _STATUS_QUALIFIER_LEXICON:
        if word in valid:
            continue
        if re.search(rf"\b{re.escape(word)}\b", q):
            return word
    return None


# --- Category (loaded at startup by the active schema's loader) ------------

_known_categories: set[str] = set()


def set_known_categories(categories: set[str]) -> None:
    """Inject the known-category set (called once at startup by
    `validation.categories.load_known_categories`)."""
    global _known_categories
    _known_categories = set(categories)


def get_known_categories() -> set[str]:
    return _known_categories


def detect_category(question: str, known_categories: Optional[set] = None) -> Optional[str]:
    """Return a known category named in the question, or None.

    Conservative: matches 1–3 word windows, multi-word names or single
    words of length >= 6, prefers the longest match. The category name
    may appear with underscores ("health_beauty") or spaces ("health
    beauty") — we normalize underscores to spaces at the question level.
    """
    cats = known_categories if known_categories is not None else _known_categories
    if not cats:
        return None

    s = question.lower().replace("_", " ")
    nfkd = unicodedata.normalize("NFKD", s)
    norm = "".join(c for c in nfkd if unicodedata.category(c) != "Mn")
    words = re.findall(r"[a-z0-9]+", norm)

    best = None
    for n in (3, 2, 1):
        for i in range(len(words) - n + 1):
            cand = " ".join(words[i : i + n])
            if cand in cats and (n > 1 or len(cand) >= 6):
                if best is None or len(cand) > len(best):
                    best = cand
    return best


# --- Connector / deixis (for follow-up classification) --------------------

# These are domain-generic (English discourse markers), not schema-specific.
_FOLLOWUP_CONNECTORS = (
    "and ",
    "also ",
    "what about ",
    "how about ",
    "about those ",
    "about these ",
    "of those ",
    "for those ",
    "& ",
    "but ",
)

RESET_WORDS = frozenset({"total", "overall", "all", "everything", "in total"})

MEASURE_NOUNS = frozenset({
    "review", "reviews",
    "order", "orders",
    "revenue", "sales",
    "product", "products",
    "status",
})


# Deictic references back to the prior turn ("those orders", "these ones").
_DEIXIS_RE = re.compile(r"\b(those|these|them|the same)\b", re.IGNORECASE)


def contains_deixis_reference(question: str) -> bool:
    """True when the user refers back to a prior result set (those/these/them)."""
    return bool(_DEIXIS_RE.search(question))


def starts_with_followup_connector(question: str) -> bool:
    q = question.lstrip().lower()
    return q.startswith(_FOLLOWUP_CONNECTORS)


def contains_measure_noun(question: str) -> bool:
    q = question.lower()
    for noun in MEASURE_NOUNS:
        if re.search(r"\b" + re.escape(noun) + r"\b", q):
            return True
    return False


def contains_reset_word(question: str) -> bool:
    q = question.lower()
    for word in RESET_WORDS:
        if re.search(r"\b" + re.escape(word) + r"\b", q):
            return True
    return False


def contains_any_filter_token(
    question: str,
    known_cities: set,
    known_categories: set,
) -> bool:
    if detect_state(question):
        return True
    if detect_date(question) is not None:
        return True
    if detect_status(question):
        return True
    if known_cities and detect_city(question, known_cities):
        return True
    if known_categories and detect_category(question, known_categories):
        return True
    return False
