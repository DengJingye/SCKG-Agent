# v0.11 Migration Evaluation Protocol

## Purpose

This protocol freezes a fresh sealed evaluation after v0.11 dev fixes improved routing on the v0.10 sealed set.

The v0.11 migration module is evaluated as:

```text
Can scKG Agent use reviewed algorithm profiles and migration vectors as guardrails
while still routing fresh exploratory queries, refusing incompatible transfers,
and avoiding evidence-lookup traps without paid LLM calls?
```

This protocol tests system-level routing and safety. It does not validate biological truth of any migration hypothesis.

## Relationship To v0.10

The v0.10 sealed first run remains the honest result for the v0.10 fresh set.

The v0.11 dev regression on v0.10 showed that known v0.10 failures were repaired, but it was not a new sealed proof.

This protocol defines a new v0.11 sealed first run. Results must be reported as-is.

## Freeze Rule

After `eval/gold_migration_sealed_v0_11.jsonl` is validated and first-run predictions are generated, the result is official for v0.11.

Not allowed after seeing first-run results:

- editing `eval/gold_migration_sealed_v0_11.jsonl`
- patching migration intent or scoring logic and calling it the same first run
- modifying candidate review decisions to improve metrics

If the first sealed result fails, fixes move to v0.12.

## Gold Set

Gold file:

```text
eval/gold_migration_sealed_v0_11.jsonl
```

Required case types:

```text
true_positive
revise_only
true_negative
needs_clarification
retrieval_trap
```

The set mixes:

- accepted migration vectors
- direct-transfer misuse
- underspecified scientific design
- normal recommendation and evidence lookup requests
- naming traps around foundation models, toolkits, benchmarks, and workflow compatibility

## Acceptance Thresholds

Required:

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

Diagnostic:

```text
positive_migration_output_rate >= 0.70
revise_decision_success_rate >= 0.75
trap_avoidance_rate >= 0.90
expected_caveat_hit_rate >= 0.50
```

## Interpretation

Passing supports only:

```text
The migration layer has sealed system-level plausibility for routing reviewed
exploratory hypotheses and blocking common unsafe transfer patterns.
```

Passing does not support:

```text
The migration hypothesis is biologically validated.
The method is benchmark-backed for the new task.
The source tool is a safe direct replacement.
The agent has discovered a proven new algorithm.
```

## Commands

```bash
/Data/Omics/dengjingye/tools/miniconda3/envs/sckg_env/bin/python -B eval/validate_migration_protocol_v0_11.py

/Data/Omics/dengjingye/tools/miniconda3/envs/sckg_env/bin/python -B eval/generate_predictions.py \
  --gold eval/gold_migration_sealed_v0_11.jsonl \
  --output eval/migration_sealed_v0_11_first_run_predictions.jsonl \
  --offline-llm --blind-migration

/Data/Omics/dengjingye/tools/miniconda3/envs/sckg_env/bin/python -B eval/run_migration_eval.py \
  --gold eval/gold_migration_sealed_v0_11.jsonl \
  --predictions eval/migration_sealed_v0_11_first_run_predictions.jsonl \
  --output eval/migration_sealed_v0_11_first_run_eval_summary.tsv \
  --json-output eval/migration_sealed_v0_11_first_run_eval_summary.json \
  --per-query-output eval/migration_sealed_v0_11_first_run_eval_per_query.tsv

/Data/Omics/dengjingye/tools/miniconda3/envs/sckg_env/bin/python -B eval/plot_migration_eval.py \
  --summary eval/migration_sealed_v0_11_first_run_eval_summary.tsv \
  --output eval/migration_sealed_v0_11_first_run_summary_chart.svg \
  --subtitle "v0.11 sealed first run: fresh migration governance queries" \
  --title "scKG v0.11 Sealed Migration Evaluation"
```

## Governance

This evaluation must not:

- write Neo4j
- call paid LLM APIs
- modify formal evidence TSVs
- promote candidate migration paths into trusted evidence
