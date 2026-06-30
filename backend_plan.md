# Implementation Plan — Backend (App State, Auth, Sessions, Conversational Resolution)

> Companion to `frontend_plan.md`. The frontend plan is the dependent half; this
> plan owns the risky 80%: a read-write app-state store, secure auth, and the
> deterministic follow-up-resolution that actually fixes the *"and how many for
> Rio de Janeiro?"* bug. Nothing in `frontend_plan.md` can land before the
> endpoints below exist.

## Guiding constraints (carried from CLAUDE.md)

1. **The Olist pool stays read-only, always.** Auth/sessions/history are a
   *separate* read-write store on a *separate* connection. The read-only
   guarantee for operational data must remain structurally true.
2. **The backend owns resolution.** Conversational context is resolved
   deterministically server-side; the model never "remembers." The frontend only
   *renders* what the backend says it inherited.
3. **Shown, never silent.** Inherited operation/filters are reported in the
   response `context` block and are auditable. When resolution is unsafe, we
   **decline with a clarify prompt** rather than answer with a guess.
4. **Faithfulness first.** A confidently-wrong answer is the worst outcome; when
   in doubt, clarify.

---

## Sequencing — fix correctness first, auth second

The live defect is *confidently-wrong answers*, and fixing it needs a **session
id**, not **user authentication**. This plan therefore front-loads the correctness
fix (**B0**) on a minimal ephemeral session, then layers durable auth/history on
top. `frontend_plan.md` has been reconciled to the same ordering — its build
order is **F-T → F2-early → F0 → F1 → F2-final → F3**, so the F2 conversational UI
ships against B0 (no auth) and only swaps its `session_id` source when B1+B3 land.

| Backend phase | Delivers | Frontend phase it unblocks | Depends on |
|---|---|---|---|
| **B0** | Conversational resolution on an *ephemeral* session id | **F2-early** (no auth) | nothing — ships now |
| **B1** | App-state store (SQLite) + migrations | F1 | B0 design |
| **B2** | Secure auth (register/login/logout/me) | F0 | B1 |
| **B3** | Durable sessions + message history | F1 | B1, B2 |
| **B4** | Resolution backed by persisted history + clarify | **F2-final** | B0, B3 |
| **B-X** | Cross-cutting: audit identity, eval multi-turn, security hardening | all | rolling |

`frontend_plan.md` → **Sequencing (cross-plan)** mirrors this table; its build
order is **F-T → F2-early → F0 → F1 → F2-final → F3**, where F2-early rides B0 on
a client-minted `session_id` and F2-final swaps that id source to the server
session once B1+B3 land. The F2 UI components are built once and unchanged across
the swap — the mirror image of "B0 built to B4's shape, storage swap only."

**Recommendation:** ship **B0** as a standalone correctness release (days, not
weeks). It requires only a client-generated `session_id` and an in-memory,
TTL'd context cache — no DB, no auth. Auth/history (B1–B3) then proceed without a
known-bad answer sitting in production behind a login wall.

---

## B0 — Conversational resolution (the actual fix), ephemeral session

Goal: reproduce the transcript and get *"and how many for Rio de Janeiro?"* → **low
reviews for Rio, Jul 2018**, with visible inheritance — without any auth or DB.

### Contract change

```
POST /api/query  { question, session_id? }  →  QueryResponse + context
```

- `session_id`: opaque client-generated UUID (frontend mints one per
  conversation). Optional — absent means "single-shot, no context" (today's
  behavior, fully backward compatible).
- New `context` block in the response (see Data Contracts).

### Context store (ephemeral)

A process-local, TTL'd map `session_id → ConversationState`, reusing the existing
`TTLCache` from `cache.py`:

```
ConversationState = {
    "operation": str,                 # last successful tool, e.g. "count_low_reviews"
    "args": dict,                     # post-validation tool args (date_token, city, ...)
    "at": float,                      # monotonic; entries expire (e.g. 30 min)
}
```

Only **successful** turns are stored (never an errored/declined turn). The cache
is **bounded** — both a TTL (`CONTEXT_TTL_MINUTES`) *and* a max-entries cap
(LRU eviction, the `TTLCache` already supports it) — so a long-lived process or a
flood of distinct `session_id`s can't grow it without limit. This is deliberately
the same shape we will persist in B3, so B4 is a storage swap, not a redesign.

### Resolution algorithm (deterministic, backend-owned)

In `orchestrator.process_question(question, session_id=None)`, *before* dispatch:

1. **Translate** the new question alone (existing LLM + cache path) → candidate
   `{operation, args}`.
2. **Classify** the turn as FRESH or FOLLOW-UP:
   - **FOLLOW-UP** when *all* hold:
     - leading connector / deixis: `^(and|also|what about|how about|& )` or the
       question is filter-only;
     - **no measure noun** present (reviews, review, orders, order, revenue,
       sales, products, product, status) — i.e. the turn names no operation of
       its own;
     - at least one **filter token** is present — a known city, an uppercase UF,
       a date phrase/year, an order **status** word, or a product **category** —
       via the detector set in *Overlay dimensions & detectors* below.
   - Otherwise **FRESH**.
   - Classification is deterministic and unit-tested; the model's tool choice is
     a tie-breaker signal only, never the sole basis.
3. **Resolve**:
   - **FRESH** → use the candidate as-is; overwrite `ConversationState`.
   - **FOLLOW-UP with prior state** → start from prior `{operation, args}`,
     **overlay** only the dimensions the new turn specifies
     (city/state/status/date/category). Inherit operation + untouched filters.
     - **Reset words** (`total`, `overall`, `all`, `everything`, `in total`)
       drop inherited *filters* (keep operation) — user signalling a scope reset.
   - **FOLLOW-UP with no prior state** (e.g. first message is a fragment) →
     **clarify** (can't inherit from nothing).
4. **Guard** the merged call through the existing `apply_filter_guard` +
   `detect_unsupported_concept`. Crucially: if the inherited operation **cannot
   filter by** a place named in the follow-up (e.g. inherited `top_products` +
   "for Rio") → **clarify**, do not answer (this is the unsupported-geo path the
   single-turn guard already models, now reached via inheritance).
5. **Annotate confidence**: when the operation was inherited (not stated this
   turn), set `context.inherited = true` and `from_operation`. The card must not
   present an inferred operation with stated-intent authority.

### Overlay dimensions & detectors (the gap that bites)

The overlay is only as good as the detectors that find the new turn's filters,
and `validation/faithfulness.py` **today detects only `state`, `city`, and
`date`.** That silently breaks the two most common non-geo follow-ups:

- *"…and the **canceled** ones?"* (status) — no status detector → the prior
  status is wrongly kept, or the change is dropped.
- *"…what about **electronics**?"* / *"…and bed & bath?"* (category) — no
  category detector → same silent miss.

So B0 must **extend the detector set** (one home, reused by both the guard and
the resolver):

- **status** — match question tokens against `validation/enums.ORDER_STATUSES`
  (delivered, shipped, canceled, processing, invoiced, unavailable, approved,
  created). Word-boundaried, conservative.
- **category** — match against the known category set (English names from
  `product_category_name_translation`, plus the PT names), loaded once at startup
  and normalized like the city dictionary (accent-stripped, lowercased,
  underscores↔spaces). Prefer the longest multi-word match.

Each detector is **gated on whether the (inherited) tool accepts that param** —
identical to the guard's rule — so `top_products` (no status/city/state) still
routes an unfilterable place/status to **clarify**, never a silent drop. The
overlay set and these detectors are the single source of truth shared by
`apply_filter_guard` and the conversational resolver, so they can't drift.

### Fail-closed clarify

When resolution is ambiguous or unsafe, return (HTTP 200) a response with
`context.clarify` populated and `result = null`:

```json
{
  "operation": null, "result": null, "formatted_answer": null,
  "context": {
    "inherited": false,
    "clarify": {
      "prompt": "Do you mean low reviews for Rio de Janeiro (last month), or order count?",
      "options": ["low reviews", "order count"]
    }
  }
}
```

The frontend renders `ClarifyPrompt`; a chip click resubmits a disambiguated,
self-contained question in the same session.

### Tests (B0, no DB/LLM)
- `test_context_resolution.py`: FRESH vs FOLLOW-UP classification table;
  slot-overlay (new city keeps prior op+date); **status overlay** ("…and the
  canceled ones?" keeps op+city+date, swaps status); **category overlay**
  ("…what about electronics?"); reset-word drops filters;
  fragment-with-no-prior → clarify; inherited-op-cannot-filter-place → clarify.
- `test_detectors.py`: new status + category detectors (positive, negative,
  param-gated) alongside the existing city/state/date ones.
- Extend the eval set with **multi-turn cases** (see B-X).

**Exit check:** with a fixed `session_id`, *"How many low reviews last month?"*
then *"and how many for Rio de Janeiro?"* → second answer is **count_low_reviews,
city=rio de janeiro, Jul 2018**, `context.inherited=true`,
`from_operation="count_low_reviews"`, carried `{date_token:"last_month"}`. The
all-time 6,882 order count never appears.

---

## B1 — App-state store + migrations

Goal: a durable, read-write store for users/sessions/messages, **isolated** from
the read-only Olist pool.

### Engine & access
- **SQLite** for dev/single-tenant (file `app_state.db`), via `aiosqlite`
  (async) so it doesn't block the event loop.
- **PRAGMAs on connect:** `journal_mode=WAL` (concurrent reads),
  `busy_timeout=5000` (wait, don't instantly fail, when a write lock is held —
  SQLite serializes writers, so this is required under any concurrency),
  `foreign_keys=ON` (the `ON DELETE CASCADE`s above are inert without it).
- A **dedicated module** `appdb.py` owns this connection — separate from `db.py`
  (Olist read-only). No code path may reach Olist through `appdb` or vice-versa.
- Config: `APP_DB_URL` (default `sqlite:///app_state.db`); designed so a Postgres
  DSN is a drop-in for multi-tenant later.

### Query portability (decide now, not at swap time)
SQLite (`aiosqlite`) uses `?` placeholders and `sqlite3.Row`; asyncpg uses `$1`
and `Record`. If endpoints write raw SQL against `?`, the Postgres "drop-in" is a
full rewrite. Resolve up front with **one of**:
- a thin **repo/DAO layer** (`appdb.py` exposes `get_user`, `insert_message`, …;
  SQL lives in one place, placeholder dialect isolated), or
- **SQLAlchemy Core** (not the ORM) — dialect-agnostic SQL, both engines for
  free, at the cost of a dependency.

Lean **repo layer** now (no new dep, smallest surface); revisit SQLAlchemy Core
only if the hand-rolled SQL grows. Either way, **no raw dialect-specific SQL in
route handlers.**

### Migrations
Reuse the existing `migrate.py` pattern (versioned, idempotent, tracked in a
`schema_migrations` table) — but against the **app-state** DB, not Olist. New
ordered files under `backend/migrations_app/`:

```sql
-- 0001_app_schema.sql
CREATE TABLE IF NOT EXISTS users (
  id            TEXT PRIMARY KEY,            -- uuid
  email         TEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,              -- argon2id
  role          TEXT,                        -- reserved; RBAC deferred
  created_at    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
  id             TEXT PRIMARY KEY,
  user_id        TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  title          TEXT,
  created_at     TEXT NOT NULL,
  last_active_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id, last_active_at);
CREATE TABLE IF NOT EXISTS messages (
  id            TEXT PRIMARY KEY,
  session_id    TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  role          TEXT NOT NULL,              -- 'user' | 'assistant'
  question      TEXT,                        -- user turn text
  response_json TEXT,                        -- full QueryResponse (assistant)
  resolved_call TEXT,                        -- {operation, args} for inheritance
  created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, created_at);
CREATE TABLE IF NOT EXISTS auth_sessions (         -- server-side cookie sessions
  id          TEXT PRIMARY KEY,             -- random 256-bit, the cookie value
  user_id     TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created_at  TEXT NOT NULL,
  expires_at  TEXT NOT NULL
);
```

`resolved_call` on the assistant message is what B4 reads to inherit context —
the durable equivalent of B0's in-memory `ConversationState`.

**Exit check:** `migrate.py --app up` creates the schema idempotently; app boots
with both pools (Olist read-only + app-state read-write) and a health probe for
each.

---

## B2 — Secure auth

Goal: register/login/logout/me with credentials handled to a standard fit for
regulated buyers. **None of this is optional.**

### Endpoints
```
POST /api/auth/register  { email, password } → { user }   (+ Set-Cookie session)
POST /api/auth/login     { email, password } → { user }   (+ Set-Cookie session)
POST /api/auth/logout    → { ok }                          (invalidate server session)
GET  /api/auth/me        → { user } | 401
```

### Requirements (non-negotiable)
- **Password hashing:** `argon2id` via `argon2-cffi` (or bcrypt via `passlib`).
  Never plaintext, never a fast/unsalted hash. Tunable cost in config.
- **Hash off the event loop:** argon2/bcrypt are deliberately CPU-heavy (tens to
  hundreds of ms); calling them inline blocks the async loop and stalls every
  concurrent request. Run hashing/verification in a threadpool
  (`anyio.to_thread.run_sync` / `loop.run_in_executor`). This interacts with the
  auth rate-limit below — both exist to keep login from becoming a CPU DoS.
- **Password policy:** min length (e.g. 10), reject common passwords; validated
  server-side.
- **Server-side sessions (httpOnly cookie):** the cookie carries a random opaque
  id; the session record lives in `auth_sessions` with `expires_at`. Logout
  deletes the record (true invalidation). Rolling expiry on activity.
- **Cookie flags:** `HttpOnly`, `Secure` (prod), `SameSite=Lax`,
  `Path=/`, sane `Max-Age`.
- **CSRF:** cookie-auth needs it. With `SameSite=Lax` most CSRF is mitigated, but
  add a **double-submit CSRF token** for all state-changing requests
  (`POST/PATCH/DELETE`), validated by a dependency. (If we instead go
  bearer-in-memory for cross-origin, CSRF is moot but XSS-token-theft returns —
  decision mirrors `frontend_plan.md` Open Questions; default to cookie+CSRF.)
- **Auth rate-limiting / lockout:** reuse the `RateLimiter`, but a **stricter,
  per-email+IP** budget on `/api/auth/*` (e.g. 5 failures / 15 min → backoff) to
  blunt brute force. Independent of the global `/api/` limiter.
- **Uniform errors:** login returns a single "invalid email or password" (no
  user enumeration). Register may reveal "email taken" (accepted trade-off) or
  use a verification flow later.
- **Secrets:** session secret / pepper from env, never committed.

### Tests (B2)
- hash round-trip + wrong-password rejection; expired/invalidated session → 401;
  CSRF token required on mutations; auth rate-limit triggers; cookie flags
  asserted; no user enumeration on login.

**Exit check:** register→cookie set→`/me` returns user; logout invalidates
server-side (reusing the cookie afterward → 401); refresh keeps session;
brute-force is throttled.

---

## B3 — Sessions + message history

Goal: durable conversations scoped to the authenticated user.

### Endpoints (all require auth; all enforce ownership)
```
GET    /api/sessions               → [SessionMeta]            (current user only)
POST   /api/sessions               → SessionMeta              (new conversation)
PATCH  /api/sessions/:id  { title }→ SessionMeta
DELETE /api/sessions/:id           → { ok }
GET    /api/sessions/:id/messages  → [Message]
```

### Ownership / IDOR — the critical control
Every `:id` route loads the row and asserts `row.user_id == current_user.id`
**before** acting; mismatch → **404** (not 403, to avoid confirming existence).
A shared dependency `require_owned_session(session_id, user)` enforces this in one
place; no endpoint touches a session/message without it. This is the multi-tenant
leak the frontend plan never mentions — it is owned here.

### Title derivation
Backend-derived from the first user question (truncated, sanitized) for
consistency across clients (per frontend Open Questions). Rename via PATCH.

### Tests (B3)
- list returns only the caller's sessions; cross-user GET/PATCH/DELETE → 404;
  cascade delete removes messages; first message creates + titles a session.

**Exit check:** two users cannot see or mutate each other's sessions/messages by
id; history persists and reloads.

---

## B4 — Resolution backed by persisted history + clarify (final F2)

Goal: replace B0's ephemeral context with the durable `messages.resolved_call`
from the active session, behind auth.

- On `POST /api/query { question, session_id }`: load the session's **most recent
  assistant message whose `resolved_call` is non-null** (ownership-checked) and
  feed it into the **same B0 resolution algorithm**. "Most recent assistant" is
  wrong — clarify/error turns are persisted with a null `resolved_call`, so the
  query must be `... WHERE resolved_call IS NOT NULL ORDER BY created_at DESC
  LIMIT 1`, or a follow-up after a clarification inherits nothing. Persist the
  user turn and the assistant turn (with its new `resolved_call`).
- Behavior, classification, clarify, and the `context` contract are **identical
  to B0** — only the context source changes (DB row vs in-memory map). This is
  why B0 is built to the final shape.
- Clarify turns are persisted as assistant messages too (so reload shows the
  prompt), but do **not** overwrite `resolved_call` (nothing was resolved).

**Exit check:** the B0 two-turn regression passes against persisted history,
across a reload, scoped to the user's session.

---

## B-X — Cross-cutting (rolling)

### Audit identity
Extend `audit.build_record` with `user_id` and `session_id` (nullable pre-auth).
Strengthens the "auditable answers" value prop: every answer is now attributable
to a user and a conversation. Keep the row-free result summary rule.

### Eval: multi-turn
The current eval set is single-turn and cannot catch the Rio regression. Add a
`conversations` section to `eval_set.json` (or a sibling file) where a case is an
ordered list of turns sharing a `session_id`, asserting the resolved
`{operation, filters}` and `context.inherited` per turn. Extend `/api/eval` and
`test_eval.py` to replay them. Pin the exact Rio transcript as a case.

### Security hardening (whole surface)
- The `/api/eval` endpoint runs the full eval (minutes, many LLM calls) and is
  currently unauthenticated — **gate it behind auth** (or an admin/CI token)
  before any deployment; it's a trivial DoS/cost amplifier otherwise.
- Confirm `expose_internal_errors=false` in all non-dev configs (already the
  default).
- Ensure the app-state DB file is outside any served/static path and in
  `.gitignore`.

### Migrate `migrate.py` to dispatch two targets
Add an `--app` flag (or a second entrypoint) so the runner can migrate either the
Olist DB or the app-state DB, tracked in separate `schema_migrations` tables.

---

## Deferred workstreams (own plans, not in B0–B4)

These are real and flagged, but out of scope for the correctness-first slice;
each gets its own plan so it isn't half-done inside the phases above.

- **Data retention & privacy.** Persisting questions + answers (and audit JSONL)
  creates a data-handling obligation, especially for the regulated buyers this
  product targets: retention window, user-initiated history/account deletion
  (cascade already supports it), purge job / TTL on audit logs, and a disclosure
  note in the UI. Needs its own `retention_plan.md` before durable history (B3)
  ships to any real user.
- **Model-serving boundary (persistent backend ↔ serverless model).** The plans
  assume the orchestrator/app-state live on a persistent host while the model may
  run on RunPod serverless. That boundary has its own concerns — cold-start
  latency (interacts with `LLM_TIMEOUT_SECONDS` and the F3 "thinking…" UI),
  network auth to the model endpoint, statelessness of the model tier, and
  failover. Captured in **`model_serving_plan.md`** (stubbed): per-customer
  topology, a `ModelClient` abstraction (Ollama / OpenAI-compat), cold-start vs
  keep-warm, endpoint auth, and the "only question text egresses, never DB rows"
  privacy framing.

## Data Contracts (server-side shapes)

```python
# Response addition (mirrors frontend QueryContext)
{
  "context": {
    "inherited": bool,                  # was operation/filters carried from prior turn
    "from_operation": str | None,       # e.g. "count_low_reviews"
    "carried": dict,                    # e.g. {"date_token": "last_month"}
    "clarify": {                        # present only when declining to answer
        "prompt": str,
        "options": list[str],
    } | None,
  }
}
```

`QueryResponse` otherwise unchanged (operation/filters/result/formatted_answer/
source/error/cached/guard) — `context` is additive and nullable, so existing
single-shot callers are unaffected.

---

## Config additions

```
APP_DB_URL=sqlite:///app_state.db        # read-write app state (NOT Olist)
SESSION_SECRET=...                        # cookie session signing/pepper
SESSION_TTL_MINUTES=43200                 # 30 days rolling
AUTH_RATE_LIMIT_PER_15MIN=5               # per email+IP on /api/auth/*
CONTEXT_TTL_MINUTES=30                    # B0 ephemeral context expiry
ARGON2_TIME_COST / MEMORY_COST / PARALLELISM   # hashing cost knobs
```

---

## Open Questions

| Question | Leaning |
|---|---|
| Auth transport | httpOnly cookie session + CSRF token (default); bearer-in-memory only if cross-origin cookies prove painful. |
| App store engine | SQLite + WAL now; Postgres drop-in later (ids as TEXT uuid). |
| Query portability | Repo/DAO layer isolating `?`↔`$1` (no new dep); SQLAlchemy Core only if hand-rolled SQL grows. No dialect SQL in handlers. |
| Status/category detectors | Add to the shared detector set (one home for guard + resolver); status from `ORDER_STATUSES`, category from the translation table loaded like the city dictionary. |
| Data retention | Out of scope for B0–B4; own `retention_plan.md` before durable history reaches real users. |
| Model serving | Persistent backend ↔ RunPod serverless model captured in `model_serving_plan.md` (stub). |
| Context source before auth | Ephemeral in-memory (B0) → durable `resolved_call` (B4); identical algorithm. |
| Follow-up classification | Deterministic (connector + no-measure-noun + filter-present); model tool-choice is a tie-breaker only. |
| Inherit across operation change | Allowed only with visible `context.inherited` + lower-confidence rendering; ambiguous → clarify. |
| `/api/eval` exposure | Gate behind auth/admin token before deploy. |
| Roles / RBAC | Reserve `users.role`; no enforcement until the roles workstream. |
```

The README's "read-only, always" guarantee remains true: this store is a
*separate* read-write connection for app state; the Olist operational data is
never written.
