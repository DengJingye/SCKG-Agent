# Knowledge Foundation Audit v1

**Audit baseline:** `feature/method-kg-expansion-v1@08c1850640226864a102f719f90535d470b621f1`
**Audit date:** 2026-09-18
**Mode:** read-only inventory and attribution
**Seed state:** `MIDTERM_CORE_SEED_V0_FROZEN = YES`

This audit does not modify knowledge, sources, indexes, Planner behavior, ToolContracts or benchmark gold. It does not promote claims, construct Seed v1, run the Midterm benchmark or create a formal holdout.

## Executive decision

```text
KNOWLEDGE_FOUNDATION_AUDIT = PASS_WITH_P0_GAPS

midterm_core_paths_ready       = 3 / 14
authoritative_evidence_ready   = 13 / 14
planning_ready                 = 3 / 14
retrieval_only                 = 6 / 14
execution_ready                = 2 / 14
```

The foundation is sufficiently inspectable and governed to support the frozen Seed v0 and a bounded Midterm evaluation. It is **not** accurate to claim that all 14 core ecosystems are production capabilities. The current production Agent consumes bounded Scientific KG applicability for Scanpy, Harmony and Scrublet. Most other v1 Core ecosystems are candidate knowledge or retrieval-only.

The P0 gaps do not invalidate the frozen Seed v0, because its scientific gold is independently reviewed and must not be derived from the current KG/RAG output. They do block broad claims of dense retrieval readiness, version-consistent scientific execution and trusted cross-tool compatibility.

## Audit method and boundaries

The following layers were counted and judged separately:

| Layer | Current role | What existence proves | What it does not prove |
| --- | --- | --- | --- |
| A. `knowledge_graph_v2` / catalog graph | Canonical discovery graph | catalogue identity, metadata connectivity and bounded governed paths | v1.1 Method/Operator semantics or scientific applicability |
| B. Scientific KG candidates | Versioned candidate Method/Operator/Port/Claim records | schema-conformant candidate scientific semantics and evidence linkage | promotion, universal truth or production consumption |
| C. Evidence RAG + catalog RAG | Production retrieval corpus | source/chunk recall and governed retrieval status | decision support unless a chunk directly supports the emitted claim |
| D. ToolContract + Planner | Production planning/execution boundary | actual contract/ledger/planner consumption | coverage merely because a KG node exists |

The audit used manifests and immutable JSON/JSONL snapshots already in the repository. It did not call a provider, crawl sources, rebuild indexes or execute a benchmark.

## A. Legacy catalog graph

`knowledge_graph_v2` contains **7,537 nodes** and **17,667 edges**, including **1,839 Tool nodes**, 2,896 Publication nodes and 2,630 SourceChunk nodes. This is primarily a catalogue/discovery graph:

- source-bound semantic coverage: **0.87%**;
- contract-qualified coverage: **0.22%**;
- formal evidence coverage: **0%**;
- execution-verified tools reported by the graph: **4**;
- promoted Scientific KG v1.1 claims: **0**.

The catalogue is useful for recall, but its node count must not be presented as 1,839 verified scientific capabilities. The catalog snapshot has 1,847 chunks while the graph has 1,839 canonical Tool nodes, an eight-record projection difference that is not explained by the catalog count alone.

## B. Scientific KG candidate inventory

The consolidated candidate view contains **1,651 physical nodes** and **2,429 physical edges** across overlapping frozen layers. No cross-layer identity merge was performed.

| Candidate layer | Claims | Derived relations | Evidence spans/references | Gaps | Status |
| --- | ---: | ---: | ---: | ---: | --- |
| Corrected UAT decision slice | 25 | 29 | 32 | 0 | candidate, production-consumed only through bounded bindings |
| Scientific KG v1 Core | 236 | 171 | 87 | 5 | candidate pending risk review |
| Broad content expansion | 92 | 38 | 32 | 72 | deferred candidate |
| Earlier Scanpy reference slice | 27 | 18 | 19 | 0 | deferred/superseded reference |

The v1 Core has 14 packages, 26 Methods, 44 OperatorRevisions, 61 RepresentationConstraints, 42 RepresentationTypes, 236 AtomicClaimRevisions, 236 EvidenceAssessments and 407 risk records. Structural checks pass, but all scientific claims and derived relations remain candidate-only.

### Core ecosystem state

| Ecosystem | Candidate depth | Evidence | ToolContract | Planner consumption | Strict readiness |
| --- | --- | --- | --- | --- | --- |
| Scanpy | 9 methods / 9 operators | ready | 1.11.2, integration-passed, execution disabled | direct Capability Pack + bounded KG applicability | planning-ready |
| Seurat | 6 / 6 | ready | missing | none | retrieval-only |
| Harmony | 1 / 1 | ready | 2.0.0 enabled | embedding→neighbors KG binding | planning-ready; version P0 |
| scvi-tools | 2 / 6 | ready | missing | none | retrieval-only |
| Scrublet | 1 / 1 | ready | 0.2.3 enabled | raw-UMI applicability in real planner | planning-ready |
| SoupX | 2 / 2 | blocking core evidence gap | missing | none | retrieval-only/not ready |
| CellTypist | 1 / 1 | ready | planning-only, execution disabled | contract planning gate, not KG | not ready |
| SingleR | 1 / 1 | ready | 2.14.0 planning-only | contract planning gate, not KG | not ready; version/reference P0 |
| edgeR | 1 / 4 | ready in candidate | missing | none | candidate-only |
| Slingshot | 1 / 1 | ready in candidate | missing | none | candidate-only |
| scVelo | 1 / 3 | ready | missing | RAG only | retrieval-only |
| CellRank | 2 / 3 | ready | missing | RAG only | retrieval-only |
| MOFA2 | 1 / 3 | ready; optional output gap | missing | RAG only | retrieval-only |
| pySCENIC | 3 / 3 | ready in candidate | missing | none | candidate-only; reference P0 |

“Evidence ready” means bounded source-backed evidence exists for the candidate decision slice; it does not mean reviewed/trusted promotion or execution qualification. SoupX is the one core path not counted because the frozen core retains a scientific input-semantics gap. The later governed acquisition/deposition pilot is still `candidate_pending_review` and is not silently merged into the core.

## C. RAG corpus inventory

### Counts

| Metric | Count |
| --- | ---: |
| SourceDocument records | 37 |
| Source text available | 33 |
| Evidence chunks | 783 |
| Catalog chunks | 1,847 |
| Dense vectors declared by manifest | 773 |
| Dense vectors actually materialized in JSONL | 0 |
| Runtime dense `.npy` / metadata pair | absent |
| Exact duplicate evidence rows | 2 in one group |
| Explicit stale/deprecated records | 0 |
| Unversioned software-document records | 17 |

The dense count is a manifest/artifact inconsistency. The production retrieval service can observe missing dense files and fall back to SQLite FTS5, but the manifest must not be used as evidence that dense retrieval is available.

### Source mix

| Source class | Records | Ratio |
| --- | ---: | ---: |
| Official project docs, including README | 17 | 45.9% |
| GitHub README | 16 | 43.2% |
| Official non-README documentation | 1 | 2.7% |
| Publications | 14 | 37.8% |
| Benchmarks | 6 | 16.2% |
| Usable source text | 33 | 89.2% |
| Authoritative identity, excluding quarantined mismatch | 36 | 97.3% |

None of the 17 software-document SourceDocument records is pinned to an immutable release/tag/commit. “No explicit stale record” therefore does **not** mean the documents are current for each frozen ToolContract.

### Claim mix

| Claim type | Chunks |
| --- | ---: |
| general | 344 |
| parameter | 140 |
| output | 104 |
| failure_mode | 56 |
| metric | 54 |
| input_requirement | 49 |
| workflow | 36 |

General claims are **344/783 (43.9%)**. They are useful for discovery but insufficient by themselves for operator applicability.

### Task imbalance

The corpus is concentrated in RNA velocity (221), batch integration (135), spatial mapping (96), annotation (89) and doublet detection (81). It is sparse for ambient RNA (1), GRN (1) and multimodal integration (6). edgeR, Slingshot and pySCENIC have zero direct tool chunks; SoupX has 2 and MOFA2 3.

This imbalance means that a global retrieval score cannot be interpreted as comparable scientific coverage across tasks.

### Governance state

- 743 chunks are `source_validated_retrieval_only`.
- 40 are `formal_frozen_retrieval_only`.
- 773/783 are source-bound.
- 10 benchmark chunks are `source_bound=false` despite `trusted_core` labels.
- all 1,847 catalog chunks are metadata-only and cannot support recommendation or execution.
- the CellTypist/SingleR benchmark source is correctly quarantined because the available candidate PDF is an unrelated PanomiR work.

## D. Production consumption

Production use was counted only when code reads the layer during a real request/planning path.

| Path | KG applicability | RAG evidence | ToolContract | RepresentationLedger | Planner |
| --- | --- | --- | --- | --- | --- |
| Scanpy Core | yes, bounded actions | yes | yes | yes | yes |
| Harmony integration/reuse | yes, corrected embedding→neighbors | yes | yes | yes | delegated through Scanpy pack |
| Scrublet applicability | yes, raw-UMI gate | yes | yes | yes | delegated through Scanpy pack |
| CellTypist | no | yes | planning gate | profile/annotation state | annotation service, not KG Planner |
| SingleR | no | yes | planning gate | profile/annotation state | annotation service, not KG Planner |
| Seurat/scvi-tools/scVelo/CellRank/MOFA2 | no | yes | no | no task-specific binding | no |
| SoupX | no | weak canonical RAG plus isolated candidate pilot | no | no | no |
| edgeR/Slingshot/pySCENIC | no | no direct core-tool chunks | no | no | no |

`ScientificKGApplicability` has three production action bindings: Scanpy Leiden, Scanpy neighbors using integrated representations, and the generic Scanpy doublet action governed by Scrublet requirements. The four previously validated scenarios arise from these three bindings. Candidate knowledge outside them retains legacy production behavior.

Strict `execution_ready=2/14` counts Harmony and Scrublet, whose ToolContracts are enabled and integration-passed. Scanpy notebook compilation/runtime has been product-validated, but its ToolContract explicitly has `enabled_for_execution=false`; it is therefore not counted as execution-ready here. ExecutionPolicy remains a separate authorization boundary.

## Task-family coverage

| Task family | RAG | Scientific KG | Production path | Readiness |
| --- | --- | --- | --- | --- |
| QC/filtering | partial | Scanpy + Seurat | Scanpy | planning-ready |
| normalization/log | partial | Scanpy + Seurat | Scanpy | planning-ready |
| HVG | no dedicated tag | corrected flavor semantics | Scanpy | planning-ready, RAG shallow |
| PCA/dimensionality reduction | no dedicated tag | corrected generic/profile split | Scanpy | planning-ready |
| neighbors | broad clustering tag | X/PCA/Harmony alternatives | Scanpy/Harmony | planning-ready, version P0 |
| clustering | 43 | Leiden/FindClusters | Scanpy | planning-ready |
| UMAP | no dedicated tag | neighbor-graph input | Scanpy | planning-ready |
| marker analysis | 28 DE-proxy chunks | marker operators | Scanpy | marker-ready, not pseudobulk |
| differential/pseudobulk | 28; edgeR 0 direct | edgeR candidate | none | candidate-only |
| annotation | 89 | CellTypist/SingleR candidate | contract gates only | not ready |
| batch integration | 135 | Harmony/Seurat/scvi-tools | bounded Harmony | planning-ready |
| doublet detection | 81 | Scrublet | Scrublet | planning-ready |
| ambient RNA | 1 | SoupX with gap | none | not ready |
| trajectory/pseudotime | 35; Slingshot 0 direct | Slingshot candidate | none | candidate-only |
| RNA velocity | 221 | scVelo candidate | RAG only | retrieval-only |
| fate mapping | conflated tags | CellRank candidate | RAG only | retrieval-only |
| multimodal integration | 6 | scvi-tools/MOFA2 candidate | none | retrieval/candidate only |
| GRN | 1; pySCENIC 0 direct | pySCENIC candidate with reference gaps | none | candidate-only |

Full row-level detail is in `task_coverage_matrix.json`.

## RAG quality risks

1. **Dense manifest drift (P0).** Declared 773 vectors versus no loadable dense index.
2. **Unresolvable formal evidence (P0).** Ten benchmark chunks are not source-bound.
3. **Version mismatch risk (P0).** Every canonical software-document source is moving/unpinned.
4. **Known wrong-source candidate (P0, contained).** CellTypist/SingleR benchmark PDF mismatch is quarantined.
5. **Overview dominance (P1).** General chunks are 43.9%; direct inputs and workflows are much smaller.
6. **README dependence.** Sixteen of 17 official-document sources are README records; README evidence often proves identity/usage but not complete operator semantics.
7. **Overly broad/task-ambiguous chunks.** Foundational Scanpy tasks lack dedicated task tags.
8. **Duplicate chunks.** One normalized duplicate group adds two redundant rows.
9. **Unsupported recommendation eligibility.** Catalog chunks and the 10 unbound benchmark chunks cannot establish recommendation eligibility.

## Scientific KG semantic risks

1. **Method/operator granularity is correct in v1 Core but not in the legacy graph.** Legacy Tool nodes must not be treated as peer Methods/Operators.
2. **ReferenceArtifact identity is missing (P0).** CellTypist, SingleR and pySCENIC cannot safely resolve reference-dependent applicability from matrices alone.
3. **Version identities conflict (P0).** Harmony 2.0.5 candidate vs 2.0.0 contract; SingleR 2.14.1 candidate vs 2.14.0 contract.
4. **Unsafe compatibility projection (P0 for promotion).** Sixty-six core `CAN_FEED` records predate the corrected UAT proof model and must not be trusted from representation-type equality.
5. **Scope correctness is not established by schema validity.** All core claims and relations await risk-appropriate review.
6. **Representation over-merging remains possible.** `expression_matrix` and `cell_embedding` do not prove value state, modality composition, sample alignment or lineage.
7. **Scientific requirement versus API contract must remain separate.** Candidate claims cannot overwrite ToolContract execution-critical fields.
8. **Study-design/sample-unit constraints are high risk.** edgeR must preserve donor/sample/replicate/design semantics; cell-level marker tests are not pseudobulk DE.
9. **Runtime facts must stay outside scientific claims.** Actual model artifacts and sample alignment belong to runtime registries/RepresentationLedger.
10. **Partial source support is not full support.** `source_bound=true` and generated alignment fields are not substitutes for independent claim-level review.

## Priority register

| Priority | Count | Interpretation |
| --- | ---: | --- |
| P0 | 9 | retrieval integrity, source binding, version/reference identity, unsafe compatibility or scope/promotion boundary |
| P1 | 8 | insufficient Midterm Core depth or production integration |
| P2 | 2 | useful comparative/interpretation expansion |
| P3 | 1 | broad catalog breadth |

The audit does **not** recommend filling every absent field. Before the Midterm benchmark, priority should be limited to preserving gold independence and ensuring that P0 items cannot silently count as supported retrieval, trusted compatibility or version-consistent execution. Broader KG expansion is not required by this checkpoint.

## Machine-readable artifacts

- `data/evaluation/knowledge_foundation_audit_v1/rag_inventory.json`
- `data/evaluation/knowledge_foundation_audit_v1/scientific_kg_inventory.json`
- `data/evaluation/knowledge_foundation_audit_v1/core_tool_coverage.json`
- `data/evaluation/knowledge_foundation_audit_v1/task_coverage_matrix.json`
- `data/evaluation/knowledge_foundation_audit_v1/gap_register.json`

## Final decision

```text
KNOWLEDGE_FOUNDATION_AUDIT = PASS_WITH_P0_GAPS

midterm_core_paths_ready = 3 / 14
authoritative_evidence_ready = 13 / 14
planning_ready = 3 / 14
retrieval_only = 6 / 14
execution_ready = 2 / 14
```

Stop condition reached. No gaps were repaired.
