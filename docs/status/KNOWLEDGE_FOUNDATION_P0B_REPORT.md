# Knowledge Foundation P0B — Core Scientific Knowledge Deepening

Status: `PASS_WITH_REMAINING_GAPS`

Baseline: Knowledge Foundation Audit v1 plus P0A freeze at `4e046fa5dbc2107e6831b7b01a593ba4532c4caa`.

## Scope and boundary

P0B deepens candidate scientific identity and governance records without changing the canonical KG, retrieval indexes, production Planner, ToolContract, RepresentationLedger, benchmark gold, or execution policy. It does not promote candidate knowledge.

The central finding is deliberately conservative: the repository already has broad candidate Method/Operator/Port/Claim coverage, but that is not the same as a production planning path. P0B therefore does not relabel candidate depth as `planning_ready`.

## Workstream A — source/version hardening

All 17 canonical software-document records were audited.

| Measure | Result |
| --- | ---: |
| software documents audited | 17 |
| local text snapshots with matching SHA-256 | 16 |
| metadata-only document with no local content | 1 |
| exact upstream release + local-content bindings proven | 0 |
| version bindings still unresolved | 17 |
| ecosystems with a separate pinned authoritative revision | 4 |

The local text hashes provide immutable identity for the captured content. They do **not** prove that a mutable GitHub default branch, `stable`, `latest`, Bioconductor `release`, or package homepage corresponds to the package version declared by the Core candidate. Scanpy, Harmony, Scrublet and SingleR do have separate pinned authoritative source revisions in the accepted UAT candidate (commit/tag or release artifact digest plus bounded source-file hashes). Version-sensitive claims may use those exact revision-bound spans, but this does not retroactively make the mutable canonical document snapshot version-bound.

This closes the integrity ambiguity without manufacturing release identity. Version-sensitive scientific use must remain unknown until a tagged/revisioned upstream artifact is bound to the captured content.

Artifact: `data/evaluation/knowledge_foundation_p0b/source_revision_hardening.jsonl`.

## Workstream B — ReferenceArtifact boundaries

Six v1.1-conformant candidate `ReferenceArtifact` family identities were introduced:

- CellTypist classifier model family;
- SingleR reference atlas family;
- SingleR reference label-mapping family;
- SingleR query/reference feature-mapping family;
- pySCENIC transcription-factor list family;
- pySCENIC motif-annotation family.

No `ReferenceArtifactRevision` was created because no exact resource version plus content digest is locally established. The unresolved revision fields are explicit and applicability remains `clarify_or_block`.

The frozen v1.1 artifact-kind vocabulary also lacks a precise kind for a motif-ranking database. P0B records that as a schema-implementation/evidence gap instead of misclassifying the resource. The frozen v1.1 architecture was not redesigned.

Runtime file paths and concrete instance alignment remain ToolContract/runtime responsibilities. Scientific identity fields include version, species, feature namespace, genome assembly, label space or biological context where applicable.

Artifacts:

- `reference_artifact_candidates.jsonl`
- `reference_artifact_requirements.json`

## Workstream C — core planning semantics

The frozen Core candidate already contains:

- 14 software projects/packages/releases;
- 44 Operators and 44 OperatorRevisions;
- canonical InputPort/OutputPort structures;
- 236 AtomicClaimRevisions with source-bound candidate assessments;
- 87 EvidenceSpans;
- explicit scope, representation and risk records.

P0B did not duplicate these records. It adds the missing reference-family boundary and source/version integrity layer around the highest-risk reference-dependent paths.

`core_semantic_closure.json` resolves every one of the 44 OperatorRevisions through its PackageRelease, Methods, canonical ports, representation types/constraints, ApplicabilityScope, AtomicClaimRevisions, EvidenceSpans and Source IDs. Its 14 ecosystem summaries preserve the real claim/evidence denominators; for example Scanpy has 9 revisions/44 operator claims/16 spans, while CellTypist and SingleR each have one operator revision and unresolved reference revisions. This artifact is an audit projection of existing candidate knowledge, not a second KG.

Strict production readiness remains unchanged:

| Readiness | Before | After P0B |
| --- | ---: | ---: |
| authoritative evidence ready | 13/14 | 13/14 |
| planning ready | 3/14 | 3/14 |
| retrieval-only primary state | 6/14 | 6/14 |
| candidate-only primary state | 3/14 | 3/14 |
| not-ready primary state | 2/14 | 2/14 |
| execution ready | 2/14 | 2/14 |

The three planning-ready ecosystems remain Scanpy, Harmony and Scrublet. Moving additional paths to planning-ready would require production Capability Pack, ToolContract and Planner integration, which is outside this knowledge-only checkpoint.

Artifact: `core_tool_coverage_after.json`.

## Workstream D — bounded compatibility closure

Only the three midterm dependency closures named by the P0B contract were packaged for review:

1. Harmony corrected embedding → Scanpy neighbors: existing claim-scoped candidate proof, review pending, cross-version execution binding unknown.
2. Scanpy neighbor graph → Leiden: existing claim-scoped candidate proof, review pending.
3. scVelo transition/velocity state → CellRank: no relation constructed; evidence/compatibility gap retained.

The first two packets require source-bound support, port-semantic compatibility, observation identity, lineage, semantic parameter compatibility and staleness checks. Neither is actionable because neither has an accepted review decision. The third remains absent rather than being inferred from type equality.

The 66 legacy/core candidate `CAN_FEED` relations remain non-actionable. P0B accepts zero relations and introduces no implicit workflow edge.

Artifact: `compatibility_review_packets.jsonl`.

## Safety and governance results

| Gate | Result |
| --- | --- |
| all 17 software documents audited | PASS |
| local content integrity represented truthfully | PASS |
| mutable source claimed immutable | 0 |
| fabricated ReferenceArtifactRevision | 0 |
| actionable unreviewed CAN_FEED | 0 |
| candidate-to-trusted leakage | 0 |
| canonical promotion | none |
| canonical KG modified | no |
| retrieval index rebuilt | no |
| production behavior modified | no |

## Remaining gaps

### P0 — source revision binding

Seventeen canonical software documents still lack a proven exact binding from the captured content to an immutable upstream software release. Content integrity is known; release identity is not.

### P0 — exact reference revisions

CellTypist, SingleR and pySCENIC now have explicit artifact-family identities, but exact revisions/digests remain unresolved. This is contained by `clarify_or_block` and candidate-only status.

### P1 — production Planner consumption

Eleven of fourteen ecosystems remain outside the production Planner applicability path. This is not repaired by adding candidate graph records.

### P1 — scVelo to CellRank compatibility

The cross-tool transition-state compatibility proof is not constructed. No edge is emitted.

## Decision

`KNOWLEDGE_FOUNDATION_P0B = PASS_WITH_REMAINING_GAPS`

P0B succeeds as a governance and semantic-boundary checkpoint: it makes unknown source versions and reference revisions explicit, packages only necessary compatibility closures, and preserves non-actionability. It does not meet the aspirational `planning_ready >= 8/14` target and must not be presented as doing so.

The next checkpoint, if authorized separately, should resolve exact tagged SourceRevision/SourceArtifact bindings for the midterm paths. Dense retrieval restoration, retrieval benchmarking, Seed v1 and real-data benchmarking remain out of scope.
