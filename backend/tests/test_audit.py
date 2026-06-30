"""Offline unit tests for the per-request audit log.

Pure Python — no DB, no LLM, no network. These pin two contracts:
  1. ``summarize_result`` collapses row lists to counts and keeps scalars, so we
     never persist raw (possibly-PII) rows into the audit log.
  2. The audit logger writes one parseable JSON line per record to its file.

Run:
    cd backend && ../venv/bin/python -m pytest tests/test_audit.py -v
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from audit import summarize_result, build_record, AuditLogger  # noqa: E402


# --- summarize_result: lists collapse, scalars survive -----------------------

def test_summarize_none_passthrough():
    assert summarize_result(None) is None


def test_summarize_keeps_scalars():
    r = summarize_result({"count": 42, "order_status": "delivered"})
    assert r == {"count": 42, "order_status": "delivered"}


def test_summarize_collapses_list_to_count():
    r = summarize_result({"orders": [{"id": 1}, {"id": 2}, {"id": 3}]})
    assert r == {"orders_count": 3}
    assert "orders" not in r  # raw rows are gone


def test_summarize_mixed_scalars_and_lists():
    r = summarize_result(
        {
            "revenue": 1234.5,
            "group_by": "month",
            "breakdown": [1, 2, 3, 4],
            "products": [],
        }
    )
    assert r == {
        "revenue": 1234.5,
        "group_by": "month",
        "breakdown_count": 4,
        "products_count": 0,
    }


def test_summarize_keeps_nested_dict():
    # dict values are not rows; keep them verbatim.
    r = summarize_result({"by": {"SP": 10, "RJ": 5}})
    assert r == {"by": {"SP": 10, "RJ": 5}}


# --- build_record: shape + guard extraction ----------------------------------

def test_build_record_has_expected_keys():
    response = {
        "operation": "count_orders",
        "filters": {"state": "SP"},
        "result": {"count": 7, "orders": [1, 2]},
        "formatted_answer": "7 orders",
        "source": "olist_orders_dataset",
        "error": None,
        "cached": True,
        "guard": {"applied": ["state"], "unresolved": []},
    }
    rec = build_record("abc123", "How many in SP?", response, 55)
    assert set(rec.keys()) == {
        "timestamp",
        "request_id",
        "question",
        "operation",
        "filters",
        "result_summary",
        "source",
        "cached",
        "guard_applied",
        "error",
        "latency_ms",
        "user_id",
        "session_id",
    }
    assert rec["request_id"] == "abc123"
    assert rec["cached"] is True
    assert rec["guard_applied"] == ["state"]
    assert rec["result_summary"] == {"count": 7, "orders_count": 2}
    assert rec["latency_ms"] == 55
    assert rec["user_id"] is None
    assert rec["session_id"] is None


def test_build_record_passes_user_and_session():
    response = {"operation": "count_orders", "result": {"count": 1}}
    rec = build_record("x", "q", response, 10, user_id="u-1", session_id="s-1")
    assert rec["user_id"] == "u-1"
    assert rec["session_id"] == "s-1"


def test_build_record_handles_missing_guard_and_result():
    rec = build_record("x", "q", {"error": "boom"}, 3)
    assert rec["guard_applied"] == []
    assert rec["result_summary"] is None
    assert rec["error"] == "boom"
    assert rec["cached"] is False


# --- AuditLogger: writes one parseable JSON line -----------------------------

def test_logger_writes_parseable_jsonl(tmp_path):
    log_path = tmp_path / "audit.jsonl"
    al = AuditLogger(str(log_path))

    al.log({"request_id": "r1", "operation": "count_orders", "latency_ms": 10})
    al.log({"request_id": "r2", "operation": "get_revenue", "latency_ms": 20})

    lines = log_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2

    first = json.loads(lines[0])
    assert first["request_id"] == "r1"
    assert first["operation"] == "count_orders"
    assert first["latency_ms"] == 10

    second = json.loads(lines[1])
    assert second["request_id"] == "r2"


def test_logger_creates_missing_directory(tmp_path):
    log_path = tmp_path / "nested" / "deep" / "audit.jsonl"
    al = AuditLogger(str(log_path))
    al.log({"request_id": "r1"})
    assert log_path.exists()
    assert json.loads(log_path.read_text(encoding="utf-8").strip())["request_id"] == "r1"
