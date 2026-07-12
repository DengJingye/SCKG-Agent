# scKG-Atlas Agent Developer Specification

Version: 0.1
Status: Working specification
Last updated: 2026-06-22

## 1. Purpose

scKG-Atlas Agent is an evidence-governed KG-RAG Agent for single-cell,
spatial, and multi-omics tool recommendation. The project is not a general
chatbot and should not optimize for unconstrained fluency. Its core product
loop is:

```text
research request
  -> structured scientific constraints
  -> governed KG retrieval
  -> formal evidence gate
  -> cautious ranking or migration routing
  -> controlled EvidenceContextPack
  -> auditable report
  -> semantic hallucination audit
```

The long-term goal is to become a callable, traceable scientific evidence
service:

```text
Evidence-governed KG-RAG MCP Server for auditable omics tool recommendation
```

This specification exists to stop scattered changes. Every new feature should
map to one stage, one contract, and one validation path in this document.

## 2. Product Positioning

### 2.1 What the system should do

- Parse user research needs into stable scientific constraints.
- Retrieve tools and evidence from a governed graph and formal TSV evidence.
- Distinguish trusted recommendation evidence from retrieval-only context.
- Rank tools conservatively with evidence-aware MCDM.
- Route to migration hypotheses only when direct tool recommendation is not
  sufficiently supported.
- Generate reports that expose evidence, missing evidence, caveats, and audit
  status.
- Block or downgrade unsupported scientific claims.
- Provide reproducible evaluations for recommendation quality, migration
  behavior, context-pack governance, and AgentRun process quality.
- Eventually expose the system through MCP tools so other agents can call it.

### 2.2 What the system should not do

- Do not auto-promote candidate evidence into formal evidence tables.
- Do not rank from GitHub activity alone.
- Do not use RAG snippets to change MCDM score or evidence trust level.
- Do not treat migration hypotheses as production recommendations.
- Do not let user memory become scientific evidence.
- Do not hide missing evidence behind fluent report text.
- Do not add open-ended autonomous agent loops before governance, trace, and
  evaluation are stable.

## 3. Current Repository Baseline

As of 2026-06-22, the repository contains:

- Streamlit UI: `app.py`.
- LangGraph workflow: `agent/workflow.py`.
- Typed state: `agent/states.py`.
- Central settings: `core/settings.py`.
- Evidence and prediction models: `core/models.py`.
- Evidence gate policy: `core/evidence_policy.py`.
- Formal evidence schemas: `core/evidence_schemas.py`.
- Neo4j client with offline fallback: `connectors/graph_client.py`,
  `connectors/offline_graph.py`.
- Context pack builder: `engine/context_pack_builder.py`.
- Controlled formal evidence RAG baseline:
  `engine/evidence_rag_pipeline.py`, `engine/formal_evidence_rag.py`.
- MCDM scoring: `engine/mcdm_calculator.py`.
- Migration logic: `engine/migration_intent.py`,
  `engine/migration_hypothesis_engine.py`.
- Hallucination auditor: `engine/semantic_hallucination_auditor.py`.
- Candidate and formal evidence workflows: `data_pipeline/`.
- Evaluation scripts and artifacts: `eval/`.

Current data inventory from local files:

- `data/scrna_tools.tsv`: 1842 tool rows excluding header.
- `data/tool_publications.tsv`: 28 formal publication rows.
- `data/tool_benchmarks.tsv`: 14 formal benchmark rows.
- `data/evidence_candidates/`: candidate-only review space.

The current project stage is between:

- B: retrieval + evidence support implemented as a usable prototype.
- C: LLM evaluation and trustworthiness as the active milestone.
- D: workflow prototype implemented but not evidence-complete.
- A: full production agent pipeline not yet complete.

## 4. System Architecture

### 4.1 Layered architecture

```text
UI / API layer
  - Streamlit chat and KG explorer now
  - MCP server later

Agent workflow layer
  - IntentAgent
  - RetrievalAgent
  - EvidenceGateAgent
  - RankingAgent
  - WorkflowPlannerAgent
  - MigrationAgent
  - ReportAgent
  - AuditorAgent

Governance layer
  - evidence policy
  - context pack policy
  - hallucination audit
  - candidate isolation

Retrieval layer
  - Neo4j/AuraDB serving graph
  - offline graph fallback
  - formal evidence RAG snippets
  - future BM25 + dense + RRF + rerank

Data layer
  - formal TSV evidence as source of truth
  - candidate review queues
  - local SQLite user store
  - future vector/BM25 stores

Evaluation layer
  - recommendation eval
  - migration eval
  - context-pack audit
  - AgentRun eval
```

### 4.2 Source of truth rule

Formal TSV files are the canonical evidence source:

- `data/tool_publications.tsv`
- `data/tool_benchmarks.tsv`
- `core/evidence_schemas.py`

Neo4j is a runtime serving graph, not the canonical evidence store. Any Neo4j
write path must be reproducible from formal TSVs or reviewed source files.

### 4.3 Runtime modes

The system must support three runtime modes:

| Mode | Purpose | Requirements |
| --- | --- | --- |
| Offline smoke | Local deterministic validation | no LLM, no Neo4j required, offline fallback enabled |
| Online graph | Real KG serving | valid Neo4j/AuraDB config |
| Online LLM | Full report generation / extraction | valid OpenAI-compatible API config |

## 5. Configuration Specification

All runtime configuration must go through `core/settings.py`.

Business logic must not add direct `os.getenv` calls unless the setting is
first represented in `Settings`.

Required local environment:

```bash
/opt/anaconda3/envs/sckg_env/bin/python
```

Recommended `.env` keys:

```env
NEO4J_URI=...
NEO4J_USER=...
NEO4J_PASSWORD=...

OPENAI_API_BASE=https://api.deepseek.com
OPENAI_API_KEY=...
DEEPSEEK_API_KEY=...
MODEL_NAME=deepseek-v4-pro
EXTRACT_MODEL=deepseek-v4-pro
CHAT_API_BASE=https://api.deepseek.com

EMBEDDING_API_KEY=...
SILICONFLOW_API_KEY=...
EMBEDDING_MODEL=BAAI/bge-m3
EMBEDDING_API_BASE=https://api.siliconflow.cn/v1/embeddings

LOG_LEVEL=INFO
KG_VERSION=v0.1
EMBEDDING_VERSION=bge-m3-v0.1
OFFLINE_GRAPH_FALLBACK=true
SCKG_OFFLINE_LLM=false
DISABLE_LLM_CALLS=false
```

Configuration acceptance:

- `.env` must remain ignored by git.
- `core.settings.get_settings()` must load `.env` without printing secrets.
- Offline smoke must run with `--offline-llm`.
- Neo4j connectivity check must print only success or sanitized error output.

## 6. Data and Evidence Governance

### 6.1 Evidence layers

| Layer | Meaning | Allowed use |
| --- | --- | --- |
| `trusted_core` | Human-reviewed formal evidence | retrieval, ranking, recommendation, report |
| `review_needed` | Candidate or source-based material awaiting review | retrieval/review only |
| `experimental` | LLM extraction, embeddings, derived similarity, migration hypotheses | exploration only |

### 6.2 Formal evidence approval

Approved formal review statuses:

- `reviewed`
- `verified`
- `human_reviewed`

Rejected or non-approved statuses:

- `pending`
- `review_needed`
- `rejected`
- `deprecated`

Formal table edits must preserve field order from `core/evidence_schemas.py`.

### 6.3 Candidate evidence isolation

Files under `data/evidence_candidates/` are candidate-only. Scripts may read
from them and write review outputs back into the candidate folder, but they
must not directly mutate:

- `data/tool_publications.tsv`
- `data/tool_benchmarks.tsv`
- Neo4j/AuraDB
- recommendation logic
- evidence policy gates

Candidate-to-formal promotion requires a separate human-reviewed action.

### 6.4 Publication evidence

Publication evidence should model:

- `publication_id`
- `work_group_id`
- canonical status
- duplicate linkage
- tool identity
- DOI / PMID / arXiv / paper URL
- task and modality when source-supported
- evidence role
- recommendation eligibility
- canonical scope
- authority tier
- audit support level

Primary recommendation publication support must require:

- `recommendation_eligible=true`
- `canonical_scope in {"core_tool", "major_version"}`
- `evidence_category="architectural_core"`
- `authority_tier in {"canonical_primary", "canonical_secondary"}`
- approved review status

### 6.5 Benchmark evidence

Benchmark evidence should model:

- source identity: benchmark name, DOI/PMID/source URL
- scope: tool, task, modality, dataset
- metric semantics: metric, direction, evaluation protocol
- result: rank, score, normalized score, or reviewed qualitative result text
- comparison context: number of tools or rank scope
- governance: review status, trust level, KG version

Do not invent:

- benchmark ranks
- benchmark scores
- metrics
- datasets
- evaluation protocols
- comparative conclusions

If exact numeric values are not curated, use reviewed `result_text` and map it
to `metric_name="benchmark_result"`, not fake rank or score fields.

## 7. Knowledge Graph Specification

### 7.1 Current graph role

KG provides:

- structured tool/task/modality constraints
- evidence links
- serving-time retrieval
- graph explorer visualization
- future workflow and protocol reasoning

KG does not provide:

- automatic truth promotion
- unrestricted answer generation
- evidence-free ranking authority

### 7.2 Target node types

Minimum durable nodes:

- `Tool`
- `Task`
- `Modality`
- `Evidence`
- `PublicationWork`
- `BenchmarkEvidence`
- `Dataset`
- `Metric`
- `Protocol`
- `Workflow`
- `WorkflowStep`
- `MigrationHypothesis`

### 7.3 Target relationships

```text
(Tool)-[:PERFORMS_TASK]->(Task)
(Tool)-[:SUPPORTS_MODALITY]->(Modality)
(Tool)-[:SUPPORTED_BY]->(Evidence)
(Tool)-[:EVALUATED_IN]->(BenchmarkEvidence)
(BenchmarkEvidence)-[:EVALUATES_TASK]->(Task)
(BenchmarkEvidence)-[:USES_DATASET]->(Dataset)
(BenchmarkEvidence)-[:USES_METRIC]->(Metric)
(BenchmarkEvidence)-[:DERIVED_FROM]->(PublicationWork)
(Evidence)-[:BELONGS_TO_WORK]->(PublicationWork)
(Workflow)-[:HAS_STEP]->(WorkflowStep)
(WorkflowStep)-[:USES_TOOL]->(Tool)
(MigrationHypothesis)-[:SOURCE_TOOL]->(Tool)
(MigrationHypothesis)-[:TARGET_TASK]->(Task)
```

### 7.4 Sync rules

- Sync scripts must be deterministic.
- Every write-capable script needs `--dry-run` or equivalent safety behavior.
- Candidate evidence must not be synced.
- Formal TSV row IDs must map to stable graph IDs.
- Neo4j sync must be rerunnable without duplicating evidence nodes.

## 8. Governed Evidence RAG Specification

### 8.1 Why this stage matters

The borrowed RAG project has strong engineering closure: chunking, hybrid
search, rerank, trace, dashboard, and MCP. scKG should not copy generic
document RAG directly. It should implement Governed Evidence RAG.

Target flow:

```text
formal TSV / reviewed paper / protocol / benchmark source
  -> evidence-aware chunks
  -> BM25 + dense index
  -> hybrid recall
  -> RRF fusion
  -> deterministic/LLM rerank
  -> governance filter
  -> EvidenceContextPack.retrieval_context
```

### 8.2 Evidence chunk metadata

Every evidence chunk must carry:

- `chunk_id`
- `source_kind`: publication, benchmark, protocol, docs, review_packet
- `tool_name`
- `task`
- `modality`
- `evidence_id`
- `work_group_id`
- `canonical_flag`
- `review_status`
- `trust_level`
- `graph_layer`
- `recommendation_eligible`
- `authority_tier`
- `doi`
- `pmid`
- `source_url`
- `claim_boundary`

### 8.3 RAG governance boundary

RAG snippets may:

- support explanation
- provide provenance
- improve report grounding
- expose missing evidence
- feed hallucination auditing

RAG snippets must not:

- change MCDM score
- promote candidate evidence
- override `core/evidence_policy.py`
- create benchmark values
- turn migration hypotheses into main recommendations

### 8.4 Implementation stages for RAG

Stage R1: existing lexical baseline

- Keep `engine/evidence_rag_pipeline.py`.
- Use formal TSV rows only.
- Validate offline smoke.

Stage R2: governed chunk builder

- Add stable `EvidenceChunk` schema.
- Build chunks from formal TSV rows and reviewed source excerpts.
- Preserve source IDs and claim boundaries.

Stage R3: BM25 index

- Add local BM25 store for evidence chunks.
- Support task/tool/modality filtering.
- Keep deterministic offline behavior.

Stage R4: dense embeddings

- Add embedding provider through settings.
- Store embedding version in chunk metadata.
- Never treat embeddings as facts.

Stage R5: hybrid search and RRF

- Implement dense + sparse retrieval.
- Add RRF fusion.
- Trace dense/sparse/fused result lists separately.

Stage R6: governed rerank

- Rerank by query relevance plus governance priority.
- Keep ranking of tools separate from ranking of snippets.
- Include `can_rank=false` in retrieval context.

Acceptance:

- Context pack present rate: 1.0 for smoke sets.
- No retrieval item can appear in `trusted_recommendation_context` unless it
  passes `is_main_recommendation_evidence`.
- Candidate files do not enter RAG unless explicitly marked review-only and
  blocked from recommendation use.

## 9. Recommendation Pipeline Specification

### 9.1 Required pipeline

```text
user_query
  -> parse constraints
  -> normalize task ontology
  -> retrieve candidates by hard constraints
  -> fetch formal evidence
  -> apply evidence gate
  -> apply trusted_core filter
  -> apply task-specific guardrails
  -> compute MCDM
  -> top-k selection
  -> build EvidenceContextPack
  -> generate report
  -> semantic audit
  -> safe output or blocked report
```

### 9.2 Constraint parsing

The constraint object is `core.constraints.ResearchConstraints`.

Required fields:

- `task`
- `task_family`
- `modality`
- `platform`
- `data_object`
- `scale`
- `noise`
- `hardware`
- `species`
- `output_goal`
- `strictness`
- `clarification_state`
- `pending_constraints`
- `constraint_warnings`

Parsing acceptance:

- Deterministic fallback must work offline.
- Unknown values must remain `Unknown`, not fabricated.
- Fine task labels must map to task families where appropriate.
- Clarification-needed state must block overconfident recommendations.

### 9.3 Evidence gate

Main recommendation evidence must pass `core/evidence_policy.py`.

The gate should enforce:

- approved formal review status
- trusted layer
- allowed source type
- allowed metric name
- recommendation eligibility
- canonical scope
- authority tier
- top-k limits

### 9.4 MCDM

MCDM should use three broad components:

```text
benchmark component
literature component
engineering component
```

The score must be modified by:

- evidence completeness
- canonical priority
- task alignment
- task-specific gates

Missing evidence must reduce confidence and appear in `missing_evidence`.

GitHub activity is engineering support only. It must never create a strong
scientific recommendation without publication or benchmark support.

### 9.5 Report generation

Reports must include:

- recommended tool or blocked status
- task/modality constraints
- evidence basis
- missing evidence
- confidence/caveats
- migration status when relevant
- audit status

Reports must not include:

- unsupported benchmark claims
- unsupported ranking claims
- unsupported numeric thresholds
- unsupported workflow transitions
- unsupported migration guarantees

## 10. Migration Hypothesis Specification

Migration is exploratory. It is used when direct tool recommendation is not
supported or when the user explicitly asks for method transfer.

Required flow:

```text
migration intent gate
  -> source and target task check
  -> algorithm feature similarity
  -> compatibility gap analysis
  -> decision: accept_exploratory / needs_more_evidence / reject / revise
  -> migration context
  -> audit
```

Accepted migration paths may enter `migration_context` only when:

- the decision is `accept_exploratory`
- evidence caveats are present
- compatibility gaps are stated
- validation requirements are stated

Migration paths must not:

- enter `scored_tools`
- change MCDM rank
- be called production-ready recommendations
- claim empirical performance unless benchmark evidence exists

## 11. Workflow Planning Specification

Current workflow planning is a deterministic prototype. It should remain
conservative until step-level evidence is available.

Workflow output should eventually include:

- workflow name
- ordered steps
- tool per step
- input/output data objects
- compatibility assumptions
- step-level evidence
- missing workflow evidence
- failure modes

Acceptance before claiming production workflow planning:

- Every workflow step has source-backed evidence or is marked template-only.
- Tool transitions are auditable.
- Unsupported workflow transitions are blocked by auditor.
- Workflow eval set includes positive, negative, and trap cases.

## 12. Agent Runtime and Trace Specification

The project should present multi-agent behavior as governed handoffs, not
open-ended agent debate.

Required roles:

- `IntentAgent`
- `RetrievalAgent`
- `EvidenceGateAgent`
- `RankingAgent`
- `WorkflowPlannerAgent`
- `MigrationAgent`
- `ReportAgent`
- `AuditorAgent`

Tool use should follow `core/agent_runtime.py`:

- `ToolSpec`
- `ToolCall`
- `ToolResult`
- `ToolRegistry`
- `ToolExecutor`
- args hash
- status
- latency
- result size
- repeated-call prevention
- max-iteration prevention

Trace acceptance:

- Every prediction JSONL record should expose trace summary.
- AgentRun eval should calculate tool-call accuracy, trajectory match,
  invalid-action rate, latency, blocked-report rate, and safety metrics.
- A failed or blocked tool call must not silently disappear.

## 13. MCP Server Roadmap

MCP turns scKG from a Streamlit app into a callable evidence service.

Target tools:

| MCP tool | Purpose |
| --- | --- |
| `recommend_omics_tools` | Return governed recommendation or blocked response |
| `query_sckg_evidence` | Retrieve formal evidence snippets and graph facts |
| `explain_recommendation_trace` | Show parse, retrieval, evidence gate, MCDM, audit |
| `list_evidence_gaps` | Expose missing publication/benchmark/protocol evidence |
| `get_tool_profile` | Return tool metadata, formal evidence, caveats |
| `audit_scientific_claim` | Check whether a user-supplied claim is supported |

MCP acceptance:

- stdout is reserved for MCP JSON-RPC.
- logs go to stderr or file.
- tools return structured JSON.
- tools expose governance status and missing evidence.
- tools must not write formal TSVs or Neo4j unless a separate reviewed admin
  tool is designed.

## 14. UI and Dashboard Specification

The Streamlit app should remain a research assistant, not a marketing page.

Required UI views:

- chat view
- KG explorer
- recommendation evidence panel
- missing evidence panel
- hallucination audit panel
- migration caveat panel
- trace/debug panel for development mode

Graph explorer rules:

- Default view should show trusted Tool-Task trunk only.
- Publication and benchmark evidence should expand through search/filter.
- Candidate evidence should be shown as counts or review status, not as trusted
  recommendation facts.

Dashboard roadmap:

- trace timeline
- constraint parse diff
- KG retrieval candidates
- evidence gate result
- RAG dense/sparse/fusion/rerank result
- MCDM breakdown
- context pack layers
- auditor issues
- eval history

## 15. Evaluation Specification

### 15.1 Required eval types

| Eval | Script | Purpose |
| --- | --- | --- |
| Recommendation eval | `eval/run_eval.py` | constraints, retrieval, evidence, report quality |
| Migration eval | `eval/run_migration_eval.py` | migration decision and trap avoidance |
| Context pack audit | `eval/audit_context_pack_v0_12.py` | KG-RAG governance violations |
| AgentRun eval | `eval/run_agent_eval.py` | process quality and trace metrics |
| Protocol validation | `eval/validate_*.py` | sealed eval schema checks |

### 15.2 Smoke commands

```bash
/opt/anaconda3/envs/sckg_env/bin/python -B -m py_compile \
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

/opt/anaconda3/envs/sckg_env/bin/python -B \
  eval/generate_predictions.py \
  --limit 3 \
  --offline-llm \
  --output /tmp/sckg_smoke_predictions.jsonl

/opt/anaconda3/envs/sckg_env/bin/python -B \
  eval/run_eval.py \
  --predictions /tmp/sckg_smoke_predictions.jsonl

/opt/anaconda3/envs/sckg_env/bin/python -B \
  eval/run_agent_eval.py \
  --predictions /tmp/sckg_smoke_predictions.jsonl \
  --json-output /tmp/sckg_agent_run_eval_summary.json \
  --output /tmp/sckg_agent_run_eval_summary.tsv \
  --per-query-output /tmp/sckg_agent_run_eval_per_query.tsv
```

### 15.3 Governance metrics

Minimum governance metrics:

- context pack present rate
- trusted non-main violation count
- retrieval rankable violation count
- candidate promotion violation count
- bad migration decision violation count
- semantic audit pass rate
- high/critical hallucination rate
- unsupported tool claim rate
- blocked report rate
- evidence coverage
- recommendation evidence coverage
- main recommendation evidence coverage

### 15.4 Definition of done for major changes

A major change is done only when:

- py_compile passes.
- relevant offline smoke passes.
- no candidate evidence promotion occurs.
- context pack governance is preserved.
- high/critical hallucination issues are blocked or resolved.
- README or spec is updated when contracts change.

## 16. Development Stages

### Stage 0: Specification and environment stabilization

Goal:

Create a stable development contract and local runnable baseline.

Tasks:

- Maintain this specification.
- Keep `.env.example` complete.
- Verify `.env` is ignored.
- Confirm local environment path.
- Confirm Neo4j connectivity without exposing secrets.
- Keep offline smoke runnable.

Deliverables:

- `docs/DEV_SPEC_scKG.md`
- updated `.env.example` when new settings are added
- smoke command list

Acceptance:

- Developer can run offline smoke on a new machine.
- Developer can verify Neo4j connectivity after setting `.env`.
- No secrets are committed.

### Stage 1: Evidence source-of-truth cleanup

Goal:

Make formal TSV evidence clean enough to support trustworthy recommendations.

Tasks:

- Run KG quality audit.
- Use `kg_quality_review_actions.tsv` as work queue.
- Remove or resolve candidate-origin markers in formal tables.
- Fill conservative task mappings only when source-supported.
- Assign `work_group_id` for benchmark rows.
- Fill DOI/PMID where available.
- Preserve schema order.

Deliverables:

- cleaned `data/tool_publications.tsv`
- cleaned `data/tool_benchmarks.tsv`
- updated KG quality audit report
- review notes for unresolved gaps

Acceptance:

- No formal row has unresolved candidate-only semantics.
- Missing fields are explicit, not hidden.
- Formal TSV row counts and schemas are validated.
- Candidate files remain isolated.

### Stage 2: Reviewed KG sync and graph serving

Goal:

Make Neo4j a reliable runtime serving graph generated from reviewed data.

Tasks:

- Review `sync_reviewed_tool_nodes.py`.
- Review `evidence_backfill.py`.
- Add dry-run summaries if missing.
- Ensure idempotent evidence upsert.
- Export read-only graph snapshots.
- Compare Neo4j graph inventory with local TSV inventory.

Deliverables:

- reviewed tool/task sync
- reviewed evidence node sync
- graph inventory report
- graph explorer validation

Acceptance:

- Re-running sync does not duplicate nodes.
- Neo4j and local inventory differences are explainable.
- Offline fallback remains available.
- No candidate evidence is synced.

### Stage 3: Governed Evidence RAG v1

Goal:

Upgrade formal evidence snippets into a true governed retrieval subsystem.

Tasks:

- Define `EvidenceChunk` contract.
- Build formal evidence chunk generator.
- Add BM25 index for evidence chunks.
- Add optional dense embedding path.
- Add RRF fusion.
- Add rerank with governance-aware scoring.
- Trace retrieval stages.

Deliverables:

- evidence chunk builder
- BM25 indexer
- optional embedding index
- hybrid evidence search module
- context pack retrieval integration

Acceptance:

- Offline lexical fallback still works.
- Hybrid retrieval improves provenance without changing tool ranking directly.
- RAG snippets remain `can_rank=false`.
- Context pack audit reports zero governance violations.

### Stage 4: Recommendation and MCDM hardening

Goal:

Make direct tool recommendation conservative, explainable, and measurable.

Tasks:

- Audit MCDM scoring inputs.
- Separate benchmark, literature, and engineering components.
- Enforce evidence completeness penalties.
- Improve task alignment checks.
- Add negative/trap cases for known false recommendations.
- Improve missing evidence reporting.

Deliverables:

- MCDM breakdown per tool
- score provenance in prediction JSONL
- expanded recommendation eval set
- failure queue for low-confidence recommendations

Acceptance:

- No strong recommendation without main evidence.
- Missing evidence lowers confidence.
- GitHub-only recommendations are blocked or exploratory.
- Ranking explanation cites formal evidence.

### Stage 5: Migration hypothesis hardening

Goal:

Make migration useful without overstating unsupported transfer claims.

Tasks:

- Freeze migration decision schema.
- Improve migration blockers and clarification states.
- Separate positive, negative, and trap eval cases.
- Require compatibility gaps and validation needs.
- Ensure semantic auditor catches migration overclaims.

Deliverables:

- migration decision protocol
- sealed migration eval
- migration failure queue
- migration context-pack audit

Acceptance:

- Negative false migration rate remains controlled.
- Trap avoidance is measured.
- Accepted migration paths are labelled exploratory.
- No migration path enters main recommendation ranking.

### Stage 6: Trace and dashboard

Goal:

Make failures debuggable from trace, not guesswork.

Tasks:

- Trace each agent role.
- Trace constraint parsing.
- Trace KG retrieval.
- Trace evidence gate.
- Trace RAG dense/sparse/fusion/rerank.
- Trace MCDM score breakdown.
- Trace context-pack construction.
- Trace auditor findings.
- Add dashboard panels for these traces.

Deliverables:

- trace JSONL schema
- dashboard trace pages
- eval history panel
- per-query debug export

Acceptance:

- A bad recommendation can be explained from trace alone.
- Dashboard adapts to offline and online modes.
- Trace does not expose secrets.

### Stage 7: MCP service interface

Goal:

Expose scKG as a callable evidence service.

Tasks:

- Add MCP server package.
- Implement read-only recommendation and evidence query tools.
- Add JSON schemas for MCP inputs/outputs.
- Add integration tests with a local MCP client.
- Add docs for client configuration.

Deliverables:

- `src` or `mcp_server` package for scKG MCP
- tool definitions
- protocol tests
- client setup docs

Acceptance:

- MCP server runs over stdio without corrupting stdout.
- Tools return structured governance-aware outputs.
- MCP calls can run offline smoke.

### Stage 8: Workflow evidence and execution planning

Goal:

Move from tool recommendation to workflow recommendation without unsafe
execution.

Tasks:

- Define workflow graph schema.
- Curate workflow protocol evidence.
- Add step-level compatibility constraints.
- Add plan-only executor.
- Add script-generation design, but keep disabled until sandbox exists.

Deliverables:

- workflow evidence schema
- workflow eval set
- plan-only workflow output
- execution safety design

Acceptance:

- Every workflow step has evidence or a template-only label.
- No real command execution happens without explicit sandbox design.
- Workflow audit blocks unsupported transitions.

### Stage 9: Production packaging

Goal:

Make the system deployable and maintainable.

Tasks:

- Add service entry point.
- Add health checks.
- Add config validation.
- Add Docker or environment lock plan.
- Add CI smoke checks.
- Add release checklist.

Deliverables:

- service package
- deployment docs
- CI commands
- release checklist

Acceptance:

- Fresh clone can run smoke checks.
- Production mode fails fast on missing config.
- Logs and traces are separated from secrets.

### Stage 10: Advanced learning systems

Goal:

Use GNN/RL/feedback only after enough governed traces and labels exist.

Prerequisites:

- stable KG schema
- large reviewed evidence graph
- sealed eval sets
- user feedback traces
- clear reward definition
- rollback plan

Possible directions:

- graph embedding for candidate recall
- GNN for relationship prediction
- learning-to-rank from reviewed outcomes
- RL from user feedback for interaction policy

Non-goal until prerequisites are met:

- using RL to invent scientific evidence
- using GNN scores as recommendation-grade facts
- optimizing engagement over trustworthiness

## 17. Borrowing Plan from MODULAR-RAG-MCP-SERVER

Borrow ideas, not domain assumptions.

Useful components to adapt:

- `DEV_SPEC.md` discipline and stage-based acceptance.
- Config-driven component factories.
- Ingestion pipeline shape.
- `Document`, `Chunk`, and `ChunkRecord` contract ideas.
- BM25 + dense + RRF + rerank architecture.
- TraceContext and TraceCollector pattern.
- Streamlit dashboard organization.
- MCP stdio hygiene.
- Unit / integration / e2e test layering.

Do not blindly copy:

- generic document chunk metadata
- generic answer generation assumptions
- RAG metrics that ignore evidence governance
- LLM enrichment that can mutate formal evidence

scKG-specific adaptation:

```text
Document chunk -> EvidenceChunk
Generic metadata -> evidence governance metadata
Generic RAG result -> retrieval-only context item
Generic dashboard -> evidence/audit/trace dashboard
Generic MCP query -> governed scientific evidence tools
```

## 18. Repository Ownership Map

| Area | Primary files | Rule |
| --- | --- | --- |
| Config | `core/settings.py`, `.env.example` | single settings entry point |
| State | `agent/states.py`, `core/models.py` | typed, serializable objects |
| Workflow | `agent/workflow.py` | governed route only |
| Evidence policy | `core/evidence_policy.py` | do not loosen casually |
| Formal schema | `core/evidence_schemas.py` | preserve field order |
| KG access | `connectors/` | offline fallback required |
| RAG | `engine/evidence_rag_pipeline.py`, future retrieval modules | retrieval-only unless gated |
| Ranking | `engine/mcdm_calculator.py` | evidence-aware, no placeholders |
| Migration | `engine/migration_*` | exploratory only |
| Audit | `engine/semantic_hallucination_auditor.py` | high/critical blocks |
| Candidate curation | `data_pipeline/`, `data/evidence_candidates/` | review queue only |
| Eval | `eval/` | every major change needs relevant eval |
| UI | `app.py`, `engine/knowledge_graph_view.py` | expose evidence status clearly |

## 19. Change Control

Before changing code, identify:

1. Which stage does this change belong to?
2. Which contract does it modify?
3. Which evidence layer can it read?
4. Can it write formal TSVs or Neo4j?
5. Which validation command proves it works?
6. Does the README or this spec need an update?

Changes that require extra care:

- evidence policy loosening
- formal schema edits
- promotion scripts
- Neo4j write scripts
- report prompt changes
- auditor changes
- MCDM scoring changes
- migration acceptance logic

## 20. Release Checklist

For a milestone release:

- Update this spec if architecture or contracts changed.
- Update README if user commands changed.
- Run py_compile.
- Run offline smoke predictions.
- Run recommendation eval.
- Run AgentRun eval.
- Run migration eval if migration logic changed.
- Run context-pack audit if RAG/context changes.
- Run KG quality audit if evidence changed.
- Record known gaps.
- Do not claim production readiness if formal evidence coverage remains small.

## 21. Long-Term North Star

The project should converge on this product loop:

```text
reviewed scientific evidence
  -> governed graph and retrieval indexes
  -> callable KG-RAG MCP service
  -> traceable recommendation / migration / workflow outputs
  -> semantic audit and eval feedback
  -> human-reviewed evidence improvement loop
```

The most important innovation is not chat. It is the controlled loop that
connects KG, formal evidence, governed RAG, MCDM, migration hypotheses, trace,
and hallucination audit into a reproducible scientific recommendation system.

