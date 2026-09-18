# Core Scientific Planner Integration v1

Status: `PASS_WITH_REMAINING_GAPS`

Baseline: `52d1d1d8ee54dc035e88c3f855cee59a35023607`

## Scope and production boundary

The integration keeps `CapabilityPlanCompiler` as the only production planner.
Its existing `scientific_decision()` boundary calls
`ScientificKGApplicability.assess()` before a current representation is reused
or a Capability Pack method is selected. Capability Pack and StepContract
records remain responsible for compiling the executable dry-run plan.

This checkpoint adds no KG records, evidence, `CAN_FEED` relations, capability
packs, tool contracts, retrieval content, or ranking changes. The Scientific KG
slice remains `candidate`; integration is not canonical promotion.

## Integrated production semantics

The existing Scanpy Core pack now has bounded, source-bound applicability
projection for:

- log-profile highly-variable-gene input;
- generic PCA expression input and optional feature mask;
- PCA coordinates consumed by neighbors;
- neighbor graph consumed by UMAP;
- neighbor graph consumed by Leiden.

The already validated Harmony-corrected embedding to neighbors and Scrublet
raw-UMI applicability paths are preserved.

Only RepresentationLedger records with explicit v1.1 representation identity
and lineage metadata opt into the newly added Scanpy decisions. Legacy records
retain the pre-checkpoint planner behavior. Exact matched constraints determine
which input claim evidence is projected; alternate HVG flavor evidence is not
attached to the log-profile decision.

## Focused development planning set

Eight production-path cases were evaluated with the same planner and ledger,
using a no-op applicability adapter as baseline and the production Scientific KG
adapter as treatment.

| Metric | Result |
| --- | ---: |
| Requirement-state correctness | 8/8 |
| ALLOW/BLOCK/CLARIFY-class correctness | 8/8 |
| Explanation/evidence fidelity | 8/8 |
| Unnecessary recomputation | 0/8 |
| Incorrect reuse | 0/8 |
| Missing prerequisite | 0/8 |
| Unsafe allow | 0/8 |
| False block | 0/8 |
| Planner behavior changes versus no-op | 0/8 |

The result demonstrates deeper governed consumption and source-bound
explanation for existing correct decisions. It does not claim a new behavioral
contribution. Raw plan/result records and per-case checks are preserved in
`data/evaluation/core_scientific_planner_integration_v1/per_case_results.json`.

## Target-path readiness

| Target path | Result | Production reason |
| --- | --- | --- |
| Scanpy base chain | INTEGRATED/EXPANDED | Existing pack; explicit ledger bindings; reviewed candidate evidence |
| Harmony to neighbors | INTEGRATED/PRESERVED | Existing delegated action, contract and KG applicability |
| Scrublet applicability | INTEGRATED/PRESERVED | Existing delegated action, contract and raw-UMI constraints |
| SoupX | NOT_READY | Pilot claim remains `candidate_pending_review`; no ToolContract or Capability Pack |
| CellTypist | NOT_READY | Immutable model revision unresolved; no Capability Pack path |
| SingleR | NOT_READY | Candidate/contract version mismatch, unresolved reference revision, no Capability Pack |
| scVelo | NOT_READY | No ToolContract or Capability Pack production path |
| CellRank | NOT_READY | scVelo/CellRank compatibility remains an EvidenceGap; no ToolContract or Capability Pack |

Conditional count-flavor HVG selection also remains outside the new production
binding because the current StepContract has no explicit flavor parameter. It
was not inferred from candidate knowledge.

## Fourteen-ecosystem matrix

The truthful readiness count remains:

- authoritative evidence ready: 13/14;
- planning ready: 3/14;
- execution ready: 2/14;
- retrieval-only: 6/14;
- candidate-only: 3/14;
- not ready: 2/14.

The count does not increase because no additional ecosystem has a complete
Capability Pack/ToolContract/planner path. Scanpy planning depth increased
within its already planning-ready ecosystem. Exact per-ecosystem reasons are in
`data/evaluation/core_scientific_planner_integration_v1/readiness_matrix.json`.

## Validation and EDD record

- New integration/evaluation tests: 13 passed.
- Planner, ledger, notebook, contribution and decision-local regression lane:
  76 passed, 2 existing warnings.
- Python compilation: passed.
- `git diff --check`: passed.

The first wider regression run exposed two changes in legacy PCA recovery. The
earliest divergence was the new adapter treating a stale/hash-mismatched legacy
record as an explicit v1.1 scientific binding. The one-layer repair requires
explicit RepresentationType plus lineage metadata for newly integrated actions.
Both reproductions and the full focused lane then passed.

An evaluation-only draft initially counted changed reason strings as behavior.
The comparison projection was corrected to compare blocked state, method order,
and reused representations while retaining raw reasons in the artifacts. The
superseded draft was not included in the deliverables.

## Artifact identity

- Candidate manifest SHA-256:
  `f5272f1e69c5766a069ca3dd6565d90b323ccdf7a3944a987bd0cba5409ef638`
- Scanpy Capability Pack manifest SHA-256:
  `327916e89045951acd068da98de217d0c2756958edc012e735216e255379bcfe`
- Evaluation manifest SHA-256:
  `66120afd85093af4ebab6441aa405050e132357d61329a402c64e2c08fa468ae`

No Seed v1 or formal Midterm holdout was created or run.

