"""MCP tool implementations — read-only access to health, eval stats, and count_orders."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from config import settings


def eval_dataset_summary() -> dict[str, Any]:
    """Summarize eval sets without running live LLM calls."""
    tests_dir = Path(__file__).resolve().parent.parent / "tests"
    files = {
        "eval_set.json": tests_dir / "eval_set.json",
        "meta_eval_set.json": tests_dir / "meta_eval_set.json",
        "chain_eval_set.json": tests_dir / "chain_eval_set.json",
    }
    summary: dict[str, Any] = {
        "pass_threshold": 0.85,
        "live_eval_command": "pytest backend/tests/test_eval.py -m live -v",
        "datasets": {},
        "total_cases": 0,
        "flags_required": {
            "requires_meta_tools": 0,
            "requires_sql_escape": 0,
            "requires_planner": 0,
        },
    }
    for name, path in files.items():
        if not path.exists():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        cases = data.get("cases", [])
        summary["datasets"][name] = len(cases)
        summary["total_cases"] += len(cases)
        for case in cases:
            if case.get("requires_meta_tools"):
                summary["flags_required"]["requires_meta_tools"] += 1
            if case.get("requires_sql_escape"):
                summary["flags_required"]["requires_sql_escape"] += 1
            if case.get("requires_planner"):
                summary["flags_required"]["requires_planner"] += 1
    summary["server_flags"] = {
        "meta_tools_enabled": settings.meta_tools_enabled,
        "sql_escape_enabled": settings.sql_escape_enabled,
        "planner_enabled": settings.planner_enabled,
        "planner_demo_fallback": settings.planner_demo_fallback,
        "active_llm_model": settings.active_llm_model,
    }
    return summary


async def service_health() -> dict[str, Any]:
    from db import check_db_health

    db_ok = await check_db_health()
    llm_ok = False
    try:
        from model_client import get_model_client

        llm_ok = await get_model_client().health_check()
    except Exception:
        llm_ok = False
    return {
        "db": "ok" if db_ok else "error",
        "llm": "ok" if llm_ok else "error",
        "llm_model": settings.active_llm_model,
        "meta_tools": "enabled" if settings.meta_tools_enabled else "disabled",
        "sql_escape": "enabled" if settings.sql_escape_enabled else "disabled",
        "planner": "enabled" if settings.planner_enabled else "disabled",
        "finetuned": "enabled" if settings.use_finetuned_model else "disabled",
    }


async def count_orders_tool(
    *,
    city: Optional[str] = None,
    state: Optional[str] = None,
    status: Optional[str] = None,
    date_token: Optional[str] = None,
) -> dict[str, Any]:
    """Run count_orders via meta-router (same path as /api/query backend)."""
    from meta_router import resolve_meta_call
    from orchestrator import dispatch_function

    args: dict[str, Any] = {"entity": "orders"}
    if city:
        args["city"] = city
    if state:
        args["state"] = state
    if status:
        args["status"] = status
    if date_token:
        args["date_token"] = date_token

    tool_name, internal_args = resolve_meta_call("count", args, "")
    result = await dispatch_function(tool_name, internal_args)
    return {
        "meta_tool": "count",
        "operation": tool_name,
        "args": internal_args,
        "result": {k: v for k, v in result.items() if k != "filters"},
        "filters": result.get("filters"),
        "error": result.get("error"),
    }


async def dispatch_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if name == "health_check":
        return await service_health()
    if name == "eval_summary":
        return eval_dataset_summary()
    if name == "count_orders":
        return await count_orders_tool(**arguments)
    raise ValueError(f"Unknown tool: {name}")
