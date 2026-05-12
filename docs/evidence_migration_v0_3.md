# Evidence Migration V0.3

## Purpose

Evidence migration is the exploratory route of scKG Agent.

It is used when direct, trusted, benchmark-backed tools are unavailable or when the user explicitly asks for innovation, method transfer, or analysis ideas for a sparse tool landscape.

The module does not produce formal tool recommendations. It produces auditable migration hypotheses:

```text
MigrationHypothesis = an exploratory, evidence-bounded idea that a mechanism from a source tool may be adapted to a target task or data scenario.
```

## Positioning

The system positioning for v0.3 is:

```text
evidence governance + trustworthy recommendation + algorithm migration hypothesis generation
```

The system is not yet an autonomous execution agent. Execution planning, sandbox running, and repair loops are roadmap items only.

## Governance Rules

- `MigrationHypothesis` is not `ScoredTool`.
- Migration output must not enter the primary recommendation top-k.
- Migration evidence belongs to the `experimental` graph layer.
- Embedding similarity is a retrieval signal, not proof.
- RAG passages may support explanation and provenance only.
- RAG passages must not automatically become trusted scientific evidence.
- Migration claims must include caveats, compatibility gaps, and a validation plan.
- Strong wording such as "best", "safe replacement", "empirically proven", or "benchmark-backed" is forbidden unless separately supported by formal evidence.

## Trigger Conditions

The migration route may run when at least one condition is true:

- no direct trusted-core candidate passes the evidence gate;
- top-k evidence confidence is low for the user task;
- the user asks for innovation, method transfer, "no existing tool", "borrow ideas", or "迁移";
- the task is rare or emerging and formal benchmark evidence is absent.

If a strong direct recommendation exists, migration output is allowed only as a separate exploratory panel.

## MigrationHypothesis Interface

The target object should contain:

```text
hypothesis_id
target_task
target_modality
source_tool
source_task
transferable_mechanism
algorithm_features
required_input
expected_output
compatibility_matches
compatibility_gaps
graph_jaccard
vector_similarity
evidence_support
risk_level
validation_plan
claim_boundary
```

`claim_boundary` must explicitly state that the output is exploratory and not a formal recommendation.

## Candidate Algorithm Profiles

Algorithm profiles are candidate-only records stored under:

```text
data/evidence_candidates/tool_algorithm_profiles.tsv
```

They summarize model assumptions, input/output signatures, optimization targets, and transferable mechanisms.

They must remain outside formal evidence tables until a later human-review path is defined.

## Migration Plausibility Score

The future migration engine should use a separate score:

```text
migration_plausibility_score
```

Suggested formula:

```text
0.35 * vector_similarity
+ 0.25 * graph_jaccard
+ 0.20 * io_compatibility
+ 0.10 * evidence_support
+ 0.10 * novelty_relevance
- risk_penalty
```

This score is not an MCDM recommendation score.

## Structural Validation

The future migration engine should validate:

- source tool and target task share algorithmic mechanism or compatible modeling assumptions;
- source input object can plausibly map to target input object;
- source output object is useful for the target analysis goal;
- graph neighborhood overlap is non-zero for relevant typed relations;
- limitations are explicit when evidence support is weak.

Typed graph neighborhood Jaccard should be computed over relations such as:

```text
PERFORMS_TASK
SUPPORTS_MODALITY
IMPLEMENTS_ALGORITHM
OPERATES_ON
REQUIRES_HARDWARE
SUPPORTED_BY
```

## Review Decisions

Migration review packets use these decisions:

```text
accept_exploratory
revise_mechanism
reject_incompatible
needs_more_evidence
```

Only `accept_exploratory` allows a hypothesis to appear in an exploratory UI panel.

Even accepted hypotheses remain experimental.

## Execution Agent Roadmap

Execution is deferred. If added later, it should proceed in stages:

1. plan-only execution agent;
2. script generator;
3. sandbox runner;
4. repair loop.

Execution must use a sandbox, explicit file write boundaries, command allowlists, resource limits, and human approval before destructive or expensive operations.

## Hybrid KG-RAG Boundary

The v0.3 direction is Hybrid KG-RAG:

- KG handles structured constraints, tool-task-modality links, algorithm profiles, evidence governance, and compatibility validation.
- RAG handles paper, protocol, documentation, and claim-span retrieval.

RAG text may explain why a hypothesis is plausible, but it cannot promote a migration idea into recommendation-grade evidence.
