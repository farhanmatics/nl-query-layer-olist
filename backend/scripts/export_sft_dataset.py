#!/usr/bin/env python3
"""Export supervised fine-tuning (SFT) JSONL for DashScope from eval + few-shot data.

Merges:
  - META_FEW_SHOT_EXAMPLES
  - meta_eval_set.json
  - eval_set.json (meta-tool labels inferred when missing)
  - chain_eval_set.json (planner mode)
  - SQL escape curriculum examples

Outputs (per schema pack):
  datasets/<schema>_sft_train.jsonl  — 90% holdout split
  datasets/<schema>_sft_val.jsonl    — 10% validation (no train leakage)

Run from repo root:
  python backend/scripts/export_sft_dataset.py
  python backend/scripts/export_sft_dataset.py --schema olist --out-dir datasets
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sys
from pathlib import Path
from typing import Any, Optional

_BACKEND = Path(__file__).resolve().parent.parent
_REPO = _BACKEND.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from meta_schemas import META_FEW_SHOT_EXAMPLES  # noqa: E402
from orchestrator import build_meta_system_prompt  # noqa: E402
from meta_schemas import get_meta_tool_schemas  # noqa: E402

_DATE_TOKEN_RE = re.compile(
    r"\b(today|yesterday|this_week|last_week|this_month|last_month|"
    r"this_year|last_year)\b",
    re.I,
)

# Internal operation → meta-tool shape for legacy eval cases.
_INTERNAL_TO_META: dict[str, dict[str, Any]] = {
    "count_orders": {"tool": "count", "entity": "orders"},
    "count_products": {"tool": "count", "entity": "products"},
    "count_by_status": {"tool": "count", "entity": "orders"},
    "count_by_category": {"tool": "count", "entity": "orders"},
    "count_by_payment_type": {"tool": "count", "entity": "payments"},
    "count_low_reviews": {"tool": "count", "entity": "reviews"},
    "get_revenue": {"tool": "sum", "measure": "revenue"},
    "revenue_by_state": {"tool": "sum", "measure": "revenue", "group_by": "state"},
    "revenue_by_category": {"tool": "sum", "measure": "revenue", "group_by": "category"},
    "revenue_trend": {"tool": "sum", "measure": "revenue", "group_by": "month"},
    "revenue_by_seller": {"tool": "sum", "measure": "revenue", "group_by": "seller"},
    "revenue_by_payment_type": {
        "tool": "sum",
        "measure": "revenue",
        "group_by": "payment_type",
    },
    "on_time_delivery_rate": {"tool": "sum", "measure": "on_time_delivery_rate"},
    "repeat_customer_rate": {"tool": "sum", "measure": "repeat_customer_rate"},
    "average_delivery_days": {"tool": "sum", "measure": "avg_delivery_days"},
    "seller_concentration": {"tool": "sum", "measure": "seller_concentration"},
    "top_products": {"tool": "rank", "entity": "products"},
    "top_categories": {"tool": "rank", "entity": "categories"},
    "top_sellers": {"tool": "rank", "entity": "sellers"},
    "products_by_rating": {"tool": "rank", "entity": "products", "by": "rating"},
    "customer_lifetime_value": {"tool": "rank", "entity": "customers"},
    "list_orders": {"tool": "list", "entity": "orders"},
    "customer_order_history": {"tool": "list", "entity": "customer_orders"},
    "fulfillment_status_breakdown": {"tool": "breakdown", "dimension": "order_status"},
    "review_score_distribution": {"tool": "breakdown", "dimension": "review_score"},
    "payment_type_breakdown": {"tool": "breakdown", "dimension": "payment_type"},
    "sellers_by_state": {"tool": "breakdown", "dimension": "seller_state"},
    "review_sentiment_trend": {"tool": "breakdown", "dimension": "review_trend"},
    "average_rating_by_category": {"tool": "breakdown", "dimension": "category_rating"},
    "seller_comparison": {"tool": "compare", "dimension": "seller"},
    "category_comparison": {"tool": "compare", "dimension": "category"},
    "state_comparison": {"tool": "compare", "dimension": "state"},
    "get_order_status": {"tool": "lookup", "entity": "order"},
    "get_customer_info": {"tool": "lookup", "entity": "customer"},
    "get_product_info": {"tool": "lookup", "entity": "product"},
    "get_seller_info": {"tool": "lookup", "entity": "seller"},
    "run_readonly_sql": {"tool": "query"},
}

_FILTER_KEY_MAP = {
    "date_range": "date_token",
    "order_id": "id",
    "customer_id": "id",
    "product_id": "id",
    "seller_id": "id",
    "states": "values",
    "categories": "values",
    "seller_ids": "values",
}

_SQL_ESCAPE_CURRICULUM = [
    (
        "How many distinct product categories are in the catalog?",
        {
            "mode": "single",
            "steps": [
                {
                    "kind": "meta",
                    "tool": "query",
                    "args": {
                        "sql": (
                            "SELECT COUNT(DISTINCT product_category_name) AS cnt "
                            "FROM olist_products_dataset LIMIT 1"
                        )
                    },
                }
            ],
        },
    ),
    (
        "Run SQL: average freight value per line item for orders in SP",
        {
            "mode": "single",
            "steps": [
                {
                    "kind": "meta",
                    "tool": "query",
                    "args": {
                        "sql": (
                            "SELECT AVG(oi.freight_value) AS avg_freight "
                            "FROM olist_order_items_dataset oi "
                            "JOIN olist_orders_dataset o ON oi.order_id = o.order_id "
                            "JOIN olist_customers_dataset c ON o.customer_id = c.customer_id "
                            "WHERE c.customer_state = 'SP' LIMIT 1"
                        )
                    },
                }
            ],
        },
    ),
    (
        "What is the median order value by payment type?",
        {
            "mode": "single",
            "steps": [
                {
                    "kind": "meta",
                    "tool": "query",
                    "args": {
                        "sql": (
                            "SELECT p.payment_type, PERCENTILE_CONT(0.5) "
                            "WITHIN GROUP (ORDER BY p.payment_value) AS median_value "
                            "FROM olist_order_payments_dataset p "
                            "GROUP BY p.payment_type LIMIT 20"
                        )
                    },
                }
            ],
        },
    ),
]


def _infer_date_token(question: str, filters: dict) -> Optional[str]:
    if filters.get("date_token"):
        return filters["date_token"]
    if "date_range" not in filters:
        return None
    m = _DATE_TOKEN_RE.search(question)
    return m.group(1).lower() if m else "last_month"


def _filters_to_meta_args(filters: dict, question: str) -> dict:
    args: dict[str, Any] = {}
    for key, value in (filters or {}).items():
        if value == "*":
            if key == "date_range":
                token = _infer_date_token(question, filters)
                if token:
                    args["date_token"] = token
            continue
        meta_key = _FILTER_KEY_MAP.get(key, key)
        if meta_key == "values" and key == "states":
            args["dimension"] = "state"
        args[meta_key] = value
    return args


def _internal_case_to_meta(case: dict) -> Optional[dict]:
    if case.get("expected_error"):
        return None
    op = case.get("expected_meta_operation") or case.get("expected_operation")
    if not op:
        return None
    if case.get("expected_meta_operation"):
        tool = case["expected_meta_operation"]
        args = _filters_to_meta_args(case.get("expected_filters") or {}, case["question"])
        if tool == "lookup":
            args.setdefault("entity", "order")
            args.setdefault("id", "unknown")
        if tool == "compare" and "states" in (case.get("expected_filters") or {}):
            args["dimension"] = "state"
            args["values"] = case["expected_filters"]["states"]
        return {"tool": tool, "args": args}

    template = _INTERNAL_TO_META.get(op)
    if not template:
        return None
    args = dict(template)
    args.pop("tool", None)
    args.update(_filters_to_meta_args(case.get("expected_filters") or {}, case["question"]))
    return {"tool": template["tool"], "args": args}


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _record(
    *,
    record_id: str,
    question: str,
    assistant: dict,
    system_prompt: str,
    source: str,
) -> dict:
    return {
        "id": record_id,
        "source": source,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": question},
            {"role": "assistant", "content": json.dumps(assistant, separators=(",", ":"))},
        ],
    }


def collect_records(system_prompt: str, tests_dir: Path) -> list[dict]:
    records: list[dict] = []

    for i, (question, answer_json) in enumerate(META_FEW_SHOT_EXAMPLES):
        assistant = json.loads(answer_json)
        records.append(
            _record(
                record_id=f"fewshot_{i:02d}",
                question=question,
                assistant={"mode": "single", "steps": [{"kind": "meta", "tool": assistant["tool"], "args": assistant["args"]}]},
                system_prompt=system_prompt,
                source="few_shot",
            )
        )

    meta_eval = _load_json(tests_dir / "meta_eval_set.json")
    for case in meta_eval.get("cases", []):
        assistant = {
            "mode": "single",
            "steps": [
                {
                    "kind": "meta",
                    "tool": case["meta_tool"],
                    "args": case.get("meta_args") or {},
                }
            ],
        }
        records.append(
            _record(
                record_id=case["id"],
                question=case["question"],
                assistant=assistant,
                system_prompt=system_prompt,
                source="meta_eval",
            )
        )

    eval_set = _load_json(tests_dir / "eval_set.json")
    for case in eval_set.get("cases", []):
        if case.get("requires_sql_escape") and case.get("expected_meta_operation") == "query":
            continue  # covered by SQL curriculum with full SQL text
        meta = _internal_case_to_meta(case)
        if not meta:
            continue
        records.append(
            _record(
                record_id=case["id"],
                question=case["question"],
                assistant={
                    "mode": "single",
                    "steps": [{"kind": "meta", "tool": meta["tool"], "args": meta["args"]}],
                },
                system_prompt=system_prompt,
                source="eval_set",
            )
        )

    chain_path = tests_dir / "chain_eval_set.json"
    if chain_path.exists():
        chain_eval = _load_json(chain_path)
        for case in chain_eval.get("cases", []):
            records.append(
                _record(
                    record_id=case["id"],
                    question=case["question"],
                    assistant=case["expected_plan"],
                    system_prompt=system_prompt,
                    source="chain_eval",
                )
            )

    for i, (question, plan) in enumerate(_SQL_ESCAPE_CURRICULUM):
        records.append(
            _record(
                record_id=f"sql_curriculum_{i:02d}",
                question=question,
                assistant=plan,
                system_prompt=system_prompt,
                source="sql_curriculum",
            )
        )

    return records


def split_records(records: list[dict], val_fraction: float, seed: int) -> tuple[list[dict], list[dict]]:
    rng = random.Random(seed)
    shuffled = list(records)
    rng.shuffle(shuffled)
    val_count = max(1, int(len(shuffled) * val_fraction))
    val = shuffled[:val_count]
    train = shuffled[val_count:]
    return train, val


def write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Export SFT JSONL for DashScope fine-tuning")
    parser.add_argument("--schema", default="olist", help="Schema name (default: olist)")
    parser.add_argument("--out-dir", default="datasets", help="Output directory (default: datasets)")
    parser.add_argument("--val-fraction", type=float, default=0.1, help="Validation holdout fraction")
    parser.add_argument("--seed", type=int, default=42, help="RNG seed for train/val split")
    args = parser.parse_args()

    tests_dir = _BACKEND / "tests"
    system_prompt = build_meta_system_prompt(get_meta_tool_schemas())

    records = collect_records(system_prompt, tests_dir)
    if not records:
        print("No records collected — check eval set paths.", file=sys.stderr)
        return 1

    train, val = split_records(records, args.val_fraction, args.seed)
    out_dir = _REPO / args.out_dir
    train_path = out_dir / f"{args.schema}_sft_train.jsonl"
    val_path = out_dir / f"{args.schema}_sft_val.jsonl"
    write_jsonl(train_path, train)
    write_jsonl(val_path, val)

    print(f"Wrote {len(train)} train + {len(val)} val records")
    print(f"  {train_path}")
    print(f"  {val_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
