# Core Capability Expansion v1 — Readiness Gate

Status: `NO_GO`

Baseline: `22a1dc9515ca18676e34a51017926a84d346a6fb`

This gate evaluated CellTypist, scVelo and SoupX before creating any new
production capability. None currently satisfies the frozen requirement:

`governed evidence → reviewed operator requirements → ToolContract → Capability Pack → CapabilityPlanCompiler`

No production implementation was started.

## Candidate decisions

### CellTypist — NOT_READY

The existing ToolContract is planning-only and its wrapper is implemented, but
the wrapper points to
`reference_packs/manifests/celltypist-immune-all-low-v1.json`, which is absent.
No immutable model artifact, content digest, model revision, or feature/label
compatibility manifest exists locally. Creating a Capability Pack now would
turn the contract's model name into an unverified reference identity.

First responsible layer: `ReferenceArtifact identity`.

### scVelo — NOT_READY

The core candidate contains version-pinned source-bound claims for moments,
velocity and velocity-graph operators. However, the decision-controlling
spliced/unspliced, neighbor-graph and moments requirements are R3
`candidate_pending_review` records whose registered governance requirement is
`qualified_human`. There is also no scVelo ToolContract, Capability Pack or
runtime binding.

The checkpoint does not use the independently frozen benchmark gold as
production knowledge and does not interpret candidate claims as trusted.
CellRank compatibility remains explicitly outside scope.

First responsible layer: `scientific review`.

### SoupX — NOT_READY

The CP5–CP7 pilot produced an exact, version-pinned source artifact and a
candidate claim for SoupChannel `tod`/`toc` semantics. Its review item remains
`pending_human_review`, has no ReviewDecision, and records
`promotion_allowed_now=false`. No SoupX ToolContract or Capability Pack exists.

First responsible layer: `human review decision`.

## Readiness matrix

| Ecosystem | Evidence | Review/reference gate | ToolContract | Capability Pack | Decision |
| --- | --- | --- | --- | --- | --- |
| CellTypist | present | immutable model revision missing | planning-only | missing | NOT_READY |
| scVelo | candidate source-bound | R3 qualified review pending | missing | missing | NOT_READY |
| SoupX | exact source-bound candidate | qualified review pending | missing | missing | NOT_READY |

The truthful global counts remain:

- authoritative evidence ready: 13/14;
- planning ready: 3/14;
- execution ready: 2/14.

## Frozen boundaries

No RAG, KG, Planner, ToolContract, Capability Pack, benchmark gold or formal
holdout content changed. No candidate was promoted and no unreviewed `CAN_FEED`
relation became actionable.

## Smallest safe continuation

Resume only after one of these external governance prerequisites is complete:

1. register and digest a real CellTypist model artifact;
2. complete qualified review of the bounded scVelo input-requirement cluster;
3. record the SoupX review decision already waiting in the admin queue.

Until then, adding production capability code would inflate readiness rather
than close a governed scientific path.

