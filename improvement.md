# Improvement Plan — 5 Days to Production-Ready Submission

> **Window:** 2026-07-09 → 2026-07-13 (hackathon extension; days 6–10 held as
> reserve buffer — nothing is scheduled there on purpose).
> **Goal:** ship a production-grade, fully-tested, fully-demoed submission —
> and leave the repo in a state we can keep building the product on after the
> hackathon.

## Ground rules

1. **Sequential, not parallel-everything.** Each task has an owner, a hard
   acceptance criterion, and blocks the tasks listed after it. If a task
   slips, cut from the *stretch* list — never from testing or recording days.
2. **Code freeze end of Day 4.** Days 5+ are recordings, submission, and
   emergency fixes only. No new features after freeze.
3. **Every change lands with tests green.** `cd backend && ../venv/bin/python
   -m pytest -q` must pass before any commit on Days 1–4.
4. **Honesty in claims.** Numbers in HACKATHON.md must be reproducible from
   `backend/scripts/eval_finetune.py` output on the day of submission.

**Owners:** `[C]` = Claude Code · `[U]` = Farhan (things only a human with
console/browser access can do) · `[C+U]` = joint.

---

## Day 1 (Thu 2026-07-09) — Fine-tune v2 kickoff + eval truth

The retrain runs unattended for hours, so it must launch **first**.

- [ ] **T1 [C] — Minimal-prompt SFT export.** Add `--system-mode minimal` to
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
- [ ] **T3 [C] — Clean eval gold labels.** Fix the systematic omissions that
  cap every accuracy number: add `entity: products` to rank cases, explicit
  `score_max` handling on review cases, and any other gaps
  `eval_finetune.py --show` surfaces. Fix in `backend/tests/eval_set.json` /
  `meta_eval_set.json` (and regenerate the *original* SFT set so it stays
  consistent).
  *Accept:* base-model eval re-run shows misses are real model errors only;
  full pytest green.
- [ ] **T4 [C] — Re-run base eval + record baseline.** Full 60-case run with
  cleaned gold; save output to `docs/eval-results.md` (new file — the
  results ledger for the submission table).
  *Accept:* `docs/eval-results.md` exists with dated base-model numbers.

## Day 2 (Fri 2026-07-10) — MCP depth + Alibaba deployment

Two independent tracks; deploy is the **hard submission requirement**.

- [ ] **T5 [C] — MCP server v2.** Expand `backend/mcp_server/` from 3 tools to
  the full meta-tool surface: `count`, `rank`, `sum`, `list`, `breakdown`,
  `compare`, `lookup` (each routed through the same validation + read-only
  path as the API), keeping `health_check` + `eval_summary`. Update
  `docs/mcp-demo.md` with a scripted Cursor/agent walkthrough: *external
  agent asks a business question → validated tool call → cited answer*.
  *Accept:* `test_mcp_tools.py` extended and green; manual stdio smoke test
  of at least `count` and `rank` returns real DB numbers with citations.
- [ ] **T6 [U] — Alibaba Cloud deploy.** Follow
  `docs/alibaba-cloud-deployment.md`: ECS instance + Postgres (RDS or
  ECS-hosted) + `.env` with production flags (`ENVIRONMENT=production`,
  `META_TOOLS_ENABLED=true`, `USE_FINETUNED_MODEL` as desired).
  *Accept:* public `curl <host>/api/health` returns `db: ok, llm: ok`; fill
  instance IDs/region into the deployment doc.
- [ ] **T7 [C] — Production config audit.** Verify boot guards (fail fast on
  missing `DASHSCOPE_API_KEY`/`DB_URL` in production), CORS locked to the
  frontend origin, cookie security flags, rate limits, statement timeout,
  and sanitized client errors. Fix anything loose; add missing boot checks.
  *Accept:* a written pass/fail list in `docs/eval-results.md` appendix;
  fixes committed with tests.

## Day 3 (Sat 2026-07-11) — Fine-tune v2 results + benchmark + hardening

- [ ] **T8 [U] — Deploy fine-tune v2** from Model Studio when training
  completes; record the new deployment ID in `.env` +
  `docs/dashscope-finetune.md`.
- [ ] **T9 [C] — Head-to-head eval.** Extend `eval_finetune.py` to support the
  minimal-prompt mode; run **base (full prompt) vs v1 (full prompt) vs v2
  (minimal prompt)** on the cleaned val set.
  *Accept:* results table in `docs/eval-results.md`. Decision gate: if v2
  holds accuracy within ~2% of base, it becomes the demo model and the
  headline is "same accuracy, ~97% fewer prompt tokens"; if not, we demo v1
  and state parity honestly — no spin.
- [ ] **T10 [C] — Latency & token benchmark.** Measure p50/p95 end-to-end
  latency and input-tokens/query for: base, fine-tune, cache-hit. Small
  script (`backend/scripts/bench_latency.py`), ~20 queries each.
  *Accept:* benchmark table added to `docs/eval-results.md` and summarized
  in HACKATHON.md.
- [ ] **T11 [C] — Bug-fix + full regression pass.** Full pytest suite,
  frontend `npm test` + `npm run build`, then a manual end-to-end session
  against the local stack: happy path, clarify path, decline path,
  multi-turn carry-over, SQL-escape path, pagination. File and fix
  everything found today, not later.
  *Accept:* all suites green; a short "known issues" list (ideally empty) in
  `improvement.md` progress notes.

## Day 4 (Sun 2026-07-12) — Freeze, docs, dress rehearsal

- [ ] **T12 [C] — Docs final sync.** HACKATHON.md gets the final results
  tables (eval + benchmark), the v2 fine-tune story, and `main` as the
  canonical branch (remove remaining `fa/cloud-dev-fine-tune` references).
  README quickstart re-verified by actually following it top-to-bottom on a
  clean checkout.
  *Accept:* a stranger can go clone → run → first answer using README alone.
- [ ] **T13 [C+U] — End-to-end dress rehearsal** of the demo script
  (`docs/hackathon-demo-script.md`), updated to include the two new beats:
  fine-tune v2 (health endpoint showing `finetuned: enabled` + the token
  win) and MCP (external agent gets a cited answer). Time it: must fit ~3
  minutes.
  *Accept:* one full uninterrupted rehearsal pass with zero errors.
- [ ] **T14 [C] — CODE FREEZE.** Tag `v1.0-hackathon` on `main`. After this
  point: recordings, submission text, and critical fixes only.
  *Accept:* tag pushed.

## Day 5 (Mon 2026-07-13) — Record + submit

- [ ] **T15 [U] — Record deployment proof** (~60s): ECS console Running →
  `curl /api/health` → Model Studio showing the fine-tune deployment.
- [ ] **T16 [U] — Record main demo video** (~3 min) per the rehearsed script.
  Upload both; paste URLs into HACKATHON.md.
- [ ] **T17 [C+U] — Submission package final check.** Every box in
  HACKATHON.md's checklist ticked: public repo URL, LICENSE visible,
  architecture PNG exported, video URLs, deployment proof, Track 4 on the
  form, team names filled.
  *Accept:* submission form completed; confirmation screenshot saved.

---

## Stretch (only if a day finishes early — never at the cost of T11/T13)

- **S1 — Second real schema.** Load a second public dataset (Northwind or
  Chinook) into Postgres + write its `SchemaConfig`; demo `SCHEMA_NAME` swap
  live. Strongest possible proof of the build-once-sell-many claim.
- **S2 — OOD / adversarial eval.** 30–50 cases: typos, slang, compound
  questions, and out-of-scope traps that must be *declined*. Publishing a
  decline-accuracy number is on-thesis (faithfulness > coverage).
- **S3 — Generalize the entity-coherence guard** in `orchestrator.py` beyond
  the reviews special-case (table-driven carry-over per entity).

## Production-ready definition of done (post-hackathon bar)

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

## Progress notes

*(append dated notes here as tasks complete)*

- 2026-07-09 — plan created.
