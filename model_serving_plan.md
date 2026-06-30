# Implementation Plan — Model Serving (STUB)

> **Status: stub.** Captures the persistent-backend ↔ model-tier boundary so it
> isn't improvised at deploy time. Not yet phased like `backend_plan.md`; the job
> here is to fix the decisions and the abstraction, then expand into phases when a
> concrete deployment target is chosen. Cross-refs: `backend_plan.md` (Deferred
> workstreams), `frontend_plan.md` (F3 "thinking…" UI), `CLAUDE.md` (privacy
> wedge, model choices).

## Context

Today the backend calls a **local Ollama** (`/api/chat`) on the same host
(`config.ollama_base_url`, `ollama_model`). That's fine for dev, but production
splits into two tiers:

- **Persistent tier** — the FastAPI orchestrator, the read-only Olist pool, the
  app-state store (auth/sessions/history), the Layer 1 cache, audit log. Always
  on, holds all state.
- **Model tier** — a stateless text-in/text-out endpoint. May be co-located
  (local Ollama / on-prem Mac Mini) or remote (RunPod serverless GPU, a persistent
  GPU pod, or an OpenAI-compatible vLLM server).

The model is already a **stateless translator** in our design (question → tool
call; formatting is deterministic in `orchestrator.format_answer`, no second model
call). That statelessness is what makes the tier cleanly separable — but it also
means **nothing about conversation/context lives in the model tier**; all of that
is the persistent tier's job (see `backend_plan.md`).

### What actually crosses the boundary (privacy)
Only the **user's question text** (plus the static system prompt) goes to the
model. **No database rows ever do** — the model never sees query results
(core principle #1). This materially shapes the privacy posture: a remote model
endpoint receives questions, not customer data. For some regulated buyers even the
question text must stay on-prem; for others, questions-only-to-a-Secure-Cloud-GPU
is acceptable. **Topology is therefore a per-customer decision**, not one default.

---

## Deployment topologies (pick per customer)

| Topology | Model host | Data residency | Latency | Cost | Fit |
|---|---|---|---|---|---|
| **Local Ollama** | same box | fully local | low | sunk | dev; tiny single-tenant |
| **On-prem Mac Mini / GPU** | LAN, customer-owned | fully local | low–med | capex | regulated buyers who can't egress anything |
| **Persistent cloud GPU pod** | always-on remote | questions egress | low (warm) | high (24/7 GPU) | latency-sensitive, egress-tolerant |
| **RunPod serverless** | scale-to-zero remote | questions egress (Secure Cloud only) | **cold-start spikes** | low (per-sec) | bursty / cost-sensitive, egress-tolerant |

CLAUDE.md constraint: if cloud, **RunPod Secure Cloud only**. Model size tracks
the host (from earlier analysis): 2B–3B on CPU/small boxes, `granite4.1:8b`-class
on a 16GB Mac Mini / modest GPU, larger only on real GPUs.

---

## The one abstraction to build now: a model client

Regardless of topology, route every model call through a single **`ModelClient`
interface** so the backend never hardcodes Ollama. Replaces the inline `httpx`
call in `orchestrator.call_llm_for_tool`.

```
ModelClient.complete(system_prompt, user_message, *, json=True) -> str
```

Implementations:
- **OllamaClient** — current `/api/chat` (`format: json`, `temperature`, the
  existing retry/timeout logic moves here).
- **OpenAICompatClient** — vLLM / RunPod / most hosted endpoints (`/v1/chat/
  completions`, bearer auth, `response_format` json).

Selected by config (`MODEL_PROVIDER`). The orchestrator's retry, JSON-extraction,
temperature-on-retry, and timeout handling (already in `call_llm_for_tool`) become
provider-agnostic and live around the client, not inside one provider.

---

## Open concerns to resolve before a remote deploy

### Cold starts (serverless)
RunPod serverless scales to zero → first request after idle pays model-load
(commonly **tens of seconds**). Interactions:
- `LLM_TIMEOUT_SECONDS` (currently 90) must cover a cold start, or first requests
  fail. But a 90s inline wait is a bad UX without feedback → **F3 "thinking…/
  warming up" UI** becomes important here (cross-ref frontend plan).
- Mitigations: **min-workers ≥ 1** (warm, costs more — kills the scale-to-zero
  saving), scheduled keep-warm pings, or accept cold starts + clear UI + generous
  timeout. Decision is cost-vs-latency per customer.
- The **Layer 1 cache** hides cold starts on *repeat* questions (cache hit = no
  model call), but not on first/unique ones.

### Endpoint auth & transport
- Remote endpoints need an API key/bearer (`MODEL_API_KEY`) and **TLS**. Local
  Ollama needs neither.
- Never log question text to a third party; keep the audit log on the persistent
  tier only.

### Caching across workers
Server-side KV/prefix caching is **per-worker**. With serverless autoscaling,
prefix-cache reuse across workers is lost, so per-call latency is closer to
cold-prompt-eval. Our **application-level Layer 1 cache lives on the persistent
tier**, so it survives model autoscaling — another reason to keep it.

### Failover & health
- Reuse the existing health probe (`/api/tags` for Ollama; provider-appropriate
  ping otherwise) for the `db/llm` status the frontend already shows.
- `llm_max_attempts` retry already exists; add a **circuit-breaker / friendly
  degradation** when the model tier is down (return a clear "assistant
  temporarily unavailable" rather than a stack of timeouts).

### Statelessness (keep it)
The model tier must stay stateless — no session, no memory. All context lives in
the persistent tier (B0–B4). This is what lets the model tier scale/restart/move
hosts freely.

---

## Config additions (provisional)

```
MODEL_PROVIDER=ollama            # ollama | openai_compat
MODEL_BASE_URL=...               # generalizes ollama_base_url
MODEL_API_KEY=...                # remote endpoints only (bearer); blank for local
MODEL_NAME=...                   # generalizes ollama_model
# LLM_TIMEOUT_SECONDS / LLM_MAX_ATTEMPTS already exist; revisit timeout for cold starts
MODEL_KEEP_WARM=false            # serverless: ping to avoid scale-to-zero cold starts
```

Keep `OLLAMA_*` as accepted aliases during transition.

---

## Open Questions

| Question | Leaning |
|---|---|
| Default prod topology | Per-customer by data-residency: on-prem (Mac Mini) for no-egress buyers; RunPod Secure Cloud for egress-tolerant. No single default. |
| Serverless cold start | Accept + warm-ping + F3 "thinking" UI for cost-sensitive; min-workers≥1 only when latency SLA demands. |
| Client abstraction | `ModelClient` with Ollama + OpenAI-compat impls; provider via config. Build before any remote deploy. |
| Where retry/JSON-parse live | Around the client (provider-agnostic), not inside a provider. |
| Privacy framing | Emphasize: only question text egresses, never DB rows — but offer fully-local topology for buyers who can't egress even that. |

---

## When this graduates from a stub

Expand into phases (M0 client abstraction → M1 remote provider + auth → M2 cold-
start/keep-warm + degradation → M3 per-customer topology playbook) once a concrete
first deployment target is chosen. Until then, the actionable item is **M0: the
`ModelClient` abstraction**, which is safe to build now and de-risks every later
topology.
