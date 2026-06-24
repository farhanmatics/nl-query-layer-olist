# Natural-Language Query Layer on Olist Dataset

A **self-hosted, trustworthy natural-language query system** that lets non-technical staff ask plain-English questions about operational data and get exact, verifiable answers from a database—without writing SQL or needing a data analyst.

> Built on the Olist Brazilian e-commerce dataset as a test bed, but schema-agnostic by design. The product is the repeatable pattern, not the dataset.

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
Web Panel (React)  ←→  Backend (FastAPI)  ←→  Local Model (Ollama + granite4:3b)
                              ↓
                        Postgres (read-only role)
```

- **Web Panel** — thin chat UI for questions and structured results
- **Backend Orchestrator** — owns tool definitions, validation, function dispatch, read-only DB connection
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
| **Deployment** | Local dev (Mac/Linux) · VPS ready (Phase 3) |

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

### Phase 0 — Foundation (Current)
Prove the vertical slice end-to-end:
- ✅ Database read-only role
- ⏳ Backend skeleton (FastAPI, async DB, config)
- ⏳ Validation layer (cities, dates, enums)
- ⏳ First two functions: `get_order_status`, `count_orders`
- ⏳ Orchestrator (LLM tool-calling loop)
- ⏳ React chat panel

**Success criteria:** Ask "How many delivered orders in São Paulo last month?" → get exact number + citation.

### Phase 1 — Core Library + MVP
- Implement functions 3–6 (revenue, reviews, top products, list orders)
- Full validation layer with fuzzy city matching
- Eval set: 50 question/answer pairs with ≥90% pass rate
- Structured JSON response contract finalized

### Phase 2 — Hardening
- Request logging & observability
- Result row caps & pagination enforcement
- Statement timeouts & rate limiting
- `/api/eval` endpoint for CI integration

### Phase 3 — Productization
Extract schema + functions + validation into per-customer **config** so new databases are onboarded by description, not code rewrites.

### Phase 4 — Long Tail (Optional)
- Fenced generated-SQL escape hatch (read-only role, LIMIT enforced)
- Multi-step orchestration
- Slack/email delivery channels

---

## Getting Started

### Prerequisites

- **Python 3.9+** (3.9 verified working; 3.10+ also fine)
- **Node.js 18+** (for frontend)
- **PostgreSQL 12+** with the Olist dataset loaded
- **Ollama** running locally with `granite4:3b` pulled

### 1. Clone & Setup Backend

```bash
git clone https://github.com/farhanmatics/nl-query-layer-olist.git
cd nl-query-layer-olist

# Create Python venv
python3 -m venv venv
source venv/bin/activate  # macOS/Linux
# or: venv\Scripts\activate  # Windows

# Install dependencies
pip install fastapi uvicorn asyncpg python-dotenv jsonschema requests pydantic

# Copy .env.example and configure
cp .env.example .env
# Edit .env with your DB credentials, Ollama URL, etc.
```

### 2. Set Up Database Role

First, create the readonly role:
```bash
psql -U postgres -d olist -f sql/readonly_role.sql
```

Edit the password in `sql/readonly_role.sql` (line 4) from `'changeme'` to your preferred password, then update your `.env` file to match:
```bash
# .env
DB_URL=postgresql://nlq_readonly:your_password@localhost/olist
```

This creates the `nlq_readonly` role with SELECT-only permissions.

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
    "date_range": ["2018-09-17", "2018-10-17"]
  },
  "result": {
    "count": 1423
  },
  "formatted_answer": "There were 1,423 delivered orders in São Paulo last month.",
  "source": "olist_orders_dataset JOIN olist_customers_dataset",
  "error": null
}
```

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

---

## Function Library

Six core functions handle the majority of real-world questions:

1. **`get_order_status(order_id)`** — Lookup a single order's status and key dates
2. **`count_orders(city?, state?, status?, date_range?)`** — Count orders with filters
3. **`get_revenue(date_range?, state?, category?, group_by?)`** — Sum payment values
4. **`count_low_reviews(score_max=2, city?, date_range?)`** — Count low-scoring reviews (disputes analog)
5. **`top_products(date_range?, limit=10, by='count'|'revenue')`** — Top-N products by count or revenue
6. **`list_orders(filters, limit=20, offset=0)`** — Paginated order lookup

Each function is a **pre-written parameterized query**. The LLM only fills typed arguments.

---

## Project Files

- `CLAUDE.md` — Standing brief with architecture & principles
- `project_plan.md` — Detailed implementation roadmap (Phase 0–2)
- `olist_tables_structure.sql` — PostgreSQL schema dump
- `sql/readonly_role.sql` — Read-only role definition
- `backend/` — Python FastAPI application
- `frontend/` — React + TypeScript chat panel
- `.env.example` — Environment variable template

---

## Testing & Evaluation

### Unit Tests
```bash
cd backend
pytest tests/test_functions.py -v
```

### Eval Set (50 Q/A pairs)
```bash
pytest tests/test_eval.py -v
```

Target: ≥90% pass rate (questions answered correctly within expected tolerance).

---

## Security & Trust

✅ **Read-only database role** — no write/DDL possible, enforced by PostgreSQL  
✅ **No LLM-authored SQL** — only pre-written, parameterized queries  
✅ **Statement timeouts** — `SET statement_timeout = '5s'` per connection  
✅ **Result capping** — >200 rows rejected at the query layer  
✅ **Citations** — every answer shows what was queried  
✅ **Validation** — all user inputs (cities, dates, enums) validated before querying  

This is designed for **regulated environments** (finance, health, legal) where data can't leave the building and answers must be auditable.

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
- [ ] Phase 0: Vertical slice (get_order_status + count_orders)
- [ ] Phase 1: Full function library + eval set
- [ ] Phase 2: Hardening (logging, timeouts, row caps)
- [ ] Phase 3: Schema extraction (config-driven onboarding)
- [ ] Phase 4: Long tail (SQL escape hatch, multi-step, integrations)

---

**Built with ❤️ for trustworthy, local data access.**
