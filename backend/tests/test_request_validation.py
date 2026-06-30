"""Offline unit tests for request-size hardening.

Pure Python — no DB, no LLM. Pin that an oversized question is rejected by
pydantic (FastAPI maps this to HTTP 422) and a normal one is accepted. Run:

    cd backend && ../venv/bin/python -m pytest tests/test_request_validation.py -v
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pydantic import ValidationError  # noqa: E402

from config import settings  # noqa: E402
from main import QueryRequest  # noqa: E402


def test_over_length_question_rejected():
    too_long = "x" * (settings.max_question_length + 1)
    with pytest.raises(ValidationError):
        QueryRequest(question=too_long)


def test_empty_question_rejected():
    with pytest.raises(ValidationError):
        QueryRequest(question="")


def test_normal_question_accepted():
    req = QueryRequest(question="hi")
    assert req.question == "hi"


def test_max_length_boundary_accepted():
    at_limit = "x" * settings.max_question_length
    req = QueryRequest(question=at_limit)
    assert len(req.question) == settings.max_question_length
