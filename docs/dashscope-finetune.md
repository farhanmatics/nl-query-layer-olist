# DashScope fine-tuning (Olist schema pack)

This guide covers Phase B of the fine-tune plan: train a domain-specific
translator on top of `qwen3.7-plus` using exported SFT data.

## 1. Export the dataset

```bash
cd backend
python scripts/export_sft_dataset.py
```

Outputs:

- `datasets/olist_sft_train.jsonl` (~90% of examples)
- `datasets/olist_sft_val.jsonl` (~10% holdout)

Schema pack metadata: [`backend/schemas/olist/pack.json`](../backend/schemas/olist/pack.json).

## 2. Validate before upload

```bash
python backend/scripts/submit_finetune_job.py \
  --train datasets/olist_sft_train.jsonl \
  --val datasets/olist_sft_val.jsonl
```

## 3. Submit SFT job (Model Studio)

1. Open [Alibaba Cloud Model Studio](https://modelstudio.console.alibabacloud.com/) (DashScope).
2. Fine-tuning → Create job.
3. Base model: `qwen3.7-plus`.
4. Upload train + validation JSONL. **Each line must be only** `{"messages": [...]}`
   with roles `system`, `user`, `assistant` — DashScope rejects extra keys like `id`
   or `source`. Our export script strips those automatically.
5. Training type: SFT / LoRA (per account availability).
6. Start job and note the **deployed model ID** when complete.

Record the job ID and model ID in [`alibaba-cloud-deployment.md`](alibaba-cloud-deployment.md).

## 4. Wire the fine-tuned model

In `.env`:

```env
DASHSCOPE_FINETUNE_MODEL=<your-deployed-model-id>
USE_FINETUNED_MODEL=true
```

The orchestrator uses `settings.active_llm_model`, which selects the fine-tuned
ID when `USE_FINETUNED_MODEL=true`.

## 5. A/B evaluation

Run the live eval suite against base vs fine-tuned:

```bash
# Base model (default)
USE_FINETUNED_MODEL=false pytest backend/tests/test_eval.py -m live -v

# Fine-tuned
USE_FINETUNED_MODEL=true pytest backend/tests/test_eval.py -m live -v
```

Target: improved pass rate on meta-tool routing and SQL escape cases without
higher guard `applied` rate or latency regression.

## 6. Planner mode (optional)

Multi-step plans are behind `PLANNER_ENABLED=true`. The SFT dataset includes
`mode: single|chain` examples from `chain_eval_set.json` and the SQL curriculum.

Offline chain tests:

```bash
pytest backend/tests/test_chain_executor_offline.py -v
```
