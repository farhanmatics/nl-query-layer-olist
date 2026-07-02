"""Phase 1+ eval harness (meta-tool era + optional SQL escape).

Replays eval_set.json against the running backend and scores tool-selection +
filter faithfulness. Requires the backend (DashScope + Postgres) to be running.

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
# Floor for cloud LLM on meta-tools. Catches regressions; not a certification bar.
PASS_THRESHOLD = float(os.environ.get("EVAL_PASS_THRESHOLD", "0.85"))
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
        expected_op = case.get("expected_operation")
        actual_op = response.get("operation")
        if expected_op and actual_op and actual_op != expected_op:
            return False, f"errored but routed to {actual_op!r}, expected {expected_op!r}"
        return True, "error as expected"

    if response.get("error"):
        return False, f"unexpected error: {response['error']}"

    expected_meta = case.get("expected_meta_operation")
    if expected_meta is not None:
        meta_op = response.get("meta_operation")
        if meta_op != expected_meta:
            return False, (
                f"meta_operation {meta_op!r} != expected {expected_meta!r}"
            )

    op = response.get("operation")
    acceptable = case.get("acceptable_operations") or []
    expected_op = case["expected_operation"]
    if op != expected_op and op not in acceptable:
        return False, f"operation {op!r} != expected {expected_op!r}"

    expected_filters = case.get("expected_filters", {})
    alt_filters = case.get("acceptable_filters") or []
    actual_filters = response.get("filters") or {}
    if _filters_match(expected_filters, actual_filters):
        return True, "ok"
    for alt in alt_filters:
        if _filters_match(alt, actual_filters):
            return True, "ok"
    return False, f"filters {actual_filters} !⊇ {expected_filters}"


def fetch_server_flags() -> dict:
    try:
        with httpx.Client(timeout=5.0) as client:
            r = client.get(f"{API_URL}/api/health")
            if r.status_code == 200:
                return r.json()
    except Exception:
        pass
    return {}


def backend_reachable() -> bool:
    flags = fetch_server_flags()
    return flags.get("db") == "ok"


def _should_skip_case(case: dict, flags: dict) -> tuple:
    """Return (skip: bool, reason: str)."""
    if case.get("requires_meta_tools") and flags.get("meta_tools") != "enabled":
        return True, "meta_tools disabled on server"
    if case.get("requires_sql_escape") and flags.get("sql_escape") != "enabled":
        return True, "sql_escape disabled on server"
    return False, ""


def run_eval(progress: bool = False) -> tuple:
    cases = load_cases()
    flags = fetch_server_flags()
    results = []
    skipped = 0
    with httpx.Client(timeout=REQUEST_TIMEOUT) as client:
        for i, case in enumerate(cases, 1):
            skip, skip_reason = _should_skip_case(case, flags)
            if skip:
                skipped += 1
                if progress:
                    print(
                        f"[SKIP] {i}/{len(cases)} {case['id']}: {skip_reason}",
                        flush=True,
                    )
                continue
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
    return results, skipped


def test_eval_pass_rate():
    """Pytest entry point: assert the eval pass rate meets the threshold."""
    import pytest

    if not backend_reachable():
        pytest.skip(f"Backend not reachable at {API_URL}; start it before running eval")

    results, skipped = run_eval()
    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)
    rate = passed / total if total else 0.0

    failures = [
        f"  [{c['id']}] {c['question']!r} -> {reason}"
        for c, ok, reason in results
        if not ok
    ]
    msg = (
        f"Eval pass rate {passed}/{total} = {rate:.0%} "
        f"(threshold {PASS_THRESHOLD:.0%}, skipped {skipped})"
    )
    if failures:
        msg += "\nFailures:\n" + "\n".join(failures)
    assert rate >= PASS_THRESHOLD, msg


if __name__ == "__main__":
    if not backend_reachable():
        print(f"Backend not reachable at {API_URL}. Start it first.")
        raise SystemExit(1)

    flags = fetch_server_flags()
    print(
        f"Server: meta_tools={flags.get('meta_tools', '?')}, "
        f"sql_escape={flags.get('sql_escape', '?')}"
    )
    results, skipped = run_eval(progress=True)
    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)
    print(f"\n{'=' * 64}")
    print(
        f"EVAL RESULTS — {passed}/{total} passed ({passed / total:.0%}) "
        f"[{skipped} skipped]"
    )
    print("=" * 64)
    for case, ok, reason in results:
        mark = "PASS" if ok else "FAIL"
        line = f"[{mark}] {case['id']}: {case['question']}"
        if not ok:
            line += f"\n        -> {reason}"
        print(line)
    print("=" * 64)
    print(
        f"Threshold: {PASS_THRESHOLD:.0%} — "
        f"{'MET' if passed / total >= PASS_THRESHOLD else 'NOT MET'}"
    )
