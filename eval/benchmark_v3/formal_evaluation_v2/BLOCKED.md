# Formal evaluation v2: scoring blocked

Status: **BLOCKED — no final scientific score is claimed.**

The frozen product run is complete and healthy:

- 36 scenarios, K=24 / O=8 / W=4.
- 432/432 run units completed; 108 per lane.
- 578/578 product-runtime provider calls completed.
- 0 product-runtime provider failures and 0 run failures.
- All frozen hashes, lane-isolation receipts, and runtime receipts passed.

The two lane-blind semantic review passes also completed 72/72 provider calls,
covering 864 review rows. Of those rows, 800 passed the frozen output schema.
The remaining 64 contained output-schema defects (non-exact quote anchors,
null in-track booleans, or an invalid required-fact map). Raw responses are
preserved. Per the frozen method, schema-invalid rows and ordinary A/B
disagreements were routed to the separate adjudication pass rather than
silently coerced.

The first adjudication request failed with HTTP 402 `Insufficient Balance`.
No adjudication result was obtained, so 167 disputed/schema-invalid run
judgments remain unresolved. Computing track scores before adjudication would
change the frozen scoring procedure and could bias the result; it was not done.

After the configured DeepSeek account has sufficient balance, resume with:

```bash
PYTHONPATH=/Users/lris/Desktop/scKG_agent/SCKG-Agent-eval-v3 \
python eval/benchmark_v3/recover_formal_evaluation_v2_scoring.py \
  --runtime /private/tmp/sckg-dev-final-freeze.1ZbAbZ/runtime \
  --env-file /Users/lris/Desktop/scKG_agent/SCKG-Agent/.env

PYTHONPATH=/Users/lris/Desktop/scKG_agent/SCKG-Agent-eval-v3 \
python eval/benchmark_v3/formal_evaluation_v2_score.py finalize \
  --runtime /private/tmp/sckg-dev-final-freeze.1ZbAbZ/runtime \
  --env-file /Users/lris/Desktop/scKG_agent/SCKG-Agent/.env
```

This resumes scoring only. It does not rerun, retry, replace, or cherry-pick
any of the 432 formal lane answers.
