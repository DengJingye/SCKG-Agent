# Ontology v2 read-only compatibility layer v1

WINDOW=02-Core-Implementation

CHECKPOINT=5E-V1-V2-Compatibility-Layer

STATUS=PASS

BASE_COMMIT=46910b46b41fe83cc4b11316028db5bfd77647f9

BRANCH=feature/ontology-v2-compat-v1

## Outcome and boundary

`ScientificOntologyV2CompatibilityService` exposes immutable qualification views
over current v1 Scientific KG records. It reads only the frozen 5C.1 artifacts in
`data/ontology/scientific_decision_ontology_v2_core/` and does not migrate, rewrite,
promote or persist scientific knowledge.

The service is deliberately not wired into Research Chat, retrieval, Planner,
RepresentationLedger, ToolContract, Admin or Knowledge Studio. Existing loaders
retain their separate authority boundaries. The view models are named compatibility
views and cannot be mistaken for canonical writable v2 production entities.

## Mapping behavior

- `AtomicClaimRevision` is exposed as `StatementRevisionView` only when its
  predicate and endpoint pair are admitted by the frozen registries. IDs, polarity,
  shared scope reference, semantic fingerprint, content hash, supersession and
  evidence references are preserved. Candidate source status is retained and the
  view is always non-trusted.
- Literal claims retain the literal but remain `AMBIGUOUS_MAPPING` when v1 has no
  explicit datatype. Unknown predicates and malformed object unions fail closed.
- `EvidenceSpanCoreView` includes only source identity/artifact fields, exact text,
  hash and locators. Trust, candidate/review state, retrieval eligibility, source
  authority, support and normalized propositions are excluded.
- Evidence assessments retain exact statement/span cardinality. `supports` becomes
  `DIRECT_SUPPORT` only when subject, predicate, object and scope are explicitly
  aligned. Missing v2 assessor/method/timestamp/status metadata remains visible as
  ambiguity and never becomes trust.
- Shared scope preserves `ALL_OF`/`ANY_OF`. Unknown is emitted as unknown, never as
  universal. Partial v1 scopes without explicit unknown dimensions and conflicting
  inline/shared values are ambiguous.
- v1 mandatory/recommended/optional requirements map to REQUIRED/RECOMMENDED/
  OPTIONAL with independent activation. Legacy `conditional` does not reveal a v2
  strength and remains ambiguous. Multi-target v1 requirements without a target
  combination also remain ambiguous.
- Reference views require an existing stable artifact and, when requested, an
  existing same-family revision. No revision identity is synthesized.
- `CONSUMES`, `PRODUCES` and `CAN_FEED` are always derived projections.
  `REQUIRES_BEFORE` remains deferred. Legacy relations are labeled compatibility
  relations and are not promoted to authoritative v2 facts.
- `effect_description` is rejected as a statement or authoritative relation.

## Full physical-inventory qualification

The audit inspected all physical records in the frozen consolidated inventory and
retained layer provenance. Counts are compatibility coverage, not scientific
accuracy.

| Surface | Inspected | Result |
|---|---:|---|
| AtomicClaimRevision | 380 | 83 direct; 17 adapter; 217 ambiguous; 63 not mappable |
| EvidenceSpan | 170 | 141 partial core views, all ambiguous; 29 invalid; 0 fully compatible |
| EvidenceAssessment | 380 | 74 partial views; all retain missing v2 audit metadata as ambiguity |
| ApplicabilityScope | 98 | 78 adapter views; 20 ambiguous |
| Requirement | 104 | 96 adapter; 8 ambiguous; 102 views retained |
| RepresentationType | 98 | 98 adapter views |
| Reference resource | 0 current inventory | 1 existing v1.1 qualification fixture mapped |
| Graph relations | 2,429 | 331 derived projections classified |

The earliest divergence is EvidenceSpan artifact identity: none of the 170 current
physical span records supplies the frozen v2 `source_artifact_id`. The service
therefore preserves 141 structurally valid partial views as ambiguous; it does not
mint artifact IDs. A further 29 broad-coverage span records fail exact UTF-8
text/hash verification and are not mappable.

Other visible legacy gaps include non-statement claim predicates, partial scopes
without `unknown_dimensions`, conditional requirements without independently
reviewed strength, and missing EvidenceAssessment audit metadata.

## Artifacts

The deterministic evaluation packet is in
`data/evaluation/ontology_v2_compatibility_v1/`:

- `manifest.json`
- `mapping_summary.json`
- `compatibility_counts.json`
- `unresolved_mappings.json`
- `integrity.json`
- `test_summary.json`

No generated scientific content was written to the Scientific KG.

## Validation

Focused compatibility tests: **30 passed**. They cover positive and negative
mappings, immutable views, exact evidence links, PDF/non-page locators, unknown
scope, reference-only requirements, cross-family rejection, deterministic output,
candidate/trust separation, derived relation authority and protected production
wiring.

Bounded production regressions: **87 passed** across Research Chat, Hybrid
Retrieval, Scientific KG evidence retrieval, CapabilityPlanCompiler,
RepresentationLedger, ToolContract, Admin Scientific KG and Knowledge Studio.

Reproduce from the repository root:

```bash
/opt/anaconda3/envs/sckg_env/bin/python -B -m pytest -q -p no:cacheprovider \
  tests/test_scientific_ontology_v2_compatibility.py
```

The exact bounded regression selection and environment are recorded in the
checkpoint handoff. Tests ran with offline LLM mode and disabled execution.

## Exit

```text
WINDOW=02-Core-Implementation
CHECKPOINT=5E-V1-V2-Compatibility-Layer
STATUS=PASS
ATOMIC_CLAIMS_INSPECTED=380
DIRECT_COMPATIBLE=83
COMPATIBLE_WITH_ADAPTER=17
AMBIGUOUS_MAPPING=217
NOT_MAPPABLE=63
EVIDENCE_SPANS_INSPECTED=170
EVIDENCE_CORE_VIEWS=141
EVIDENCE_AMBIGUOUS=141
SCOPE_MAPPINGS=78
REQUIREMENT_MAPPINGS=102
REFERENCE_MAPPINGS=1 qualification fixture; 0 current inventory
DERIVED_RELATIONS_CLASSIFIED=331
FOCUSED_TESTS=30 passed
REGRESSION_TESTS=87 passed
CHAT_IMPORT=PASS
CHAT_RUNTIME=PASS
CHAT_RETRIEVAL=PASS
CHAT_PLANNER=PASS
SCIENTIFIC_KG_CHANGED=false
CATALOG_KG_CHANGED=false
RAG_CHANGED=false
PLANNER_CHANGED=false
PRODUCTION_ONTOLOGY_CHANGED=false
PRIMARY_LIMITATION=Current v1 EvidenceSpan records lack explicit v2 source_artifact_id; conditional v1 requirements lack independent strength.
EARLIEST_DIVERGENCE=EvidenceSpan source artifact identity, followed by 29 exact-text/hash mismatches.
NEXT_RECOMMENDED_ACTION=STOP_FOR_QA
STOPPED=true
```
