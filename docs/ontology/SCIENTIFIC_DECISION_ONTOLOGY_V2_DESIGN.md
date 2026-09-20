# Scientific Decision Ontology v2 Research & Design Audit

STATUS=PASS
DESIGN_ONLY=true
PRODUCTION_MIGRATION=false

## Decision

The frozen v1 ontology is useful but is not yet precise and governed enough for unrestricted long-term extraction, evidence evolution, and action authorization. Its strongest foundations are release-bound operators, representation constraints, applicability scopes, evidence-bound claim revisions, and fail-closed review semantics. V2 should preserve these foundations while making the authoritative statement, provenance, evidence drift, identity drift, and action layers explicit.

This design does not replace the production schema. It introduces no Scientific KG content and performs no migration.

## Bounded scope

Scientific Decision Ontology v2 covers evidence-governed single-cell and multi-omics analysis decisions: methods, software implementations, data representations, applicability, evidence, version/provenance, governance, actions, and evaluation context.

It excludes gene/protein/pathway biological truth, comprehensive disease and cell ontologies, general chemistry, and clinical diagnosis. External ontologies should supply those identities.

## Competency-question result

- Total: 77
- Answerable by current v1: 19
- Answerable by v2 design: 45
- Partially answerable: 11
- Out of scope: 2

## Current audit

- Physical v1 graph classes: 21
- Audited current classes including schema, pilot, and runtime surfaces: 37
- Current graph predicates: 33
- Candidate v2 classes: 45
- Candidate v2 predicates: 46

Observed predicate risks: {'AMBIGUOUS_PREDICATE': 3, 'DUPLICATE_PREDICATE': 3, 'MISSING_DOMAIN_RANGE': 4, 'MISSING_INVERSE': 18, 'OVERLOADED_PREDICATE': 5, 'UNSAFE_TRANSITIVE_ASSUMPTION': 1}. Upper-case structural edges remain projections only; lower-case governed predicates and StatementRevision records carry authoritative semantics.

## Core v2 decisions

1. `ScientificStatement` is stable identity; `StatementRevision` is the authoritative versioned S-P-O-Q assertion.
2. `AtomicClaimRevision` is a future compatibility surface for StatementRevision, not a second assertion model.
3. Evidence existence, support, review, and trust remain separate gates.
4. Provenance aligns with PROV-O Entity/Activity/Agent relations while retaining scKG domain classes.
5. Runtime state, scientific knowledge, and governed action remain separate layers.
6. Graph projections are derived views and must reference the statement revisions that justify them.
7. Ontology and evidence drift require explicit revalidation states; no source monitor is implemented here.

## V1 to v2 dispositions

{"ADD": 45, "DEPRECATE": 1, "EXTERNALIZE": 1, "KEEP": 28, "MERGE": 4, "REFINE": 35, "SPLIT": 1}

Every ADD or REFINE entry cites competency-question IDs in `v1_v2_gap_analysis.json`.

## External alignment

- EDAM: reuse established operation, data, and format identifiers where the mapping is strong.
- PROV-O: adopt provenance relation semantics and qualified influence when role or time matters.
- Biolink: reuse the S-P-O-Q association pattern, while retaining scKG evidence assessment and governance.
- OBO/RO: search and reuse existing relations before minting local predicates.
- RO-Crate: plan a future exchange profile; do not use it as the internal statement model.

## Quality metrics

Ontology-Eval uses 12 separate metrics; it deliberately has no single global score. Competency Question Coverage is the primary completeness measure.

## Validation

- Focused design consistency: 25 passed
- Bounded v1 KG and Studio regression: 70 passed

## Integrity and stop

Production ontology, Scientific KG, RAG, Planner, and Studio extractor hashes are frozen in the manifest and validated by focused tests. No quarantined C7 payload was accessed. Human review of competency questions, class hierarchy, predicates, statement model, action model, and shapes is required before any migration plan can become executable.

## Exit

```text
CHECKPOINT=Scientific-Decision-Ontology-v2-Design-Audit
STATUS=PASS

COMPETENCY_QUESTIONS=77
ANSWERABLE_CURRENT_V1=19
ANSWERABLE_V2_DESIGN=45
PARTIALLY_ANSWERABLE=11
NOT_IN_SCOPE=2

CURRENT_CLASSES=37
PROPOSED_CLASSES=45
CURRENT_PREDICATES=33
PROPOSED_PREDICATES=46

KEEP=28
REFINE=35
SPLIT=1
MERGE=4
ADD=45
DEPRECATE=1
EXTERNALIZE=1

INTERFACES=7
CONSTRAINT_SHAPES=8
EXTERNAL_ALIGNMENTS=5

PRIMARY_V1_GAPS=["Authoritative statement identity/revision and graph projections are not cleanly separated.", "Predicate registry contains duplicate projection/claim forms and incomplete domain/range semantics.", "Evidence support, provenance activities, evidence drift, and ontology drift are not governed end to end.", "Runtime state, scientific knowledge, and governed action exist across separate models without a shared interface contract.", "Pilot SourceWork/SourceRevision/SourceArtifact and review flows are not production ontology classes."]

FOCUSED_TESTS=25 passed
ARTIFACT_INTEGRITY=PASS

PRODUCTION_ONTOLOGY_CHANGED=false
SCIENTIFIC_KG_CHANGED=false
RAG_CHANGED=false
PLANNER_CHANGED=false
STUDIO_EXTRACTOR_CHANGED=false

CHECKPOINT_5A_COMMIT=c8cef942f214efb2844cd3e5bf1aa0c28a4a50ab
LOCAL_HEAD=c8cef942f214efb2844cd3e5bf1aa0c28a4a50ab
REMOTE_HEAD=c8cef942f214efb2844cd3e5bf1aa0c28a4a50ab
PUSH_STATUS=VERIFIED

NEXT_RECOMMENDED_CHECKPOINT=Ontology v2 Human Review / EvidenceSpan + AtomicClaim Quality Gate after ontology freeze
STOPPED=true
```
