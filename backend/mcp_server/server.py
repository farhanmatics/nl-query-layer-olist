#!/usr/bin/env python3
"""Minimal stdio MCP server (Python 3.9+ compatible).

Exposes three tools for hackathon judges / Cursor integration:
  - health_check   — DB + LLM + feature flags
  - eval_summary   — eval set case counts and required flags
  - count_orders   — validated count via meta-router → Postgres

Run:
  cd backend && python -m mcp_server

Cursor config: see docs/mcp-demo.md
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any, Optional

_BACKEND = Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from mcp_server.tools import dispatch_tool  # noqa: E402

logger = logging.getLogger(__name__)
PROTOCOL_VERSION = "2024-11-05"

TOOL_DEFINITIONS = [
    {
        "name": "health_check",
        "description": (
            "Check Verifiable Query backend health: Postgres connectivity, "
            "DashScope LLM reachability, and feature flags (meta_tools, planner, sql_escape)."
        ),
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "eval_summary",
        "description": (
            "Summarize the eval harness datasets (case counts, required feature flags, "
            "pass threshold). Does not run live LLM eval — use pytest for that."
        ),
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "count_orders",
        "description": (
            "Count orders matching optional filters. Uses the same meta-router and "
            "parameterized SQL as the /api/query backend (read-only Postgres)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "city": {"type": "string", "description": "Customer city, e.g. sao paulo"},
                "state": {"type": "string", "description": "Brazilian UF code, e.g. SP"},
                "status": {
                    "type": "string",
                    "description": "Order status, e.g. delivered, shipped, canceled",
                },
                "date_token": {
                    "type": "string",
                    "description": "Relative date: last_month, this_year, etc.",
                },
            },
        },
    },
]


def _response(req_id: Any, result: Any) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _error(req_id: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


async def _handle(req: dict) -> Optional[dict]:
    req_id = req.get("id")
    method = req.get("method", "")
    params = req.get("params") or {}

    if method == "notifications/initialized":
        return None

    if method == "initialize":
        return _response(
            req_id,
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "verifiable-query", "version": "0.1.0"},
            },
        )

    if method == "tools/list":
        return _response(req_id, {"tools": TOOL_DEFINITIONS})

    if method == "tools/call":
        name = params.get("name", "")
        arguments = params.get("arguments") or {}
        try:
            payload = await dispatch_tool(name, arguments)
            return _response(
                req_id,
                {
                    "content": [
                        {"type": "text", "text": json.dumps(payload, indent=2, default=str)}
                    ],
                    "isError": False,
                },
            )
        except Exception as e:
            logger.exception("Tool %s failed", name)
            return _response(
                req_id,
                {
                    "content": [{"type": "text", "text": str(e)}],
                    "isError": True,
                },
            )

    if method == "ping":
        return _response(req_id, {})

    if req_id is not None:
        return _error(req_id, -32601, f"Method not found: {method}")
    return None


async def _ensure_db() -> None:
    from db import get_pool

    await get_pool()


def run_stdio(loop: asyncio.AbstractEventLoop) -> None:
    loop.run_until_complete(_ensure_db())
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        resp = loop.run_until_complete(_handle(req))
        if resp is not None:
            print(json.dumps(resp), flush=True)


def main() -> None:
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        run_stdio(loop)
    finally:
        from db import close_pool

        loop.run_until_complete(close_pool())
        loop.close()


if __name__ == "__main__":
    main()
