# Improvement Plan — Submission Path (revised)

> **Window:** 2026-07-09 → 2026-07-13 (hackathon extension; days 6–10 held as
> reserve buffer — nothing is scheduled there on purpose).
> **Revised:** 2026-07-10 — Day 1 slipped; this doc is the recovery plan.
> **Goal:** ship a fully-tested, fully-demoed Track 4 submission — and leave
> the repo in a state we can keep building the product on after the hackathon.

## Status (as of 2026-07-10)

| Item | Reality |
|------|---------|
| Day 1 (T1–T4) | **Not started** — no `_min` datasets; no fine-tune v2 job; no `docs/eval-results.md` |
| Branch | On `main`; `HACKATHON.md` still references `fa/cloud-dev-fine-tune` |
| MCP | 3 tools (`health_check`, `eval_summary`, `count_orders`) |
| Fine-tune v1 | At parity with base (~92%); v2 (minimal prompt) is the only plausible win |

**Implication:** the retrain must launch **today** or the Day 3 eval/benchmark
story collapses. If training cannot start by end of Day 2, drop the v2
headline and demo base/v1 with honest parity (see Fallback below).

## Ground rules

1. **Protect the critical path.** If something slips, cut from *Defer / cut*
   first, then Stretch — never from deploy (T6), regression (T11), dress
   rehearsal (T13), or recording days.
2. **Code freeze end of Day 4.** Days 5+ are recordings, submission text, and
   emergency fixes only. No new features after freeze.
3. **Every change lands with tests green.** `cd backend && ../venv/bin/python
   -m pytest -q` must pass before any commit on Days 2–4.
4. **Honesty in claims.** Numbers in HACKATHON.md must be reproducible from
   `backend/scripts/eval_finetune.py` (and `bench_latency.py` if shipped)
   on the day of submission. No spin if v2 misses the gate.

**Owners:** `[C]` = Claude Code · `[U]` = Farhan (console/browser only) ·
`[C+U]` = joint.

---

## Priority ladder (use this when time runs out)

| Pri | Tasks | Why |
|-----|-------|-----|
| **P0** | T1 → T2, T6, T3 | Unblocks model story; deploy is a hard requirement; gold cleanup makes all numbers honest |
| **P1** | T5-slim, T7, T11, T12–T14 | Enough MCP for the demo beat; don't ship a broken stack |
| **P2** | T4, T8–T10 | Eval ledger + head-to-head + latency — nice if v2 lands |
| **Cut** | Full 7-shape MCP, stretch S1–S3 | Do not burn Days 4–5 |

---

## Fallback (if fine-tune v2 does not start by EOD Day 2)

- Skip T8–T10 (or run base-only baseline into `docs/eval-results.md`).
- Demo **base / v1** with the honest line: *in-distribution ceiling ~92%;
  fine-tune at parity; value is faithfulness + local DB, not a bigger model.*
- Reallocate hours to T6, T5-slim, T7, T11, T13.
- Do **not** invent a token-win claim without v2 numbers.

---

## Day 1 (Thu 2026-07-09) — MISSED

Originally: fine-tune v2 kickoff + eval truth. None of T1–T4 landed.
Work rolled into Day 2 as P0.

---

## Day 2 (Fri 2026-07-10) — Recover critical path

**Order matters:** T1 → T2 first (hours of unattended training), then T6 in
parallel with T3. T5-slim and T7 only after P0 is moving.

- [x] **T1 [C] — Minimal-prompt SFT export.** Add `--system-mode minimal` to
  `backend/scripts/export_sft_dataset.py`: replace the ~3,800-token schema
  prompt with a short fixed instruction (< 100 tokens) in every record.
  Re-export ~600 examples; re-run format/leakage/label validation (0
  mismatches, 0 train/val overlap).
  *Accept:* new `datasets/olist_sft_train_min.jsonl` + `_val_min.jsonl`
  validated; `test_export_sft_dataset.py` green.

- [ ] **T2 [U] — Launch fine-tune v2 on Model Studio.** Base `qwen3-14b`,
  SFT/LoRA, batch 128, LR 1e-4, epochs 5, eval steps 5, max seq len **1024**
  (records are now tiny). Upload the `_min` files.
  *Accept:* job status = Running; job ID recorded in
  `docs/dashscope-finetune.md`.
  *Gate:* if this is not Running by EOD, trigger Fallback.

- [ ] **T6 [U] — Alibaba Cloud deploy (hard requirement).** Follow
  `docs/alibaba-cloud-deployment.md`: ECS + Postgres (RDS or ECS-hosted) +
  `.env` with production flags (`ENVIRONMENT=production`,
  `META_TOOLS_ENABLED=true`, `USE_FINETUNED_MODEL` as desired).
  *Accept:* public `curl <host>/api/health` returns `db: ok, llm: ok`; fill
  instance IDs/region into the deployment doc.

- [ ] **T3 [C] — Clean eval gold labels.** Fix systematic omissions that cap
  every accuracy number: add `entity: products` to rank cases, explicit
  `score_max` on review cases, and any other gaps
  `eval_finetune.py --show` surfaces. Fix in `backend/tests/eval_set.json` /
  `meta_eval_set.json` (regenerate the *original* SFT set so it stays
  consistent).
  *Accept:* base-model misses are real model errors only; full pytest green.

- [ ] **T5-slim [C] — MCP demo surface (not full catalog).** Expand
  `backend/mcp_server/` from 3 tools to a **demo-complete** set:
  keep `health_check` + `eval_summary`; add/route `count`, `rank`, `sum`,
  `lookup` through the same validation + read-only path as the API.
  (`list` / `breakdown` / `compare` → Defer.) Update `docs/mcp-demo.md`
  with a scripted walkthrough: *external agent asks a business question →
  validated tool call → cited answer*.
  *Accept:* `test_mcp_tools.py` extended and green; manual stdio smoke of
  `count` and `rank` returns real DB numbers with citations.

- [ ] **T7 [C] — Production config audit.** Verify boot guards (fail fast on
  missing `DASHSCOPE_API_KEY`/`DB_URL` in production), CORS locked to the
  frontend origin, cookie security flags, rate limits, statement timeout,
  and sanitized client errors. Fix anything loose; add missing boot checks.
  *Accept:* pass/fail list in `docs/eval-results.md` appendix (create the
  file if needed); fixes committed with tests.

- [ ] **T4 [C] — Re-run base eval + record baseline (P2 — if time).** Full
  cleaned-gold run; save to `docs/eval-results.md`.
  *Accept:* dated base-model numbers in the ledger.
  *If cut:* run a shorter subset and note sample size; do not invent full-set
  numbers.

---

## Day 3 (Sat 2026-07-11) — Results (if v2) + harden

Only run T8–T10 if T2 launched. Otherwise skip to T11 and note Fallback in
progress notes.

- [ ] **T8 [U] — Deploy fine-tune v2** from Model Studio when training
  completes; record the new deployment ID in `.env` +
  `docs/dashscope-finetune.md`.

- [ ] **T9 [C] — Head-to-head eval.** Extend `eval_finetune.py` for
  minimal-prompt mode; run **base (full prompt) vs v1 (full prompt) vs v2
  (minimal prompt)** on the cleaned val set.
  *Accept:* results table in `docs/eval-results.md`.
  *Decision gate:* if v2 holds accuracy within ~2% of base → demo model +
  headline *"same accuracy, ~97% fewer prompt tokens"*; else demo v1/base
  and state parity honestly — no spin.

- [ ] **T10 [C] — Latency & token benchmark (P2).** Measure p50/p95
  end-to-end latency and input-tokens/query for: base, fine-tune,
  cache-hit. Small script (`backend/scripts/bench_latency.py`), ~20 queries
  each.
  *Accept:* benchmark table in `docs/eval-results.md` and summarized in
  HACKATHON.md. *Cut if behind* — eval accuracy table alone is enough.

- [ ] **T11 [C] — Bug-fix + full regression pass (P1 — do not cut).** Full
  pytest suite, frontend `npm test` + `npm run build`, then a manual
  end-to-end session against the local stack: happy path, clarify path,
  decline path, multi-turn carry-over, SQL-escape path, pagination. File
  and fix everything found today, not later.
  *Accept:* all suites green; short "known issues" list (ideally empty) in
  Progress notes below.

---

## Day 4 (Sun 2026-07-12) — Freeze, docs, dress rehearsal

- [ ] **T12 [C] — Docs final sync.** HACKATHON.md gets final results tables
  (eval + benchmark if present), the v2 story **or** honest parity Fallback,
  and **`main` as the canonical branch** (remove remaining
  `fa/cloud-dev-fine-tune` references). README quickstart re-verified by
  actually following it top-to-bottom on a clean checkout.
  *Accept:* a stranger can clone → run → first answer using README alone.

- [ ] **T13 [C+U] — End-to-end dress rehearsal** of
  `docs/hackathon-demo-script.md`, updated for:
  - model beat: v2 token win **or** faithfulness/parity (per gate)
  - MCP beat: external agent gets a cited answer via T5-slim tools
  Time it: must fit ~3 minutes.
  *Accept:* one full uninterrupted rehearsal pass with zero errors.

- [ ] **T14 [C] — CODE FREEZE.** Tag `v1.0-hackathon` on `main`. After this
  point: recordings, submission text, and critical fixes only.
  *Accept:* tag pushed.

---

## Day 5 (Mon 2026-07-13) — Record + submit

- [ ] **T15 [U] — Record deployment proof** (~60s): ECS console Running →
  `curl /api/health` → Model Studio showing the fine-tune deployment (or
  base model if Fallback).
- [ ] **T16 [U] — Record main demo video** (~3 min) per the rehearsed script.
  Upload both; paste URLs into HACKATHON.md.
- [ ] **T17 [C+U] — Submission package final check.** Every box in
  HACKATHON.md's checklist ticked: public repo URL, LICENSE visible,
  architecture PNG exported, video URLs, deployment proof, Track 4 on the
  form, team names filled.
  *Accept:* submission form completed; confirmation screenshot saved.

---

## Defer / cut (explicit — do not sneak back onto Days 2–5)

- Full MCP meta surface (`list`, `breakdown`, `compare`) — post-hackathon.
- Latency script (T10) if Day 3 is tight.
- Full 60-case baseline (T4) if gold cleanup + deploy ate the day — prefer
  honest partial numbers over fake full-set claims.

## Stretch (only if a day finishes early — never at the cost of T6/T11/T13)

Ranked by thesis fit:

1. **S2 — OOD / adversarial eval.** 30–50 cases: typos, slang, compound
   questions, and out-of-scope traps that must be *declined*. Publishing a
   decline-accuracy number is on-thesis (faithfulness > coverage).
2. **S3 — Generalize the entity-coherence guard** in `orchestrator.py`
   beyond the reviews special-case (table-driven carry-over per entity).
3. **S1 — Second real schema.** Load Northwind/Chinook + write its
   `SchemaConfig`; demo `SCHEMA_NAME` swap live. Strongest sell-many proof,
   but highest effort — last among stretch.

---

## Production-ready definition of done (post-hackathon bar)

Hackathon "done" ≠ product "done." Submission needs the checklist above;
this bar is what we keep building toward:

- [ ] All access through `nlq_readonly`; write/DDL structurally impossible.
- [ ] Statement timeout, row caps, rate limiting, request validation active
      in production config.
- [ ] Boot fails fast on missing secrets in `ENVIRONMENT=production`.
- [ ] Errors sanitized client-side; full detail only in server logs + audit
      JSONL.
- [ ] Health endpoint reports db/llm/model/feature-flags truthfully.
- [ ] Full test suite + eval harness runnable by one command each,
      documented in README.
- [ ] Every number claimed in HACKATHON.md reproducible from a committed
      script.
- [ ] Deployment documented well enough that a second engineer can redeploy
      from scratch (`docs/alibaba-cloud-deployment.md`).
- [ ] *(post)* Local LLM path (Ollama/vLLM) behind the same `model_client`
      interface.
- [ ] *(post)* Second real schema (not Shopify stub-only).
- [ ] *(post)* MCP exposes the full meta-tool surface.

## Progress notes

*(append dated notes here as tasks complete)*

- 2026-07-09 — plan created.
- 2026-07-10 — Day 1 missed (T1–T4 unchecked). Plan revised: P0 = T1→T2 +
  T6 + T3; MCP slimmed to count/rank/sum/lookup; Fallback if v2 not Running
  by EOD Day 2; stretch re-ranked S2 > S3 > S1.
- 2026-07-10 — **T1 done.** `--system-mode minimal` on
  `export_sft_dataset.py`; prompt ~98 tokens; wrote
  `datasets/olist_sft_train_min.jsonl` (531) + `_val_min.jsonl` (60);
  DashScope JSONL validate clean; 0 train/val overlap;
  `test_export_sft_dataset.py` 9 passed. **Next: T2** (upload + launch
  fine-tune v2 on Model Studio).
