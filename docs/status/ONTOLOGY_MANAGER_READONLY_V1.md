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
  edges; module and authority filters; clickable node/edge inspection; zero
  Scientific KG instance nodes loaded.

## Integrity boundary

`OntologyManagerReadOnlyService` verifies the exact 12 manifest-listed artifact
hashes before loading registries. Missing artifacts, hash mismatches, invalid
registry structures, version drift, and count inconsistencies fail closed. The
service exposes read projections only and has no edit, review, promotion, or KG
mutation API.

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

- 5D service/UI plus existing Scientific KG Admin and Candidate Studio:
  `37 passed`.
- Frozen ontology functional contracts compatible with an approved Admin
  extension: `131 passed, 12 deselected`.
- Research Chat ask/run and UI rerun smoke tests: `3 passed`.
- Python compilation and `git diff --check`: passed.

An exploratory run of the entire legacy 5C/hash and Research entrypoint set
reported `141 passed, 8 failed`. Six failures are legacy tree-hash assumptions:
five expect files absent from the base commit, while the protected-source case
rejects any intentional `app.py`/service addition. Two Research entrypoint
failures reproduce from unchanged code or a string already absent in base
`app.py`. No frozen manifest or protected subsystem was edited to mask these
baseline/incompatible checks.

## Current limitation

The schema graph is deliberately a design-level browser, not a production KG
viewer. Extension and deferred types have no core edges unless the frozen core
registry defines one. No Review Queue, ReviewDecision control, promotion,
candidate staging, migration, or mutation action exists in this checkpoint.

Next recommended action: `STOP_FOR_QA`.
