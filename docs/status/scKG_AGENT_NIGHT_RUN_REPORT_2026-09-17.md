# scKG-Agent Final Night Run Report

## Run identity

- Run ID: `night-2026-09-14-to-2026-09-17`
- Baseline commit: `e0ab62c368b6a544f077c601e5590e785578fae2`
- Pre-closure HEAD: `232a3f10787fafa2bd07a3f8eec9480fa9444e52`
- Branch: `feature/method-kg-expansion-v1`
- Overall status: `PASS`
- Final checkpoint: `CP7 — PASS`

## A. Justification Fidelity

| Metric | v1.1 pre-fix | v1.2 post-fix |
|---|---:|---:|
| Scientific evidence recall | 5/5 | 5/5 |
| Decision-evidence precision | 5/17 | 5/5 |
| Extra non-decision evidence | 12 | 0 |
| Runtime citation abstention | 7/7 | 7/7 |
| Ownership fidelity | 12/12 | 12/12 |
| Negative-control first cause | 8/8 | 8/8 |
| Behavior invariance | 4/4 | 4/4 |

The accepted intervention is decision-local evidence projection. It improves
precision without reducing recall and does not change Planner behavior. The
frozen four scenarios still show `KG behavioral contribution = 0/4`.

Formal v1.2 result: `PASS`, ordinal `1`. The historical v1/v1.1 artifacts,
frozen spec, and formal result remain unchanged.

## B. Evidence Acquisition

The governed CP5 chain is complete:

`EvidenceGap -> SoupX 1.6.2 official manual -> SourceWork -> SourceRevision -> SourceArtifact -> exact EvidenceSpan`

- Evidence gap: `evidence-gap:v1-core:soupx:droplet-profile`
- Source work: `source-work:soupx:official-manual`
- Source revision: `source-revision:soupx:official-manual:1.6.2`
- Source artifact SHA-256:
  `dabbfdf10c0ab46efee927026f77494e1df096999742f86705b91dcd0b1dac19`
- Evidence span: `evidence-span:cp5:soupx:soupchannel-inputs:1.6.2`
- Acquisition deduplication: `PASS`
- Promotion performed: `false`

The first CP5 parsing/runtime failure remains preserved separately. The
accepted repaired run reused the existing acquisition stack and did not create
a second crawler or source identity.

## C. Candidate Self-Deposition

- Evidence assessment: `supports`
- Evidence assessment ID: `evidence-assessment:cp6:7005e7aaf1f910d6`
- Candidate claim revision: `claim-revision:cp6:7005e7aaf1f910d6:1`
- Knowledge status: `candidate_pending_review`
- Candidate KG deposition: `PASS`
- Candidate RAG deposition: `PASS`
- Second-query reuse: `PASS`
- External reacquisition: `0`
- Duplicate candidates: `0`
- Canonical KG modified: `false`
- Execution authority granted: `false`

## D. Governance Closure

- Review item: `review-item:cp7:soupx:soupchannel-inputs:1.6.2`
- Queue status: `pending_human_review`
- Allowed actions represented: `PROMOTE`, `REJECT`, `NEEDS_REVISION`,
  `MERGE`, `SUPERSEDE`
- Review decision created: `false`
- KnowledgeChangeSet created: `false`
- Canonical snapshot created: `false`
- Canonical promotion performed: `false`
- Promotion guard: blocked by `qualified_review_decision_missing`

The review packet preserves the complete chain:

`AtomicClaimRevision -> EvidenceAssessment -> EvidenceSpan -> SourceArtifact -> SourceRevision -> SourceWork`

Broken IDs, source swaps, scope loss, and epistemic conflation are all `0`.
The final reuse query reused the candidate claim, span, and artifact with
`external_reacquisition_count = 0`, while retaining
`candidate_pending_review`.

## E. Trace and EDD

Key bounded traces:

- CP5 reuse: `trace_c78dd43454724634aee211761b88c599`
  (`REQUEST -> STATE_INSPECTION -> RETRIEVAL -> DECISION -> RETRIEVAL -> VALIDATION -> VALIDATION`)
- CP6 deposition: `trace_0c9c5aa867a143f182b20c9a6e0a3621`
  (`REQUEST -> STATE_INSPECTION -> RETRIEVAL -> DECISION -> VALIDATION -> DECISION -> RETRIEVAL -> RETRIEVAL -> VALIDATION`)
- CP7 governance: `trace_e15c5fc520d544a68b78bda852480277`
  (`REQUEST -> STATE_INSPECTION -> VALIDATION -> RETRIEVAL -> DECISION -> VALIDATION`)
- Representative Stepwise compile: `trace_2f29c812b4c24f10bba6658bddb28864`
  (`REQUEST -> STATE_INSPECTION -> PLANNING -> NOTEBOOK_COMPILE`)

No inspected trace contains raw PDF text, credentials, or an absolute local
path. No PLAN-only trace entered `EXECUTION`.

The following actual EDD events remain recorded:

1. Evaluation version-routing coupled immutable evidence identity to mutable
   SUT identity. It was fixed by separating historical and active SUT lanes.
2. v1.2 lacked a canonical write-once formal entrypoint. It was fixed in the
   evaluation runner layer before the single formal run.
3. The first CP5 acquisition attempt failed at the PDF parsing/runtime
   boundary. The failed artifacts were preserved; the repaired run used the
   existing extraction runtime.
4. CP6 initially risked binding package-level evidence to an unsupported
   operator scope. The accepted candidate was narrowed before deposition.

## F. Regression

Focused results:

- CP5 + CP6 + CP7: `19 passed`
- CP7 alone: `6 passed`
- Hybrid retrieval: `8 passed`
- Scientific KG -> Planner integration: `5 passed`
- Justification Fidelity: `47 passed`, `1 ENVIRONMENT_FAILURE`
- Capability/Research/Stepwise focused lane: `46 passed`,
  `2 PREEXISTING_FAILURE`
- Scientific conformance: `11 passed`, `1 PREEXISTING_FAILURE`
- `git diff --check`: `PASS`

Full suite:

- `936 passed`
- `10 failed`
- `8 warnings`
- `NEW_FAILURE = 0`
- `PREEXISTING_FAILURE = 9`, each reproduced on clean HEAD `232a3f1`
- `ENVIRONMENT_FAILURE = 1`: a legacy test asserts the v1.2 formal directory
  must not exist, while the preserved single formal run intentionally exists
- `FLAKY = 0`

The nine preexisting failures cover Decision Graph/evaluation fixture drift,
one mainline gate, Research handoff/smoke expectations, and the archived
AtomicClaim crosswalk count. None is owned by CP7.

## G. Repository

Accepted commits created during this run:

- `a0d391280eac5af6951ca7fb02f7ae236f0303b3` — separate frozen evaluation artifacts from SUT
- `65bb8ff8eb2aeb25da81ad771bb96e8bd962fb3c` — project decision-local scientific evidence
- `11f11cc621d2193cd8823969405068db287da996` — separate historical and active SUT regression lanes
- `d35e4bc038b075ae0db9b435b63cc10106dac3a2` — add write-once v1.2 formal runner
- `c0f43e22ff62b0405b424f9638672d303056e128` — add governed EvidenceGap acquisition pilot
- `232a3f10787fafa2bd07a3f8eec9480fa9444e52` — add governed candidate knowledge deposition pilot
- `273b516ea88597793bdbf9fe1413917b04b7e918` — freeze v1.2 formal artifacts
- `968502254d9999ea5c6eaf3c448e658afb02ae94` — add candidate admin review queue

CP7 implementation and tests are frozen. Its pilot audit directory follows the
existing local-untracked pilot convention. Existing pilot/development artifact
directories were not deleted, overwritten, promoted, or mixed into the formal
artifact commit.

## Final decision

`CP7 — PASS`

`NIGHT_RUN_COMPLETE`

The autonomous loop stops at human governance:

`EvidenceGap -> acquisition -> EvidenceSpan -> Candidate AtomicClaimRevision -> reuse -> Admin Review Item`

No candidate was promoted to canonical/trusted knowledge.
