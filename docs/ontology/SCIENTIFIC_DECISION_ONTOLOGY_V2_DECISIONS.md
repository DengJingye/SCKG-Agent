# 5C design decision log

Status: 5C.1 targeted correction proposal; human_decision remains blank in the CSV packet.

| ID | Decision | Rationale and repository evidence |
|---|---|---|
| D01 | Keep entity subject separate from assertion identity | design.1 generator lines 410–417 put applicability on ScientificStatement; actual v1 AtomicClaimRevision.subject_id refers to an entity (conformance model lines 354–360, 653–654). |
| D02 | Core has four scientific modules and an external runtime bridge | Scientific v1.1 representation types encode universal semantics; `core/representation_models.py:18` owns concrete indices, slot, provenance and freshness. |
| D03 | Use exact revision-family pairs | design.1 VersionedResource interface excludes stable identity targets; broad revision→revision permissions are invalid. |
| D04 / N01 | Four strengths with orthogonal activation | strength is REQUIRED/RECOMMENDED/OPTIONAL/DISCOURAGED; when is independent. Explicit activation_status distinguishes specified, unconditional and unknown; no verb inference. |
| D05 | EvidenceAssessment owns support types | Existing assessment has exact claim/span references and alignment; separate supports/contradicts/refutes core predicates would duplicate this object. |
| D06 | EvidenceSpan owns immutable excerpt identity only | Old observed spans mix authority, normalized proposition and retrieval flags. These move to separate conceptual owners; existing extractor remains unchanged. |
| D07 | Prefer inline context, reusable scope only when justified | Existing scope is mandatory in v1; 5C is a review proposal permitting simple inline context, not a compatibility promise. |
| D08 | Transformations use methods, typed ports and declared effects | Avoid modifies/filters/normalizes/integrates/aggregates/projects_to verb proliferation. Runtime invalidation remains outside scientific truth. |
| D09 | Identity and provenance extensions remain unapproved | Correct identity assertion endpoints and one optional was_derived_from relation; no broad external ontology imports or identity merges. |
| D10 | Preserve design.1 and distinguish design checks from runtime readiness | Old 25 tests check documentary closure and baseline integrity; they do not validate entity-first semantics or migrate any production schema. |

## Example identifier audit

The old generator selects example IDs using a generic sequence ending in scope_id
(`eval/scientific_decision_ontology_v2_design_audit.py:475`). For
RepresentationConstraint, InputPort and OutputPort, actual records have their own
constraint_id/input_port_id/output_port_id but the old audit chose parent scope
IDs. ApplicabilityScope correctly uses scope_id. The new object registry records
both historical and verified actual IDs with source graph node references; these
are audit references only, not new KG instances.

## Boundary between test evidence and production behavior

`AtomicClaimRevision.predicate` and `object_id` remain unrestricted strings in the
v1 schema. The bundle checks subject existence but does not provide a comprehensive
predicate registry/domain/range check. 5C synthetic positive/negative examples
validate the design contract in ontology-focused tests only. They are not an
implemented ingestion validator, staging pipeline or adapter.

Typed literal unions, aligned evidence judgments and context conflicts are
reviewed without generating any scientific assertion or ReviewDecision record.
`is_sparse` remains a bounded scalar assertion. N03 removes `effect_description`
from the assertion surface entirely; it is display-only and cannot supply a
decision gate, support, trust or authorization.

## Targeted N01–N05 decisions

| Correction | Final design contract | Verification scope |
|---|---|---|
| N01 | strength independent of when; CONDITIONAL removed from strength; unknown activation never universal; OPTIONAL+when allowed as conditional admissibility | all four strengths with unknown/unconditional/specified activation plus invalid cases |
| N02 | ReferenceArtifact/Revision enter Core; representation-only/reference-only/mixed target requirements; same-family revision pin | target family, combination, empty targets, resource identity and digest negatives |
| N03 | effect_description is display-only, assertion_allowed=false and decision_gate_allowed=false | display text rejected as assertion/effect decision evidence; typed statement plus assessment required and still no authorization |
| N04 | shared scope declares status, combination and context; duplicates deduplicate without flattening ANY_OF; conflicts reject; changed payload gets new ID | distinguishing ALL_OF/ANY_OF cases, unknown contradiction, partial dimensions, immutable identity and inline/shared conflicts |
| N05 | check enum/value shape, datatype, exact unit, operator revision ownership and version family | negative cases at helper and StatementRevision/Requirement entry points; no production validator |

Minimal reference resources were moved from extension in response to N02, not as
an unrelated expansion. The extension registry, mapping draft and human packet
are synchronized to avoid duplicate dispositions. Scope serialization now uses
ALL_OF/ANY_OF for combination while retaining explicit/partially_known/unknown/
not_applicable for scope_status. This is a design-only correction, not a migration
of existing v1 records. `value_domain` is a small typed embedded parameter domain;
revision-specific parameter membership in synthetic fixtures represents existing
has_parameter bindings, not a new production registry.

F01 (semantic PASS weakness) and F04 (qualifier/scope incompleteness) are reassessed
against the new executable negative tests, including cases sent through statement
and requirement entry points. The current tested result and precise limits are
recorded in the 5C review/manifest; neither item is closed by documentary assertion
alone. Independent QA recheck is still required.

No new effect predicate, downloader, lifecycle manager, migration adapter or
production decision gate is implemented. Unknown/unregistered qualifiers,
unsupported version schemes and effects not expressible by an admitted assertion
remain review/defer cases.

Next action: `STOP_FOR_QA_RECHECK`. No commit/push or 5D.
