# Ontology Manager Read-only v1

## Status

Checkpoint 5D is implemented as a fifth `Ontology` section inside the existing
`Admin · Scientific KG` workspace. It is a read-only design browser. It does not
claim or perform production KG migration.

- Design state: `DESIGN FROZEN`
- Production migration: `NO`
- Authoritative source: `data/ontology/scientific_decision_ontology_v2_core/`
- Frozen artifacts regenerated: no
- Scientific KG, RAG, Planner, Research Chat, and Candidate Studio behavior changed: no

## Delivered views

- Ontology Overview: version, schema version, freeze commit, and frozen counts.
- Object Types: searchable/filterable active core, extension, and deferred types;
  fields, links, CQ support, and static v1 compatibility details.
- Link Types: core link registry with explicit `AUTHORITATIVE` versus
  `DERIVED PROJECTION` treatment and frozen evidence/qualifier policies.
- Properties & Qualifiers: separate searchable tables. `effect_description` is
  visibly marked `DISPLAY ONLY / NO MACHINE AUTHORITY`.
- Schema Graph: bounded to 41 active design object types and core link endpoint
  edges; module and authority filters; deterministic parallel curves for
  same-endpoint predicates; clickable node/edge inspection; zero Scientific KG
  instance nodes loaded.

## 5D.1 targeted safety and UX patch

- M01: all 11 manifest-listed JSON artifacts now enforce the same schema,
  ontology version, and design-only boundary after SHA-256 verification. The
  manifest additionally enforces the exact frozen 5C checkpoint boundary.
- M02: every public service projection is defensively deep-copied. Mutating
  returned object, link, property, qualifier, graph, overview, or integrity data
  cannot alter later reads or internal state.
- M03: extension/deferred display layers use explicit frozen layer information
  first, then a deterministic module category. Unknown modules display
  `UNDECLARED`; they never default to `scientific`.
- M04: same-endpoint links receive stable symmetric curve offsets and distinct
  DOM/selection identities. `consumes` and `produces` remain separately visible
  and inspectable.

## 5D.2 final migration-boundary closure

The frozen `v1_v2_mapping_draft.json` contract now requires both
`status=NON_EXECUTABLE_DRAFT` and an actual JSON boolean
`migration_implemented=false`. `true`, a missing field, string `"false"`, and
integer `0` all fail closed even if the manifest hash is recomputed to match the
tampered artifact. This validates the frozen design contract; it does not add a
migration mechanism or workflow.

## Integrity boundary

`OntologyManagerReadOnlyService` verifies the exact 12 manifest-listed artifact
hashes before loading registries, then validates all 11 JSON artifacts against
the frozen version/design boundary. Missing artifacts, hash mismatches, invalid
registry structures, version drift, and count inconsistencies fail closed. The
service exposes detached read projections only and has no edit, review,
promotion, or KG mutation API.

Frozen overview counts:

| Measure | Count |
| --- | ---: |
| Core object types | 26 |
| Authoritative links | 23 |
| Derived projections | 2 |
| Properties | 74 |
| Qualifiers | 10 |
| Extension object types | 7 |
| Deferred object types | 8 |

The source registries additionally preserve 17 extension items, 39
deferred/disposition items, and four compatibility concepts whose disposition is
`MERGE`; merged concepts are not presented as active v2 object types.

## Verification

- 5D.2 service/UI plus existing Scientific KG Admin and Candidate Studio:
  `49 passed`.
- Frozen ontology functional contracts compatible with an approved Admin
  extension: `131 passed, 12 deselected`.
- Research Chat ask/run and UI rerun smoke tests: `3 passed`.
- Python compilation and `git diff --check`: passed.

The earlier expanded legacy probe reported `141 passed, 8 failed`. Independent
QA classified seven as `PRE_EXISTING_BASELINE_FAILURE`, one as
`EXPECTED_AUTHORIZED_DIFF`, and zero as a real 5D regression. The authorized
diff is the old protected-source test rejecting the required `app.py` change and
new `ontology_manager.py`. The seven baseline failures cover already-missing
`.DS_Store`/legacy index files, the old protected-tree assumption, the existing
Research PLAN result, and the legacy AUTO-routing string already absent from the
base `app.py`. Old tests and frozen manifests were not edited to mask them.

## Current limitation

The schema graph is deliberately a design-level browser, not a production KG
viewer. Extension and deferred types have no core edges unless the frozen core
registry defines one. No Review Queue, ReviewDecision control, promotion,
candidate staging, migration, or mutation action exists in this checkpoint.

Next recommended action: `STOP_FOR_FINAL_QA`.
