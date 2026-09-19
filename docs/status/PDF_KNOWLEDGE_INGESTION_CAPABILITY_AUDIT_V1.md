# PDF Knowledge Ingestion Capability Audit v1

STATUS=PASS
CHECKPOINT=PDF-Knowledge-Ingestion-Capability-Audit-v1
AUDIT_MODE=read-only

## Decision

The repository already contains **17/30 implemented reusable or pilot stages (56.7%)**, but only **2/30** are generic reusable capabilities without relying on a tool-specific pilot. The SoupX work proves the governed candidate boundary, exact evidence binding, isolated candidate deposit/reuse, trace, review-item creation, and a fail-closed promotion guard. It does not provide a general PDF-to-Scientific-KG extractor.

`MIDTERM_SINGLE_PDF_DEMO_FEASIBLE=false` for the repository as it stands. The blockers are generic source/revision registration, page-stable EvidenceSpan generation, governed entity and relation extraction, identity resolution, and one orchestrated candidate-only path. The safe backbone should be reused rather than replaced.

## Capability counts

| Classification | Count |
|---|---:|
| IMPLEMENTED_PRODUCTION | 0 |
| IMPLEMENTED_REUSABLE | 2 |
| IMPLEMENTED_PILOT | 15 |
| PARTIAL | 9 |
| MISSING | 2 |
| UNSAFE_TO_REUSE | 2 |
| **TOTAL** | **30** |

## What already exists

- **Reusable:** PDF text extraction in `data_pipeline/ingest_evidence_pdfs.py` and Scientific KG schema/cross-reference validation in `core/scientific_knowledge_conformance_models.py`.
- **SoupX pilot:** artifact hashing, SourceWork/SourceRevision records, exact EvidenceSpan binding, EvidenceAssessment, typed/scoped AtomicClaimRevision, candidate identity, isolated candidate KG/RAG deposit, reuse, review-item creation, and trace.
- **Candidate-only guarantee:** the audited SoupX path writes to an isolated evaluation directory and sets retrieval-only/non-recommendation-eligible gates. It cannot overwrite canonical knowledge. No claim is reviewed, trusted, promoted, or execution-authorized.
- **Trace:** 3 of 15 requested knowledge-evolution stages are directly represented, 6 are partial through generic operations, and 6 are absent. The trace framework is reusable; the knowledge-evolution vocabulary is not yet canonical.

## What is pilot-only

The SourceWork, SourceRevision, EvidenceSpan, claim text, scope, version, and identity slice are fixed to SoupX. Candidate storage is a write-once evaluation directory rather than a revisioned repository. The review queue is a read-only decision surface; its actions are descriptions rather than persisted backend operations.

## Unsafe paths

`data_pipeline/neo4j_loader.py` can send LLM-derived Tool KG content directly to mutable Neo4j without Scientific KG candidate schemas or evidence-span bindings. It is flagged `UNSAFE_DIRECT_KG_MUTATION` and must not be reused for Checkpoint 5. Legacy review/promotion scripts target a different evidence lifecycle and are not a Scientific KG promotion backend.

## Review and promotion

`ReviewDecision` has a formal model but no persistence owner. KEEP, REJECT, MERGE, SUPERSEDE, APPROVE, and PROMOTE have no usable Scientific KG backend. The promotion gate fails closed, but canonical promotion is not safe to expose: `PROMOTION_UI_ALLOWED=false`.

## P0 for one-PDF demo

- generic local PDF registration
- formal SourceWork/SourceRevision/SourceArtifact adapter
- page-preserving parser mode with parser-version provenance
- generic exact EvidenceSpan candidate generation
- versioned structured candidate entity/relation/claim/scope extraction with mandatory span IDs
- entity resolution and per-type dedup keys
- external EvidenceSpan binding validation
- general before/after candidate diff
- candidate-only orchestration over the existing isolated deposit pattern

## Checkpoint 5 reuse boundary

Reuse the generic PDF parser, source-registry dedup policy, section/chunk locator helpers, conformance models, candidate identity/deposit pattern, retrieval-only index primitives, and canonical trace framework. Add a thin generic orchestrator and the missing candidate-only structured extraction/resolution layer. Do not call the legacy Neo4j loader, grant production retrieval eligibility, or add canonical mutation.

## Audit integrity

- Focused audit tests validate the stage set, classification, path evidence, owner conflicts, unsafe mutation flag, SoupX mapping, reusable pipeline, protected artifacts, and C7 non-access contract.
- Bounded related regression: **82 passed, 1 deselected in 0.90s**. The one excluded stale assertion expects an archived 48-claim asset that is absent from this branch; this checkpoint did not modify that builder, test, or asset path.
- Frozen KG/corpus/index/planner/gold hashes: **PASS**.
- Quarantined C7 payload accessed: **false**.
- This checkpoint added no PDF ingestion, extractor, KG content, index, planner, gold, review UI, trace UI, benchmark, or promotion implementation.

## Exit

```text
CHECKPOINT=PDF-Knowledge-Ingestion-Capability-Audit-v1
STATUS=PASS

TOTAL_STAGES=30

IMPLEMENTED_PRODUCTION=0
IMPLEMENTED_REUSABLE=2
IMPLEMENTED_PILOT=15
PARTIAL=9
MISSING=2
UNSAFE_TO_REUSE=2

SOUPX_REUSABLE_STAGES=11 mapped pilot steps; 3 directly reusable component patterns

PDF_UPLOAD_READY=false
PDF_PARSE_READY=true_with_limitations
SOURCE_REVISION_READY=pilot_only
EVIDENCE_SPAN_READY=pilot_only
ENTITY_EXTRACTION_READY=false
RELATION_EXTRACTION_READY=false
CLAIM_EXTRACTION_READY=pilot_only
ONTOLOGY_VALIDATION_READY=true_with_external_span_limit
CANDIDATE_DEPOSIT_READY=pilot_only
REVIEW_DECISION_READY=false
TRACE_READY=pilot_only
CANONICAL_PROMOTION_READY=false

MIDTERM_SINGLE_PDF_DEMO_FEASIBLE=false

P0_MISSING_COMPONENTS=["generic local PDF registration", "formal SourceWork/SourceRevision/SourceArtifact adapter", "page-preserving parser mode with parser-version provenance", "generic exact EvidenceSpan candidate generation", "versioned structured candidate entity/relation/claim/scope extraction with mandatory span IDs", "entity resolution and per-type dedup keys", "external EvidenceSpan binding validation", "general before/after candidate diff", "candidate-only orchestration over the existing isolated deposit pattern"]

FOCUSED_TESTS=14 passed in 0.08s
ARTIFACT_INTEGRITY=PASS

KG_CONTENT_CHANGED=false
CORPUS_CHANGED=false
INDEX_CHANGED=false
PLANNER_CHANGED=false
GOLD_CHANGED=false
CANONICAL_PROMOTION=none

CHECKPOINT_3_COMMIT=453cb31f27fc4f9e7bc6e810100848847ac9bd05
LOCAL_HEAD=453cb31f27fc4f9e7bc6e810100848847ac9bd05
REMOTE_HEAD=453cb31f27fc4f9e7bc6e810100848847ac9bd05
PUSH_STATUS=VERIFIED

NEXT_RECOMMENDED_CHECKPOINT=PDF Candidate Ingestion V1 / STOP_FOR_REVIEW
STOPPED=true
```
