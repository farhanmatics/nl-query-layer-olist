#!/usr/bin/env python3
"""Export supervised fine-tuning (SFT) JSONL for DashScope from eval + few-shot data.

Merges:
  - META_FEW_SHOT_EXAMPLES
  - meta_eval_set.json
  - eval_set.json (meta-tool labels inferred when missing)
  - chain_eval_set.json (planner mode)
  - SQL escape curriculum examples

Outputs (per schema pack):
  datasets/<schema>_sft_train.jsonl       — 90% holdout (full system prompt)
  datasets/<schema>_sft_val.jsonl         — 10% validation (no train leakage)
  datasets/<schema>_sft_train_min.jsonl   — same split with --system-mode minimal
  datasets/<schema>_sft_val_min.jsonl

Run from repo root:
  python backend/scripts/export_sft_dataset.py
  python backend/scripts/export_sft_dataset.py --schema olist --out-dir datasets
  python backend/scripts/export_sft_dataset.py --system-mode minimal --target-size 600
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

# Prompt-compression experiment: train the model to emit the same JSON tool call
# with a short fixed instruction instead of the ~3k-token schema dump. Keep this
# under ~100 tokens (approx chars/4) so max_seq_len can stay at 1024.
MINIMAL_SYSTEM_PROMPT = (
    "Convert the question into ONE JSON meta-tool call for Olist data. "
    "Backend runs SQL — choose shape and filters only.\n"
    "Tools: count, rank, sum, list, breakdown, compare, lookup, query.\n"
    'Reply ONLY: {"tool":"<name>","args":{...}}\n'
    "count.entity: products=catalog, orders=sales, reviews, payments. "
    "Dates: today/yesterday/this|last_week|month|year. "
    "Keep every filter (city, state, status, date_token)."
)

# ~4 chars/token is a conservative English estimate used only as a soft guard.
_MINIMAL_PROMPT_MAX_APPROX_TOKENS = 100


def approx_token_count(text: str) -> int:
    """Rough token estimate (chars/4). Good enough for the <100-token gate."""
    return max(1, (len(text) + 3) // 4)


def resolve_system_prompt(mode: str) -> str:
    """Return the system prompt for the requested export mode."""
    if mode == "minimal":
        prompt = MINIMAL_SYSTEM_PROMPT
        tokens = approx_token_count(prompt)
        if tokens > _MINIMAL_PROMPT_MAX_APPROX_TOKENS:
            raise ValueError(
                f"MINIMAL_SYSTEM_PROMPT is ~{tokens} tokens "
                f"(limit {_MINIMAL_PROMPT_MAX_APPROX_TOKENS}); shorten it."
            )
        return prompt
    if mode == "full":
        return build_meta_system_prompt(get_meta_tool_schemas())
    raise ValueError(f"Unknown system mode: {mode!r} (expected 'full' or 'minimal')")


def train_val_filenames(schema: str, mode: str) -> tuple[str, str]:
    """Return (train.jsonl, val.jsonl) names; minimal mode uses `_min` suffix."""
    if mode == "minimal":
        return f"{schema}_sft_train_min.jsonl", f"{schema}_sft_val_min.jsonl"
    return f"{schema}_sft_train.jsonl", f"{schema}_sft_val.jsonl"

# Match date phrases in either spaced ("this year") or tokenized ("this_year")
# form — questions use spaces, tokens use underscores. Normalize to the token.
_DATE_TOKEN_RE = re.compile(
    r"\b(today|yesterday|this[ _](?:week|month|year)|last[ _](?:week|month|year))\b",
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
    return m.group(1).lower().replace(" ", "_") if m else "last_month"


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


# ---------------------------------------------------------------------------
# Label-safe augmentation
#
# We multiply the base examples without a model in the loop, so every generated
# label stays provably correct:
#   * slot substitution — swap a city/state/date in BOTH the question text and
#     the typed args together (only applied to single meta-tool records whose
#     args carry the slot and whose surface form appears in the question);
#   * opener paraphrase — reword the leading phrase of the question; the label
#     is untouched, so this is safe for every record type (including chains and
#     the SQL curriculum, whose labels contain literal hardcoded values).
# ---------------------------------------------------------------------------

# (display form, canonical arg form) — arg form matches the lowercase,
# accent-stripped `customer_city` the validation layer normalizes to.
_CITY_PAIRS: list[tuple[str, str]] = [
    ("São Paulo", "sao paulo"),
    ("Rio de Janeiro", "rio de janeiro"),
    ("Belo Horizonte", "belo horizonte"),
    ("Brasília", "brasilia"),
    ("Curitiba", "curitiba"),
    ("Porto Alegre", "porto alegre"),
    ("Salvador", "salvador"),
    ("Campinas", "campinas"),
    ("Guarulhos", "guarulhos"),
    ("Fortaleza", "fortaleza"),
    ("Recife", "recife"),
    ("Niterói", "niteroi"),
]

_STATES: list[str] = ["SP", "RJ", "MG", "RS", "PR", "SC", "BA", "DF", "GO", "ES", "CE", "PE"]

_DATE_PAIRS: list[tuple[str, str]] = [
    ("last month", "last_month"),
    ("this month", "this_month"),
    ("last week", "last_week"),
    ("this week", "this_week"),
    ("last year", "last_year"),
    ("this year", "this_year"),
    ("yesterday", "yesterday"),
    ("today", "today"),
]

# Leading-opener synonym groups. Only the first group that prefixes the question
# is used, and only the leading phrase is rewritten — meaning is preserved.
_PARAPHRASE_GROUPS: list[list[str]] = [
    ["how many", "count the number of", "count how many", "what is the number of", "tell me how many"],
    ["what are the top", "list the top", "show me the top", "which are the top"],
    ["list", "show me", "give me a list of"],
    ["show me", "share", "give me"],
    ["what is", "what's", "tell me"],
]


def _cap(text: str) -> str:
    return text[:1].upper() + text[1:] if text else text


def _swap_surface(text: str, old_forms: list[str], new_display: str) -> tuple[str, bool]:
    """Replace the first matching surface form (case-insensitive) with new_display."""
    for form in old_forms:
        if re.search(re.escape(form), text, re.I):
            return re.sub(re.escape(form), new_display, text, count=1, flags=re.I), True
    return text, False


def _slot_variants(question: str, args: dict, rng: random.Random, per_slot: int) -> list[tuple[str, dict]]:
    """Enumerate (question, args) pairs by swapping present city/state/date slots."""
    variants: list[tuple[str, dict]] = [(question, args)]

    def expand(pairs: list[tuple[str, dict]], swap) -> list[tuple[str, dict]]:
        out: list[tuple[str, dict]] = []
        for q, a in pairs:
            produced = swap(q, a)
            out.append((q, a))  # keep the un-swapped branch too
            out.extend(produced)
        return out

    city = args.get("city")
    if isinstance(city, str) and city:
        cur_display = next((d for d, a in _CITY_PAIRS if a == city.lower()), city)
        alts = [(d, a) for d, a in _CITY_PAIRS if a != city.lower()]
        rng.shuffle(alts)
        alts = alts[:per_slot]

        def swap_city(q, a):
            res = []
            for disp, argval in alts:
                nq, ok = _swap_surface(q, [cur_display, city], disp)
                if ok:
                    na = dict(a)
                    na["city"] = argval
                    res.append((nq, na))
            return res

        variants = expand(variants, swap_city)

    state = args.get("state")
    if isinstance(state, str) and re.fullmatch(r"[A-Z]{2}", state or ""):
        alts_s = [s for s in _STATES if s != state]
        rng.shuffle(alts_s)
        alts_s = alts_s[:per_slot]

        def swap_state(q, a):
            res = []
            for s in alts_s:
                if re.search(rf"\b{state}\b", q):
                    nq = re.sub(rf"\b{state}\b", s, q, count=1)
                    na = dict(a)
                    na["state"] = s
                    res.append((nq, na))
            return res

        variants = expand(variants, swap_state)

    token = args.get("date_token")
    if isinstance(token, str) and token:
        cur_phrase = next((p for p, t in _DATE_PAIRS if t == token), None)
        if cur_phrase:
            alts_d = [(p, t) for p, t in _DATE_PAIRS if t != token]
            rng.shuffle(alts_d)
            alts_d = alts_d[:per_slot]

            def swap_date(q, a):
                res = []
                for phrase, tok in alts_d:
                    if re.search(re.escape(cur_phrase), q, re.I):
                        nq = re.sub(re.escape(cur_phrase), phrase, q, count=1, flags=re.I)
                        na = dict(a)
                        na["date_token"] = tok
                        res.append((nq, na))
                return res

            variants = expand(variants, swap_date)

    # Drop the untouched original; caller re-adds the base record separately.
    return [(q, a) for (q, a) in variants if (q, a) != (question, args)]


def _paraphrase(question: str) -> list[str]:
    ql = question.lower()
    for group in _PARAPHRASE_GROUPS:
        for member in group:
            if ql.startswith(member):
                rest = question[len(member):]
                return [_cap(other + rest) for other in group if other != member]
    return []


def _is_slot_augmentable(assistant: dict) -> bool:
    """True only for single meta-tool records (not query/chain, whose labels hold literal values)."""
    if assistant.get("mode") != "single":
        return False
    steps = assistant.get("steps") or []
    if len(steps) != 1:
        return False
    return steps[0].get("tool") not in (None, "query")


def augment_record(record: dict, rng: random.Random, per_slot: int, max_per_record: int) -> list[dict]:
    question = record["messages"][1]["content"]
    assistant = json.loads(record["messages"][2]["content"])
    system_prompt = record["messages"][0]["content"]

    # Start from slot substitutions (or just the base question if not augmentable).
    if _is_slot_augmentable(assistant):
        args = assistant["steps"][0].get("args") or {}
        pairs = _slot_variants(question, args, rng, per_slot)
        base_pairs = [(question, args)] + pairs
    else:
        base_pairs = [(question, None)]

    seen: set[tuple[str, str]] = {(question, json.dumps(assistant, sort_keys=True))}
    out: list[dict] = []
    n = 0
    for q, args in base_pairs:
        # Rebuild the assistant label if the args changed.
        if args is not None:
            new_assistant = dict(assistant)
            new_assistant["steps"] = [dict(assistant["steps"][0])]
            new_assistant["steps"][0]["args"] = args
        else:
            new_assistant = assistant
        for variant_q in [q] + _paraphrase(q):
            key = (variant_q, json.dumps(new_assistant, sort_keys=True))
            if key in seen:
                continue
            seen.add(key)
            out.append(
                _record(
                    record_id=f"{record.get('id', 'aug')}_aug{n:03d}",
                    question=variant_q,
                    assistant=new_assistant,
                    system_prompt=system_prompt,
                    source=f"{record.get('source', 'base')}_aug",
                )
            )
            n += 1
    rng.shuffle(out)
    return out[:max_per_record]


def augment_to_target(
    base: list[dict], target: int, rng: random.Random, per_slot: int, max_per_record: int
) -> list[dict]:
    """Return base records plus augmented variants, up to `target` total (leakage-safe within a split)."""
    result = list(base)
    pool: list[dict] = []
    for rec in base:
        pool.extend(augment_record(rec, rng, per_slot, max_per_record))
    rng.shuffle(pool)
    for rec in pool:
        if len(result) >= target:
            break
        result.append(rec)
    return result


def split_records(records: list[dict], val_fraction: float, seed: int) -> tuple[list[dict], list[dict]]:
    rng = random.Random(seed)
    shuffled = list(records)
    rng.shuffle(shuffled)
    val_count = max(1, int(len(shuffled) * val_fraction))
    val = shuffled[:val_count]
    train = shuffled[val_count:]
    return train, val


def to_dashscope_record(record: dict) -> dict:
    """DashScope SFT accepts only {\"messages\": [...]} per line — no extra keys."""
    return {"messages": record["messages"]}


def write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(to_dashscope_record(rec), ensure_ascii=False) + "\n")


def validate_export(train: list[dict], val: list[dict], system_prompt: str, mode: str) -> None:
    """Fail closed on format / leakage / label issues before writing JSONL."""
    if mode == "minimal":
        tokens = approx_token_count(system_prompt)
        if tokens > _MINIMAL_PROMPT_MAX_APPROX_TOKENS:
            raise ValueError(f"minimal system prompt ~{tokens} tokens exceeds limit")

    train_q = {r["messages"][1]["content"] for r in train}
    val_q = {r["messages"][1]["content"] for r in val}
    overlap = train_q & val_q
    if overlap:
        sample = sorted(overlap)[:3]
        raise ValueError(f"train/val question overlap ({len(overlap)}): {sample!r}")

    for split_name, records in (("train", train), ("val", val)):
        for i, rec in enumerate(records):
            msgs = rec["messages"]
            roles = [m.get("role") for m in msgs]
            if roles != ["system", "user", "assistant"]:
                raise ValueError(f"{split_name}[{i}]: bad roles {roles}")
            if msgs[0]["content"] != system_prompt:
                raise ValueError(f"{split_name}[{i}]: system prompt mismatch")
            try:
                assistant = json.loads(msgs[2]["content"])
            except json.JSONDecodeError as exc:
                raise ValueError(f"{split_name}[{i}]: assistant JSON invalid: {exc}") from exc
            if "mode" not in assistant or not assistant.get("steps"):
                raise ValueError(f"{split_name}[{i}]: assistant missing mode/steps")


def main() -> int:
    parser = argparse.ArgumentParser(description="Export SFT JSONL for DashScope fine-tuning")
    parser.add_argument("--schema", default="olist", help="Schema name (default: olist)")
    parser.add_argument("--out-dir", default="datasets", help="Output directory (default: datasets)")
    parser.add_argument("--val-fraction", type=float, default=0.1, help="Validation holdout fraction")
    parser.add_argument("--seed", type=int, default=42, help="RNG seed for train/val split")
    parser.add_argument(
        "--system-mode",
        choices=("full", "minimal"),
        default="full",
        help="full = schema prompt (~3k tokens); minimal = short fixed instruction (<100 tokens)",
    )
    parser.add_argument(
        "--target-size",
        type=int,
        default=0,
        help="Total records to reach via label-safe augmentation (0 = no augmentation)",
    )
    parser.add_argument(
        "--per-slot",
        type=int,
        default=4,
        help="Max alternative values tried per city/state/date slot when augmenting",
    )
    parser.add_argument(
        "--max-per-record",
        type=int,
        default=16,
        help="Cap on augmented variants generated from any single base record",
    )
    args = parser.parse_args()

    tests_dir = _BACKEND / "tests"
    system_prompt = resolve_system_prompt(args.system_mode)

    records = collect_records(system_prompt, tests_dir)
    if not records:
        print("No records collected — check eval set paths.", file=sys.stderr)
        return 1

    # Split base records first so augmented variants of a base example can never
    # straddle the train/val boundary (no near-duplicate leakage).
    train, val = split_records(records, args.val_fraction, args.seed)

    if args.target_size > 0:
        target_val = max(len(val), int(args.target_size * args.val_fraction))
        target_train = args.target_size - target_val
        train = augment_to_target(
            train, target_train, random.Random(args.seed), args.per_slot, args.max_per_record
        )
        val = augment_to_target(
            val, target_val, random.Random(args.seed + 1), args.per_slot, args.max_per_record
        )
        # Two different base records can independently generate the same
        # paraphrase; drop such collisions from train so no val question leaks.
        val_questions = {r["messages"][1]["content"] for r in val}
        train = [r for r in train if r["messages"][1]["content"] not in val_questions]
        random.Random(args.seed).shuffle(train)
        random.Random(args.seed + 2).shuffle(val)

    validate_export(train, val, system_prompt, args.system_mode)

    out_dir = _REPO / args.out_dir
    train_name, val_name = train_val_filenames(args.schema, args.system_mode)
    train_path = out_dir / train_name
    val_path = out_dir / val_name
    write_jsonl(train_path, train)
    write_jsonl(val_path, val)

    print(f"Wrote {len(train)} train + {len(val)} val records (system-mode={args.system_mode})")
    print(f"  system prompt ~{approx_token_count(system_prompt)} tokens ({len(system_prompt)} chars)")
    print(f"  {train_path}")
    print(f"  {val_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
