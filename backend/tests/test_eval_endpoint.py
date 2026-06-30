"""Tests for the /api/eval endpoint and filter matching logic.

The _filters_match helper is tested offline (pure Python). The full endpoint
integration test requires the backend to be running. Run:

    cd backend && ../venv/bin/python -m pytest tests/test_eval_endpoint.py -v
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from main import _filters_match  # noqa: E402


def test_filters_match_exact():
    assert _filters_match({"city": "sao paulo"}, {"city": "sao paulo"}) is True
    assert _filters_match({"city": "sao paulo"}, {"city": "rio"}) is False


def test_filters_match_wildcard():
    assert _filters_match({"date_range": "*"}, {"date_range": ["2018-01-01", "2018-12-31"]}) is True
    assert _filters_match({"date_range": "*"}, {"date_range": None}) is False
    assert _filters_match({"date_range": "*"}, {}) is False


def test_filters_match_empty_expected():
    assert _filters_match({}, {"city": "sao paulo"}) is True
    assert _filters_match({}, {}) is True


def test_filters_match_multiple():
    expected = {"city": "sao paulo", "status": "delivered", "date_range": "*"}
    actual = {"city": "sao paulo", "status": "delivered", "date_range": ["2018-01-01", "2018-12-31"]}
    assert _filters_match(expected, actual) is True


def test_filters_match_partial_actual():
    """Actual can have extra keys — we only check expected is a subset."""
    expected = {"status": "delivered"}
    actual = {"status": "delivered", "city": "sao paulo", "date_range": ["a", "b"]}
    assert _filters_match(expected, actual) is True


def test_filters_match_missing_key():
    assert _filters_match({"city": "sao paulo"}, {}) is False
    assert _filters_match({"city": "sao paulo"}, {"status": "delivered"}) is False


def test_filters_match_wildcard_rejects_empty_string():
    assert _filters_match({"city": "*"}, {"city": ""}) is False
    assert _filters_match({"city": "*"}, {"city": []}) is False
    assert _filters_match({"city": "*"}, {"city": {}}) is False


def test_filters_match_wildcard_accepts_nonempty():
    assert _filters_match({"city": "*"}, {"city": "sao paulo"}) is True
    assert _filters_match({"limit": "*"}, {"limit": 10}) is True
