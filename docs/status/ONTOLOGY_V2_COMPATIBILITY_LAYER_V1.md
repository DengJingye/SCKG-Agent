# Ontology v2 final testcase-outcome evidence closure

WINDOW=02-Core-Implementation

CHECKPOINT=5E.3-Final-Test-Evidence-Closure

STATUS=PASS

BASE_COMMIT=389d0d5b6cfbf7e34b3a4c82f52e54308debb031

EVALUATED_REVISION=2e58bb17555938c345e7bed701ecb01ead83c628

ACCEPTED_ONTOLOGY_COMMIT=46910b46b41fe83cc4b11316028db5bfd77647f9

BRANCH=feature/ontology-v2-compat-v1

## Outcome and boundary

`ScientificOntologyV2CompatibilityService` remains a deterministic, immutable,
fail-closed qualification layer over current v1 Scientific KG records. It reads the
frozen 5C.1 ontology artifacts and does not migrate, rewrite, promote, persist or
generate scientific knowledge.

The patch is still not wired into Research Chat, Hybrid Retrieval, Scientific KG
retrieval, Planner, RepresentationLedger, ToolContract, Admin or Knowledge Studio.
It does not start 5F and does not change any production ontology or schema.

## Safety corrections

- Atomic claims now require the supplied scope's exact source identity to equal
  `claim.scope_id`. Similar qualifiers under another ID, a richer substitute, or a
  missing expected scope fail closed.
- Effective scope retains shared qualifiers and inline-only qualifiers separately.
  Equal duplicates are deduplicated, conflicts are ambiguous, and shared `ANY_OF`
  plus inline conjunction is represented without flattening or dropping context.
- `StatementRevisionView` now retains inline-only qualifiers through the final
  returned and serialized claim view. `scope_ref` preserves the shared scope while
  `context_composition=SHARED_SCOPE_AND_INLINE` makes the conjunction explicit;
  different inline flavors are therefore semantically distinct.
- Predicate/link semantics and source-record authority are separate fields.
  An authoritative link type does not promote a candidate or legacy record, invalid
  endpoint pairs remain unresolved, and every relation view is non-trusted and
  non-canonical.
- Frozen predicate qualifier policies and scalar-property object kinds are executed.
  Disallowed dimensions are reported, never deleted. Entity predicates require
  entity objects; scalar properties such as `is_sparse` reject entity objects and
  require a typed scalar for direct compatibility.
- Provenance identity is record-type-specific: claim revision, assessment, evidence
  span, requirement, graph edge and scope views point to their exact source records.
- `EvidenceSpanCoreView` contains no legacy governance status. Forensic legacy status
  is available only in the outer compatibility diagnostics.
- Evidence assessment binding checks the actual span view and provenance identity,
  and the inventory builder retains multiple assessment identities per statement.
  Support and refutation remain independent and never aggregate into trust.
- Declared test status is separated from verified evidence status. A checkpoint
  `PASS` requires repository-local result JSON and JUnit artifacts whose suite ID,
  tested revision, counts, required node IDs and SHA-256 values all verify. Recorded
  commands are provenance only and are never executed by the evaluation builder.
- Every JUnit testcase is independently classified as `PASSED`, `FAILED`, `ERROR`
  or `SKIPPED`. Counts are recomputed from testcase elements and checked against
  suite/root headers. Only individually passed nodes enter `verified_node_ids`, so a
  failed, errored, skipped or missing Chat node cannot satisfy Chat coverage.

## Full physical-inventory qualification

The audit inspected all physical records in the frozen consolidated inventory and
retained layer provenance. Counts measure compatibility coverage, not scientific
accuracy.

| Surface | Inspected | Result |
|---|---:|---|
| AtomicClaimRevision | 380 | 0 direct; 0 adapter; 317 ambiguous; 63 not mappable |
| EvidenceSpan | 170 | 141 partial core views, all ambiguous; 29 hash-rejected; 0 fully compatible |
| EvidenceAssessment | 380 | 0 views; 380 not mappable because no source statement passes all frozen constraints |
| ApplicabilityScope | 98 | 78 adapter views; 20 ambiguous |
| Requirement | 104 | 96 adapter; 8 ambiguous; 102 views retained |
| RepresentationType | 98 | 98 adapter views |
| Reference resource | 0 current inventory | 1 existing v1.1 qualification fixture mapped |
| Graph relations | 2,429 | 1,182 authoritative link types; 331 derived projections; 916 unresolved predicates |

Relation semantics and record authority remain separate: 1,099 records combine an
authoritative link type with candidate authority, 83 combine that link type with
unresolved record authority, 331 are derived projections/derived records, and 916
have unresolved predicates/records. There are zero supported-authoritative records.

The previously reviewed 217 ambiguous claims remain explainable as 198
non-Statement relations and 19 incomplete partially-known scopes. Executing the
frozen predicate qualifier policies adds 100 explicit ambiguities: their v1 scopes
carry dimensions that the corresponding v2 predicate does not permit. The 63
not-mappable claims remain 59 predicates without an approved crosswalk and four
invalid-domain `supports_task` assertions. No mapping was added merely to increase
coverage.

All 141 structurally valid but ambiguous EvidenceSpan views lack
`source_artifact_id`; 90 of those also lack `source_revision_id`. The other 29
records all come from `content_expansion_v1`. Its historical generator stored only
the first 800 characters of an excerpt while retaining the full chunk hash. This is
not evidence of adapter normalization failure or proof of text corruption; exact
verification nevertheless fails closed, and this patch does not repair the records.

Because the newly enforced frozen qualifier policies leave no current source claim
with a compatible `StatementRevisionView`, all 380 current EvidenceAssessment
records fail closed on statement availability. No assessment identity is collapsed,
and synthetic focused fixtures verify independent support and refutation behavior.

## Artifacts and validation

The deterministic mapping packet remains in
`data/evaluation/ontology_v2_compatibility_v1/`. Its manifest, mapping summary,
counts, unresolved records, integrity hashes and structured test summary are
generated together. No generated scientific content is written to the KG.

Run-specific, machine-verifiable evidence is retained under `test_evidence/`:

- `focused_5e2.junit.xml` and `focused_5e2.json`: 58 passed under suite ID
  `ontology-v2-compatibility-focused-5e3`.
- `regression_5e2.junit.xml` and `regression_5e2.json`: 88 passed.

Both result records identify evaluated revision
`2e58bb17555938c345e7bed701ecb01ead83c628`, bind the raw JUnit SHA-256, record
every testcase outcome, and list only passed nodes as verified. The builder
independently verifies the result JSON hash, nested JUnit hash, recomputed counts and
required passed-node coverage before emitting `PASS`.

Focused compatibility tests cover every H01-H03 and M01-M05 requirement, inventory
root-cause counts, deterministic output and protected production wiring. Bounded
regressions cover Research Chat, Hybrid Retrieval, Scientific KG evidence,
CapabilityPlanCompiler, RepresentationLedger, ToolContract, Admin Scientific KG and
Knowledge Studio. The commands and verified counts are recorded in
`test_summary.json`.

Reproduce the focused suite from the repository root:

```bash
/opt/anaconda3/envs/sckg_env/bin/python -B -m pytest -q -p no:cacheprovider \
  tests/test_scientific_ontology_v2_compatibility.py
```

Tests use offline LLM mode and disabled execution where production surfaces are
involved.

## Exit

```text
WINDOW=02-Core-Implementation
CHECKPOINT=5E.3-Final-Test-Evidence-Closure
STATUS=PASS
BASE_COMMIT=389d0d5b6cfbf7e34b3a4c82f52e54308debb031
EVALUATED_REVISION=2e58bb17555938c345e7bed701ecb01ead83c628
TESTCASE_OUTCOME_PARSING=PASS
RECOMPUTED_COUNTS=PASS
VERIFIED_NODE_FILTERING=PASS
CHAT_NODE_COVERAGE=PASS
FAILURE_NODE_NEGATIVE=PASS
ERROR_NODE_NEGATIVE=PASS
SKIPPED_NODE_NEGATIVE=PASS
HEADER_MISMATCH_NEGATIVE=PASS
H01_SCOPE_IDENTITY=PASS
H02_INLINE_CONTEXT_END_TO_END=PASS
H03_AUTHORITY_SEPARATION=PASS
M01_FROZEN_CONSTRAINTS=PASS
M02_SOURCE_IDENTITY=PASS
M03_EVIDENCE_SEPARATION=PASS
M04_ASSESSMENT_BINDING=PASS
M05_VERIFIABLE_TEST_EVIDENCE=PASS
ATOMIC_CLAIMS_INSPECTED=380
DIRECT_COMPATIBLE=0
COMPATIBLE_WITH_ADAPTER=0
AMBIGUOUS_MAPPING=317
NOT_MAPPABLE=63
EVIDENCE_SPANS_INSPECTED=170
EVIDENCE_CORE_VIEWS=141
EVIDENCE_AMBIGUOUS=141
EVIDENCE_HASH_REJECTED=29
EVIDENCE_MISSING_ARTIFACT_ID=141
EVIDENCE_MISSING_REVISION_ID=90
ASSESSMENTS_INSPECTED=380
ASSESSMENT_VIEWS=0
ASSESSMENT_AMBIGUOUS=0
ASSESSMENT_NOT_MAPPABLE=380
FOCUSED_TEST_EVIDENCE=VERIFIED
REGRESSION_TEST_EVIDENCE=VERIFIED
FOCUSED_TESTS=58 passed
REGRESSION_TESTS=88 passed
CHAT_IMPORT=PASS
CHAT_RUNTIME=PASS
CHAT_RETRIEVAL=PASS
CHAT_PLANNER=PASS
SCIENTIFIC_KG_CHANGED=false
CATALOG_KG_CHANGED=false
RAG_CHANGED=false
PLANNER_CHANGED=false
FROZEN_ONTOLOGY_CHANGED=false
PRIMARY_LIMITATION=Current v1 records do not satisfy all frozen v2 qualifier and provenance requirements.
EARLIEST_DIVERGENCE=Predicate qualifier policy for claims; EvidenceSpan artifact/revision identity for evidence.
NEXT_RECOMMENDED_ACTION=STOP_FOR_MICRO_CONFIRMATION
STOPPED=true
```
