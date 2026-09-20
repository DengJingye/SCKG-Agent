# Scientific Knowledge Studio v1

STATUS=PASS
MODE=PREVIEW_ONLY

One real local PDF now runs through source identity, page-preserving parsing, bounded exact EvidenceSpanProposal generation, ontology-constrained semantic Proposal generation, exact identity resolution, four-part validation, CandidateDiff, Proposal Graph, and an eight-stage RunManifest. Scientific KG, retrieval, Planner, contracts, and gold remain unchanged.

## First real run

- PDF: `soupx-1.6.2-manual.pdf` (binary not committed)
- SHA256: `dabbfdf10c0ab46efee927026f77494e1df096999742f86705b91dcd0b1dac19`
- Pages: 26 total / 26 parsed / 0 parse gaps
- Proposals: 16 evidence, 1 entities, 0 relations, 8 claims, 8 scopes
- Validation: 23 VALID, 0 NEEDS_REVIEW, 10 INVALID
- Identity: {"AMBIGUOUS": 0, "EXACT_EXISTING_IDENTITY": 1, "NEW_CANDIDATE": 0, "POSSIBLE_EXISTING_IDENTITY": 0, "UNRESOLVED": 0}
- Real LLM extraction: `NOT_RUN`

The local run used conservative deterministic ontology/identity extraction because no authorized live LLM configuration was available. It is labeled accordingly and is not presented as model output. Zero relation proposals is preserved rather than fabricating a relation.

## Human sanity review

- Provenance: user-supplied semantic sanity review; this is not an automated score.
- Status: `COMPLETED_PENDING_PDF_PAGE_CONFIRMATION`; final PDF-page confirmation remains required.
- Entity: {'CORRECT': 0, 'PARTIAL': 1, 'INCORRECT': 0, 'UNCERTAIN': 0, 'total': 1}
- Claims: {'CORRECT': 3, 'PARTIAL': 4, 'INCORRECT': 1, 'UNCERTAIN': 0, 'total': 8}
- Evidence: {'CORRECT': 6, 'PARTIAL': 3, 'INCORRECT': 1, 'UNCERTAIN': 0, 'total': 10}

This bounded 1-entity / 8-claim / 10-evidence review is a sanity check, not a formal benchmark or Ingestion-Eval. It indicates that evidence grounding is generally traceable, while atomic-claim normalization is the primary bottleneck and evidence-span boundaries are the secondary bottleneck. One claim/evidence pair crosses from example code into the next section. `REAL_LLM_EXTRACTION=NOT_RUN`, so these results do not support an LLM extraction superiority claim.

## Governance

- Every scientific object remains `candidate_proposal`.
- Candidate Diff says “If accepted, proposed delta would be…”; it never claims KG mutation.
- ReviewDecision and promotion controls are absent.
- The run writes only to a local ignored runtime directory; the committed snapshot contains bounded evidence and proposal records, no PDF binary or full text dump.
- Protected artifact integrity: **PASS**.

## Validation

- Focused: 76 passed, 2 warnings in 11.58s
- UI: 11 passed, 2 warnings in 6.59s
- Bounded regression: 85 passed, 4 pre-existing deselected, 2 warnings in 11.49s

## Exit

```text
CHECKPOINT=Scientific-Knowledge-Studio-v1
STATUS=PASS

CHECKPOINT_4_COMMIT=cd4988e27acbe36f0f4489c6591bdad76374d7ef
LOCAL_HEAD=cd4988e27acbe36f0f4489c6591bdad76374d7ef
REMOTE_HEAD=cd4988e27acbe36f0f4489c6591bdad76374d7ef
PUSH_STATUS=CHECKPOINT_4_VERIFIED

PDF_REAL_RUN=PASS
PDF_FILE=soupx-1.6.2-manual.pdf
PDF_SHA256=dabbfdf10c0ab46efee927026f77494e1df096999742f86705b91dcd0b1dac19
PAGE_COUNT=26
PARSED_PAGES=26
PARSE_GAPS=0

EVIDENCE_SPAN_PROPOSALS=16
ENTITY_PROPOSALS=1
RELATION_PROPOSALS=0
ATOMIC_CLAIM_PROPOSALS=8
SCOPE_PROPOSALS=8

VALID=23
NEEDS_REVIEW=0
INVALID=10

EXACT_EXISTING_IDENTITY=1
POSSIBLE_EXISTING_IDENTITY=0
NEW_CANDIDATE=0
AMBIGUOUS=0
UNRESOLVED=0

CANDIDATE_DIFF=PASS
PROPOSAL_GRAPH=PASS
EVIDENCE_VIEWER=PASS
PIPELINE_STEPPER=PASS
RUN_TRACE=PASS
PREVIEW_ONLY_BANNER=PASS

REAL_LLM_EXTRACTION=NOT_RUN
HUMAN_SANITY_REVIEW=COMPLETED_PENDING_PDF_PAGE_CONFIRMATION
HUMAN_SANITY_ENTITY={'CORRECT': 0, 'PARTIAL': 1, 'INCORRECT': 0, 'UNCERTAIN': 0, 'total': 1}
HUMAN_SANITY_CLAIMS={'CORRECT': 3, 'PARTIAL': 4, 'INCORRECT': 1, 'UNCERTAIN': 0, 'total': 8}
HUMAN_SANITY_EVIDENCE={'CORRECT': 6, 'PARTIAL': 3, 'INCORRECT': 1, 'UNCERTAIN': 0, 'total': 10}
FOCUSED_TESTS=76 passed, 2 warnings in 11.58s
REGRESSION_TESTS=85 passed, 4 pre-existing deselected, 2 warnings in 11.49s
ARTIFACT_INTEGRITY=PASS

SCIENTIFIC_KG_MUTATED=false
LEGACY_KG_MUTATED=false
DECISION_GRAPH_MUTATED=false
CORPUS_CHANGED=false
INDEX_CHANGED=false
PLANNER_CHANGED=false
GOLD_CHANGED=false
CONTRACTS_CHANGED=false
CAPABILITY_PACKS_CHANGED=false

REVIEW_DECISION_CREATED=false
CANONICAL_PROMOTION=none
TRUSTED_KNOWLEDGE_CREATED=false

PRIMARY_LIMITATION=The bounded user-supplied sanity review identifies claim atomization and evidence-span boundaries as the current quality bottlenecks; PDF-page confirmation is pending, and real LLM extraction was not run.
NEXT_EARLIEST_DIVERGENCE=EvidenceSpan boundary repair and atomic proposition normalization after the bounded sanity review.
NEXT_RECOMMENDED_CHECKPOINT=EvidenceSpan Boundary + Atomic Claim Normalization v1
STOPPED=true
```
