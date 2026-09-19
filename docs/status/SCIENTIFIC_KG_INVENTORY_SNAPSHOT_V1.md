# Scientific KG Inventory & Ontology Audit — Snapshot v1

Checkpoint: `1`
Git HEAD: `0158c146eff697fdd9266bbeac7f00b0aef71b18`
Mode: read-only inventory; no identity merge, promotion, retrieval rebuild, or KG content change.

## Two substrates

| Substrate | Role | Nodes | Edges | Entity types | Relation types |
| --- | --- | ---: | ---: | ---: | ---: |
| Legacy Tool KG | discovery/catalog | 7537 | 17667 | 14 | 27 |
| Scientific KG | ontology-backed decision knowledge, four physical frozen layers | 1651 | 2429 | 21 | 33 |

The Scientific KG total is a physical-layer inventory. Overlapping identities remain separate until adjudicated identity mappings exist.

## Scientific semantic inventory

| Type | Physical records | Distinct IDs |
| --- | ---: | ---: |
| SoftwareProject | 38 | 22 |
| Package | 39 | 23 |
| PackageRelease | 26 | 20 |
| Operator | 69 | 59 |
| OperatorRevision | 69 | 64 |
| Method | 65 | 39 |
| MethodVariant | 23 | 15 |
| RepresentationType | 98 | 66 |
| RepresentationConstraint | 107 | 98 |
| ApplicabilityScope | 98 | 87 |
| AtomicClaimRevision | 380 | 353 |
| EvidenceSpan | 170 | 151 |
| SourceRevision | 6 | 5 |
| EvidenceAssessment | 380 | 353 |
| EvidenceGap | 77 | 77 |

Strict `SourceRevision` records: **6** physical / **5** distinct. Core also has **27** legacy Source records; these are reported separately.

## Governance

| State | Count |
| --- | ---: |
| Candidate claims | 380 |
| Reviewed claims | 0 |
| Trusted/canonical claims | 0 |
| Rejected claims | 0 |
| Superseded claims | 0 |
| Trusted source-evidence nodes | 119 |

Trusted source evidence describes provenance quality; it does not promote candidate scientific claims.

## Production readiness (UAT overlay only)

| Highest exclusive level | Operators |
| --- | ---: |
| L0 | 0 |
| L1 | 0 |
| L2 | 2 |
| L3 | 0 |
| L4 | 6 |

Broad candidate coverage is not production readiness. Of 8 UAT OperatorRevisions, 2 have no mapped direct evidence in the frozen RAG corpus.

## Integrity

Status: **PASS_WITH_DECLARED_WARNINGS**
Hard issues: **0**
Declared warning records: **43**

Warnings preserve evidence gaps rather than hiding them: deferred/reference layers contain referenced span IDs without a materialized span in that layer, and some materialized spans are not referenced by an assessment.

## Current limitations

- Counts span four frozen layers and therefore are physical coverage counts, not a canonical deduplicated KG size.
- L0–L4 is recomputed only for the production UAT direct-evidence overlay.
- Core legacy Source records and publication/repository references do not satisfy the strict SourceRevision ontology type.
- Candidate claims have not undergone review or canonical promotion.

## Exit report

```text
CHECKPOINT=1
STATUS=PASS
CHANGED_FILES=eval/scientific_kg_inventory_snapshot_v1.py; tests/test_scientific_kg_inventory_snapshot_v1.py; docs/status/SCIENTIFIC_KG_INVENTORY_SNAPSHOT_V1.md; data/evaluation/scientific_kg_inventory_snapshot_v1/*
FOCUSED_TESTS=5 passed in 0.63s
REGRESSION_TESTS=66 passed, 1 historical stale-hash preflight deselected in 7.31s
REAL_RUN=python -m eval.scientific_kg_inventory_snapshot_v1 --write
ARTIFACT_INTEGRITY=PASS
PRIMARY_RESULT=Scientific KG 1651 nodes/2429 edges physical; 380 candidate claims; UAT L4=6/8
CURRENT_LIMITATION=no cross-layer identity merge; readiness limited to production UAT overlay
NEXT_EARLIEST_DIVERGENCE=Checkpoint 2 scKG-Eval Specification v1 (not started)
CORPUS_CHANGED=false
KG_CONTENT_CHANGED=false
PLANNER_CHANGED=false
GOLD_CHANGED=false
CANONICAL_PROMOTION=false
LOCAL_HEAD=0158c146eff697fdd9266bbeac7f00b0aef71b18
REMOTE_HEAD=0158c146eff697fdd9266bbeac7f00b0aef71b18
PUSH_STATUS=NOT_REQUESTED_FOR_CHECKPOINT_1
STOPPED=true
```
