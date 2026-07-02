# Implementation Plan — Model Serving (DashScope)

> **Status: implemented on `fa/cloud-dev`.** The backend uses Alibaba DashScope
> `qwen3.7-plus` via the native `dashscope` SDK. Cross-refs: `backend/model_client/`,
> `backend/orchestrator.py`, `CLAUDE.md` (privacy wedge).

## Context

The backend splits into two tiers:

- **Persistent tier** — FastAPI orchestrator, read-only Olist pool, app-state store
  (auth/sessions/history), Layer 1 translation cache, audit log. Always on, holds
  all state.
- **Model tier** — Alibaba DashScope (`qwen3.7-plus`), stateless text-in/text-out.
  Reached via `backend/model_client/dashscope_client.py`.

The model is a **stateless translator** (question → tool call) plus a **formatter**
(aggregates → natural-language sentence). Conversation context (B0–B4) lives
entirely on the persistent tier.

### What crosses the boundary (privacy)

| Data | Egress? |
|------|---------|
| User question text | Yes |
| Static system prompt (tool schemas, few-shots) | Yes |
| Aggregated results (counts, sums, top-N labels) | Yes (for formatting) |
| Raw DB rows | **Never** |
| DB credentials, session tokens | **Never** |

`list_orders` results are sampled (total + first 3 rows) before formatting egress.

For regulated buyers who cannot egress even question text, use a fully local model
branch instead of this cloud deployment.

---

## Implementation

### Model client

```
backend/model_client/
  __init__.py           # get_model_client() singleton
  dashscope_client.py   # DashScopeClient
```

```python
DashScopeClient.complete_json(system, user) -> str   # tool translation
DashScopeClient.complete_text(system, user) -> str # answer formatting
DashScopeClient.health_check() -> bool
```

`qwen3.7-plus` requires `MultiModalConversation.call()` even for text-only
requests, with content shaped as `[{"text": "..."}]`.

The sync `dashscope` SDK runs in a threadpool (`anyio.to_thread.run_sync`) so
the FastAPI event loop is not blocked.

### Orchestrator pipeline (two cloud calls per query)

1. **Tool translation** — `call_llm_for_tool` → `complete_json` with
   `response_format={"type": "json_object"}`, `enable_thinking=False`
2. **Validation + DB query** — unchanged (local)
3. **Answer formatting** — `call_llm_for_format` → `complete_text`; falls back
   to deterministic templates on failure

Retry, JSON extraction, and timeout handling live in `orchestrator.py`.

### Layer 1 cache

Translation cache (question → tool call) still runs on the persistent tier.
Cache hits skip the tool-translation cloud call but always re-query the live DB.

---

## Config

```env
DASHSCOPE_API_KEY=sk-...
DASHSCOPE_BASE_URL=https://dashscope-intl.aliyuncs.com/api/v1
DASHSCOPE_MODEL=qwen3.7-plus
DASHSCOPE_ENABLE_THINKING=false
LLM_TIMEOUT_SECONDS=30
LLM_MAX_ATTEMPTS=2
```

Production boot refuses to start without a valid `DASHSCOPE_API_KEY`.

---

## Health & degradation

- `/api/health` → `llm: ok` when DashScope responds to a minimal ping
- Tool call failures → retry with higher temperature, then error response
- Format failures → deterministic template fallback (number in `result` is always authoritative)
- `llm_max_attempts` retry already exists; circuit-breaker is a future enhancement

---

## Latency expectations

| Step | Typical latency |
|------|-----------------|
| Tool translation | ~1–3s |
| Answer formatting | ~1–2s |
| **Total per query** | **~2–5s** |

Repeat questions may skip tool translation via Layer 1 cache.

---

## Open items (future)

- Streaming SSE for progressive answer rendering (frontend F3)
- Token usage logging in audit records
- Per-customer topology playbook (local vs cloud) as product option
- Circuit-breaker when DashScope is unreachable
