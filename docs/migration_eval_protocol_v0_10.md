# v0.10 Migration Evaluation Protocol

## Purpose

This protocol freezes a fresh sealed evaluation for the exploratory algorithm migration module after the v0.10 dev regression repaired known v0.9 sealed failure modes.

The v0.10 migration module is evaluated as:

```text
Can scKG Agent route reviewed exploratory migration hypotheses while refusing
direct-transfer misuse, toolkit/API traps, evidence lookups, underspecified
I/O requests, and foundation-model overclaims under fresh wording?
```

This protocol does not claim biological validation of any migration hypothesis.

## Relationship To v0.9

The v0.9 sealed first run remains the honest baseline for the prior sealed set.

The v0.10 dev regression on the v0.9 set demonstrates that known v0.9 failures were repaired, but it is not a new sealed proof.

This v0.10 protocol defines a new sealed first run with fresh queries. Results from this run must be reported even if they fail acceptance thresholds.

## Freeze Rule

After `eval/gold_migration_sealed_v0_10.jsonl` is created and validated, the first sealed v0.10 run must be treated as the official v0.10 result.

Allowed before first sealed run:

- code compilation checks
- gold-set schema validation
- candidate-layer review packet synchronization
- plotting script validation on previous outputs

Not allowed after seeing first sealed-run results:

- patching `engine/migration_intent.py`
- patching `engine/migration_hypothesis_engine.py`
- patching scoring logic to improve v0.10 sealed metrics
- editing `eval/gold_migration_sealed_v0_10.jsonl`
- rerunning the same sealed set and presenting the later run as first-run performance

If the first sealed result fails acceptance thresholds, fixes must move to the next version label, `v0.11`.

## Frozen Components

The sealed evaluation tests these code paths:

- `engine/migration_intent.py`
- `engine/migration_hypothesis_engine.py`
- `eval/generate_predictions.py --offline-llm --blind-migration`
- `eval/run_migration_eval.py`
- `eval/plot_migration_eval.py`

No paid LLM API is required.

## Gold Set

Gold file:

```text
eval/gold_migration_sealed_v0_10.jsonl
```

Required case types:

```text
true_positive
revise_only
true_negative
needs_clarification
retrieval_trap
```

The set must include:

- accepted exploratory vectors from the reviewed migration packet
- direct-transfer boundary failures
- true non-migration requests
- underspecified requests that should ask for clarification
- retrieval/name/API traps that should not trigger migration
- hard governance traps for scVelo layers, CellRank kernels, foundation-model causal claims, Scanpy toolkit misuse, scvi-tools suite-level ambiguity, nicheformer deconvolution misuse, and popularity-as-proof claims

## Acceptance Thresholds

v0.10 passes the system-level migration evaluation only if all required thresholds hold:

```text
high_hallucination_rate = 0
unsupported_tool_claim_rate = 0
negative_false_migration_rate <= 0.05
forbidden_tool_violation_rate <= 0.05
clarification_success_rate >= 0.80
positive_source_tool_hit >= 0.60
mixed_decision_accuracy >= 0.75
unreviewed_migration_path_rate <= 0.40
```

Additional diagnostic targets:

```text
positive_migration_output_rate >= 0.70
revise_decision_success_rate >= 0.75
trap_avoidance_rate >= 0.90
expected_caveat_hit_rate >= 0.50
```

Diagnostic targets are not hard pass/fail gates, but failures must be reported.

## Interpretation Levels

Passing this protocol supports only this claim:

```text
scKG Agent shows system-level plausibility for safely routing and caveating
reviewed exploratory algorithm migration hypotheses in a sealed deterministic evaluation.
```

It does not support:

```text
The migrated algorithm is biologically validated.
The migration hypothesis is benchmark-backed.
The source tool is a safe direct replacement for the target task.
The agent has discovered a proven new method.
```

Scientific validity requires later expert review and empirical case studies.

## First-Run Commands

Validate protocol and gold file:

```bash
/Data/Omics/dengjingye/tools/miniconda3/envs/sckg_env/bin/python -B eval/validate_migration_protocol_v0_10.py
```

Generate first-run predictions:

```bash
/Data/Omics/dengjingye/tools/miniconda3/envs/sckg_env/bin/python -B eval/generate_predictions.py \
  --gold eval/gold_migration_sealed_v0_10.jsonl \
  --output eval/migration_sealed_v0_10_first_run_predictions.jsonl \
  --offline-llm --blind-migration
```

Evaluate:

```bash
/Data/Omics/dengjingye/tools/miniconda3/envs/sckg_env/bin/python -B eval/run_migration_eval.py \
  --gold eval/gold_migration_sealed_v0_10.jsonl \
  --predictions eval/migration_sealed_v0_10_first_run_predictions.jsonl \
  --output eval/migration_sealed_v0_10_first_run_eval_summary.tsv \
  --json-output eval/migration_sealed_v0_10_first_run_eval_summary.json \
  --per-query-output eval/migration_sealed_v0_10_first_run_eval_per_query.tsv
```

Plot:

```bash
/Data/Omics/dengjingye/tools/miniconda3/envs/sckg_env/bin/python -B eval/plot_migration_eval.py \
  --summary eval/migration_sealed_v0_10_first_run_eval_summary.tsv \
  --output eval/migration_sealed_v0_10_first_run_summary_chart.svg \
  --subtitle "v0.10 sealed first run: fresh migration governance queries" \
  --title "scKG v0.10 Sealed Migration Evaluation"
```

## Governance

Migration evidence remains exploratory.

The sealed migration evaluation must not:

- write Neo4j
- modify formal evidence TSVs
- promote candidate migration paths into trusted evidence
- alter `data/tool_publications.tsv`
- alter `data/tool_benchmarks.tsv`
