# MCP Demo — Verifiable Query

Thin **Model Context Protocol (MCP)** server exposing three tools for hackathon judges and Cursor integration. Demonstrates sophisticated Qwen Cloud stack integration beyond basic chat API calls.

## Tools

| Tool | Description |
|------|-------------|
| `health_check` | Postgres + DashScope LLM status, feature flags |
| `eval_summary` | Eval dataset stats (67+ cases, required flags, pass threshold) |
| `count_orders` | Live order count via meta-router → read-only SQL |

## Run the server

```bash
cd backend
../venv/bin/python -m mcp_server
```

Requires `.env` with `DB_URL` (and `DASHSCOPE_API_KEY` for LLM health check).

## Cursor configuration

Add to **Cursor Settings → MCP** (or `.cursor/mcp.json`):

```json
{
  "mcpServers": {
    "verifiable-query": {
      "command": "/ABS/PATH/TO/basic-analysis/venv/bin/python",
      "args": ["-m", "mcp_server"],
      "cwd": "/ABS/PATH/TO/basic-analysis/backend",
      "env": {
        "META_TOOLS_ENABLED": "true",
        "PLANNER_ENABLED": "true"
      }
    }
  }
}
```

Replace `/ABS/PATH/TO/basic-analysis` with your clone path.

## Example tool calls (from an MCP client)

**health_check**
```json
{}
```

**eval_summary**
```json
{}
```

**count_orders**
```json
{
  "city": "sao paulo",
  "status": "delivered",
  "date_token": "last_month"
}
```

## Planner chain demo

Enable in `.env`:

```env
META_TOOLS_ENABLED=true
PLANNER_ENABLED=true
PLANNER_DEMO_FALLBACK=true
```

Ask in the chat UI:

```
Top category by revenue last year, then best product in that category
```

The UI shows a **Planner chain** trace (2 steps) plus the final top-product card. With `PLANNER_DEMO_FALLBACK=true`, the chain plan is deterministic for demo reliability; without it, Qwen emits the plan JSON.

## Tests

```bash
cd backend
../venv/bin/python -m pytest tests/test_mcp_tools.py tests/test_planner_chain_demo.py -v
```
