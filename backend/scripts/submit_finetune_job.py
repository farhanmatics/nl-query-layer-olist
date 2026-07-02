#!/usr/bin/env python3
"""Prepare and optionally submit a DashScope fine-tuning job.

DashScope Model Studio fine-tuning is done via the Alibaba Cloud console or
the DashScope fine-tuning API. This script validates the exported JSONL and
prints the upload/submit checklist.

Usage:
  python backend/scripts/export_sft_dataset.py
  python backend/scripts/submit_finetune_job.py --train datasets/olist_sft_train.jsonl

To submit via API (when enabled in your account):
  python backend/scripts/submit_finetune_job.py --submit \\
    --train datasets/olist_sft_train.jsonl \\
    --val datasets/olist_sft_val.jsonl \\
    --base-model qwen3.7-plus
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent.parent


def _validate_jsonl(path: Path) -> int:
    count = 0
    with path.open(encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            extra = set(rec.keys()) - {"messages"}
            if extra:
                raise ValueError(
                    f"{path}:{line_no}: unexpected keys {sorted(extra)} "
                    "(DashScope allows only 'messages' per line)"
                )
            if "messages" not in rec:
                raise ValueError(f"{path}:{line_no}: missing messages")
            roles = [m.get("role") for m in rec["messages"]]
            if roles != ["system", "user", "assistant"]:
                raise ValueError(f"{path}:{line_no}: expected system/user/assistant roles")
            count += 1
    return count


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate / submit DashScope SFT job")
    parser.add_argument("--train", required=True, help="Path to train JSONL")
    parser.add_argument("--val", help="Path to validation JSONL")
    parser.add_argument("--base-model", default="qwen3.7-plus")
    parser.add_argument(
        "--submit",
        action="store_true",
        help="Submit job via DashScope API (requires account API access)",
    )
    args = parser.parse_args()

    train_path = Path(args.train)
    if not train_path.is_absolute():
        train_path = (_REPO / train_path).resolve()
    train_count = _validate_jsonl(train_path)
    print(f"Train: {train_count} records in {train_path}")

    val_count = 0
    if args.val:
        val_path = Path(args.val)
        if not val_path.is_absolute():
            val_path = (_REPO / val_path).resolve()
        val_count = _validate_jsonl(val_path)
        print(f"Val:   {val_count} records in {val_path}")

    print()
    print("DashScope fine-tuning checklist:")
    print(f"  1. Base model: {args.base_model}")
    print(f"  2. Upload train JSONL ({train_count} examples)")
    if val_count:
        print(f"  3. Upload val JSONL ({val_count} examples)")
    print("  4. Start SFT job in Model Studio (console) or via API")
    print("  5. Copy deployed model ID to DASHSCOPE_FINETUNE_MODEL in .env")
    print("  6. Set USE_FINETUNED_MODEL=true and run eval: pytest backend/tests/test_eval.py -m live")

    if args.submit:
        print()
        print(
            "API submit is account-specific — use Model Studio console or wire "
            "dashscope.FineTune API here once your tenant exposes it.",
            file=sys.stderr,
        )
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
