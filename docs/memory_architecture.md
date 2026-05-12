# scKG Agent Memory Architecture V0.1

## Scope

This document is a design note only. It does not promote memory into scientific evidence and does not change the recommendation pipeline.

The current source of truth for scientific evidence remains:

- `data/tool_publications.tsv`
- `data/tool_benchmarks.tsv`

Neo4j is the runtime graph serving layer. SQLite is the proposed local operational memory store.

## Memory Classes

| Memory class | Purpose | Storage | Can affect scientific authority? |
| --- | --- | --- | --- |
| `session_context` | Current conversation, temporary constraints, unresolved user preferences | SQLite | No |
| `project_memory` | Project-level preferences, recurring user goals, selected default route | SQLite first, optional Neo4j summary | No |
| `governance_memory` | Review decisions, audit events, promotion provenance, eval run metadata | SQLite event log plus Neo4j provenance nodes | No, unless separately promoted through formal evidence workflow |
| `trusted_evidence` | Human-reviewed publication and benchmark facts | TSV source of truth, Neo4j serving copy | Yes, through evidence gate only |

## Proposed Storage Split

### SQLite

SQLite should store append-only operational state:

- sessions
- messages
- parsed constraints
- recommendation runs
- audit results
- review events
- user preference snapshots

SQLite is suitable for conversational continuity because it is simple, portable, and easy to inspect.

### Neo4j

Neo4j should store structured, queryable project memory only when the memory has graph semantics:

- project goals
- review provenance
- recommendation run provenance
- evidence lineage
- tool-task-modality links

Neo4j should not become the source of truth for raw chat logs.

## Non-Negotiable Rule

Memory can personalize context, restore unfinished work, and explain previous decisions.

Memory cannot automatically become publication evidence, benchmark evidence, ranking evidence, or scientific proof.

Any memory-derived scientific claim must enter the normal governance path:

candidate -> human review -> formal TSV -> backfill -> evidence gate

## Minimal Schema Sketch

### SQLite Tables

`sessions`

- `session_id`
- `created_at`
- `updated_at`
- `project_id`
- `summary`

`messages`

- `message_id`
- `session_id`
- `role`
- `content`
- `created_at`

`recommendation_runs`

- `run_id`
- `session_id`
- `query`
- `parsed_constraints_json`
- `route`
- `recommended_tools_json`
- `evidence_ids_json`
- `audit_status`
- `blocked_by_auditor`
- `created_at`

`governance_events`

- `event_id`
- `event_type`
- `target_id`
- `decision`
- `notes`
- `reviewer`
- `created_at`

### Neo4j Node/Edge Sketch

Nodes:

- `ProjectMemory`
- `RecommendationRun`
- `GovernanceEvent`
- `Evidence`
- `Tool`

Edges:

- `(RecommendationRun)-[:USED_EVIDENCE]->(Evidence)`
- `(RecommendationRun)-[:RECOMMENDED]->(Tool)`
- `(GovernanceEvent)-[:DECIDED_ON]->(Evidence)`
- `(ProjectMemory)-[:PREFERS_ROUTE]->(:Route)`

## Retrieval Policy

At recommendation time, memory may provide:

- user-preferred strictness
- previous unresolved constraints
- preferred output format
- project route, such as Strategy A or C
- prior audit warnings

At recommendation time, memory must not provide:

- unsupported tool claims
- benchmark rankings
- unreviewed DOI claims
- invented thresholds
- candidate evidence as trusted evidence

## Implementation Order

1. Keep current stateless recommendation path stable.
2. Add SQLite event logging for recommendation and audit runs.
3. Add read-only session summary injection into the parser prompt.
4. Add Neo4j provenance nodes for recommendation runs only after the event schema is stable.
5. Never let memory bypass the evidence gate.
