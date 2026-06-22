# scKG-Atlas Agent

scKG-Atlas Agent is an evidence-governed recommendation and workflow prototype for single-cell, spatial, and multi-omics tool selection. It is not meant to behave like an unconstrained chatbot. Its core job is to convert a research request into structured constraints, retrieve only governed evidence, rank cautiously, expose missing evidence, and prevent unsupported scientific claims from entering the final report.

The current system combines:

- a Streamlit research assistant UI;
- a LangGraph workflow for parsing, retrieval, ranking, workflow assembly, migration routing, and report generation;
- formal TSV evidence tables for reviewed publication and benchmark support;
- optional Neo4j / AuraDB graph access with a local offline fallback;
- a controlled Hybrid KG-RAG `EvidenceContextPack`;
- semantic hallucination auditing before reports are accepted;
- candidate evidence and review queues kept outside the trusted recommendation path;
- a read-only KG quality audit and a quieter default graph explorer view.

## Current Status

This repository is now closer to an evidence-governance system than a simple MVP. The main recommendation path is intentionally narrow:

### Stage Position

If the project is mapped onto the four working stages below, the current primary stage is **C. LLM evaluation / trustworthiness**.

| Stage | Current status | Evidence from the repository |
| --- | --- | --- |
| A. Complete agent pipeline | Partial, not production-complete | LangGraph has a closed parse -> retrieve -> rank/migrate -> report -> audit loop, but execution agents, full workflow graph evidence, robust production serving, and large reviewed evidence coverage are still missing. |
| B. Retrieval + evidence support | Implemented and active | Formal publication/benchmark TSVs, Neo4j/offline fallback retrieval, evidence gates, `trusted_core` filtering, and candidate-only review queues are in place. |
| C. LLM evaluation / trustworthiness | Current focus | Ablation modes, sealed migration evals, semantic hallucination audits, controlled `EvidenceContextPack`, and safe blocked reports are implemented and have local result artifacts. |
| D. Tool workflow prototype | Implemented as a prototype | Deterministic workflow templates exist and are shown in predictions/reports, but step-level benchmark evidence and workflow graph validation remain open. |

The short answer: **B and D are usable prototypes; C is the current active milestone; A has a working skeleton but is not complete enough to claim a full production agent pipeline.**

```text
raw retrieval
  -> evidence gate
  -> trusted_core filtering
  -> top-k selection
  -> EvidenceContextPack
  -> report generation
  -> semantic hallucination audit
```

Important current inventory, regenerated from local files:

| Asset | Current count |
| --- | ---: |
| `data/scrna_tools.tsv` rows excluding header | 1,842 |
| formal publication rows | 28 |
| formal benchmark rows | 14 |
| unique candidate evidence IDs counted by graph inventory | 178 |
| default graph visible nodes | 23 Tool + 23 Task |
| default graph visible edges | 44 |
| full local graph inventory edges | 86 |
| KG quality audit issues | 126 |
| KG quality review actions | 49 |

The formal publication and benchmark tables are still small and conservative. That is deliberate: weak candidate material must stay in review queues until human-approved.

## Repository Layout

```text
app.py
  Streamlit UI. Provides chat history, upload context, local user memory,
  API-key settings, and the sidebar-linked KG explorer.

agent/
  states.py              State model for the LangGraph workflow.
  workflow.py            Main agent graph: parse -> retrieve -> rank/migrate -> report -> audit.

core/
  constraints.py         Research-constraint parsing and deterministic fallback.
  evidence_policy.py     Recommendation-grade evidence gates and top-k limits.
  evidence_schemas.py    Canonical TSV field order for formal publication/benchmark evidence.
  llm_client.py          OpenAI-compatible LLM client wrapper.
  models.py              Pydantic scientific objects: Evidence, ToolCandidate, ScoredTool,
                         WorkflowRecommendation, MigrationPath, EvidenceContextPack,
                         PredictionRecord.
  prompts.py             Prompt contracts for parsing and report generation.
  settings.py            Single configuration entry point.
  task_ontology.py       Task aliases, task families, and tool-task hints.
  user_store.py          Local SQLite chat history, memory, working context, encrypted API config.

connectors/
  graph_client.py        Neo4j client with optional offline fallback.
  offline_graph.py       Local read-only graph store built from data files.

engine/
  context_pack_builder.py        Builds the controlled Hybrid KG-RAG context.
  context_pack_reporter.py       Deterministic offline report renderer.
  formal_evidence_rag.py         Read-only formal evidence snippets from local TSVs.
  isomorphism_analyzer.py        Embedding-based exploratory algorithm similarity search.
  knowledge_graph_view.py        Read-only local TSV graph explorer model and HTML renderer.
  mcdm_calculator.py             Evidence-aware MCDM scoring.
  migration_hypothesis_engine.py Reviewed exploratory migration hypothesis builder.
  migration_intent.py            Deterministic migration intent gate and blockers.
  semantic_hallucination_auditor.py Report claim audit.
  workflow_recommender.py        Minimal workflow skeleton builder.

data/
  scrna_tools.tsv                 Tool catalog.
  tool_publications.tsv           Formal reviewed publication evidence.
  tool_benchmarks.tsv             Formal reviewed benchmark evidence.
  scKG_embeddings_backup.jsonl    Local algorithm feature / embedding backup.
  evidence_candidates/            Candidate-only evidence, review packets, audit reports.

data_pipeline/
  evidence_candidate_crawler.py   Candidate publication/benchmark crawl.
  build_*_review*.py              Review packet builders.
  promote_*_evidence.py           Human-reviewed promotion scripts for formal TSVs.
  evidence_backfill.py            Formal evidence backfill into graph Evidence nodes.
  sync_reviewed_tool_nodes.py     Reviewed Tool node sync.
  kg_quality_audit.py             Read-only local KG quality audit.
  export_graph_snapshot.py        Read-only Neo4j graph snapshot export.

eval/
  generate_predictions.py         Standard prediction JSONL generator.
  run_eval.py                     Constraint/retrieval/evidence/report eval.
  run_migration_eval.py           Exploratory migration evaluation.
  audit_context_pack_v0_12.py     ContextPack hallucination/governance audit.
  validate_*.py                   Protocol validators.
  gold_*.jsonl                    Gold query sets.

docs/
  schema.md                       Graph and evidence governance schema.
  evidence_curation_verification.md Candidate curation verification notes.
  migration_eval_protocol_*.md    Frozen migration evaluation protocols.
  roadmap_v0_12.md                Hybrid KG-RAG / context-pack roadmap.
```

## Governance Rules

The project follows the rules in `AGENTS.md`. The short version:

- Do not make recommendation-grade claims without structured evidence.
- Candidate evidence under `data/evidence_candidates/` is not trusted evidence.
- Candidate evidence must not be auto-promoted into `data/tool_publications.tsv`, `data/tool_benchmarks.tsv`, AuraDB, or Neo4j.
- Formal evidence tables must preserve field order from `core/evidence_schemas.py`.
- Approved formal review statuses are `reviewed`, `verified`, and `human_reviewed`.
- Rejected/deprecated evidence must not enter recommendation pathways.
- GitHub activity alone is not enough for strong scientific recommendation claims.
- Migration paths are exploratory hypotheses unless separately reviewed and validated.
- Reports must be auditable against `Evidence`, `scored_tools`, workflow state, migration paths, and `EvidenceContextPack`.

## Evidence Layers

The project separates evidence into layers:

| Layer | Meaning | Allowed use |
| --- | --- | --- |
| `trusted_core` | Human-reviewed or otherwise trusted formal evidence. | Retrieval, ranking, recommendation, report, if policy gates pass. |
| `review_needed` | Candidate or source-based material needing human review. | Retrieval/review only. |
| `experimental` | LLM extraction, derived similarity, synthetic templates, migration hypotheses. | Exploration only. |

Formal table approval is still not sufficient by itself. The main recommendation path also checks source type, metric, canonical scope, authority tier, recommendation eligibility, and use flags through `core/evidence_policy.py`.

## Configuration

Use Python 3.10+.

The current dependency file is:

```bash
pip install -r requirements.txt
```

Create local configuration from the template:

```bash
cp .env.example .env
```

Important environment variables:

```env
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=change_me

OPENAI_API_BASE=https://api.deepseek.com
OPENAI_API_KEY=change_me
DEEPSEEK_API_KEY=change_me
MODEL_NAME=deepseek-v4-pro
EXTRACT_MODEL=deepseek-v4-pro
CHAT_API_BASE=https://api.deepseek.com

EMBEDDING_API_KEY=change_me
SILICONFLOW_API_KEY=
EMBEDDING_MODEL=BAAI/bge-m3
EMBEDDING_API_BASE=https://api.siliconflow.cn/v1/embeddings

LOG_LEVEL=INFO
KG_VERSION=v0.1
EMBEDDING_VERSION=bge-m3-v0.1
OFFLINE_GRAPH_FALLBACK=true
SCKG_OFFLINE_LLM=false
DISABLE_LLM_CALLS=false
```

`core/settings.py` is the only configuration entry point. Avoid adding direct `os.getenv` calls in business logic.

## Running the App

From the repository root:

```bash
/Data/Omics/dengjingye/tools/miniconda3/envs/sckg_env/bin/python -B -m streamlit run app.py
```

or, if your shell has the environment activated:

```bash
streamlit run app.py
```

The UI has two main views:

- Chat view: evidence-governed assistant, file upload context, local chat history, project memory, and optional user API config.
- Graph view: entered from the sidebar Knowledge graph card. The default graph shows only the formal trusted Tool-Task trunk. Publication and Benchmark nodes stay hidden until the user searches or changes filters.

The local user store lives under `.sckg_user/`. It contains chat sessions, project memory, working context, and encrypted user API configuration.

## KG Quality Audit

Phase 1 KG quality governance is read-only. It audits formal TSVs and writes review outputs under `data/evidence_candidates/`.

Run:

```bash
/Data/Omics/dengjingye/tools/miniconda3/envs/sckg_env/bin/python -B data_pipeline/kg_quality_audit.py
```

Outputs:

```text
data/evidence_candidates/kg_quality_audit_report.tsv
data/evidence_candidates/kg_quality_review_actions.tsv
```

Current audit highlights:

| Issue type | Count |
| --- | ---: |
| `candidate_marker_in_formal_table` | 28 |
| `missing_task` | 7 |
| `missing_work_group_id` | 14 |
| `missing_pmid` | 28 |
| `missing_paper_pmid` | 14 |
| `duplicate_tool_task_edge` | 6 |
| `high_degree_hub` | 1 |

This script does not modify `data/tool_publications.tsv`, `data/tool_benchmarks.tsv`, AuraDB, or Neo4j. Every generated review action keeps `formal_table_mutation_allowed=false`.

## Formal Evidence Workflow

Preferred evidence workflow:

```text
generate candidates
  -> normalize records
  -> group duplicates
  -> generate review actions
  -> human review
  -> promote reviewed evidence
  -> backfill structured graph
  -> run evaluation
  -> run semantic hallucination audit
```

Useful commands:

```bash
# Candidate crawl. Network access required.
/Data/Omics/dengjingye/tools/miniconda3/envs/sckg_env/bin/python -B \
  data_pipeline/evidence_candidate_crawler.py --help

# Build publication review packet.
/Data/Omics/dengjingye/tools/miniconda3/envs/sckg_env/bin/python -B \
  data_pipeline/build_publication_review_packet.py --help

# Build benchmark review packet.
/Data/Omics/dengjingye/tools/miniconda3/envs/sckg_env/bin/python -B \
  data_pipeline/build_benchmark_review_packet.py --help

# Promote only after explicit human review.
/Data/Omics/dengjingye/tools/miniconda3/envs/sckg_env/bin/python -B \
  data_pipeline/promote_publication_evidence.py --help

/Data/Omics/dengjingye/tools/miniconda3/envs/sckg_env/bin/python -B \
  data_pipeline/promote_benchmark_evidence.py --help
```

Do not hand-edit formal TSV schemas casually. If columns change, update `core/evidence_schemas.py`, promotion scripts, backfill scripts, tests, and docs together.

## Graph and Neo4j

The recommendation pipeline can query Neo4j through `connectors/graph_client.py`. If `OFFLINE_GRAPH_FALLBACK=true`, connection failures fall back to `connectors/offline_graph.py`, which reads local data files.

Connectivity check:

```bash
/Data/Omics/dengjingye/tools/miniconda3/envs/sckg_env/bin/python -B -c \
"from neo4j import GraphDatabase; from core.settings import get_settings; s=get_settings(); uri,user,pwd=s.require_neo4j(); d=GraphDatabase.driver(uri, auth=(user,pwd)); d.verify_connectivity(); print('neo4j_connectivity_ok'); d.close()"
```

Read-only graph snapshot export:

```bash
/Data/Omics/dengjingye/tools/miniconda3/envs/sckg_env/bin/python -B \
  data_pipeline/export_graph_snapshot.py --help
```

Reviewed Tool/Evidence sync scripts exist, but they should be run only when the formal TSV evidence has passed review.

## Evaluation

Latest local evaluation artifacts indicate that the trustworthiness layer is now being measured explicitly, not just described in code:

| Artifact | Snapshot |
| --- | --- |
| `eval/ablation_deepseek_aura_v0_2_blind_after_mcdm_qual_benchmark_fix_v2/ablation_summary.json` | 12 blind recommendation queries. `full_kg_pipeline`: top-k hit 1.0000, recommendation type accuracy 0.9167, hallucination rate 0.0058, high hallucination rate 0.0000, semantic audit pass rate 0.8333, blocked report rate 0.2500. `evidence_gate_auditor`: hallucination rate 0.0000 and semantic audit pass rate 1.0000. |
| `eval/context_pack_v0_12_full_offline_audit_summary_v2.json` | 35 context-pack predictions audited. Context pack present rate 1.0000, retrieval rankable violations 0, trusted non-main violations 0, bad migration decision violations 0, failed queries 0. |
| `eval/context_pack_v0_12_full_offline_migration_eval_summary_v2.json` | 35 migration/boundary queries. Mixed decision accuracy 1.0000, positive source-tool hit 1.0000, negative false migration rate 0.0000, clarification success rate 1.0000, trap avoidance rate 1.0000, semantic audit pass rate 1.0000. |

These numbers support the current **C-stage** claim, but they do not make the system production-complete. The eval sets are still bounded, and formal reviewed evidence coverage remains intentionally small.

## Production Agent Engineering Highlights

The current engineering upgrade adds a job-ready Agent layer without weakening evidence governance:

- Typed Tool Use: `ToolSpec`, `ToolCall`, `ToolResult`, `ToolRegistry`, and `ToolExecutor` wrap key agent operations with schema names, argument hashes, status, latency, and result sizing.
- Traceable governed multi-agent workflow: deterministic prediction runs now expose role handoffs for `IntentAgent`, `RetrievalAgent`, `EvidenceGateAgent`, `RankingAgent`, `WorkflowPlannerAgent`, `MigrationAgent`, `ReportAgent`, and `AuditorAgent`.
- Guardrail-first auditing: `AuditorAgent` can mark a run as `blocked_by_guardrail`; high/critical semantic hallucination findings are replaced by a safe blocked report.
- AgentRun evaluation: `eval/run_agent_eval.py` reports task success, progress, Pass@1, tool-call accuracy, trajectory match, invalid action rate, average steps, latency, hallucination rates, blocked report rate, and recovery success.
- Controlled RAG baseline: formal TSV rows are chunked, retrieved with an offline lexical fallback, reranked deterministically, and inserted only into `EvidenceContextPack.retrieval_context`.

This is intentionally **not** an open-ended AutoGPT/AutoGen-style free conversation between agents. It is a governed LangGraph-compatible handoff model: every role has a narrow responsibility, evidence boundaries remain explicit, and candidate evidence cannot be promoted automatically.

Generate deterministic predictions:

```bash
/Data/Omics/dengjingye/tools/miniconda3/envs/sckg_env/bin/python -B \
  eval/generate_predictions.py \
  --gold eval/gold_queries.jsonl \
  --output eval/predictions.jsonl \
  --offline-llm
```

Evaluate predictions:

```bash
/Data/Omics/dengjingye/tools/miniconda3/envs/sckg_env/bin/python -B \
  eval/run_eval.py \
  --gold eval/gold_queries.jsonl \
  --predictions eval/predictions.jsonl
```

Run a migration sealed evaluation:

```bash
/Data/Omics/dengjingye/tools/miniconda3/envs/sckg_env/bin/python -B \
  eval/generate_predictions.py \
  --gold eval/gold_migration_sealed_v0_11.jsonl \
  --output eval/migration_sealed_v0_11_predictions.jsonl \
  --offline-llm \
  --blind-migration

/Data/Omics/dengjingye/tools/miniconda3/envs/sckg_env/bin/python -B \
  eval/run_migration_eval.py \
  --gold eval/gold_migration_sealed_v0_11.jsonl \
  --predictions eval/migration_sealed_v0_11_predictions.jsonl \
  --output eval/migration_sealed_v0_11_eval_summary.tsv \
  --json-output eval/migration_sealed_v0_11_eval_summary.json \
  --per-query-output eval/migration_sealed_v0_11_eval_per_query.tsv
```

Run context-pack audit:

```bash
/Data/Omics/dengjingye/tools/miniconda3/envs/sckg_env/bin/python -B \
  eval/audit_context_pack_v0_12.py --help
```

Run AgentRun engineering evaluation:

```bash
/Data/Omics/dengjingye/tools/miniconda3/envs/sckg_env/bin/python -B \
  eval/run_agent_eval.py \
  --gold eval/gold_queries_v0_2_blind.jsonl \
  --predictions eval/predictions.jsonl \
  --json-output eval/agent_run_eval_summary.json \
  --output eval/agent_run_eval_summary.tsv \
  --per-query-output eval/agent_run_eval_per_query.tsv
```

Prediction JSONL records follow `core.models.PredictionRecord` and include:

```text
query_id, user_query, parsed_constraints, candidate_tools, scored_tools,
migration_paths, recommendation_type, evidence_bundle, context_pack,
workflow_recommendation, final_report, missing_components,
clarification_needed, execution_status, recommended_tools,
claim_count, unsupported_claims, hallucination_audit, trace_id,
agent_trace_summary, tool_call_count, failed_tool_call_count,
mean_tool_latency_ms, invalid_action_count, blocked_by_guardrail
```

## Validation Before Major Changes

At minimum:

```bash
/Data/Omics/dengjingye/tools/miniconda3/envs/sckg_env/bin/python -B -m py_compile \
  app.py \
  agent/workflow.py \
  core/models.py \
  core/agent_runtime.py \
  core/evidence_policy.py \
  engine/context_pack_builder.py \
  engine/evidence_rag_pipeline.py \
  engine/knowledge_graph_view.py \
  data_pipeline/kg_quality_audit.py \
  eval/generate_predictions.py \
  eval/run_eval.py \
  eval/run_agent_eval.py

/Data/Omics/dengjingye/tools/miniconda3/envs/sckg_env/bin/python -B data_pipeline/kg_quality_audit.py

/Data/Omics/dengjingye/tools/miniconda3/envs/sckg_env/bin/python -B \
  eval/generate_predictions.py --limit 3 --offline-llm --output /tmp/sckg_smoke_predictions.jsonl

/Data/Omics/dengjingye/tools/miniconda3/envs/sckg_env/bin/python -B \
  eval/run_eval.py --predictions /tmp/sckg_smoke_predictions.jsonl

/Data/Omics/dengjingye/tools/miniconda3/envs/sckg_env/bin/python -B \
  eval/run_agent_eval.py \
  --predictions /tmp/sckg_smoke_predictions.jsonl \
  --json-output /tmp/sckg_agent_run_eval_summary.json \
  --output /tmp/sckg_agent_run_eval_summary.tsv \
  --per-query-output /tmp/sckg_agent_run_eval_per_query.tsv
```

For UI work, also start Streamlit and check:

- chat view still loads;
- history and new chat switch back to chat view;
- sidebar Knowledge graph card switches to graph view;
- default graph shows Tool/Task only;
- searching a tool expands publication/benchmark evidence;
- candidate evidence is shown only as a count.

## Known Gaps

Current priority gaps:

- Formal publication rows still carry candidate-origin markers.
- Some publication rows lack task mappings and therefore cannot create Tool-Task trunk edges.
- Benchmark rows still need conservative `work_group_id` assignment.
- PMID fields are currently blank for formal publication and benchmark rows.
- Candidate/review files are numerous and need continued normalization.
- Neo4j/AuraDB sync governance should be treated as phase 2 after local TSV audit stabilizes.

Non-goals for the next step:

- Do not expand the graph before evidence quality improves.
- Do not auto-promote candidate evidence.
- Do not loosen hallucination audit gates to improve surface fluency.
- Do not use GitHub popularity as a substitute for scientific evidence.

## Recommended Next Work

1. Use `kg_quality_review_actions.tsv` as the work queue.
2. Human-review and normalize candidate-origin markers in formal publication rows.
3. Assign conservative benchmark `work_group_id` values.
4. Fill missing task mappings only when source-supported.
5. Add DOI/PMID metadata where available, or record explicit no-PMID notes.
6. Re-run `kg_quality_audit.py`, then run smoke predictions and hallucination audit.
7. Only after the local TSV layer is clean, sync reviewed evidence into Neo4j/AuraDB.

The north star is not maximal automation. It is trustworthy scientific recommendation: traceable evidence, conservative reasoning, reproducible outputs, and clear boundaries between formal evidence, retrieval-only context, and exploratory hypotheses.
