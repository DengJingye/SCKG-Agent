# Roadmap v0.12: Minimal Hybrid KG-RAG

## Position

v0.12 stops treating the knowledge graph as an all-purpose answer machine.

The target architecture is:

```text
LLM: synthesize, explain, and organize the answer
KG: provide structured evidence, constraints, ranking inputs, and safety boundaries
RAG: provide paper/protocol/docs snippets for explanation and provenance
Auditor: block unsupported or unsafe claims before user-visible output
```

The current milestone implements only the minimal context pack needed to support that architecture.

## Phase 1: Evidence-Governed Recommendation

Status: active and stable enough for the main route.

- Keep formal evidence in TSV as the source of truth.
- Use Neo4j as runtime serving, not as the canonical evidence store.
- Preserve evidence gate, MCDM ranking, semantic audit, and top-k limits.
- Do not rank from GitHub/docs/candidate evidence alone.

## Phase 2: Migration Hypothesis Panel

Status: exploratory, not the main recommendation path.

- Migration output is `MigrationHypothesis`, not `ScoredTool`.
- Only `accept_exploratory` migration vectors may enter the migration context.
- Rejected, `needs_more_evidence`, and `revise_mechanism` rows stay blocked.
- Migration plausibility is separate from MCDM score.
- Migration claims must include caveats, compatibility gaps, and validation needs.

## Phase 3: Hybrid KG-RAG Context Pack

Status: implemented as the v0.12 minimal interface.

`EvidenceContextPack` separates:

- `trusted_recommendation_context`: trusted-core publication/benchmark evidence that may support recommendation wording and ranking explanations.
- `retrieval_context`: DOI, docs, protocol, paper, benchmark, GitHub, and derived evidence for explanation/provenance only.
- `migration_context`: accepted exploratory migration hypotheses only.
- `blocked_context`: forbidden tools, missing prerequisites, pending constraints, and auditor risks.
- `missing_evidence`: benchmark/publication/protocol gaps that must be stated, not hallucinated away.
- `prompt_policy`: explicit allowed and forbidden report-generation behavior.

RAG text cannot change MCDM score and cannot promote evidence to trusted status.

## Phase 4: Memory/Event Log

Status: design only.

- Short-term memory should hold the active query/session state.
- Working memory should hold intermediate constraints, scored tools, context packs, and audit output.
- Long-term memory should be SQLite plus graph-backed event logs, but only after KG-RAG is stable.
- Memory must not become scientific evidence automatically.

## Phase 5: Frontend Polish

Status: after KG-RAG context pack.

- Use a GPT/Gemini-style layout: conversation plus evidence/audit/recommendation panels.
- Remove fake graph counts, dashboard theatrics, and misleading metrics.
- Display recommendation tools, evidence source, missing evidence, audit status, DOI/benchmark traceability, and migration caveats.

## Phase 6: Execution Agent Roadmap

Status: roadmap only.

Execution is not implemented in v0.12.

If added later, it should proceed through:

1. plan-only executor;
2. script generator;
3. sandbox runner;
4. repair loop.

Execution must require sandboxing, command allowlists, resource limits, and explicit user approval for destructive or expensive operations.

## v0.12 Non-Goals

- No paid LLM calls.
- No Neo4j writes.
- No formal evidence table edits.
- No automatic evidence promotion.
- No vector database or paid embedding API.
- No long-term memory implementation.
- No frontend overhaul.
- No execution agent implementation.
