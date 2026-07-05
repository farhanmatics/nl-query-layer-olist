# Hackathon Demo Script — Track 4 (~3 minutes)

Use this script while screen-recording the **React chat panel** with the **backend on Alibaba Cloud** (or local if pre-deploy). Speak clearly; pause 2–3 seconds after each answer loads.

**Before recording**

- [ ] Backend running: `curl <API>/api/health` → `db: ok`, `llm: ok`, `meta_tools: enabled`
- [ ] Browser zoom ~100%; chat panel visible; no sensitive keys in `.env` on screen
- [ ] Optional: open backend terminal showing `SQL>` log line for one query (trust moment)
- [ ] `REFERENCE_DATE=2018-08-20` so “last month” hits real data

**Timing target:** 2:45 – 3:15 total

---

## 0:00 – 0:25 | Hook — the workflow we automate

**[Screen: Chat UI empty state or title slide]**

**Say:**

> "Operations teams ask analysts hundreds of ad-hoc questions — counts, revenue, rankings — and wait hours for a number they need to trust.  
> **Verifiable Query** is an autopilot analyst: you ask in plain English, **Qwen on Alibaba DashScope** figures out what to run, but **our backend** executes verified SQL on **your** database and shows exactly where every number came from.  
> I'm submitting to **Track 4 — Autopilot Agent**."

**[Click into the chat app]**

---

## 0:25 – 0:55 | Scene 1 — Standard operational question

**Type:**

```
How many delivered orders did we have in Sao Paulo last month?
```

**[Wait for result card — large count, filter chips, citation footer]**

**Say:**

> "Qwen translated that into a structured **count** with city, status, and date. The backend validated São Paulo, resolved 'last month' against our reference date, ran a **read-only** query, and returned **one exact number** — with filters and source tables cited.  
> The model never touched the database; it only chose the tool and arguments."

**[Optional: flash backend log line `SQL> SELECT ...`]**

---

## 0:55 – 1:25 | Scene 2 — Ambiguous input (human-in-the-loop)

**Type:**

```
How many products in perfumaria?
```

**[If clarify chips appear: "Products in catalog" vs "Orders sold"]**

**Say:**

> "This is intentionally ambiguous — catalog SKUs versus orders that included perfumaria products. Instead of guessing, the agent **asks** which you mean. That's our human-in-the-loop checkpoint."

**[Click: "Products in catalog"]**  
*(Or retype: `How many products do we have in the catalog for perfumaria?` if chips don't appear)*

**[Wait for count — should be catalog product count, measure footer if visible]**

**Say:**

> "Now we get **products in the catalog** — not orders — routed through our meta-tool layer to the right internal function."

---

## 1:25 – 1:55 | Scene 3 — Multi-turn autopilot (follow-up)

**Type (same session, no refresh):**

```
Which is the best one last year by revenue?
```

**[Wait for top product card — single product hero or rank #1]**

**Say:**

> "Follow-up inherits **perfumaria** from the prior turn and switches from **count** to **rank** — Qwen picks the shape, the meta-router maps to **top products**, and we get the best seller by revenue for last year.  
> This is the analyst workflow continuing across turns without re-explaining context."

---

## 1:55 – 2:20 | Scene 4 — Honest decline (production trust)

**Type:**

```
How many returned orders?
```

**[Expect error / decline — schema doesn't track returns]**

**Say:**

> "The autopilot **refuses** when the dataset can't answer honestly. We don't map 'returns' to a proxy metric and return a confident lie.  
> Same for filters a tool can't support — the faithfulness guard blocks wrong answers."

---

## 2:20 – 2:45 | Scene 5 — Breakdown / compare (tool orchestration)

**Type:**

```
Revenue by state this year
```

**[Bar chart / breakdown view]**

**Say:**

> "Breakdown questions route to grouped revenue SQL — again, computed in the database, summarized for Qwen to narrate."

**Type (optional if time):**

```
Compare revenue in SP and RJ
```

**[Comparison table]**

**Say:**

> "Side-by-side state comparison — multiple tools, one conversational interface."

---

## 2:20 – 2:50 | Scene 6 — Planner chain (2-step autopilot)

**Type:**

```
Top category by revenue last year, then best product in that category
```

**[Wait for Planner chain trace (2 steps) + top product card]**

**Say:**

> "For compound questions, the **planner** emits a two-step chain: first rank categories, then bind `$step0.category` into a second rank for the best product.  
> The backend executes each step with the same validation and read-only SQL — Qwen plans, Postgres computes."

**Env for demo:** `PLANNER_ENABLED=true`, `PLANNER_DEMO_FALLBACK=true` (reliable baked-in plan).

---

## 2:50 – 3:10 | Scene 7 — MCP integration (optional B-roll)

**[Screen: Cursor MCP panel or terminal showing MCP tools]**

**Say:**

> "We also expose **MCP tools** — health check, eval summary, and direct `count_orders` — so external agents can call the same verified backend without going through chat."

See [docs/mcp-demo.md](mcp-demo.md).

---

## 3:10 – 3:25 | Close — architecture & Qwen role

**[Screen: HACKATHON.md architecture diagram, or simple slide: User → FastAPI → Postgres + DashScope]**

**Say:**

> "Architecture: **React** front end, **FastAPI** on **Alibaba Cloud**, **Postgres** with a read-only role, and **Qwen 3.7 Plus** via **DashScope** for two calls per question — tool JSON and answer formatting.  
> Forty-three internal SQL functions, seven meta-tools, eval harness, audit logging, and an optional fenced SQL escape for the long tail.  
> **Qwen provides intelligence; the backend provides truth.**  
> Code is open source — link in the repo. Thanks."

**[End recording]**

---

## Backup questions (if something fails live)

| If this fails… | Try instead |
|----------------|-------------|
| Sao Paulo last month | `Total revenue last month` |
| Perfumaria clarify | `How many products do we have in perfumaria category?` |
| Best product follow-up | `Top 5 products by revenue this year` |
| Returns decline | `How many orders in Nowhereville?` (unknown city) |
| SQL escape | `How many distinct product categories are in the catalog?` |
| Planner chain | `Top category by revenue last year, then best product in that category` |

---

## Post-production checklist

- [ ] Blur any API keys / cookies in editor or terminal
- [ ] Add title card: project name + Track 4 + Qwen Cloud Hackathon
- [ ] Add end card: GitHub repo URL
- [ ] Upload public to YouTube/Vimeo; paste link in `HACKATHON.md`
- [ ] Keep under 3:30; trim Scene 5 if long

---

## One-paragraph description (paste into submission form)

**Verifiable Query** automates the operational analyst workflow for Track 4. Business users ask ad-hoc questions in natural language; **Qwen 3.7 Plus on Alibaba DashScope** translates each question into a structured meta-tool call and formats the final answer, while a **FastAPI backend on Alibaba Cloud** validates filters, executes read-only parameterized SQL against PostgreSQL, and returns citable results with audit logs. The system handles ambiguous inputs via clarification prompts, refuses unsupported questions honestly, supports multi-turn follow-ups with filter inheritance, and includes a fenced SQL escape hatch for long-tail analytics — demonstrating production-ready autopilot behavior rather than a toy chatbot.
