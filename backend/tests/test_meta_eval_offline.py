"""Offline eval for meta-tool → internal routing (no LLM, no HTTP).

Run:
    cd backend && ../venv/bin/python -m pytest tests/test_meta_eval_offline.py -v
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from meta_router import resolve_meta_call  # noqa: E402

EVAL_FILE = Path(__file__).resolve().parent / "meta_eval_set.json"


def load_cases():
    data = json.loads(EVAL_FILE.read_text())
    return data["cases"]


@pytest.mark.parametrize("case", load_cases(), ids=lambda c: c["id"])
def test_meta_route_case(case):
    tool, args = resolve_meta_call(
        case["meta_tool"],
        case.get("meta_args") or {},
        case["question"],
    )
    assert tool == case["expected_operation"], (
        f"{case['id']}: routed to {tool!r}, expected {case['expected_operation']!r}"
    )
    for key, value in (case.get("expected_filters") or {}).items():
        assert args.get(key) == value, f"{case['id']}: args[{key!r}]={args.get(key)!r} != {value!r}"


def test_meta_eval_set_has_minimum_coverage():
    cases = load_cases()
    ops = {c["expected_operation"] for c in cases}
    assert "count_products" in ops
    assert "top_products" in ops
    assert "get_revenue" in ops
    assert len(cases) >= 10
