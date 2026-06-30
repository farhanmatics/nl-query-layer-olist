"""Out-of-scope concept guard (backend-owned, deterministic, schema-aware).

The out-of-scope lexicon is a property of the schema, not the codebase.
Olist has no returns → decline "returns" with a redirect to canceled
orders. Shopify tracks returns → no decline. Adding a new schema is
a config change, not a code change.

The detector walks the schema's `scope` patterns in order; the first
match declines. Patterns are word-boundaried and high-precision so
legitimate questions ("returning customers", "delivered orders") are
not caught.
"""
import re
from typing import Optional

from schemas import get_active_config


def detect_unsupported_concept(question: str) -> Optional[dict]:
    """Return {'concept', 'suggestion'} if the question targets a concept
    the active schema cannot answer, else None."""
    if not question:
        return None
    cfg = get_active_config()
    for entry in cfg.scope:
        if re.search(entry.pattern, question, re.IGNORECASE):
            return {"concept": entry.concept, "suggestion": entry.suggestion}
    return None
