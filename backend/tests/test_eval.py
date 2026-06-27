"""Phase 1 eval harness.

Replays eval_set.json against the running backend and scores tool-selection +
filter faithfulness. Requires the backend (and Ollama + Postgres) to be running.

Run standalone (prints a full report):
    cd backend && ../venv/bin/python tests/test_eval.py

Run under pytest (fails if pass rate < threshold):
    cd backend && ../venv/bin/python -m pytest tests/test_eval.py -v

Override the target with API_URL, e.g. API_URL=http://localhost:8000
"""
import json
import os
from pathlib import Path

import httpx

API_URL = os.environ.get("API_URL", "http://localhost:8000")
EVAL_FILE = Path(__file__).resolve().parent / "eval_set.json"
# Realistic floor for the 2B dev model (qwen3.5:2b) on CPU. Tool-selection is
# near-perfect; the residual gap is filter-faithfulness on multi-filter or
# ambiguous phrasings, which a larger model (e.g. qwen3.5:9b) closes. The eval's
# purpose is to catch regressions below this floor, not to certify the model.
PASS_THRESHOLD = 0.85
REQUEST_TIMEOUT = 120.0


def load_cases() -> list:
    data = json.loads(EVAL_FILE.read_text())
    return data["cases"]


def _filters_match(expected: dict, actual: dict) -> bool:
    actual = actual or {}
    for key, value in expected.items():
        if value == "*":
            if key not in actual or actual[key] in (None, "", [], {}):
                return False
        else:
            if actual.get(key) != value:
                return False
    return True


def evaluate_case(case: dict, response: dict) -> tuple:
    """Return (passed: bool, reason: str)."""
    if case.get("expected_error"):
        if not response.get("error"):
            return False, f"expected an error, got operation={response.get('operation')}"
        # If the case pins an operation, the error must still have routed correctly
        # (e.g. unknown order id should route to get_order_status, then 404).
        expected_op = case.get("expected_operation")
        actual_op = response.get("operation")
        if expected_op and actual_op and actual_op != expected_op:
            return False, f"errored but routed to {actual_op!r}, expected {expected_op!r}"
        return True, "error as expected"

    if response.get("error"):
        return False, f"unexpected error: {response['error']}"

    op = response.get("operation")
    if op != case["expected_operation"]:
        return False, f"operation {op!r} != expected {case['expected_operation']!r}"

    if not _filters_match(case.get("expected_filters", {}), response.get("filters")):
        return False, f"filters {response.get('filters')} !⊇ {case.get('expected_filters')}"

    return True, "ok"


def run_eval(progress: bool = False) -> tuple:
    cases = load_cases()
    results = []
    with httpx.Client(timeout=REQUEST_TIMEOUT) as client:
        for i, case in enumerate(cases, 1):
            try:
                r = client.post(
                    f"{API_URL}/api/query", json={"question": case["question"]}
                )
                r.raise_for_status()
                response = r.json()
                passed, reason = evaluate_case(case, response)
            except Exception as e:
                passed, reason = False, f"request failed: {e!r}"
            results.append((case, passed, reason))
            if progress:
                mark = "PASS" if passed else "FAIL"
                line = f"[{mark}] {i}/{len(cases)} {case['id']}: {case['question']}"
                if not passed:
                    line += f"  -> {reason}"
                print(line, flush=True)
    return results


def backend_reachable() -> bool:
    try:
        with httpx.Client(timeout=5.0) as client:
            return client.get(f"{API_URL}/api/health").status_code == 200
    except Exception:
        return False


def test_eval_pass_rate():
    """Pytest entry point: assert the eval pass rate meets the threshold."""
    import pytest

    if not backend_reachable():
        pytest.skip(f"Backend not reachable at {API_URL}; start it before running eval")

    results = run_eval()
    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)
    rate = passed / total if total else 0.0

    failures = [
        f"  [{c['id']}] {c['question']!r} -> {reason}"
        for c, ok, reason in results
        if not ok
    ]
    msg = f"Eval pass rate {passed}/{total} = {rate:.0%} (threshold {PASS_THRESHOLD:.0%})"
    if failures:
        msg += "\nFailures:\n" + "\n".join(failures)
    assert rate >= PASS_THRESHOLD, msg


if __name__ == "__main__":
    if not backend_reachable():
        print(f"Backend not reachable at {API_URL}. Start it first.")
        raise SystemExit(1)

    results = run_eval(progress=True)
    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)
    print(f"\n{'=' * 64}")
    print(f"EVAL RESULTS — {passed}/{total} passed ({passed / total:.0%})")
    print("=" * 64)
    for case, ok, reason in results:
        mark = "PASS" if ok else "FAIL"
        line = f"[{mark}] {case['id']}: {case['question']}"
        if not ok:
            line += f"\n        -> {reason}"
        print(line)
    print("=" * 64)
    print(f"Threshold: {PASS_THRESHOLD:.0%} — {'MET' if passed / total >= PASS_THRESHOLD else 'NOT MET'}")
