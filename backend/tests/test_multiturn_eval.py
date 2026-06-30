"""Multi-turn conversational eval (B4).

Replays multiturn_eval_set.json against the running backend. Unlike the
single-shot eval (test_eval.py), each conversation is replayed against ONE
*durable* server session — the authenticated path that persists each turn's
resolved_call and inherits it on the follow-up. This is the path that had the
"date silently dropped on follow-up" bug, so this is where B4 gets locked.

Two invariant classes:
  - Scored (vs PASS_THRESHOLD): operation + filter-subset match. The 2B dev
    model has some tool-selection variance, so we score these.
  - HARD (always fail): `forbid_count` (a confidently-wrong all-time number
    must never surface) and `expect_clarify` (the resolver must decline rather
    than answer when an inherited op can't apply a new filter). These encode
    the faithfulness guarantees and must not regress.

Run standalone (prints a report):
    cd backend && ../venv/bin/python tests/test_multiturn_eval.py

Run under pytest (skips if backend down; fails on regression):
    cd backend && ../venv/bin/python -m pytest tests/test_multiturn_eval.py -v

Override the target with API_URL.
"""
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402

from main import _filters_match  # noqa: E402

API_URL = os.environ.get("API_URL", "http://localhost:8000")
EVAL_FILE = Path(__file__).resolve().parent / "multiturn_eval_set.json"
PASS_THRESHOLD = 0.80  # scored turns; HARD invariants are separate and absolute
REQUEST_TIMEOUT = 120.0
PASSWORD = "correct horse battery staple"


def load_conversations() -> list:
    return json.loads(EVAL_FILE.read_text())["conversations"]


def backend_reachable() -> bool:
    try:
        with httpx.Client(timeout=5.0) as client:
            return client.get(f"{API_URL}/api/health").status_code == 200
    except Exception:
        return False


def _auth_client() -> httpx.Client:
    """Register a fresh user and return a cookie-bearing client. httpx.Client
    persists cookies (session + csrf) across requests automatically."""
    client = httpx.Client(base_url=API_URL, timeout=REQUEST_TIMEOUT)
    email = f"mt_eval_{int(time.time() * 1000)}@example.com"
    client.get("/api/auth/csrf")
    csrf = client.cookies.get("nlq_csrf")
    r = _post_with_retry(
        client,
        "/api/auth/register",
        json={"email": email, "password": PASSWORD},
        headers={"X-CSRF-Token": csrf},
    )
    r.raise_for_status()
    return client


def _post_with_retry(client: httpx.Client, path: str, *, json: dict, headers: dict = None,
                     attempts: int = 4) -> httpx.Response:
    """POST that tolerates the global per-IP rate limiter (HTTP 429). The live
    eval fires many requests in a burst; a transient 429 should back off and
    retry, not fail the suite."""
    delay = 2.0
    for i in range(attempts):
        r = client.post(path, json=json, headers=headers or {})
        if r.status_code != 429:
            return r
        if i < attempts - 1:
            time.sleep(delay)
            delay *= 2
    return r


def _new_session(client: httpx.Client) -> str:
    csrf = client.cookies.get("nlq_csrf")
    r = _post_with_retry(client, "/api/sessions", json={}, headers={"X-CSRF-Token": csrf})
    r.raise_for_status()
    return r.json()["id"]


def _evaluate_turn(turn: dict, response: dict) -> tuple:
    """Return (passed, hard_failed, reason). `passed` counts toward the
    threshold; `hard_failed` is an absolute regression that fails the suite."""
    context = response.get("context") or {}

    # --- HARD: clarify expected -------------------------------------------
    if turn.get("expect_clarify"):
        if context.get("clarify"):
            return True, False, "clarified as expected"
        return False, True, (
            f"expected a clarify prompt, got operation={response.get('operation')!r} "
            f"answer={response.get('formatted_answer')!r}"
        )

    # An unexpected clarify on a turn that should have answered is a miss.
    if context.get("clarify"):
        return False, False, f"unexpected clarify: {context['clarify'].get('prompt')!r}"

    if response.get("error"):
        return False, False, f"unexpected error: {response['error']}"

    # --- HARD: forbidden (confidently-wrong) result count -----------------
    forbid = turn.get("forbid_count") or []
    result = response.get("result") or {}
    count = result.get("count")
    if forbid and count in forbid:
        return False, True, (
            f"FORBIDDEN count {count} surfaced — the inherited filter was dropped "
            f"(operation={response.get('operation')!r})"
        )

    # --- Scored: operation -------------------------------------------------
    expected_op = turn.get("expected_operation")
    actual_op = response.get("operation")
    if expected_op and actual_op != expected_op:
        return False, False, f"operation {actual_op!r} != expected {expected_op!r}"

    # --- Scored: filter subset --------------------------------------------
    if not _filters_match(turn.get("expected_filters", {}), response.get("filters")):
        return False, False, (
            f"filters {response.get('filters')} !⊇ {turn.get('expected_filters')}"
        )

    # --- Scored: conversational inheritance -------------------------------
    if "expect_inherited" in turn:
        if bool(context.get("inherited")) != bool(turn["expect_inherited"]):
            return False, False, (
                f"context.inherited={context.get('inherited')} != "
                f"expected {turn['expect_inherited']}"
            )

    carried = context.get("carried") or {}
    for slot in turn.get("expect_carried", []):
        if slot not in carried:
            return False, False, f"expected {slot!r} in carried, got {list(carried.keys())}"

    return True, False, "ok"


def run_eval(progress: bool = False) -> tuple:
    """Replay every conversation on its own durable session.

    Returns (results, hard_failures) where results is a list of
    (conversation_id, turn_index, passed, reason) and hard_failures is a list
    of human-readable absolute regressions.
    """
    conversations = load_conversations()
    results = []
    hard_failures = []
    client = _auth_client()
    try:
        for convo in conversations:
            sid = _new_session(client)
            for i, turn in enumerate(convo["turns"], 1):
                try:
                    r = _post_with_retry(
                        client,
                        "/api/query",
                        json={"question": turn["question"], "session_id": sid},
                    )
                    r.raise_for_status()
                    response = r.json()
                    passed, hard, reason = _evaluate_turn(turn, response)
                except Exception as e:
                    passed, hard, reason = False, False, f"request failed: {e!r}"
                results.append((convo["id"], i, passed, reason))
                if hard:
                    hard_failures.append(f"[{convo['id']} turn {i}] {reason}")
                if progress:
                    mark = "HARD-FAIL" if hard else ("PASS" if passed else "FAIL")
                    line = f"[{mark}] {convo['id']} turn {i}: {turn['question']}"
                    if not passed:
                        line += f"  -> {reason}"
                    print(line, flush=True)
    finally:
        client.close()
    return results, hard_failures


def test_multiturn_eval():
    """Pytest entry point: scored pass rate must meet the threshold AND there
    must be zero hard failures (forbidden counts / missing clarifies)."""
    import pytest

    if not backend_reachable():
        pytest.skip(f"Backend not reachable at {API_URL}; start it before running eval")

    results, hard_failures = run_eval()
    passed = sum(1 for _, _, ok, _ in results if ok)
    total = len(results)
    rate = passed / total if total else 0.0

    failures = [
        f"  [{cid} turn {i}] -> {reason}"
        for cid, i, ok, reason in results
        if not ok
    ]

    assert not hard_failures, (
        "HARD faithfulness regression(s):\n" + "\n".join(hard_failures)
    )

    msg = f"Multi-turn pass rate {passed}/{total} = {rate:.0%} (threshold {PASS_THRESHOLD:.0%})"
    if failures:
        msg += "\nFailures:\n" + "\n".join(failures)
    assert rate >= PASS_THRESHOLD, msg


if __name__ == "__main__":
    if not backend_reachable():
        print(f"Backend not reachable at {API_URL}. Start it first.")
        raise SystemExit(1)

    results, hard_failures = run_eval(progress=True)
    passed = sum(1 for _, _, ok, _ in results if ok)
    total = len(results)
    print(f"\n{'=' * 64}")
    print(f"MULTI-TURN EVAL — {passed}/{total} turns passed ({passed / total:.0%})")
    print("=" * 64)
    if hard_failures:
        print("HARD FAILURES (faithfulness regressions):")
        for h in hard_failures:
            print(f"  {h}")
        print("=" * 64)
    print(f"Scored threshold: {PASS_THRESHOLD:.0%} — "
          f"{'MET' if (passed / total) >= PASS_THRESHOLD else 'NOT MET'}")
    print(f"Hard invariants: {'CLEAN' if not hard_failures else 'VIOLATED'}")
    raise SystemExit(1 if (hard_failures or (passed / total) < PASS_THRESHOLD) else 0)
