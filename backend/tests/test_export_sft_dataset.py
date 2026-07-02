"""Tests for SFT dataset export."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from scripts.export_sft_dataset import (  # noqa: E402
    _internal_case_to_meta,
    collect_records,
    split_records,
    to_dashscope_record,
)
from orchestrator import build_meta_system_prompt  # noqa: E402
from meta_schemas import get_meta_tool_schemas  # noqa: E402


def test_internal_case_maps_count_orders():
    case = {
        "question": "How many delivered orders in Sao Paulo last month?",
        "expected_operation": "count_orders",
        "expected_filters": {"city": "sao paulo", "status": "delivered", "date_range": "*"},
    }
    meta = _internal_case_to_meta(case)
    assert meta is not None
    assert meta["tool"] == "count"
    assert meta["args"]["entity"] == "orders"
    assert meta["args"]["city"] == "sao paulo"


def test_collect_records_minimum_size():
    tests_dir = _BACKEND / "tests"
    prompt = build_meta_system_prompt(get_meta_tool_schemas())
    records = collect_records(prompt, tests_dir)
    assert len(records) >= 50
    for rec in records:
        assert "messages" in rec
        assistant = json.loads(rec["messages"][-1]["content"])
        assert "mode" in assistant
        assert assistant["steps"]


def test_dashscope_record_strips_metadata_keys():
    internal = {
        "id": "e01",
        "source": "eval_set",
        "messages": [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "q"},
            {"role": "assistant", "content": "{}"},
        ],
    }
    assert to_dashscope_record(internal) == {"messages": internal["messages"]}


def test_train_val_split_no_overlap():
    records = [{"id": f"r{i}"} for i in range(20)]
    train, val = split_records(records, val_fraction=0.1, seed=1)
    train_ids = {r["id"] for r in train}
    val_ids = {r["id"] for r in val}
    assert not train_ids & val_ids
    assert len(val) >= 1
    assert len(train) + len(val) == 20
