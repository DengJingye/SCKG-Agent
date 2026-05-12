# v0.2 Freeze Scope

## Purpose

v0.2 is frozen as the trusted recommendation baseline for scKG Agent.

The goal is no longer broad evidence expansion. The goal is to stabilize:

- task parsing
- trusted evidence gating
- MCDM ranking
- semantic audit behavior
- reproducible offline evaluation
- traceable user-facing recommendations

## Frozen Pipeline

The default v0.2 pathway is:

```text
user query
-> deterministic or LLM constraint parsing
-> task ontology refinement
-> trusted evidence gate
-> MCDM top-k ranking
-> structured report generation
-> semantic hallucination audit
```

`evidence_gate_auditor` is the default safe route for user-visible recommendation reports.

`full_kg_pipeline` remains a diagnostic route, not the default product route.

## Allowed Changes Before v0.2 Release

Only these changes are allowed:

- Fix cost-control and offline development behavior.
- Fix deterministic task parsing bugs that clearly route a query to the wrong task.
- Fix evaluation bugs that make route comparisons unfair.
- Fix MCDM bugs where existing reviewed evidence is ignored or mis-scored.
- Fix semantic audit false positives caused by deterministic wording.
- Improve frontend traceability and remove misleading UI elements.

## Deferred To Backlog

The following are intentionally deferred:

- Large-scale evidence expansion.
- Automatic candidate promotion.
- New Neo4j write pathways.
- Complex long-term memory implementation.
- Autonomous execution agent behavior.
- New embedding or retrieval architecture.
- Broad benchmark mining beyond reviewed queues.

## Evidence Rules

Formal evidence source of truth remains:

- `data/tool_publications.tsv`
- `data/tool_benchmarks.tsv`

Candidate evidence under `data/evidence_candidates/` must remain isolated.

Memory, chat history, GitHub metadata, and retrieval-only documents must not become scientific recommendation evidence.

## Offline Development Rule

During development, use:

```bash
--offline-llm
```

or:

```bash
SCKG_OFFLINE_LLM=true
```

Do not run DeepSeek/OpenAI-backed evaluation until code and deterministic metrics are stable.

## Release Validation

Before calling v0.2 stable:

```bash
/Data/Omics/dengjingye/tools/miniconda3/envs/sckg_env/bin/python -B -m py_compile \
  app.py \
  agent/workflow.py \
  core/constraints.py \
  core/llm_client.py \
  core/settings.py \
  engine/mcdm_calculator.py \
  engine/workflow_recommender.py \
  eval/run_ablation.py \
  eval/generate_predictions.py
```

Then run an offline blind eval:

```bash
/Data/Omics/dengjingye/tools/miniconda3/envs/sckg_env/bin/python -B eval/run_ablation.py \
  --gold eval/gold_queries_v0_2_blind.jsonl \
  --output-dir eval/ablation_v0_2_blind_offline_release_candidate \
  --modes evidence_gate,evidence_gate_auditor \
  --offline-llm
```

Only after this passes should the DeepSeek-backed formal comparison be rerun.
