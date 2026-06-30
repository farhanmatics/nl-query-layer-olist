# Natural-Language Query Layer on Olist Dataset

A **self-hosted, trustworthy natural-language query system** that lets non-technical staff ask plain-English questions about operational data and get exact, verifiable answers from a database—without writing SQL or needing a data analyst.

> Built on the Olist Brazilian e-commerce dataset as a test bed, but schema-agnostic by design. The product is the repeatable pattern, not the dataset.

---

## Table of Contents

- [The Problem](#the-problem)
- [The Solution](#the-solution)
- [Core Principles (Non-Negotiable)](#core-principles-non-negotiable)
- [Architecture](#architecture)
- [Tech Stack](#tech-stack)
- [Database Schema (Olist)](#database-schema-olist)
- [Project Phases](#project-phases)
- [Getting Started](#getting-started)
  - [TL;DR — Run the whole thing](#tldr--run-the-whole-thing)
  - [Prerequisites](#prerequisites)
  - [1. Clone & Setup Backend](#1-clone--setup-backend)
  - [2. Set Up the Database (Migrations)](#2-set-up-the-database-migrations)
  - [3. Start Ollama](#3-start-ollama)
  - [4. Start Backend](#4-start-backend)
  - [5. Setup & Start Frontend](#5-setup--start-frontend)
  - [6. Test](#6-test)
- [API Endpoints](#api-endpoints)
- [Function Library](#function-library)
- [Project Files](#project-files)
- [Testing & Evaluation](#testing--evaluation)
- [Security & Trust](#security--trust)
- [Contributing](#contributing)
- [License](#license)
- [Questions?](#questions)
- [Roadmap](#roadmap)

---

## The Problem

Most organizations have critical operational data locked in databases that only analysts can access. Business users hit analysts with ad-hoc questions, creating bottlenecks. BI dashboards don't cover every question. And sending data to cloud LLM APIs raises compliance concerns.

## The Solution

A **local, read-only query layer** that:
- Translates plain-English questions into typed function calls (not SQL)
- Executes pre-written, parameterized database queries (no model-generated SQL)
- Returns structured, verifiable answers with citations
- Keeps data on-prem and never sends it to an external API

**Example:**
```
Q: "How many delivered orders did we have in São Paulo last month?"
→ [Backend resolves city name, date range, validates status]
→ [Runs parameterized query]
→ [Returns: 1,423 orders from olist_orders_dataset JOIN olist_customers_dataset]
```

---

## Core Principles (Non-Negotiable)

1. **The model never touches the database.** It only translates intent into tool calls; the backend executes queries.
2. **Read-only, always.** DB role has `SELECT` only. Write/DDL is structurally impossible.
3. **Pre-defined functions, not generated SQL.** The model fills typed arguments; it never authors SQL.
4. **The database does the math.** Sums, counts, averages computed in SQL, not the model.
5. **Deterministic validation.** Dates, cities, enums validated server-side before querying.
6. **Results capped before reaching the model.** Pagination/aggregation in SQL; never feed thousands of rows into the LLM context.
7. **Every answer is cited.** Users see what table/filters were queried so they can verify.

---

## Architecture

```
Web Panel (React)  ←→  Backend (FastAPI)  ←→  Local Model (Ollama + qwen3.5:2b)
                              ↓
                        Postgres (read-only role)
```

- **Web Panel** — thin chat UI for questions and structured results
- **Backend Orchestrator** — owns tool definitions, validation, function dispatch, and the read-only DB connection. Also runs the cross-cutting trust layer: a translation cache, a deterministic filter-faithfulness guard, per-request audit logging, and client-facing error sanitization.
- **Local LLM** — stateless intent translator (question → tool call, rows → formatted answer)
- **PostgreSQL** — source of truth, reached only via pre-written parameterized queries

---

## Tech Stack

| Layer | Technology |
|-------|------------|
| **Backend** | Python 3.9+ · FastAPI · asyncpg (async Postgres) |
| **Frontend** | React + TypeScript · Vite · TailwindCSS |
| **LLM** | Ollama · qwen3.5:2b (2B params, excellent tool-calling, CPU-friendly) |
| **Database** | PostgreSQL (read-only role) |
| **Deployment** | Local dev (Mac/Linux) · VPS ready · schema-agnostic via `SCHEMA_NAME` |

---

## Database Schema (Olist)

The Olist dataset captures 2.5+ years of Brazilian e-commerce data (Sept 2016 – Oct 2018):

| Table | Purpose | Key Columns |
|-------|---------|-------------|
| `olist_orders_dataset` | Core orders | `order_id`, `customer_id`, `order_status`, `order_purchase_timestamp` |
| `olist_customers_dataset` | Customer geography | `customer_id`, `customer_city`, `customer_state` |
| `olist_order_items_dataset` | Order line items | `order_id`, `product_id`, `seller_id`, `price`, `freight_value` |
| `olist_order_payments_dataset` | Payment records | `order_id`, `payment_type`, `payment_value` |
| `olist_order_reviews_dataset` | Customer reviews | `review_id`, `order_id`, `review_score` (1-5) |
| `olist_products_dataset` | Product metadata | `product_id`, `product_category_name` |
| `olist_sellers_dataset` | Seller info | `seller_id`, `seller_city`, `seller_state` |
| `product_category_name_translation` | PT → EN | `product_category_name`, `product_category_name_english` |

**Note:** Dataset is historical. Order volume is rich through **August 2018** then drops to near-zero (Sept: 16 orders, Oct: 4). The true max purchase date is `2018-10-17`, but relative date expressions ("last month", "today") anchor to `2018-08-20` (`REFERENCE_DATE`) so demo queries land in data-rich windows.

---

## Project Phases

> **Current status:** Phases 0, 1, and 2 are complete and operational.

### Phase 0 — Foundation ✅
Prove the vertical slice end-to-end:
- ✅ Database read-only role
- ✅ Backend skeleton (FastAPI, async DB, config)
- ✅ Validation layer (cities, dates, enums)
- ✅ First two functions: `get_order_status`, `count_orders`
- ✅ Orchestrator (LLM tool-calling loop)
- ✅ React chat panel

**Success criteria met:** "How many delivered orders in São Paulo last month?" → exact number + citation.

### Phase 1 — Core Library + MVP ✅
- ✅ All six functions implemented (`get_order_status`, `count_orders`, `get_revenue`, `count_low_reviews`, `top_products`, `list_orders`)
- ✅ Full validation layer with fuzzy city matching
- ✅ Eval set: 50 question/answer pairs (currently **94%** pass; harness gate at 85%)
- ✅ Structured JSON response contract finalized

### Phase 2 — Hardening & Trust ✅
- ✅ Per-request audit log (append-only JSONL, row-free result summaries)
- ✅ Layer 1 translation cache (question → tool call; live DB still queried on hits)
- ✅ Deterministic filter-faithfulness guard (repairs/blocks dropped filters)
- ✅ Statement timeouts (`SET statement_timeout` per session)
- ✅ Result caps & pagination enforcement (`list_orders` ≤ 50, `top_products` ≤ 25)
- ✅ Client error sanitization (no DB/internal leakage to the client)
- ✅ Request validation (empty / oversized questions rejected with HTTP 422)
- ✅ Rate limiting (sliding-window per IP, configurable via `RATE_LIMIT_PER_MINUTE`)
- ✅ `/api/eval` endpoint for CI integration (returns pass rate + threshold check)
- ✅ Global row cap (queries returning >200 rows rejected via `RowCapExceeded`)

### Phase 3 — Productization ✅
Schema-agnostic onboarding via per-schema config. The active schema is
selected at startup via the `SCHEMA_NAME` env var (default: `olist`).
Each schema is a self-contained module under `backend/schemas/<name>/`
with a `SchemaConfig` dataclass: tables, columns, enums, state codes,
out-of-scope lexicon, prompt text + few-shots, and source citations.
The function library, validation layer, and orchestrator's system
prompt all read from the active config — no per-schema code paths.
- `SCHEMA_NAME=olist` — default; runs against the Olist Brazilian e-commerce dataset
- `SCHEMA_NAME=shopify` — config-only stub that proves the abstraction
  generalizes (its functions return a "not wired" error until a real
  Shopify adapter lands)
- Adding a new schema = one config module + one entry in
  `schemas/__init__.py::_BUILTIN`

### Phase 4 — Long Tail (Optional)
- Fenced generated-SQL escape hatch (read-only role, LIMIT enforced)
- Multi-step orchestration
- Slack/email delivery channels

---

## Getting Started

### TL;DR — Run the whole thing

Assuming Postgres has the `olist` DB loaded, the `nlq_readonly` role exists (see step 2), `.env` is configured, deps are installed, and the model is pulled, you need **three things running**:

```bash
# 1. Ollama (if not already running as a service)
ollama serve

# 2. Backend (terminal 1) — from the repo root
cd backend && ../venv/bin/uvicorn main:app --reload --port 8000
#   (or: source venv/bin/activate, then `cd backend && uvicorn main:app --reload --port 8000`)

# 3. Frontend (terminal 2)
cd frontend && npm run dev
```

Then open **http://localhost:3000** and ask a question. The Vite dev server proxies `/api/*` to the backend on `:8000`, so no CORS or URL config is needed.

Quick sanity checks:
```bash
curl http://localhost:8000/api/health          # {"db":"ok","llm":"ok",...}
curl -X POST http://localhost:8000/api/query \
  -H "Content-Type: application/json" \
  -d '{"question":"How many delivered orders in São Paulo last month?"}'
```

First-time setup (DB role, venv, `.env`, model) is detailed in the numbered steps below.

### Prerequisites

- **Python 3.9+** (3.9 verified working; 3.10+ also fine)
- **Node.js 18+** (for frontend)
- **PostgreSQL 12+** with the Olist dataset loaded
- **Ollama** running locally with `qwen3.5:2b` pulled

### 1. Clone & Setup Backend

```bash
git clone https://github.com/farhanmatics/nl-query-layer-olist.git
cd nl-query-layer-olist

# Create Python venv
python3 -m venv venv
source venv/bin/activate  # macOS/Linux
# or: venv\Scripts\activate  # Windows

# Install dependencies
pip install -r backend/requirements.txt

# Copy .env.example and configure
cp .env.example .env
# Edit .env with your DB credentials, Ollama URL, etc.
```

### 2. Set Up the Database (Migrations)

The backend ships a small, dependency-free migration runner (`backend/migrate.py`)
that creates the Olist schema (tables, indexes, foreign keys) **and** the
read-only `nlq_readonly` role. Migrations are idempotent and tracked in a
`schema_migrations` table, so they run exactly once and are safe to re-run.

> The running app connects with the read-only role and can never alter the
> schema. Migrations use a separate admin/superuser connection, configured via
> `MIGRATION_DB_URL` in `.env` (needs `CREATE` + `CREATEROLE`, e.g.
> `postgresql://postgres:pass@localhost/olist`).

```bash
cd backend

# (optional) create the target database if it doesn't exist yet
../venv/bin/python migrate.py create-db

# see what will run
../venv/bin/python migrate.py status

# apply all pending migrations (schema + read-only role)
../venv/bin/python migrate.py up
```

After running, change the default role password and update `.env` to match:
```sql
ALTER ROLE nlq_readonly WITH PASSWORD 'your-strong-password';
```
```bash
# .env
DB_URL=postgresql://nlq_readonly:your-strong-password@localhost/olist
```

**Loading data:** migrations create the *structure* only. Load the Olist CSVs
(from Kaggle) into the tables separately, e.g. with `\copy` in `psql`, or restore
a full dump. The app needs data present to return non-empty answers.

<details>
<summary>Manual alternative (no migration runner)</summary>

```bash
psql -d olist -f olist_tables_structure.sql   # schema
psql -d olist -f sql/readonly_role.sql        # read-only role
```
</details>

### 3. Start Ollama

```bash
ollama serve
# In another terminal:
ollama pull qwen3.5:2b
```

### 4. Start Backend

```bash
cd backend
uvicorn main:app --reload --port 8000
```

Visit `http://localhost:8000/api/health` to verify backend + DB + LLM connectivity.

### 5. Setup & Start Frontend

```bash
cd frontend
npm install
npm run dev
```

Visit `http://localhost:3000` to open the chat panel.

### 6. Test

First, get a real order ID from the database:
```bash
psql -U nlq_readonly -d olist -c "SELECT order_id FROM olist_orders_dataset LIMIT 1;"
```

Then ask questions:
> "What is the status of order abc123xyz?" (replace with real order_id)
> "How many delivered orders did we have in São Paulo last month?"

---

## API Endpoints

### `POST /api/query`
Ask a natural-language question.

**Request:**
```json
{
  "question": "How many delivered orders in São Paulo last month?"
}
```

**Response:**
```json
{
  "operation": "count_orders",
  "filters": {
    "city": "sao paulo",
    "status": "delivered",
    "date_range": ["2018-07-01T00:00:00", "2018-07-31T23:59:59"]
  },
  "result": {
    "count": 1059
  },
  "formatted_answer": "There were 1,059 orders (city: sao paulo status: delivered ...).",
  "source": "olist_orders_dataset JOIN olist_customers_dataset",
  "error": null,
  "cached": false,
  "guard": { "repairs": {}, "applied": [], "unresolved": [] }
}
```

- `cached` — `true` when the question→tool translation was served from the Layer 1 cache (the DB is still queried, so the number is always live).
- `guard` — what the filter-faithfulness guard did: `applied` lists filters it recovered from the question that the model had dropped; `unresolved` lists detected-but-unsafe filters (when non-empty, the request is refused rather than answered with a wrong number).
- Empty or oversized questions are rejected with **HTTP 422** before reaching the model or DB.

### `GET /api/health`
Check backend, database, and LLM connectivity.

**Response:**
```json
{
  "db": "ok",
  "llm": "ok",
  "timestamp": "2026-06-23T..."
}
```

### `GET /api/cache/stats`
Layer 1 translation-cache stats: `{entries, max_entries, hits, misses, hit_rate, ttl_seconds, enabled}`.

### `POST /api/cache/clear`
Flush the translation cache (e.g. after manually changing the prompt). Returns `{"cleared": true}`.

### `POST /api/eval`
Run the eval set (50 test cases) and return pass/fail results for CI integration.

**Response:**
```json
{
  "total": 50,
  "passed": 47,
  "failed": 3,
  "pass_rate": 0.94,
  "threshold": 0.85,
  "threshold_met": true,
  "results": [
    {"id": "e01", "question": "...", "passed": true, "reason": "ok", ...},
    ...
  ]
}
```

CI can check `threshold_met` to decide whether to fail the build.

### Rate Limiting
All `/api/*` endpoints are rate-limited to **30 requests/minute per IP** (configurable via `RATE_LIMIT_PER_MINUTE`). Exceeding the limit returns **HTTP 429**:
```json
{"error": "Rate limit exceeded (30 requests/minute)"}
```

---

## Function Library

Six core functions handle the majority of real-world questions:

1. **`get_order_status(order_id)`** — Lookup a single order's status and key dates
2. **`count_orders(city?, state?, status?, date_range?)`** — Count orders with filters
3. **`get_revenue(date_range?, city?, state?, category?, group_by?)`** — Sum payment values
4. **`count_low_reviews(score_max=2, city?, date_range?)`** — Count low-scoring reviews (disputes analog)
5. **`top_products(date_range?, limit=10, by='count'|'revenue')`** — Top-N products by count or revenue
6. **`list_orders(filters, limit=20, offset=0)`** — Paginated order lookup

Each function is a **pre-written parameterized query**. The LLM only fills typed arguments.

---

## Project Files

- `CLAUDE.md` — Standing brief with architecture & principles
- `project_plan.md` — Detailed implementation roadmap (Phase 0–2)
- `olist_tables_structure.sql` — PostgreSQL schema dump (reference)
- `sql/readonly_role.sql` — Read-only role definition (manual setup)
- `backend/migrate.py` — Database migration runner (`status` / `up` / `create-db`)
- `backend/migrations/` — Ordered, idempotent SQL migrations (schema + role)
- `backend/` — Python FastAPI application
  - `orchestrator.py` — tool-calling loop, prompt, caching + guard wiring
  - `functions/` — the six parameterized query functions + registry
  - `validation/` — cities, dates, enums, and the filter-faithfulness guard
  - `cache.py` — Layer 1 LLM-translation cache (TTL + LRU)
  - `audit.py` — append-only JSONL per-request audit log
  - `errors.py` — client-facing error sanitization
- `frontend/` — React + TypeScript chat panel
- `logs/audit.jsonl` — per-request audit trail (created at runtime)
- `.env.example` — Environment variable template

---

## Testing & Evaluation

### Unit Tests (no LLM required)
These hit the DB and pure logic directly, bypassing the model:
```bash
cd backend
pytest tests/test_functions.py -v          # the six functions against real data
pytest tests/test_cache.py -v              # translation cache: hit/miss/TTL/LRU
pytest tests/test_faithfulness.py -v       # filter-guard detection/repair
pytest tests/test_audit.py -v              # audit record shape + JSONL writing
pytest tests/test_request_validation.py -v # empty/oversized question rejection
```

### Eval Set (50 Q/A pairs, needs the backend + Ollama running)
```bash
# standalone report (prints per-case PASS/FAIL + pass rate):
API_URL=http://localhost:8000 ../venv/bin/python tests/test_eval.py
# or under pytest (skips if backend unreachable, fails below threshold):
pytest tests/test_eval.py -v
```

Current: **94% pass** with `qwen3.5:2b`. The harness gate is **85%** — a realistic
floor for a 2B dev model (tool selection is near-perfect; the residual gap is
filter faithfulness on ambiguous phrasings, which a larger model closes). The
eval's job is to catch regressions below that floor, not to certify the model.

---

## Security & Trust

✅ **Read-only database role** — no write/DDL possible, enforced by PostgreSQL  
✅ **No LLM-authored SQL** — only pre-written, parameterized queries  
✅ **Statement timeouts** — `SET statement_timeout` per session  
✅ **Result capping** — pagination enforced in SQL (`list_orders` ≤ 50, `top_products` ≤ 25); never thousands of rows into the model  
✅ **Filter-faithfulness guard** — recovers filters the model dropped, and refuses rather than return a confidently wrong number it can't apply safely  
✅ **Out-of-scope guard** — declines concepts the schema can't answer (returns, refunds, profit, inventory, …) with an honest "not tracked" message instead of silently substituting a proxy  
✅ **Citations** — every answer shows what table/filters were queried  
✅ **Validation** — all user inputs (cities, dates, enums) validated before querying; empty/oversized questions rejected with HTTP 422  
✅ **Audit log** — one append-only JSONL record per request (question, tool, filters, row-free result summary, timing, guard repairs) for verifiable answers  
✅ **Error sanitization** — raw DB/internal errors never leak to the client (configurable for dev)  
✅ **Authentication** — argon2id password hashing (off the event loop), signed httpOnly session cookies, CSRF double-submit, per-(email, IP) throttling on login **and** register, uniform login errors (no user enumeration), and a production boot guard that refuses to start with a default `SESSION_SECRET` or `COOKIE_SECURE=false`  
✅ **Multi-tenant isolation (IDOR-safe)** — every session/message route enforces ownership and returns **404** (not 403) on cross-user or unknown ids; `/api/query` re-checks session ownership before persisting; `ON DELETE CASCADE` wipes a user's sessions and messages  

This is designed for **regulated environments** (finance, health, legal) where data can't leave the building and answers must be auditable.

### Accepted risks (single-tenant / local deployment)

The current target is **one self-hosted instance per customer**. Under that model the following are accepted, and should be revisited before any **multi-user-per-customer** or **public** deployment:

- **`/api/eval` and `/api/cache/clear` are available to any authenticated user.** `/api/eval` runs the full eval set (~100 LLM calls/request) and `/api/cache/clear` flushes the shared translation cache. There is no role/admin tier yet (the `role` column is reserved). For multi-user, gate these behind an admin role or disable them in production.
- **Anonymous `/api/query` accepts a client-supplied `session_id`** keyed to a process-global, TTL-bounded in-memory context store (F2-early back-compat). It never reads or writes another user's **durable** history (that requires auth + ownership), but a guessed `session_id` could pollute or evict ephemeral context. For multi-user, require authentication whenever `session_id` is present.

---

## Contributing

This is an active R&D project. Issues and PRs welcome.

For architecture deep-dives, see `CLAUDE.md` and `project_plan.md`.

---

## License

MIT

---

## Questions?

- **What is this actually for?** See `CLAUDE.md` (standing brief)
- **How do I build this?** See `project_plan.md` (implementation roadmap)
- **Why no generated SQL?** See "Core Principles" above (faithfulness + control)
- **Can I use my own database?** Yes — Phase 3 makes this schema-agnostic. For now, load Olist as a testbed.

---

## Roadmap

- [x] Project brief & architecture (CLAUDE.md)
- [x] Implementation plan (project_plan.md)
- [x] Phase 0: Vertical slice (get_order_status + count_orders)
- [x] Phase 1: Full function library + eval set
- [x] Phase 2: Hardening (audit log, cache, faithfulness guard, timeouts, row caps, rate limiting, error sanitization, request validation, `/api/eval`)
- [ ] Phase 3: Schema extraction (config-driven onboarding)
- [ ] Phase 4: Long tail (SQL escape hatch, multi-step, integrations)

---

**Built with ❤️ for trustworthy, local data access.**
