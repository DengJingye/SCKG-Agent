# Checkpoint 5C.1 targeted corrections review

WINDOW=01-Ontology-Core  
CHECKPOINT=5C.1-Targeted-Core-Corrections  
STATUS=PASS  
NEXT_RECOMMENDED_ACTION=STOP_FOR_QA_RECHECK

## Scope and repository baseline

Only N01–N05 from the supplied 5C.1 instruction were corrected. Work is confined
to the existing 5C core design artifacts, four ontology review documents and the
ontology-focused test helper. This is not a broad ontology redesign or production
validator. Repository ownership and actual v1 reference/requirement models were
read before editing; `core/scientific_knowledge_conformance_models.py` remains the
unchanged production owner. Historical design.1 remains byte-for-byte unchanged.

Baseline/current HEAD: `c8cef942f214efb2844cd3e5bf1aa0c28a4a50ab`  
Branch: `feature/method-kg-expansion-v1`

The manifest retains the original protected-file baseline and previous 5C test
result separately. Current results below supersede the previous 5C report. Existing
untracked unrelated work is preserved. No commit, push, production migration,
compatibility adapter, external LLM call, PDF rerun or 5D work was performed.

## Targeted corrections and executable evidence

| Item | Implemented design correction | Test evidence in `tests/test_ontology_v2_core_5c.py` |
|---|---|---|
| N01 | Four-value strength independent of optional when; explicit specified/unconditional/unknown activation; CONDITIONAL removed; no verb inference; OPTIONAL+when means conditional admissibility | `test_n01_strength_condition_orthogonality` checks all 12 strength/activation combinations; `test_n01_n05_invalid_strength_or_activation_rejected` and requirement entry-point negatives |
| N02 | ReferenceArtifact and immutable pinned ReferenceArtifactRevision promoted to Core; reuse requires_reference alongside requires_constraint; representation-only, reference-only and mixed requirements supported | `test_n02_representation_reference_and_mixed_requirements`, invalid target-family tests and reference identity/pin/digest tests |
| N03 | effect_description is display metadata; assertion_allowed=false; forbidden for gates, blocking, applicability, authorization, scientific truth and trusted projections | `test_n03_effect_description_is_display_only_and_cannot_satisfy_gate`; `test_n03_machine_readable_effect_requires_statement_and_assessment_without_authorization` |
| N04 | Shared status/combination/context explicit; partial unknown dimensions; same-value deduplication; conflicts rejected; ALL_OF/ANY_OF group preserved; changed scope gets new ID | `test_n04_preserve_all_of_any_of_not_interchangeable`, duplicate/conflict tests, inline conjunction tests, statement-boundary status validation, partial/unknown/immutable tests |
| N05 | Statement enums and object/value XOR; parameter datatype/unit/operator/revision membership; version state/pin/family; qualifier value checks; requirement activation/strength negatives | `test_n05_statement_semantic_negatives`, parameter/version/value negative groups and checks through StatementRevision/Requirement entry points |

Scientific effects need an admitted StatementRevision plus EvidenceAssessment;
that structure alone grants no decision authority. Actual runtime effects remain
owned by RepresentationLedger/Trace. Unrepresentable scientific effects and
temporal scope lineage remain deferred. No generic Effect object was added.

Scope combination uses ALL_OF/ANY_OF; scope_status retains the documented lower-case
serialization explicit/partially_known/unknown/not_applicable. Unknown is not a
universal context. Shared ANY_OF remains a group; new inline dimensions are
conjoined outside it, with matching duplicates retained only in the shared group.

## F01 / F04 reassessment

- **F01=RESOLVED within the 5C.1 design-test scope.** The new semantic negatives
  actually passed for statements, parameter/version conditions, qualifier values
  and requirements, including validation through their entry points. PASS no
  longer rests on documentary closure alone.
- **F04=RESOLVED within the 5C.1 design-test scope.** Scope status contradictions,
  distinguishing ALL_OF/ANY_OF cases, duplicate/conflict handling, partial unknown
  dimensions, immutable IDs and invalid qualifier values have executable evidence.

This is the ontology window's tested reassessment. Independent QA recheck and human
acceptance remain pending; human_decision/human_notes remain blank in all 191 rows.

## Actual counts and coverage

26 Core object types = 25 scientific + 1 external runtime bridge; 23 authoritative
Core links + 2 derived projections; 74 properties; 10 qualifiers. Extension has
7 object types and 10 links; 8 object types remain deferred and 4 are merged
compatibility surfaces. No count was forced to match a target.

83 CQs = 77 original questions retained verbatim + 6 existing 5C additions.
Coverage: 39 Core, 11 Extension, 17 partial, 14 deferred, 2 out of scope.
CQ-D03 moves Extension → Core after the minimal reference-resource promotion.
CQ-C05 moves partial → deferred because display text cannot represent a scientific
effect for decision use. CQ-L02 wording tracks strength/activation orthogonality.
`evidence_model.json` needed no change. Extension/deferred/mapping registries were
synchronized only where N01–N05 changed their dispositions or semantics.

## Validation

Focused plus historical suite: **143 passed**, 0 failed/errors/skipped, comprising
118 current ontology checks and 25 historical design audit checks. Bounded existing
product regression: **10 passed**, 0 failed/errors/skipped. JUnit case-level evidence,
selected regression node IDs and test-source hashes are retained in the manifest.

| Protection check | Actual evidence | Result |
|---|---|---|
| Chat import | ResearchChatService, HybridRetrievalService, CapabilityPlanCompiler, ScientificKGEvidence | PASS |
| Chat runtime | ASK routing, blocked unregistered-data RUN, Streamlit Chat reruns and route round trip | PASS |
| Chat retrieval | BM25/source binding/index reuse, three real operator searches and ResearchToolRegistry evidence entry | PASS |
| Chat planner | Existing workspace/compiler plan test; execution disabled | PASS |
| Protected assets | All 11 groups compare complete path/hash inventories, including additions/deletions | UNCHANGED |

Regression used temporary SCKG_HOME and MPLCONFIGDIR, offline LLM mode, disabled
execution and no bytecode writes. No notebook, scientific tool, external extraction,
benchmark campaign or real dataset run was started. Existing conda Python with
pytest 7.4.4 was used; no installation or environment modification was required.

Reproduce focused checks from the repository root:

```bash
/opt/anaconda3/envs/sckg_env/bin/python -B -m pytest -q -p no:cacheprovider tests/test_ontology_v2_core_5c.py tests/test_scientific_decision_ontology_v2_design_audit.py
```

All protected groups remain unchanged: production ontology, Scientific KG, Catalog
KG, Decision Graph, RAG, Planner, contracts, Capability Packs, gold, protected source
and design.1. Hash policy excludes __pycache__ and sealed/quarantined/C7 payloads
without opening them. HEAD is unchanged; tracked diff/whitespace check is clean.

## Files changed in 5C.1

17 existing files changed relative to the pre-5C.1 snapshot; no files created.
Exact paths and before/after hashes are in the manifest.

- 12 Core artifacts: object_type_registry.json, property_registry.json,
  link_type_registry.json, qualifier_registry.json, scope_policy.json,
  statement_model.json, extension_registry.json, deferred_registry.json,
  v1_v2_mapping_draft.json, competency_question_coverage.json,
  ontology_v2_core_human_review.csv, manifest.json.
- Four docs: SCIENTIFIC_DECISION_ONTOLOGY_V2_CORE.md,
  SCIENTIFIC_DECISION_ONTOLOGY_V2_MODULES.md,
  SCIENTIFIC_DECISION_ONTOLOGY_V2_DECISIONS.md, this review.
- One test: tests/test_ontology_v2_core_5c.py.

## Required exit report

```text
WINDOW=01-Ontology-Core
CHECKPOINT=5C.1-Targeted-Core-Corrections
STATUS=PASS
N01_REQUIREMENT_MODEL=PASS
N02_REFERENCE_RESOURCE=PASS
N03_EFFECT_DESCRIPTION=PASS
N04_SCOPE_VALIDATION=PASS
N05_NEGATIVE_TESTS=PASS
F01_STATUS=RESOLVED (design-test scope; independent QA pending)
F04_STATUS=RESOLVED (design-test scope; independent QA pending)
CORE_OBJECT_TYPES=26
CORE_LINK_TYPES=23 (plus 2 derived projections)
PROPERTIES=74
QUALIFIERS=10
FOCUSED_TESTS=143 passed (118 current + 25 historical)
REGRESSION_TESTS=10 passed
CHAT_IMPORT=PASS
CHAT_RUNTIME=PASS
CHAT_RETRIEVAL=PASS
CHAT_PLANNER=PASS
SCIENTIFIC_KG_CHANGED=false
CATALOG_KG_CHANGED=false
RAG_CHANGED=false
PLANNER_CHANGED=false
PRODUCTION_ONTOLOGY_CHANGED=false
FILES_CHANGED=17; FILES_CREATED=0
PRIMARY_LIMITATION=Design-only helpers; independent QA and human acceptance pending; no production migration or adapter.
NEXT_RECOMMENDED_ACTION=STOP_FOR_QA_RECHECK
STOPPED=true
```
