# CLAUDE.md — Natural-Language Query Layer (Olist test bed)

> Standing brief for this project. Read this first every session. Longer design
> detail lives in `docs/architecture.md`; this file is the orientation + rules.

## What we're building

A **trustworthy, self-hosted, natural-language query layer** that lets
non-technical staff ask plain-English questions of a company's operational
database and get exact, verifiable answers — without an analyst, a BI
dashboard, or writing SQL.

Example question: *"How many delivered orders did we have in São Paulo last
month?"* → exact number from the database, rendered in the chat panel.

This repo uses the **Olist Brazilian e-commerce dataset** (loaded in local
Postgres) as a stand-in for a real customer's operational DB. The product is
**schema-agnostic by design** — Olist is the first schema, not the product.

### Business framing (why this exists)
- The value is **faithfulness**: answers a manager can act on without
  double-checking. We are not selling "AI"; we're selling correct answers.
- The wedge is **data stays local** — opens customers who can't ship data to a
  cloud LLM (financial, health, legal, regulated).
- The goal is **recurring revenue from a repeatable product**, not bespoke
  consulting. The strategic unit is "a schema we support," not "a customer."

## Core principles (non-negotiable — enforce in code, never trust the model)

1. **The model never touches the database.** The backend is the only DB client.
   The model only does: (a) question → tool call, (b) rows → formatted answer.
2. **Read-only, always.** The DB role used by the backend has `SELECT` only.
   Write/DDL must be structurally impossible, not merely discouraged.
3. **Predefined functions, not generated SQL.** The model picks a function and
   fills typed arguments. It never authors SQL. (Generated SQL is a fenced,
   far-later escape hatch — see roadmap Phase 4.)
4. **The database does the math.** Counts, sums, averages computed in SQL. The
   model never counts, estimates, or recalls a number.
5. **Deterministic handling of dates, validation, and arithmetic** in the
   backend — never in the model (see "Validation rules" below).
6. **Cap results before they reach the model.** Paginate / aggregate in SQL.
   Never feed thousands of rows into the context window.
7. **Cite the source.** Every answer carries what was queried (table/filters)
   so the user can verify. For operational/financial data this is mandatory.

## Architecture

```
Web panel  <-->  Backend orchestrator  <-->  Model (DashScope cloud today;
                        |                          local Ollama/vLLM as privacy path)
                        v
                  Postgres (read-only role)
```

- **Web panel** — thin. Sends the question, renders structured results.
- **Backend orchestrator** — owns tool definitions, the function-calling loop,
  validation, the read-only DB connection, response assembly. All real logic
  lives here.
- **Model** — stateless translator (cloud DashScope today, local Ollama/vLLM as
  the privacy path), called twice per request (intent in, format out). No DB
  awareness.
- **Postgres** — source of truth, reached only via pre-written parameterized
  queries through a read-only role.

## Tech stack (decisions)

- **DB:** PostgreSQL (already loaded). Dedicated read-only role in place.
- **Model serving (current):** Alibaba **DashScope / Model Studio** (cloud).
  Base translator is `qwen3.6-flash` (multimodal-series → `MultiModalConversation`
  API). A fine-tuned **`qwen3-14b`** (SFT/LoRA on the Olist meta-tool schema, a
  *text* model → `Generation` API) is deployed and selectable via
  `USE_FINETUNED_MODEL`. See `docs/dashscope-finetune.md`,
  `backend/scripts/export_sft_dataset.py`, `backend/scripts/eval_finetune.py`.
- **Model serving (privacy path):** the design stays local-capable — swap the
  DashScope client for Ollama/vLLM (`granite4:3b`, `qwen` 4-9B) with no
  orchestrator changes, for customers who can't ship any text to the cloud.
- **Only aggregates leave the box:** on the cloud path, question text + already-
  aggregated results (counts/sums) are sent for translation/formatting; **raw DB
  rows never leave the server.**
- **Backend:** Python + FastAPI (tool schemas, validation, function-calling loop,
  auth + durable sessions, orchestrator).
- **Frontend:** simple web chat panel (React or plain HTML/JS).
- **Deployment:** local VPS for testing → Mac Mini (on-prem) or RunPod
  serverless (cloud, Secure Cloud only) for production, decided per privacy.

## Database setup

Create the read-only role the backend connects as:

```sql
CREATE ROLE nlq_readonly LOGIN PASSWORD '...';
GRANT CONNECT ON DATABASE <db> TO nlq_readonly;
GRANT USAGE ON SCHEMA public TO nlq_readonly;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO nlq_readonly;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT TO nlq_readonly;
```

Also set, per connection/session, a statement timeout as a safety net:
`SET statement_timeout = '5s';`

## Olist schema (the tables we query)

| Table | Key columns | Notes |
|---|---|---|
| `olist_orders_dataset` | `order_id` PK, `customer_id`, `order_status`, `order_purchase_timestamp`, `order_estimated_delivery_date`, `order_delivered_customer_date` | Core table. `order_status` ∈ {delivered, shipped, canceled, processing, invoiced, unavailable, ...}. |
| `olist_customers_dataset` | `customer_id` PK, `customer_unique_id`, `customer_city`, `customer_state` | **City lives here** — join orders→customers for city/state filters. |
| `olist_order_items_dataset` | (`order_id`,`order_item_id`) PK, `product_id`, `seller_id`, `price`, `freight_value` | One row per item. Order value = sum(price+freight). |
| `olist_order_payments_dataset` | (`order_id`,`payment_sequential`) PK, `payment_type`, `payment_value` | **Revenue source** = sum(`payment_value`). |
| `olist_order_reviews_dataset` | (`review_id`,`order_id`) PK, `review_score` (1-5), `review_creation_date` | Low scores (≤2) are our **"disputes" analog** for prototyping. |
| `olist_products_dataset` | `product_id` PK, `product_category_name` | Category is in Portuguese — join translation for English. |
| `olist_sellers_dataset` | `seller_id` PK, `seller_city`, `seller_state` | Seller-side geography. |
| `product_category_name_translation` | `product_category_name` PK, `_english` | PT → EN category names. |

### Critical data caveat — dates are historical
Olist spans **~Sept 2016 to Oct 2018**. `order_purchase_timestamp` is
`timestamp without time zone`. So *"orders today"* returns zero against real
"now". For testing relative dates, **anchor "today" to the dataset max date**
(≈ `2018-10-17`) via a configurable reference date, or test with explicit
ranges. Do not hardcode `now()` for relative-date logic during dev.

## Function library

Each function = one operation, parameterized. The model only fills arguments.
The library has grown from the original six seed functions to **~44 registered
factories** (`backend/functions/`, wired in `functions/all_factories.py`)
spanning orders, revenue/payments, reviews, products/catalog, sellers,
customers, and delivery metrics.

**The seed six** (the canonical count / lookup / sum / top-N / list shapes):
`get_order_status`, `count_orders`, `get_revenue`, `count_low_reviews`,
`top_products`, `list_orders`.

**Meta-tool layer (`meta_router.py`, `meta_schemas.py`).** Rather than exposing
44 tools to the model, the orchestrator can present **7 generic shapes** —
`count`, `rank`, `sum`, `list`, `breakdown`, `compare`, `lookup` (plus a fenced
`query` for the SQL escape hatch) — parameterized by `entity`/`measure`/
`dimension`. The router resolves a shape+entity to the concrete internal
function. This keeps the model's decision space small and is what the fine-tune
was trained to emit. Gated by `meta_tools_enabled`.

Adding a function = one module in `functions/`, one entry in
`all_factories.py`, one `SOURCE_CITATIONS` line in the active schema config, and
(if it introduces a new shape) a meta-tool mapping.

## Validation rules (backend-owned, pre-query)

- **City normalization:** Olist `customer_city` is lowercase Portuguese (e.g.
  `sao paulo`). Normalize input to lowercase, strip accents, match against the
  distinct set of known cities. Unknown/ambiguous → ask the user, never run a
  query that silently returns 0.
- **Date resolution:** model emits a *token* (`today`, `last_month`, explicit
  range) — backend expands to concrete timestamps against the reference date
  (see date caveat). Model never emits raw dates.
- **Enum validation:** validate `order_status`, `payment_type`, etc. against
  known allowed values before querying.
- **Argument sanity:** validate ID formats, clamp `limit`/`offset`.

## Response format

Backend asks the model for **structured JSON** (e.g.
`{operation, filters, result, source}`) and the frontend renders it (number,
card, table). Free-form prose only as a thin wrapper sentence — never where
structure matters.

## Roadmap

**Phase 0 — Foundation.** ✅ *DONE.* Read-only role; backend skeleton;
`get_order_status` + `count_orders` end-to-end. One working vertical slice.

**Phase 1 — Core function library + panel.** ✅ *DONE.* Seed functions,
validation layer (city, date, enums), structured JSON output, React chat panel.

**Phase 2 — Hardening + trust.** ✅ *DONE.* Citations/verification surface;
result capping & pagination; statement timeouts; request logging + audit
(`audit.py`); LLM/translation caching; an **eval set** (`backend/tests/*.json`)
run on every change. Also added: auth + durable sessions, conversational
multi-turn resolution, and faithfulness guards (e.g. the entity-coherence guard
that refuses to silently pivot a "reviews" turn into a "products" answer).

**Phase 3 — Productization (build-once-sell-many).** ✅ *DONE — see
`backend/schemas/`. Per-schema config; `SCHEMA_NAME` env var selects
the active config at startup; Olist is the default, Shopify is a
configuration-only stub that proves the abstraction generalizes.
Adding a new schema = one config module + one entry in
`schemas/__init__.py::_BUILTIN`. The function library, validation
layer, and orchestrator's system prompt all read from the active
config — no other code changes needed.*

**Phase 4 — Long tail.** ✅ *Largely DONE (feature-flagged).*
- Fenced generated-SQL escape hatch (`functions/sql_escape.py`, read-only role,
  mandatory LIMIT, timeouts, allowlisted tables) — `sql_escape_enabled`.
- Meta-tool layer (7 generic shapes) — `meta_tools_enabled`.
- Multi-step/agentic orchestration (`chain_executor.py`, `planner_*`) —
  `planner_enabled`, `planner_max_steps`.
- **Model fine-tuning** on the Olist schema (SFT/LoRA on `qwen3-14b` via
  DashScope) — dataset export + augmentation + base-vs-finetune eval harness.
- **MCP server** (`backend/mcp_server/`) exposing tools to Cursor/judges.
- *Remaining/optional:* delivery channels (Slack, scheduled digests).

## Open questions to resolve as we build
- ~~Reference-date strategy for relative dates in the historical dataset.~~
  *Resolved: `reference_date` config anchors "today" to the dataset max; the
  date validator expands tokens against `settings.reference_datetime`.*
- ~~Exact JSON response contract between backend and frontend.~~ *Resolved:
  `QueryResponse` (`backend/main.py`) → the frontend `ResultCard` renders
  number/card/table with the citation surface.*
- ~~How much per-schema config Phase 3 actually needs.~~ *Resolved
  by the SchemaConfig shape: tables + columns + enums + states + scope
  + prompt. The `tests/test_schemas.py` suite pins the contract.*
- **Fine-tune value:** on the in-distribution eval the fine-tuned `qwen3-14b`
  is at *parity* with base `qwen3.6-flash` (both ~92%, misses are gold-label
  gaps) — base is already at ceiling. A measurable win would require retraining
  with a minimal system prompt (prompt-compression) or a harder OOD eval. Also:
  clean the eval gold's systematic omissions (`entity` on rank, `score_max` on
  reviews) that cap every accuracy number.
- Target production deployment: on-prem (Mac Mini) vs serverless — gated by the
  customer's data-residency requirements.
