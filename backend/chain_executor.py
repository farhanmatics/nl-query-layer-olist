"""Execute bounded multi-step plans against validated meta-tools / SQL escape."""
from __future__ import annotations

import logging
import re
from typing import Any, Optional

from config import settings

logger = logging.getLogger(__name__)

_BINDING_RE = re.compile(r"^\$step(\d+)\.([a-zA-Z_][a-zA-Z0-9_]*)$")
_RESULT_ARRAY_KEYS = ("categories", "products", "orders", "rows", "sellers", "customers")


def _extract_field(step_result: dict, field: str) -> Any:
    """Pull a binding field from a step result payload."""
    if field in step_result and step_result[field] not in (None, "", [], {}):
        return step_result[field]
    for key in _RESULT_ARRAY_KEYS:
        items = step_result.get(key)
        if isinstance(items, list) and items:
            first = items[0]
            if isinstance(first, dict) and field in first:
                return first[field]
    filters = step_result.get("filters") or {}
    if field in filters:
        return filters[field]
    raise KeyError(f"Cannot resolve binding field {field!r} from step result")


def resolve_bindings(args: dict, step_results: list[dict]) -> dict:
    """Replace $stepN.field placeholders with values from prior step results."""
    resolved: dict[str, Any] = {}
    for key, value in (args or {}).items():
        if isinstance(value, str):
            m = _BINDING_RE.match(value.strip())
            if m:
                step_idx = int(m.group(1))
                field = m.group(2)
                if step_idx >= len(step_results):
                    raise ValueError(f"Binding {value!r} references missing step {step_idx}")
                resolved[key] = _extract_field(step_results[step_idx], field)
                continue
        resolved[key] = value
    return resolved


async def execute_plan(
    plan: dict,
    *,
    question: str,
    resolve_meta_call,
    dispatch_function,
    apply_filter_guard,
) -> dict:
    """Run a normalized plan; returns aggregated step results or first error."""
    steps = plan.get("steps") or []
    if not steps:
        return {"error": "Empty plan"}

    step_results: list[dict] = []
    step_traces: list[dict] = []

    for i, step in enumerate(steps):
        kind = step.get("kind", "meta")
        if kind != "meta":
            return {"error": f"Unsupported step kind: {kind!r}"}

        tool = step.get("tool")
        if not tool:
            return {"error": f"Step {i} missing tool"}

        try:
            args = resolve_bindings(step.get("args") or {}, step_results)
        except (KeyError, ValueError) as e:
            return {"error": str(e), "failed_step": i}

        internal_tool = tool
        internal_args = args
        if tool != "query":
            try:
                internal_tool, internal_args = resolve_meta_call(tool, args, question)
            except ValueError as e:
                return {"error": str(e), "failed_step": i, "meta_tool": tool}

        guard = {"applied": [], "unresolved": []}
        if internal_tool != "run_readonly_sql":
            guard = apply_filter_guard(question, internal_tool, internal_args)
        if guard.get("unresolved"):
            return {
                "error": "Filter faithfulness guard blocked step",
                "failed_step": i,
                "guard": guard,
                "operation": internal_tool,
            }

        result = await dispatch_function(internal_tool, internal_args)
        if result.get("error"):
            return {
                "error": result["error"],
                "failed_step": i,
                "operation": internal_tool,
                "filters": result.get("filters"),
            }

        payload = {k: v for k, v in result.items() if k != "filters"}
        step_results.append(payload)
        step_traces.append(
            {
                "step": i,
                "meta_tool": tool,
                "operation": internal_tool,
                "filters": result.get("filters") or internal_args,
                "result": payload,
                "guard": guard,
            }
        )

    return {
        "mode": plan.get("mode", "single"),
        "steps": step_traces,
        "final_operation": step_traces[-1]["operation"] if step_traces else None,
        "final_result": step_results[-1] if step_results else None,
        "final_filters": step_traces[-1]["filters"] if step_traces else None,
    }
