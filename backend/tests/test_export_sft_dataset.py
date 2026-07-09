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
    MINIMAL_SYSTEM_PROMPT,
    _internal_case_to_meta,
    approx_token_count,
    collect_records,
    resolve_system_prompt,
    split_records,
    to_dashscope_record,
    train_val_filenames,
    validate_export,
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


def test_minimal_system_prompt_under_100_tokens():
    assert approx_token_count(MINIMAL_SYSTEM_PROMPT) <= 100
    prompt = resolve_system_prompt("minimal")
    assert prompt == MINIMAL_SYSTEM_PROMPT
    assert "count" in prompt and "rank" in prompt


def test_resolve_system_mode_full_is_long():
    full = resolve_system_prompt("full")
    assert approx_token_count(full) > 500


def test_train_val_filenames_minimal_suffix():
    assert train_val_filenames("olist", "full") == (
        "olist_sft_train.jsonl",
        "olist_sft_val.jsonl",
    )
    assert train_val_filenames("olist", "minimal") == (
        "olist_sft_train_min.jsonl",
        "olist_sft_val_min.jsonl",
    )


def test_validate_export_rejects_question_overlap():
    prompt = MINIMAL_SYSTEM_PROMPT
    rec = {
        "messages": [
            {"role": "system", "content": prompt},
            {"role": "user", "content": "How many orders?"},
            {
                "role": "assistant",
                "content": json.dumps(
                    {"mode": "single", "steps": [{"kind": "meta", "tool": "count", "args": {}}]}
                ),
            },
        ]
    }
    with pytest.raises(ValueError, match="overlap"):
        validate_export([rec], [rec], prompt, "minimal")


def test_collect_records_with_minimal_prompt():
    tests_dir = _BACKEND / "tests"
    records = collect_records(MINIMAL_SYSTEM_PROMPT, tests_dir)
    assert len(records) >= 50
    assert all(r["messages"][0]["content"] == MINIMAL_SYSTEM_PROMPT for r in records)
