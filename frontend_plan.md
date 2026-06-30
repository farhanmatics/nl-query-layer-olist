# Implementation Plan — Frontend (Auth, Sessions, History, Conversational Context)

## Context

The current frontend is a single stateless chat panel: messages live only in
`App.tsx` `useState`, every question is independent, and there is no auth, no
persistence, and no concept of a conversation. This plan adds the product-polish
layer we decided on:

1. **Multi-user auth** (login/register; roles deferred — reserve the shape only).
2. **Sessions + persisted chat history** (a sidebar of past conversations,
   backed by the backend's SQLite app-state store, migratable to Postgres).
3. **Conversational context continuity** — the fix for the *"and how many for
   Rio de Janeiro?"* bug. The frontend carries a `session_id`; the backend
   resolves each follow-up against the previous turn's structured tool call and
   tells the frontend what it inherited; the frontend **renders that inheritance
   visibly** so it is never silent.

Non-negotiable carried over from the product thesis: inheritance and context are
**shown, never silent** — the citation surface is the trust surface, and that
now includes conversational state.

Stack additions: `react-router-dom` (routing for auth vs app), a lightweight
`AuthContext` + `SessionContext` + `ThemeContext`, and a hardened `api.ts` (auth,
401 handling, `session_id`). Keep `fetch` — no new data-fetching dependency
required (TanStack Query is optional, noted under Open Questions). Tailwind +
existing component style retained, but the palette moves from hardcoded
`slate-*` classes to **semantic tokens** so light/dark is a variable swap (see
Phase F-T).

---

## Backend contract this depends on

The frontend cannot land ahead of these endpoints. They live on the **persistent
backend** (not the RunPod serverless model) and read/write the **SQLite app-state
DB** (separate read-write connection from the read-only Olist pool).

```
POST   /api/auth/register   { email, password } → { user }            (+ sets session)
POST   /api/auth/login      { email, password } → { user }            (+ sets session)
POST   /api/auth/logout     → { ok }
GET    /api/auth/me         → { user } | 401

GET    /api/sessions        → [{ id, title, created_at, last_active_at }]
POST   /api/sessions        → { id, title, ... }              (new conversation)
PATCH  /api/sessions/:id    { title } → { ... }               (rename)
DELETE /api/sessions/:id    → { ok }
GET    /api/sessions/:id/messages → [{ id, role, question, response, created_at }]

POST   /api/query   { question, session_id } → QueryResponse + context block
```

`POST /api/query` gains a `session_id` and a `context` block in the response (see
Data Contracts). Auth: **httpOnly cookie session** recommended (backend is
persistent, so a server-side session is cheap and avoids XSS token theft); bearer
token in memory is the fallback — decided under Open Questions.

---

## Directory Structure

```
frontend/src/
├── main.tsx                  # mount + <BrowserRouter>
├── App.tsx                   # route table only (was: the whole app)
├── api.ts                    # fetch wrapper: credentials, 401→logout, session_id
├── auth/
│   ├── AuthContext.tsx       # current user, login/register/logout, bootstrap via /me
│   └── ProtectedRoute.tsx    # redirect to /login when unauthenticated
├── theme/
│   └── ThemeContext.tsx      # light/dark/system, localStorage, toggles .dark on <html>
├── session/
│   └── SessionContext.tsx    # session list, active session, messages, send()
├── pages/
│   ├── LoginPage.tsx
│   ├── RegisterPage.tsx
│   └── ChatPage.tsx          # sidebar + ChatPanel (the authenticated app)
└── components/
    ├── Sidebar.tsx           # session list: new / select / rename / delete
    ├── ChatPanel.tsx         # (existing) message list + input
    ├── MessageBubble.tsx     # (existing)
    ├── ResultCard.tsx        # (existing)
    ├── CarryoverChip.tsx     # NEW — renders inherited context ("↩ last month")
    ├── ClarifyPrompt.tsx     # NEW — renders backend's "which did you mean?" ask
    └── ThemeToggle.tsx       # NEW — light/dark/system control
```

---

## Phase F-T — Theming foundation (light/dark) — do this first

Goal: a semantic theme system in place **before** the auth/sidebar/chip UI is
built, so every new component is theme-aware from the start instead of being
retrofitted with `dark:` variants later. The current components hardcode
`slate-*` / `white` inline; those migrate to semantic tokens here.

### Step 1: Token strategy — semantic CSS variables (recommended)

Rather than sprinkling `dark:` on every element (which doubles every class list
against the existing hardcoded palette), define **semantic color tokens** as CSS
variables and map them into Tailwind. You write `bg-surface text-content
border-line` once; the theme swaps the variable.

`index.css`:
```css
:root {
  --bg: 241 245 249;          /* slate-100 */
  --surface: 255 255 255;     /* card      */
  --content: 15 23 42;        /* slate-900 */
  --muted: 100 116 139;       /* slate-500 */
  --line: 226 232 240;        /* slate-200 */
  color-scheme: light;
}
.dark {
  --bg: 2 6 23;               /* slate-950 */
  --surface: 15 23 42;        /* slate-900 */
  --content: 226 232 240;     /* slate-200 */
  --muted: 148 163 184;       /* slate-400 */
  --line: 30 41 59;           /* slate-800 */
  color-scheme: dark;
}
```

`tailwind.config.js`:
```js
darkMode: 'class',
theme: { extend: { colors: {
  bg:      'rgb(var(--bg) / <alpha-value>)',
  surface: 'rgb(var(--surface) / <alpha-value>)',
  content: 'rgb(var(--content) / <alpha-value>)',
  muted:   'rgb(var(--muted) / <alpha-value>)',
  line:    'rgb(var(--line) / <alpha-value>)',
  // brand + result tones (rose) stay as-is — they read on both themes
}}}
```

`<alpha-value>` keeps opacity utilities working (`bg-surface/80`).
`color-scheme` themes native controls (inputs, date pickers, scrollbars) for
free.

### Step 2: `ThemeContext`

- State: `theme: 'light' | 'dark' | 'system'`, persisted to `localStorage`
  (key `theme`).
- Resolves `system` against `matchMedia('(prefers-color-scheme: dark)')` and
  listens for OS changes while in `system` mode.
- Applies by toggling `.dark` on `document.documentElement`.
- Exposes `theme`, `resolvedTheme`, `setTheme`.

### Step 3: Prevent the flash (FOUC)

React mounts after first paint, so the class must be set *before* that. Inline a
tiny blocking script in `index.html` `<head>` so there's no light→dark flicker:
```html
<script>
  (function () {
    var t = localStorage.getItem('theme');
    var dark = t === 'dark' || (t !== 'light' &&
      matchMedia('(prefers-color-scheme: dark)').matches);
    document.documentElement.classList.toggle('dark', dark);
  })();
</script>
```

### Step 4: Migrate existing components to tokens

Mechanical, scoped to a handful of files:
- `App.tsx` gradient `from-slate-100 … text-slate-900` → `bg-bg text-content`.
- `MessageBubble` assistant bubble / `ResultCard` cards → `bg-surface
  border-line text-content`, `text-muted` for secondary text.
- User bubble keeps `bg-brand-600 text-white` (brand reads on both).
- `index.css` scrollbar colors → reference `--line` / `--muted` so the scrollbar
  themes too.
- Verify the rose "low reviews" tone and the green "Verified" citation have
  adequate contrast on the dark surface; nudge shades if needed.

### Step 5: Toggle UI — `ThemeToggle.tsx`

- Light/dark/system control (icon button cycling, or a 3-way segmented control),
  placed in the header next to the connection pill now, and added to the account
  menu once F0 lands.
- Icon reflects `resolvedTheme`; click sets `theme`.

**Exit check:** toggle flips the whole app instantly; choice survives reload; on
first load with no stored preference the app follows the OS setting; changing the
OS theme live-updates while in `system` mode; a hard refresh shows no
light→dark flash.

---

## Phase F0 — Auth shell + routing + API hardening

Goal: a logged-in user reaches the existing chat; everyone else is bounced to
login. No history yet — proves the auth round-trip end to end.

### Step 1: Routing

`main.tsx` wraps the app in `<BrowserRouter>`. `App.tsx` becomes a route table:

```
/login      → <LoginPage />
/register   → <RegisterPage />
/           → <ProtectedRoute><ChatPage /></ProtectedRoute>
```

### Step 2: `AuthContext`

- State: `user: User | null`, `status: 'loading' | 'authed' | 'anon'`.
- On mount: `GET /api/auth/me` → set user or mark `anon`. This is the session
  bootstrap (cookie already present → silent login on refresh).
- `login()`, `register()`, `logout()` call the auth endpoints and update state.
- `ProtectedRoute`: while `loading` show a spinner; if `anon` redirect to
  `/login`; else render children.

### Step 3: `api.ts` hardening

- `credentials: 'include'` on every request (cookie session).
- Central response handler: on **401**, clear auth state and redirect to
  `/login` (handles session expiry mid-use).
- Read `VITE_API_BASE_URL` from env instead of hardcoded localhost (needed once
  frontend and backend are deployed to different hosts).

### Step 4: Login / Register pages

- Minimal forms (email + password), inline validation, error surface for
  "invalid credentials" / "email taken".
- On success → navigate to `/`.
- Match existing visual language (Tailwind, brand color, rounded cards).

**Exit check:** register → land in chat; refresh → still in (cookie bootstrap);
logout → bounced to `/login`; deep-link to `/` while logged out → redirect.

---

## Phase F1 — Sessions + persisted history (the sidebar)

Goal: conversations persist across reloads and are organized in a sidebar, like
the Claude web app.

### Step 1: `SessionContext`

- State: `sessions: SessionMeta[]`, `activeId: string | null`,
  `messages: Message[]`, `isLoading`.
- On mount (authed): `GET /api/sessions`; select the most recent or start empty.
- `selectSession(id)` → `GET /api/sessions/:id/messages` → hydrate `messages`.
- `newSession()` → `POST /api/sessions` → prepend to list, make active, clear
  messages.
- `renameSession(id, title)`, `deleteSession(id)` → call endpoints, update list.

### Step 2: `Sidebar.tsx`

- "New chat" button at top.
- Session list: title + relative timestamp, active row highlighted.
- Per-row hover actions: rename (inline edit), delete (confirm).
- Empty state: "No conversations yet."
- Collapses to a drawer on narrow screens (mobile polish — can defer to F3).

### Step 3: Refactor `App.tsx` / `ChatPage.tsx`

- `App.tsx`'s old message state moves into `SessionContext`. `ChatPage` renders
  `<Sidebar /> + <ChatPanel />`, both reading the context.
- `handleSendMessage` becomes `SessionContext.send(text)`:
  - if no active session, `newSession()` first (so the first message creates a
    conversation),
  - append the user message optimistically,
  - call `POST /api/query` with `{ question, session_id: activeId }`,
  - append the assistant message from the response.
- The first user message of a session sets its title (client-side truncate, or
  let the backend derive it — Open Questions).

**Exit check:** ask a question → reload → conversation still there; switch
sessions → correct history loads; new chat → clean slate; delete → gone from
list and from the backend.

---

## Phase F2 — Conversational context + visible inheritance

Goal: fix the screenshot bug *in the UI*. The backend now resolves follow-ups
against the previous turn (structured `resolved_call` from history); the frontend
must **send the session and surface what was inherited**.

### Step 1: Send the session

`POST /api/query` already carries `session_id` (F1). That alone lets the backend
read the prior turn's `{operation, args}` from history and resolve
*"and how many for Rio de Janeiro?"* → inherit `count_low_reviews` + `last_month`,
overlay `city`. **No extra frontend call needed** — the fix rides on F1's plumbing
plus the backend's context-resolution layer.

### Step 2: Render inheritance — `CarryoverChip.tsx`

The response's `context` block reports what was carried over. Render it on the
assistant message so inheritance is visible and verifiable:

```
There were 17 low reviews (score ≤ 2, Rio de Janeiro, Jul 2018).
  ↩ carried over: operation = low reviews · last month
  ✓ Verified from olist_order_reviews_dataset JOIN olist_orders_dataset
```

This is the existing citation principle extended to conversational state: the
user can see *at a glance* that the follow-up inherited the right operation and
date, instead of silently becoming an all-time order count.

### Step 3: Handle the fail-closed ask — `ClarifyPrompt.tsx`

When the backend can't safely resolve a follow-up (ambiguous, or a place named
that the inherited operation can't filter), it returns a clarification instead of
a number. Render it as an inline prompt with the suggested options as quick-reply
chips:

```
Do you mean low reviews for Rio de Janeiro (last month), or order count?
   [ low reviews ]   [ order count ]
```

Clicking a chip resubmits a disambiguated question in the same session. This is
the UI half of "decline honestly beats answering with a proxy."

**Exit check:** reproduce the transcript — *"How many low reviews last month?"*
then *"and how many for Rio de Janeiro?"* → second answer is **low reviews for
Rio, Jul 2018**, with a visible carry-over chip; the all-time 6,882 order count
never appears. Add this exact two-turn flow as a regression test (F3 / e2e).

---

## Phase F3 — Polish (optional, post-alpha)

- Mobile sidebar drawer; keyboard shortcuts (Cmd+K new chat).
- Streaming / progressive "thinking…" state during the model round-trip (matters
  more once RunPod cold starts add latency — see backend plan).
- Error toasts vs inline warnings; retry affordance on backend-unreachable.
- Account menu: email, logout, (later) role badge — the reserved RBAC surface.
- A settings/retention note (privacy: persisted history disclosure).

---

## Data Contracts (TypeScript)

```ts
export interface User {
  id: string
  email: string
  role: string | null   // reserved; RBAC deferred
}

export interface SessionMeta {
  id: string
  title: string
  created_at: string
  last_active_at: string
}

// Extends the existing QueryResponse
export interface QueryContext {
  inherited: boolean
  from_operation?: string                 // e.g. "count_low_reviews"
  carried: Record<string, unknown>        // e.g. { date_token: "last_month" }
  clarify?: { prompt: string; options: string[] }   // fail-closed ask
}

export interface QueryResponse {
  operation: string | null
  filters: Record<string, unknown> | null
  result: Record<string, unknown> | null
  formatted_answer: string | null
  source: string | null
  error: string | null
  cached?: boolean
  guard?: GuardReport | null
  context?: QueryContext | null           // NEW
}
```

---

## Verification

**After F-T:** toggle flips the app instantly and persists across reloads; no
stored preference → follows OS; live OS-theme change updates `system` mode; hard
refresh shows no light→dark flash; spot-check contrast of brand, rose, and
"Verified" green on the dark surface.

**After F0:** register/login/logout round-trip; refresh keeps session; protected
route redirects; 401 mid-session bounces to login.

**After F1:** history survives reload; session switch loads correct messages;
rename/delete persist to backend; first message creates + titles a session.

**After F2:** the Rio-de-Janeiro two-turn transcript resolves to *low reviews for
Rio, Jul 2018* with a visible carry-over chip; ambiguous follow-ups render the
clarify prompt instead of a number.

**Regression:** an e2e test (Playwright) drives login → ask → follow-up → assert
the carry-over chip and the correct operation; asserts 6,882 never renders.

---

## Open Questions

| Question | Leaning |
|---|---|
| Auth transport | **httpOnly cookie session** (backend persistent; avoids XSS token theft). Bearer-in-memory if cross-origin cookie setup proves painful. |
| Session title source | Backend-derived from first question (consistent across clients) vs client truncate. Lean backend. |
| Server-state lib | Plain `fetch` + context for now; adopt **TanStack Query** only if cache/invalidation churn grows. |
| Optimistic vs await | Optimistic user-message append, await assistant — matches current feel. |
| `context` resolution owner | Backend owns resolution (deterministic, testable); frontend only **renders** `context`. Confirmed. |
| Roles / RBAC | Reserve `user.role` now; no UI enforcement until the roles workstream. |
| Theme tokens | Semantic CSS-variable tokens (`bg/surface/content/muted/line`) over per-element `dark:` variants — one class set, theme is a variable swap. |
| Default theme | `system` (follow OS) until the user picks; persist their choice in `localStorage`. |
| Theme persistence | `localStorage` now (client-only). Optionally mirror to the user profile later so it follows them across devices. |
```
