"""Planner output contract: mode=single|chain with bounded meta/SQL steps."""
from __future__ import annotations

import json
from typing import Any

from config import settings

PLANNER_FEW_SHOT_EXAMPLES = (
    (
        "Which category had the most revenue last year, and what was our best product in it?",
        json.dumps(
            {
                "mode": "chain",
                "steps": [
                    {
                        "kind": "meta",
                        "tool": "rank",
                        "args": {
                            "entity": "categories",
                            "by": "revenue",
                            "limit": 1,
                            "date_token": "last_year",
                        },
                    },
                    {
                        "kind": "meta",
                        "tool": "rank",
                        "args": {
                            "entity": "products",
                            "category": "$step0.category",
                            "by": "revenue",
                            "limit": 1,
                            "date_token": "last_year",
                        },
                    },
                ],
            },
            separators=(",", ":"),
        ),
    ),
    (
        "How many delivered orders in Sao Paulo last month?",
        json.dumps(
            {
                "mode": "single",
                "steps": [
                    {
                        "kind": "meta",
                        "tool": "count",
                        "args": {
                            "entity": "orders",
                            "city": "sao paulo",
                            "status": "delivered",
                            "date_token": "last_month",
                        },
                    }
                ],
            },
            separators=(",", ":"),
        ),
    ),
)


def build_planner_system_prompt(base_meta_prompt: str) -> str:
    """Extend the meta-tool prompt with planner output rules."""
    examples = "\n\n".join(f'Q: "{q}"\nA: {a}' for q, a in PLANNER_FEW_SHOT_EXAMPLES)
    max_steps = settings.planner_max_steps
    return f"""{base_meta_prompt}

PLANNER MODE — output a plan JSON (not a bare tool call):
- Respond with ONLY valid JSON.
- Top-level keys: "mode" ("single" or "chain") and "steps" (array, max {max_steps} steps).
- Each step: {{"kind": "meta", "tool": "<meta-tool>", "args": {{...}}}}
- For chained follow-ups, bind prior step fields as "$step0.category", "$step0.product_id", etc.
- Use mode=single for one-step questions; mode=chain only when a later step needs a prior result.
- Never emit free SQL unless kind=meta tool=query (SQL escape).

--- PLANNER EXAMPLES ---

{examples}

--- END PLANNER EXAMPLES ---
"""


def normalize_plan(raw: dict[str, Any]) -> dict[str, Any]:
    """Accept legacy {{tool, args}} or planner {{mode, steps}} shapes."""
    if not raw or "error" in raw:
        return raw
    if "steps" in raw:
        steps = raw.get("steps") or []
        if len(steps) > settings.planner_max_steps:
            return {"error": f"Plan exceeds max {settings.planner_max_steps} steps"}
        return {"mode": raw.get("mode") or ("single" if len(steps) <= 1 else "chain"), "steps": steps}
    if raw.get("tool"):
        return {
            "mode": "single",
            "steps": [{"kind": "meta", "tool": raw["tool"], "args": dict(raw.get("args") or {})}],
        }
    return {"error": "Invalid plan: expected mode/steps or tool/args"}
