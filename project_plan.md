# Implementation Plan — Natural-Language Query Layer (Olist)

## Context

Build a self-hosted, trustworthy NL→SQL query layer on top of the Olist PostgreSQL dataset. Non-technical staff ask plain-English questions; a local LLM translates intent into a typed function call; the backend executes a pre-written parameterized query and returns a verifiable, structured answer. The model never touches the DB and never authors SQL.

Stack: Python + FastAPI · PostgreSQL (read-only role) · Ollama + qwen3.5:2b · React chat panel · Local dev deployment · Dataset max-date anchor (2018-10-17) for relative date resolution.

---

## Directory Structure

```
basic-analysis/
├── backend/
│   ├── main.py                  # FastAPI app entrypoint
│   ├── config.py                # Settings (DB URL, Ollama URL, SCHEMA_NAME, ...)
│   ├── db.py                    # Read-only async DB connection (asyncpg)
│   ├── orchestrator.py          # Tool-calling loop: question → LLM → validated call → answer
│   ├── appdb.py                 # Read-write app-state DB (users, auth_sessions, chat sessions)
│   ├── auth.py / auth_routes.py / auth_rate_limit.py
│   ├── session_routes.py        # B3: chat session CRUD (IDOR-safe)
│   ├── functions/
│   │   ├── __init__.py
│   │   ├── registry.py          # Maps tool names → handler functions + JSON schemas
│   │   ├── get_order_status.py
│   │   ├── count_orders.py
│   │   ├── get_revenue.py
│   │   ├── count_low_reviews.py
│   │   ├── top_products.py
│   │   └── list_orders.py
│   ├── schemas/                 # Phase 3: per-schema config
│   │   ├── __init__.py          # Loader, registry, SCHEMA_NAME env var
│   │   ├── base.py              # SchemaConfig, ColumnRef, ScopePattern, PromptConfig
│   │   ├── olist/config.py      # Default (Olist Brazilian e-commerce)
│   │   └── shopify/config.py    # Stub (proves the abstraction generalizes)
│   ├── validation/
│   │   ├── __init__.py
│   │   ├── cities.py            # Schema-aware known-city loader
│   │   ├── categories.py        # Schema-aware known-category loader
│   │   ├── dates.py             # Token → concrete timestamp range
│   │   ├── enums.py             # Schema-aware enum validators
│   │   ├── scope.py             # Schema-aware out-of-scope guard
│   │   ├── detectors.py         # Shared detector set (state/city/date/status/category)
│   │   └── faithfulness.py      # Filter-faithfulness guard
│   ├── resolver.py              # B0 conversational resolution
│   ├── cache.py                 # Layer 1 translation cache
│   ├── audit.py                 # B2 per-request audit log
│   └── tests/                   # test_*.py
├── frontend/
│   ├── src/
│   │   ├── App.tsx
│   │   ├── pages/               # LoginPage, RegisterPage, ChatPage
│   │   ├── auth/                # AuthContext, ProtectedRoute
│   │   ├── session/             # SessionContext (F1)
│   │   ├── theme/               # ThemeContext (F-T theming)
│   │   ├── components/
│   │   │   ├── ChatPanel.tsx
│   │   │   ├── MessageBubble.tsx
│   │   │   ├── ResultCard.tsx
│   │   │   ├── Sidebar.tsx      # F1
│   │   │   ├── AuthCard.tsx
│   │   │   ├── AccountMenu.tsx
│   │   │   ├── ThemeToggle.tsx
│   │   │   ├── CarryoverChip.tsx
│   │   │   └── ClarifyPrompt.tsx
│   │   └── api.ts               # fetch wrapper (credentials, CSRF, 401)
│   └── package.json
├── sql/
│   ├── olist_tables_structure.sql  # existing schema
│   └── readonly_role.sql           # CREATE ROLE + GRANT statements
├── migrations_app/             # App-state DB migrations (users, auth_sessions, ...)
├── .env.example
└── docker-compose.yml           # optional: postgres + ollama for fresh-machine setup
```

---

## Phase 0 — Foundation

### Step 1: Database — Read-Only Role

Create `sql/readonly_role.sql`:

```sql
CREATE ROLE nlq_readonly LOGIN PASSWORD 'changeme';
GRANT CONNECT ON DATABASE olist TO nlq_readonly;
GRANT USAGE ON SCHEMA public TO nlq_readonly;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO nlq_readonly;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT TO nlq_readonly;
```

Apply with:
```bash
psql -U postgres -d olist -f sql/readonly_role.sql
```

The backend connects exclusively as `nlq_readonly`. No write path exists structurally.

---

### Step 2: Backend Skeleton

**`config.py`** — load from `.env`:
```python
DB_URL = "postgresql://nlq_readonly:changeme@localhost/olist"
OLLAMA_BASE_URL = "http://localhost:11434"
OLLAMA_MODEL = "qwen3.5:2b"
REFERENCE_DATE = "2018-10-17"   # dataset max date — anchors "today" / "last month"
```

**`db.py`** — async connection pool (asyncpg):
- `get_pool()` → singleton asyncpg pool
- Each request: `SET statement_timeout = '5s'` on the connection before any query
- Pool min=2, max=10

**`main.py`** — FastAPI app:
```
POST /api/query    { "question": str } → { "result": ..., "source": ..., "error": str|null }
GET  /api/health   → { "db": ok, "llm": ok }
```

CORS enabled for localhost:3000 (React dev server).

---

### Step 3: Validation Layer

**`validation/cities.py`**
- On startup: `SELECT DISTINCT customer_city FROM olist_customers_dataset` → build a set of ~5000 known cities
- `normalize(city: str) → str`: lowercase + strip accents (using `unicodedata`)
- `resolve(city: str) → str | None`: exact match first, then fuzzy via `difflib.get_close_matches` (cutoff 0.85, n=1). If no match → `None` (backend returns "city not found, did you mean X?" — never queries)

**`validation/dates.py`**
- Token vocabulary the LLM is told to emit: `today`, `yesterday`, `this_week`, `last_week`, `this_month`, `last_month`, `this_year`, `last_year`, or `{"from": "YYYY-MM-DD", "to": "YYYY-MM-DD"}`
- `resolve(token, reference_date=REFERENCE_DATE) → (start: datetime, end: datetime)`
- All arithmetic done in Python against the reference date anchor

**`validation/enums.py`**
- `ORDER_STATUSES = {"delivered","shipped","canceled","processing","invoiced","unavailable","approved","created"}`
- `PAYMENT_TYPES = {"credit_card","boleto","voucher","debit_card","not_defined"}`
- Validators raise a typed `ValidationError` returned to the user as a clarification prompt

---

### Step 4: Function Library

Each function lives in `functions/<name>.py`. Pattern:

```python
async def execute(pool, **validated_args) -> dict:
    # runs one parameterized query via asyncpg
    # returns {"count": N, "filters": {...}} or equivalent
    ...

SCHEMA = {
    "name": "count_orders",
    "description": "...",
    "parameters": { ... }   # JSON Schema — what the LLM fills in
}
```

**Function 1 — `get_order_status(order_id: str)`**
```sql
SELECT order_id, order_status,
       order_purchase_timestamp, order_delivered_customer_date,
       order_estimated_delivery_date
FROM olist_orders_dataset
WHERE order_id = $1
```
Returns: status card with dates. Simplest vertical slice.

**Function 2 — `count_orders(city?, state?, status?, date_token?)`**
```sql
SELECT COUNT(*) FROM olist_orders_dataset o
JOIN olist_customers_dataset c ON o.customer_id = c.customer_id
WHERE ($1::text IS NULL OR c.customer_city = $1)
  AND ($2::text IS NULL OR c.customer_state = $2)
  AND ($3::text IS NULL OR o.order_status = $3)
  AND ($4::timestamp IS NULL OR o.order_purchase_timestamp >= $4)
  AND ($5::timestamp IS NULL OR o.order_purchase_timestamp < $5)
```
City arg runs through `validation/cities.py` before the query. Date token runs through `validation/dates.py`.

**Function 3 — `get_revenue(date_token?, state?, category?, group_by?)`**
```sql
SELECT SUM(p.payment_value) as revenue
FROM olist_order_payments_dataset p
JOIN olist_orders_dataset o ON p.order_id = o.order_id
JOIN olist_customers_dataset c ON o.customer_id = c.customer_id
-- optional: JOIN items→products→translation for category filter
WHERE ...
```
`group_by` ∈ {state, category, month} — drives a GROUP BY clause variation (3 pre-written query variants, not dynamic SQL construction).

**Function 4 — `count_low_reviews(score_max=2, city?, date_token?)`**
```sql
SELECT COUNT(*) FROM olist_order_reviews_dataset r
JOIN olist_orders_dataset o ON r.order_id = o.order_id
JOIN olist_customers_dataset c ON o.customer_id = c.customer_id
WHERE r.review_score <= $1
  AND ...
```

**Function 5 — `top_products(date_token?, limit=10, by='count'|'revenue')`**
- `by=count`: GROUP BY product_id ORDER BY COUNT(*) DESC
- `by=revenue`: GROUP BY product_id ORDER BY SUM(payment_value) DESC
- JOIN `product_category_name_translation` for English name
- Hard LIMIT capped at max 25; LLM-supplied limit clamped server-side

**Function 6 — `list_orders(filters, limit=20, offset=0)`**
- Paginated lookup; LIMIT capped at 50 always
- Returns rows + total_count for pagination controls

---

### Step 5: Orchestrator (Tool-Calling Loop)

**`orchestrator.py`** — the core pipeline:

```
question (str)
    │
    ▼
[1] Build system prompt: tool schemas + instruction to emit ONE tool call as JSON
    │
    ▼
[2] POST to Ollama /api/chat (qwen3.5:2b)
    │   model response = { "tool": "count_orders", "args": { "city": "São Paulo", "date_token": "last_month", "status": "delivered" } }
    ▼
[3] Parse + validate args (validation layer)
    │   on error → return clarification message, no DB call
    ▼
[4] Dispatch to function handler → execute parameterized query
    │
    ▼
[5] Format result: POST to Ollama again ("here are the rows, write one sentence answer")
    │
    ▼
[6] Return structured JSON: { operation, filters, result, formatted_answer, source }
```

Key invariants enforced in code:
- LLM output is parsed with `json.loads` + schema validation (`jsonschema`). Any parse failure → retry once, then return error.
- Only function names in `registry.py` are callable — unknown names raise immediately.
- All DB calls go through `db.py` pool, never a raw connection the LLM can influence.

---

### Step 6: Frontend — React Chat Panel

Bootstrapped with Vite (`npm create vite@latest frontend -- --template react-ts`).

**Components:**
- `App.tsx` — state: `messages[]`, `loading bool`. Renders `<ChatPanel>` + input bar.
- `ChatPanel.tsx` — scrollable message list. Each message is `{role: 'user'|'assistant', content}`.
- `ResultCard.tsx` — renders structured result: big number for counts/revenue, table for list_orders/top_products, detail card for get_order_status. Falls back to plain text.
- `api.ts` — `async function query(question: string)` → `POST http://localhost:8000/api/query`.

**UX details:**
- Input disabled while loading (spinner on send button)
- Each assistant message shows the `source` field (what was queried) as a collapsible citation line — this is the trust surface
- Error messages from the backend render as yellow inline warnings, not crashes

---

## Phase 1 — Core Library + Validation (MVP)

After Phase 0 proves the vertical slice (functions 1+2), implement:
- Functions 3–6 following the same pattern
- Full validation layer (city fuzzy matching, date token resolution, enum checks)
- Structured JSON response contract (finalized below)
- Eval set: 50 question/expected-answer pairs in `backend/tests/eval_set.json`
- Run eval set: `pytest backend/tests/test_eval.py` — fails if any answer deviates

**Response contract (finalized):**
```json
{
  "operation": "count_orders",
  "filters": { "city": "sao paulo", "status": "delivered", "date_range": ["2018-09-01","2018-10-01"] },
  "result": { "count": 1423 },
  "formatted_answer": "There were 1,423 delivered orders in São Paulo last month.",
  "source": "olist_orders_dataset JOIN olist_customers_dataset",
  "error": null
}
```

---

## Phase 2 — Hardening

- Statement timeout `SET statement_timeout = '5s'` per connection (already planned in db.py) ✅
- Request logging middleware: log question, resolved function, execution time, row count ✅ (`audit.py` — JSONL, PII-safe summaries)
- Result row cap: any query returning >200 rows is rejected at the query layer — the function must aggregate or paginate ✅ (`db.py` — `RowCapExceeded` exception, configurable via `MAX_RESULT_ROWS`)
- Add `/api/eval` endpoint: runs eval_set.json and returns pass/fail counts (for CI) ✅ (`main.py` — returns structured JSON with pass rate and threshold check)
- Rate limiting: simple in-memory sliding-window limiter per IP ✅ (`main.py` — configurable via `RATE_LIMIT_PER_MINUTE`)

## Phase 3 — Productization ✅

Schema-agnostic onboarding via per-schema config. The active schema is
selected at startup via the `SCHEMA_NAME` env var (default: `olist`).
Each schema is a self-contained module under `backend/schemas/<name>/`
with a `SchemaConfig` dataclass: tables, columns, enums, state codes,
out-of-scope lexicon, prompt text + few-shots, and source citations.
The function library, validation layer, and orchestrator's system
prompt all read from the active config — no per-schema code paths.
- `SCHEMA_NAME=olist` — default; runs against the Olist Brazilian e-commerce dataset
- `SCHEMA_NAME=shopify` — config-only stub that proves the abstraction generalizes (its functions return a "not wired" error until a real Shopify adapter lands)
- Adding a new schema = one config module + one entry in `schemas/__init__.py::_BUILTIN`
- The `tests/test_schemas.py` suite pins the SchemaConfig contract so future schemas follow it
- Resolves the original Phase 3 open question ("How much per-schema config?") — the answer is one dataclass

---

## Verification

**After Phase 0:**
1. `psql -U nlq_readonly -d olist -c "INSERT INTO olist_orders_dataset ..."` → must fail with permission denied
2. `curl -X POST http://localhost:8000/api/query -d '{"question":"What is the status of order abc123?"}'` → JSON response with status card
3. `curl http://localhost:8000/api/health` → `{"db": "ok", "llm": "ok"}`
4. Open React panel at localhost:3000, ask "How many delivered orders did we have last month?" → formatted number answer with citation

**After Phase 1:**
5. Run `pytest backend/tests/` → all function unit tests pass (real DB, read-only role)
6. Run eval set: `pytest backend/tests/test_eval.py -v` → ≥90% pass rate target

---

## Open Questions (resolved)

| Question | Decision |
|---|---|
| Reference date for relative terms | Anchor to `2018-10-17` (dataset max); `REFERENCE_DATE` env var switchable |
| Frontend | React + Vite + TypeScript |
| Backend | Python 3.9+ + FastAPI + asyncpg |
| LLM | qwen3.5:2b via Ollama (local, 2B params, excellent tool-calling) |
| Deployment | Local dev first |
| JSON contract | Defined above under Phase 1 |
