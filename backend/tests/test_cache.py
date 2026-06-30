"""Offline unit tests for the Layer 1 translation cache key.

Pure Python — no DB, no LLM. These pin that the cache key is bound to the
served model, so a translation produced by one model can never be served for
another (a latent faithfulness/correctness bug). Run:

    cd backend && ../venv/bin/python -m pytest tests/test_cache.py -v
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cache import translation_key  # noqa: E402
from config import settings  # noqa: E402

QUESTION = "How many delivered orders in sao paulo last month?"
PROMPT = "SYSTEM PROMPT v1"


def test_model_changes_key():
    """Different models must produce different keys for identical question/prompt."""
    assert translation_key(QUESTION, PROMPT, model="a") != translation_key(
        QUESTION, PROMPT, model="b"
    )


def test_default_model_matches_settings():
    """Omitting model defaults to the served model from settings."""
    assert translation_key(QUESTION, PROMPT) == translation_key(
        QUESTION, PROMPT, model=settings.ollama_model
    )


def test_stable_for_identical_inputs():
    """Identical inputs (incl. model) yield a stable, repeatable key."""
    k1 = translation_key(QUESTION, PROMPT, model="granite4:3b")
    k2 = translation_key(QUESTION, PROMPT, model="granite4:3b")
    assert k1 == k2


def test_prompt_still_part_of_key():
    """A prompt change still invalidates the key (regression guard)."""
    assert translation_key(QUESTION, "PROMPT A", model="x") != translation_key(
        QUESTION, "PROMPT B", model="x"
    )
