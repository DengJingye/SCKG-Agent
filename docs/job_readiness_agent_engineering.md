# Job Readiness: Agent Engineering Narrative

This project should be presented as a trustworthy scientific Agent system, not
as a generic chatbot demo.

## Positioning

scKG-Atlas Agent is a governed LangGraph-style multi-agent workflow for
single-cell, spatial, and multi-omics tool recommendation. It combines typed
tool use, Hybrid KG-RAG, evidence gates, MCDM ranking, semantic hallucination
auditing, and AgentRun evaluation.

Recommended resume framing:

> Built a trustworthy scientific AI Agent with governed multi-agent handoffs,
> typed Tool Use, Hybrid KG-RAG, trace logging, semantic hallucination audit,
> and AgentRun evaluation. The system separates trusted recommendation
> evidence, retrieval-only context, exploratory migration hypotheses, and
> blocked claims to reduce unsupported scientific recommendations.

## JD Keyword Mapping

| JD keyword | Project evidence |
| --- | --- |
| Planning | LangGraph route: intent -> retrieval -> evidence gate -> rank/migrate -> context pack -> report -> audit. |
| Memory | Streamlit/user store provides conversation, project memory, and working context; memory never becomes trusted evidence. |
| Tool Use / Function Calling | `ToolSpec`, `ToolCall`, `ToolResult`, `ToolRegistry`, `ToolExecutor`. |
| ReAct / observations | Tool calls are traced as external observations with role/node name, args hash, status, latency, and result size. |
| Prompt Engineering | Prompt contracts exist for intent extraction/report generation; deterministic offline report path prevents unsafe free-form claims. |
| RAG | Formal TSV evidence is chunked, retrieved, reranked, and inserted only into `EvidenceContextPack.retrieval_context`. |
| Rerank | Offline lexical retrieval is reranked by tool/task/modality/source-kind relevance. |
| Multi-Agent | Governed role handoffs: Intent, Retrieval, EvidenceGate, Ranking, WorkflowPlanner, Migration, Report, Auditor. |
| Hallucination Reduction | Semantic auditor blocks high/critical unsupported tool, benchmark, literature, ranking, threshold, workflow, and migration claims. |
| Agent Evaluation | `eval/run_agent_eval.py` reports task success, progress, Pass@1, tool-call accuracy, trajectory match, invalid action rate, latency, and safety metrics. |

## Architecture Story

The key design decision is conservative control. The system does not let agents
freely rewrite evidence or promote candidate records. Each role receives a
structured handoff and can only contribute to its assigned layer:

```text
IntentAgent
  -> RetrievalAgent
  -> EvidenceGateAgent
  -> RankingAgent or MigrationAgent
  -> WorkflowPlannerAgent
  -> ReportAgent
  -> AuditorAgent
```

`AuditorAgent` has veto power. If the report contains high or critical
unsupported claims, the unsafe report is replaced by a safe blocked report.

## RAG Boundary

The RAG chain is deliberately controlled:

```text
formal TSV rows
  -> evidence chunks
  -> offline lexical retrieval
  -> deterministic rerank
  -> formal RAG snippets
  -> EvidenceContextPack.retrieval_context
```

RAG snippets are explanation/provenance only. They cannot change MCDM score,
cannot promote candidate evidence, and cannot relax trusted-core gates.

## Evaluation Commands

Generate a small offline prediction set:

```bash
/Data/Omics/dengjingye/tools/miniconda3/envs/sckg_env/bin/python -B \
  eval/generate_predictions.py \
  --gold eval/gold_queries_v0_2_blind.jsonl \
  --limit 3 \
  --offline-llm \
  --output /tmp/sckg_job_smoke_predictions.jsonl
```

Run legacy recommendation eval:

```bash
/Data/Omics/dengjingye/tools/miniconda3/envs/sckg_env/bin/python -B \
  eval/run_eval.py \
  --gold eval/gold_queries_v0_2_blind.jsonl \
  --predictions /tmp/sckg_job_smoke_predictions.jsonl
```

Run AgentRun engineering eval:

```bash
/Data/Omics/dengjingye/tools/miniconda3/envs/sckg_env/bin/python -B \
  eval/run_agent_eval.py \
  --gold eval/gold_queries_v0_2_blind.jsonl \
  --predictions /tmp/sckg_job_smoke_predictions.jsonl \
  --json-output /tmp/sckg_agent_run_eval_summary.json \
  --output /tmp/sckg_agent_run_eval_summary.tsv \
  --per-query-output /tmp/sckg_agent_run_eval_per_query.tsv
```

## Interview Talking Points

- Tool results are treated as external observations and traced separately from model-generated report text.
- Repeated tool-call fingerprints and max iteration limits prevent uncontrolled tool loops.
- Candidate evidence stays isolated under `data/evidence_candidates/` and cannot enter recommendation-grade pathways without review.
- The system measures both final answer quality and agent process quality.
- The multi-agent design is governed handoff, not open-ended agent debate.

## Current Limitations

- TTFT, token cost, and cost-per-success are placeholders until streaming and token telemetry are captured.
- RAG uses an offline lexical baseline; embedding/vector-index support can be added later without changing the governance boundary.
- Workflow planning is deterministic template-based and still needs step-level benchmark evidence.
- FastAPI service packaging is still future work.
