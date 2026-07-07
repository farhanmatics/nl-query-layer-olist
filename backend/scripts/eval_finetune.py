#!/usr/bin/env python3
"""Base-vs-fine-tune eval harness for the Olist meta-tool translator.

Runs the held-out SFT validation set through both the base model and the
deployed fine-tuned model, then reports accuracy on the underlying tool call.
Both models are exercised through the exact same request path the backend uses
(`raw_complete`), with each model's correct API style (multimodal vs text).

Grading normalizes the two output envelopes — the fine-tune emits the full
plan schema ({"mode","steps":[{"kind","tool","args"}]}) while the base tends to
emit a bare {"tool","args"} — so models are compared on semantics, not format.

Run from repo root:
  python backend/scripts/eval_finetune.py                 # full val set
  python backend/scripts/eval_finetune.py --limit 20      # quick sample
  python backend/scripts/eval_finetune.py --models finetune
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Optional

_BACKEND = Path(__file__).resolve().parent.parent
_REPO = _BACKEND.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from config import settings  # noqa: E402
from model_client.dashscope_client import DashScopeError, raw_complete  # noqa: E402

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def _model_spec(name: str) -> tuple[str, bool]:
    """Map a friendly name to (model_id, is_multimodal)."""
    if name == "base":
        return settings.dashscope_model, settings.dashscope_base_is_multimodal
    if name == "finetune":
        if not settings.dashscope_finetune_model.strip():
            raise SystemExit("DASHSCOPE_FINETUNE_MODEL is not set in .env")
        return settings.dashscope_finetune_model.strip(), settings.dashscope_finetune_is_multimodal
    raise SystemExit(f"Unknown model '{name}' (use: base, finetune)")


def _parse_json(text: str) -> Optional[dict]:
    m = _FENCE_RE.search(text)
    if m:
        text = m.group(1)
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        return None


# Backend-applied defaults: an arg equal to its default is semantically the
# same as omitting it (e.g. count_low_reviews defaults score_max=2 in the
# resolver), so we drop these before comparing to avoid false mismatches.
_DEFAULT_ARGS = {"score_max": 2, "offset": 0}


def _norm_args(args: dict) -> dict:
    return {k: v for k, v in (args or {}).items() if _DEFAULT_ARGS.get(k) != v}


def _core_steps(obj: dict) -> list[tuple[Optional[str], dict]]:
    """Normalize either envelope to a comparable list of (tool, args) steps."""
    if not isinstance(obj, dict):
        return []
    if isinstance(obj.get("steps"), list):
        return [(s.get("tool"), _norm_args(s.get("args"))) for s in obj["steps"] if isinstance(s, dict)]
    if "tool" in obj:
        return [(obj.get("tool"), _norm_args(obj.get("args")))]
    return []


def _canon(steps: list[tuple[Optional[str], dict]]) -> str:
    return json.dumps(steps, sort_keys=True, ensure_ascii=False)


def _tools_only(steps: list[tuple[Optional[str], dict]]) -> list:
    return [t for t, _ in steps]


def evaluate(model_name: str, cases: list[dict], show: int) -> dict:
    model_id, multimodal = _model_spec(model_name)
    exact = tool_ok = parse_fail = 0
    mismatches: list[str] = []

    for i, case in enumerate(cases):
        msgs = case["messages"]
        system, user = msgs[0]["content"], msgs[1]["content"]
        gold = _core_steps(json.loads(msgs[2]["content"]))
        try:
            raw = raw_complete(
                model=model_id, system=system, user=user,
                multimodal=multimodal, temperature=0,
            )
        except DashScopeError as e:
            parse_fail += 1
            continue
        pred_obj = _parse_json(raw)
        if pred_obj is None:
            parse_fail += 1
            if len(mismatches) < show:
                mismatches.append(f"  [parse-fail] {user!r}\n     raw: {raw[:120]!r}")
            continue
        pred = _core_steps(pred_obj)
        if _canon(pred) == _canon(gold):
            exact += 1
            tool_ok += 1
        else:
            if _tools_only(pred) == _tools_only(gold):
                tool_ok += 1
            if len(mismatches) < show:
                mismatches.append(f"  [miss] {user!r}\n     gold: {_canon(gold)}\n     pred: {_canon(pred)}")

    n = len(cases)
    return {
        "model": model_name,
        "model_id": model_id,
        "n": n,
        "exact": exact,
        "tool_ok": tool_ok,
        "parse_fail": parse_fail,
        "exact_acc": exact / n if n else 0.0,
        "tool_acc": tool_ok / n if n else 0.0,
        "mismatches": mismatches,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Base-vs-fine-tune eval on the SFT val set")
    parser.add_argument("--val-path", default="datasets/olist_sft_val.jsonl")
    parser.add_argument("--limit", type=int, default=0, help="Cap cases (0 = all)")
    parser.add_argument("--models", default="base,finetune", help="Comma list: base,finetune")
    parser.add_argument("--show", type=int, default=5, help="Sample mismatches to print per model")
    args = parser.parse_args()

    val_path = (_REPO / args.val_path)
    cases = [json.loads(l) for l in val_path.read_text().splitlines() if l.strip()]
    if args.limit > 0:
        cases = cases[: args.limit]
    print(f"Evaluating {len(cases)} cases from {val_path.name}\n")

    results = [evaluate(m.strip(), cases, args.show) for m in args.models.split(",") if m.strip()]

    print(f"{'model':<10} {'model_id':<26} {'exact':>7} {'tool':>7} {'parse_fail':>11}")
    print("-" * 66)
    for r in results:
        print(f"{r['model']:<10} {r['model_id']:<26} {r['exact_acc']*100:>6.1f}% {r['tool_acc']*100:>6.1f}% {r['parse_fail']:>11}")

    by_name = {r["model"]: r for r in results}
    if "base" in by_name and "finetune" in by_name:
        d_exact = (by_name["finetune"]["exact_acc"] - by_name["base"]["exact_acc"]) * 100
        d_tool = (by_name["finetune"]["tool_acc"] - by_name["base"]["tool_acc"]) * 100
        print("-" * 66)
        print(f"{'DELTA (ft-base)':<37} {d_exact:>+6.1f}% {d_tool:>+6.1f}%")

    for r in results:
        if r["mismatches"]:
            print(f"\n--- {r['model']} sample mismatches ---")
            print("\n".join(r["mismatches"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
