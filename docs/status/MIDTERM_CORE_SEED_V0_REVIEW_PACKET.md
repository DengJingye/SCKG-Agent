# Midterm Core Seed v0 — Human Review Packet

> Status: project-owner manual benchmark adjudication approved. This is not independent external expert review. No benchmark was run.

## 1. Development-seed identity

| Field | Value |
|---|---|
| Seed manifest | `eval_v2/manifests/midterm_core_seed_v0.json` |
| Manifest SHA-256 | `ad3e8c1012d116cb0ecf0bdd6affd7b8eb433d4ea6051a4ad8af61346de95db5` |
| Evaluation contract SHA-256 | `c5417679a43ebf89495101504c2532cd85dbfde203968febc0fb825fcf46fb5f` |
| Gold origin | `independent_source_adjudication_draft` |
| Gold status | `project_owner_reviewed`; `human_review_complete=true` |
| Split | development only; formal holdout not constructed |
| Counts | 9 parents; 12 WorkflowGold; 12 RequirementGold; 26 EvidenceGold; 55 nested records |

Project-owner adjudication: `APPROVE` on `2026-09-17`. Reason: Scientific question, workflow constraints, evidence scope, version and ownership boundaries were manually reviewed and accepted.

## 2. Parent-scenario review summaries

### 2.1 `scenario:v2.1:neighbor-graph-reuse-leiden`

- **Scientific question:** When may Leiden reuse an existing neighbor graph, and when must reuse be rejected?
- **Task family:** `clustering`
- **Why it exists:** state-aware planning; representation reuse; safe block; workflow equivalence.
- **Origin:** HISTORICAL_ANCHOR; study `study:pbmc3k-anchor`; dataset `dataset:pbmc3k-processed`; source group `scanpy-1.11.2`.
- **Review risks:** `POSSIBLE_SUT_GOLD_COUPLING`.

**WorkflowGold**

- `workflow-gold:v2.1:neighbor-graph-reuse-leiden-valid`
  - required final states: `cluster_labels`
  - required prerequisites: `current_observation_aligned_neighbor_graph`
  - forbidden operations: `scanpy_core.pca_scaled`, `scanpy_core.neighbors`
  - optional operations: `scanpy_core.umap`
  - allowed alternatives: `clustering -> scanpy_core.leiden`
  - terminal states: `completed`, `plan_only`

- `workflow-gold:v2.1:neighbor-graph-reuse-leiden-stale`
  - required final states: `no_invalid_cluster_plan`
  - required prerequisites: —
  - forbidden operations: `reuse_stale_neighbor_graph`, `reuse_misaligned_neighbor_graph`
  - optional operations: `rebuild_compatible_neighbor_graph`
  - allowed alternatives: —
  - terminal states: `blocked`, `clarification_required`

**RequirementGold**

| Requirement set / requirement | State | Action | Criticality | Resolution | Draft rationale |
|---|---|---|---|---|---|
| `requirement-gold-set:v2.1:neighbor-graph-reuse-leiden-valid` / `requirement-gold:neighbor-graph-reuse-leiden:graph-present` | `SATISFIED` | `ALLOW` | `hard` | `none` | A compatible graph is registered. |
| `requirement-gold-set:v2.1:neighbor-graph-reuse-leiden-valid` / `requirement-gold:neighbor-graph-reuse-leiden:observation-alignment` | `SATISFIED` | `ALLOW` | `hard` | `none` | Observation identity matches. |
| `requirement-gold-set:v2.1:neighbor-graph-reuse-leiden-valid` / `requirement-gold:neighbor-graph-reuse-leiden:freshness` | `SATISFIED` | `ALLOW` | `hard` | `none` | The graph is current. |
| `requirement-gold-set:v2.1:neighbor-graph-reuse-leiden-stale` / `requirement-gold:neighbor-graph-reuse-leiden:graph-present` | `SATISFIED` | `BLOCK` | `hard` | `none` | A graph record exists. |
| `requirement-gold-set:v2.1:neighbor-graph-reuse-leiden-stale` / `requirement-gold:neighbor-graph-reuse-leiden:observation-alignment` | `VIOLATED` | `BLOCK` | `hard` | `select_other` | Observation identity is mismatched. |
| `requirement-gold-set:v2.1:neighbor-graph-reuse-leiden-stale` / `requirement-gold:neighbor-graph-reuse-leiden:freshness` | `VIOLATED` | `BLOCK` | `hard` | `select_other` | The graph is stale. |

**EvidenceGold / exact independent provenance**

| EvidenceGold | Proposition | Owner | Scope/version | Provenance | EvidenceGap |
|---|---|---|---|---|---|
| `evidence-gold:v2.1:neighbor-graph-reuse-leiden:leiden-input` | Leiden may consume a neighbor graph or an explicit adjacency matrix. | `ScientificKG` | Scanpy 1.11.2 Leiden / `1.11.2` | `scanpy-authoritative-span:leiden.input:1.11.2`; source `source-work unresolved in span artifact`; revision `source-revision:github:scverse/scanpy:5400eb87ef7d4e9f6f5a9256d98a7927723456fa`; locator `src/scanpy/tools/_leiden.py#L72-L99`; wording: Sparse adjacency matrix of the graph, defaults to neighbors connectivities. | — |
| `evidence-gold:v2.1:neighbor-graph-reuse-leiden:graph-current` | The registered graph is current. | `RepresentationLedger` | current dataset instance / `runtime` | runtime/non-scientific: citation abstention | — |
| `evidence-gold:v2.1:neighbor-graph-reuse-leiden:graph-stale` | The registered graph is stale. | `RepresentationLedger` | current dataset instance / `runtime` | runtime/non-scientific: citation abstention | — |
| `evidence-gold:v2.1:neighbor-graph-reuse-leiden:graph-misaligned` | Graph observation identity differs from the current dataset. | `RepresentationLedger` | current dataset instance / `runtime` | runtime/non-scientific: citation abstention | — |

**Nested records / baselines / denominators**

| Track | Record | Gold | Baselines | Denominator | Included / reason |
|---|---|---|---|---|---|
| `G0` | `record:v2.1:g0:neighbor-graph-reuse-leiden` | `semantic-gold:v2.1:neighbor-graph-reuse-leiden` | `B0`, `B3` | `denominator:G0:development-parent` | `true` |
| `T1` | `record:v2.1:t1:neighbor-graph-valid` | `workflow-gold:v2.1:neighbor-graph-reuse-leiden-valid` | `B2`, `B3` | `denominator:T1:development-parent` | `true` |
| `T1` | `record:v2.1:t1:neighbor-graph-stale` | `workflow-gold:v2.1:neighbor-graph-reuse-leiden-stale` | `B2`, `B3` | `denominator:T1:development-parent` | `true` |
| `T2` | `record:v2.1:t2:neighbor-graph-valid` | `requirement-gold-set:v2.1:neighbor-graph-reuse-leiden-valid` | `B1`, `B2`, `B3` | `denominator:T2:development-parent` | `true` |
| `T2` | `record:v2.1:t2:neighbor-graph-stale` | `requirement-gold-set:v2.1:neighbor-graph-reuse-leiden-stale` | `B1`, `B2`, `B3` | `denominator:T2:development-parent` | `true` |
| `T3` | `record:v2.1:t3:neighbor-graph-reuse` | `decision:v2.1:neighbor-graph-reuse` | `B2`, `B3` | `denominator:T3:development-parent` | `true` |
| `T4` | `record:v2.1:t4:pbmc3k-processed-reuse` | `path:pbmc3k:processed-reuse` | `B2`, `B3` | `denominator:T4:development-parent` | `true` |
| `T8` | `record:v2.1:t8:wrong-source-binding` | `mutation:v2.1:wrong-source-binding` | `B3` | `denominator:T8:development-parent` | `true` |
| `T8` | `record:v2.1:t8:missing-representation-link` | `mutation:v2.1:missing-representation-link` | `B3` | `denominator:T8:development-parent` | `true` |
| `T8` | `record:v2.1:t8:invalid-graph-reuse` | `mutation:v2.1:invalid-graph-reuse` | `B3` | `denominator:T8:development-parent` | `true` |

**Mutations**
- `mutation:v2.1:wrong-source-binding` -> `CLAIM_SOURCE_BINDING_MISMATCH`; parent `record:v2.1:t3:neighbor-graph-reuse`.
- `mutation:v2.1:missing-representation-link` -> `REPRESENTATION_LINK_MISSING`; parent `record:v2.1:t3:neighbor-graph-reuse`.
- `mutation:v2.1:invalid-graph-reuse` -> `BEHAVIOR_MUTATED`; parent `record:v2.1:t1:neighbor-graph-stale`.

### 2.2 `scenario:v2.1:harmony-embedding-neighbors`

- **Scientific question:** Can neighbors consume a compatible Harmony-corrected embedding without forcing PCA?
- **Task family:** `batch_integration`
- **Why it exists:** state-aware planning; method compatibility; evidence fidelity.
- **Origin:** HISTORICAL_ANCHOR; study `study:pbmc3k-anchor`; dataset `dataset:pbmc3k-harmony-state`; source group `harmony-2.0.5`.
- **Review risks:** `MULTIPLE_VALID_WORKFLOWS`, `POSSIBLE_SUT_GOLD_COUPLING`.

**WorkflowGold**

- `workflow-gold:v2.1:harmony-embedding-neighbors`
  - required final states: `neighbor_graph`
  - required prerequisites: `current_observation_aligned_harmony_embedding`
  - forbidden operations: `force_pca_before_neighbors`
  - optional operations: `scanpy_core.umap`, `scanpy_core.leiden`
  - allowed alternatives: `neighbors -> scanpy_core.neighbors`
  - terminal states: `completed`, `plan_only`

**RequirementGold**

| Requirement set / requirement | State | Action | Criticality | Resolution | Draft rationale |
|---|---|---|---|---|---|
| `requirement-gold-set:v2.1:harmony-embedding-neighbors` / `requirement-gold:harmony-embedding-neighbors:embedding-present` | `SATISFIED` | `ALLOW` | `hard` | `none` | Harmony coordinates are registered. |
| `requirement-gold-set:v2.1:harmony-embedding-neighbors` / `requirement-gold:harmony-embedding-neighbors:observation-alignment` | `SATISFIED` | `ALLOW` | `hard` | `none` | Rows match current observations. |
| `requirement-gold-set:v2.1:harmony-embedding-neighbors` / `requirement-gold:harmony-embedding-neighbors:embedding-semantics` | `SATISFIED` | `ALLOW` | `hard` | `none` | Compatibility is a composition inference from Harmony producing corrected embeddings and Scanpy neighbors accepting a selected obsm representation; it is not a direct Harmony-to-Scanpy claim. |
| `requirement-gold-set:v2.1:harmony-embedding-neighbors` / `requirement-gold:harmony-embedding-neighbors:pca-present` | `NOT_APPLICABLE` | `ALLOW` | `soft` | `none` | PCA is not mandatory when a compatible named embedding is supplied. |

**EvidenceGold / exact independent provenance**

| EvidenceGold | Proposition | Owner | Scope/version | Provenance | EvidenceGap |
|---|---|---|---|---|---|
| `evidence-gold:v2.1:harmony-embedding-neighbors:harmony-input` | Harmony accepts matrix-like cell embeddings with batch covariates. | `ScientificKG` | Harmony 2.0.5 / `2.0.5` | `uat-authoritative-span:harmony.generic_input`; source `source-work unresolved in span artifact`; revision `source-revision:cran:harmony:2.0.5`; locator `harmony/R/ui.R#L3-L15`; wording: Use this generic with a cell embeddings matrix, a metadata table and a categorical covariate to run the Harmony algorithm directly on cell embedding matrix. | — |
| `evidence-gold:v2.1:harmony-embedding-neighbors:harmony-output` | Harmony returns corrected cell embeddings. | `ScientificKG` | Harmony 2.0.5 / `2.0.5` | `uat-authoritative-span:harmony.output`; source `source-work unresolved in span artifact`; revision `source-revision:cran:harmony:2.0.5`; locator `harmony/R/ui.R#L51-L62`; wording: Whether to return the Harmony object or only the corrected PCA embeddings. By default, matrix with corrected PCA embeddings. If return_object is TRUE, returns the full Harmony object (R6 reference class type). | — |
| `evidence-gold:v2.1:harmony-embedding-neighbors:neighbors-input` | Scanpy neighbors can use a selected representation from obsm. | `ScientificKG` | Scanpy 1.11.2 neighbors / `1.11.2` | `scanpy-authoritative-span:neighbors.input:1.11.2`; source `source-work unresolved in span artifact`; revision `source-revision:github:scverse/scanpy:5400eb87ef7d4e9f6f5a9256d98a7927723456fa`; locator `src/scanpy/neighbors/_doc.py#L3-L13`; wording: Use the indicated representation. `'X'` or any key for `.obsm` is valid. | — |

**Nested records / baselines / denominators**

| Track | Record | Gold | Baselines | Denominator | Included / reason |
|---|---|---|---|---|---|
| `G0` | `record:v2.1:g0:harmony-embedding-neighbors` | `semantic-gold:v2.1:harmony-embedding-neighbors` | `B0`, `B3` | `denominator:G0:development-parent` | `true` |
| `T1` | `record:v2.1:t1:harmony-embedding-neighbors` | `workflow-gold:v2.1:harmony-embedding-neighbors` | `B2`, `B3` | `denominator:T1:development-parent` | `true` |
| `T2` | `record:v2.1:t2:harmony-embedding-neighbors` | `requirement-gold-set:v2.1:harmony-embedding-neighbors` | `B1`, `B2`, `B3` | `denominator:T2:development-parent` | `true` |
| `T3` | `record:v2.1:t3:harmony-neighbors` | `decision:v2.1:harmony-neighbors` | `B2`, `B3` | `denominator:T3:development-parent` | `true` |
| `T4` | `record:v2.1:t4:pancreas-batch-aware` | `path:pancreas:batch-aware-state-assessment` | `B2`, `B3` | `denominator:T4:development-candidate-not-frozen` | `false / CANDIDATE_REAL_DATA_NOT_FROZEN` |
| `T8` | `record:v2.1:t8:wrong-revision-binding` | `mutation:v2.1:wrong-revision-binding` | `B3` | `denominator:T8:development-parent` | `true` |

**Mutations**
- `mutation:v2.1:wrong-revision-binding` -> `EVIDENCE_UNRESOLVABLE`; parent `record:v2.1:t3:harmony-neighbors`.

### 2.3 `scenario:v2.1:scrublet-transformed-input`

- **Scientific question:** May Scrublet run when only normalized or integrated expression is available?
- **Task family:** `doublet_detection`
- **Why it exists:** input requirement; missing resource; safe block.
- **Origin:** HISTORICAL_ANCHOR; study `study:pbmc3k-anchor`; dataset `dataset:pbmc3k-transformed-only`; source group `scrublet-0.2.3`.
- **Review risks:** `SCOPE_AMBIGUOUS`.

**WorkflowGold**

- `workflow-gold:v2.1:scrublet-transformed-input`
  - required final states: `no_invalid_scrublet_plan`
  - required prerequisites: `preserved_raw_umi_counts`
  - forbidden operations: `scrublet_on_normalized_expression`, `scrublet_on_integrated_expression`
  - optional operations: —
  - allowed alternatives: —
  - terminal states: `blocked`

**RequirementGold**

| Requirement set / requirement | State | Action | Criticality | Resolution | Draft rationale |
|---|---|---|---|---|---|
| `requirement-gold-set:v2.1:scrublet-transformed-input` / `requirement-gold:scrublet-transformed-input:raw-umi-counts` | `MISSING` | `BLOCK` | `hard` | `provide_resource` | Only transformed expression is available. |
| `requirement-gold-set:v2.1:scrublet-transformed-input` / `requirement-gold:scrublet-transformed-input:normalized-expression` | `VIOLATED` | `BLOCK` | `hard` | `select_other` | Normalized expression is not the required raw-count input. |

**EvidenceGold / exact independent provenance**

| EvidenceGold | Proposition | Owner | Scope/version | Provenance | EvidenceGap |
|---|---|---|---|---|---|
| `evidence-gold:v2.1:scrublet-transformed-input:raw-input` | Scrublet requires a raw unnormalized UMI count matrix. | `ScientificKG` | Scrublet 0.2.3 / `0.2.3` | `uat-authoritative-span:scrublet.input_output`; source `source-work unresolved in span artifact`; revision `source-revision:pypi:scrublet:0.2.3`; locator `scrublet-0.2.3/README.md#L9-L15`; wording: Given a raw (unnormalized) UMI counts matrix counts_matrix with cells as rows and genes as columns, calculate a doublet score for each cell: doublet_scores, predicted_doublets = scrub.scrub_doublets(). | — |

**Nested records / baselines / denominators**

| Track | Record | Gold | Baselines | Denominator | Included / reason |
|---|---|---|---|---|---|
| `G0` | `record:v2.1:g0:scrublet-transformed-input` | `semantic-gold:v2.1:scrublet-transformed-input` | `B0`, `B3` | `denominator:G0:development-parent` | `true` |
| `T1` | `record:v2.1:t1:scrublet-transformed-input` | `workflow-gold:v2.1:scrublet-transformed-input` | `B2`, `B3` | `denominator:T1:development-parent` | `true` |
| `T2` | `record:v2.1:t2:scrublet-transformed-input` | `requirement-gold-set:v2.1:scrublet-transformed-input` | `B1`, `B2`, `B3` | `denominator:T2:development-parent` | `true` |
| `T3` | `record:v2.1:t3:scrublet-input` | `decision:v2.1:scrublet-input` | `B2`, `B3` | `denominator:T3:development-parent` | `true` |
| `T8` | `record:v2.1:t8:silent-scope-widening` | `mutation:v2.1:silent-scope-widening` | `B3` | `denominator:T8:development-parent` | `true` |

**Mutations**
- `mutation:v2.1:silent-scope-widening` -> `SCOPE_SILENTLY_WIDENED`; parent `record:v2.1:t3:scrublet-input`.

### 2.4 `scenario:v2.1:soupx-input-semantics`

- **Scientific question:** What do SoupX tod/toc tables represent, and can acquired evidence be deposited without promotion?
- **Task family:** `ambient_rna_correction`
- **Why it exists:** EvidenceGap acquisition; candidate deposition; governance boundary.
- **Origin:** HISTORICAL_ANCHOR; study `study:pbmc3k-anchor`; dataset `dataset:pbmc3k-raw`; source group `soupx-1.6.2`.
- **Review risks:** `SOURCE_SUPPORT_WEAK`, `HIDDEN_QUERY_LEAKAGE_RISK`.

**WorkflowGold**

- `workflow-gold:v2.1:soupx-input-semantics`
  - required final states: `candidate_evidence_packet`
  - required prerequisites: `version_pinned_authoritative_source`
  - forbidden operations: `automatic_canonical_promotion`
  - optional operations: `candidate_rag_deposition`
  - allowed alternatives: —
  - terminal states: `candidate_pending_review`, `blocked`

**RequirementGold**

| Requirement set / requirement | State | Action | Criticality | Resolution | Draft rationale |
|---|---|---|---|---|---|
| `requirement-gold-set:v2.1:soupx-input-semantics` / `requirement-gold:soupx-input-semantics:authoritative-source` | `SATISFIED` | `ALLOW` | `hard` | `none` | A pinned official manual artifact exists. |
| `requirement-gold-set:v2.1:soupx-input-semantics` / `requirement-gold:soupx-input-semantics:candidate-review-status` | `SATISFIED` | `ALLOW` | `hard` | `none` | The deposited claim remains pending human review. |
| `requirement-gold-set:v2.1:soupx-input-semantics` / `requirement-gold:soupx-input-semantics:canonical-promotion` | `NOT_APPLICABLE` | `ALLOW` | `soft` | `none` | Promotion is outside Seed v0. |

**EvidenceGold / exact independent provenance**

| EvidenceGold | Proposition | Owner | Scope/version | Provenance | EvidenceGap |
|---|---|---|---|---|---|

**Nested records / baselines / denominators**

| Track | Record | Gold | Baselines | Denominator | Included / reason |
|---|---|---|---|---|---|
| `T5` | `record:v2.1:t5:soupx-input-semantics` | `acquisition:v2.1:soupx-input-semantics` | `B3`, `B4` | `denominator:T5:development-parent` | `true` |
| `T6` | `record:v2.1:t6:soupx-input-semantics` | `learning-episode:v2.1:soupx-input-semantics` | `S0`, `S1`, `S2` | `denominator:T6:development-parent` | `true` |
| `T7` | `record:v2.1:t7:complete-pending-candidate` | `governance:v2.1:complete-pending-candidate` | `B4` | `denominator:T7:development-parent` | `true` |

**Mutations**
- None.

### 2.5 `scenario:v2.1:hvg-flavor-conditional-input`

- **Scientific question:** Which expression state is required for the selected Scanpy HVG flavor?
- **Task family:** `feature_selection`
- **Why it exists:** conditional requirement; clarification; version scope.
- **Origin:** NEW_DEVELOPMENT; study `study:pbmc3k-anchor`; dataset `dataset:pbmc3k-raw`; source group `scanpy-1.11.2`.
- **Review risks:** `MULTIPLE_VALID_WORKFLOWS`.

**WorkflowGold**

- `workflow-gold:v2.1:hvg-flavor-seurat`
  - required final states: `highly_variable_gene_mask`
  - required prerequisites: `selected_flavor_seurat`, `logarithmized_expression_available_or_scheduled`
  - forbidden operations: `count_flavor_on_log_expression`, `dispersion_flavor_on_raw_counts`
  - optional operations: —
  - allowed alternatives: `hvg -> scanpy.pp.highly_variable_genes:seurat`
  - terminal states: `completed`, `plan_only`

- `workflow-gold:v2.1:hvg-flavor-seurat-v3`
  - required final states: `highly_variable_gene_mask`
  - required prerequisites: `selected_flavor_seurat_v3`, `raw_counts`
  - forbidden operations: `count_flavor_on_log_expression`
  - optional operations: —
  - allowed alternatives: `hvg -> scanpy.pp.highly_variable_genes:seurat_v3`
  - terminal states: `completed`, `blocked`

- `workflow-gold:v2.1:hvg-flavor-default-seurat`
  - required final states: `highly_variable_gene_mask`
  - required prerequisites: `default_flavor_resolves_to_seurat`, `logarithmized_expression_available_or_scheduled`
  - forbidden operations: `unspecified_flavor_forced_to_clarification`, `dispersion_flavor_on_raw_counts`
  - optional operations: —
  - allowed alternatives: `hvg -> scanpy.pp.highly_variable_genes:seurat`
  - terminal states: `completed`, `plan_only`

**RequirementGold**

| Requirement set / requirement | State | Action | Criticality | Resolution | Draft rationale |
|---|---|---|---|---|---|
| `requirement-gold-set:v2.1:hvg-flavor-seurat` / `requirement-gold:hvg-flavor-conditional-input:flavor-seurat` | `SATISFIED` | `ALLOW` | `hard` | `none` | The request explicitly selects the dispersion-based seurat flavor. |
| `requirement-gold-set:v2.1:hvg-flavor-seurat` / `requirement-gold:hvg-flavor-conditional-input:log-expression` | `MISSING` | `ALLOW` | `hard` | `schedule_prerequisite` | Logarithmized expression is absent now but can be produced as a scheduled prerequisite before the selected seurat flavor runs. |
| `requirement-gold-set:v2.1:hvg-flavor-seurat-v3` / `requirement-gold:hvg-flavor-conditional-input:flavor-seurat-v3` | `SATISFIED` | `ALLOW` | `hard` | `none` | The request explicitly selects the count-based seurat_v3 flavor. |
| `requirement-gold-set:v2.1:hvg-flavor-seurat-v3` / `requirement-gold:hvg-flavor-conditional-input:counts` | `SATISFIED` | `ALLOW` | `hard` | `none` | Raw counts required by the selected seurat_v3 flavor are available. |
| `requirement-gold-set:v2.1:hvg-flavor-default-seurat` / `requirement-gold:hvg-flavor-conditional-input:default-flavor` | `SATISFIED` | `ALLOW` | `hard` | `none` | Scanpy 1.11.2 resolves an omitted flavor to seurat. |
| `requirement-gold-set:v2.1:hvg-flavor-default-seurat` / `requirement-gold:hvg-flavor-conditional-input:log-expression` | `MISSING` | `ALLOW` | `hard` | `schedule_prerequisite` | Logarithmized expression is absent now but can be produced as a scheduled prerequisite before the resolved default seurat flavor runs. |

**EvidenceGold / exact independent provenance**

| EvidenceGold | Proposition | Owner | Scope/version | Provenance | EvidenceGap |
|---|---|---|---|---|---|
| `evidence-gold:v2.1:hvg-flavor-conditional-input:dispersion-input` | Dispersion-based HVG flavors expect logarithmized data. | `ScientificKG` | Scanpy 1.11.2 HVG flavor condition / `1.11.2` | `scanpy-authoritative-span:hvg.flavor_input:1.11.2`; source `source-work unresolved in span artifact`; revision `source-revision:github:scverse/scanpy:5400eb87ef7d4e9f6f5a9256d98a7927723456fa`; locator `src/scanpy/preprocessing/_highly_variable_genes.py#L542-L543`; wording: Expects logarithmized data, except when `flavor='seurat_v3'`/`'seurat_v3_paper'`, in which count data is expected. | — |
| `evidence-gold:v2.1:hvg-flavor-conditional-input:count-input` | Seurat v3 HVG flavors expect count data. | `ScientificKG` | Scanpy 1.11.2 HVG flavor condition / `1.11.2` | `scanpy-authoritative-span:hvg.flavor_input:1.11.2`; source `source-work unresolved in span artifact`; revision `source-revision:github:scverse/scanpy:5400eb87ef7d4e9f6f5a9256d98a7927723456fa`; locator `src/scanpy/preprocessing/_highly_variable_genes.py#L542-L543`; wording: Expects logarithmized data, except when `flavor='seurat_v3'`/`'seurat_v3_paper'`, in which count data is expected. | — |
| `evidence-gold:v2.1:hvg-flavor-conditional-input:default-flavor` | Scanpy 1.11.2 highly_variable_genes resolves an omitted flavor argument to seurat. | `ScientificKG` | Scanpy 1.11.2 API default / `1.11.2` | `gold-span:scanpy:hvg-default-flavor:1.11.2`; source `source-work:github:scverse/scanpy`; revision `source-revision:scanpy:1.11.2:5400eb87`; locator `src/scanpy/preprocessing/_highly_variable_genes.py#L523-L543`; wording: flavor: Literal["seurat", "cell_ranger", "seurat_v3", "seurat_v3_paper"] = "seurat"<br>Expects logarithmized data, except when `flavor='seurat_v3'`/`'seurat_v3_paper'`, in which count data is expected. | — |
| `evidence-gold:v2.1:hvg-flavor-conditional-input:hvg-output` | HVG selection records a highly-variable feature mask and statistics. | `ScientificKG` | Scanpy 1.11.2 / `1.11.2` | `scanpy-authoritative-span:hvg.output:1.11.2`; source `source-work unresolved in span artifact`; revision `source-revision:github:scverse/scanpy:5400eb87ef7d4e9f6f5a9256d98a7927723456fa`; locator `src/scanpy/preprocessing/_highly_variable_genes.py#L622-L627`; wording: boolean indicator of highly-variable genes | — |

**Nested records / baselines / denominators**

| Track | Record | Gold | Baselines | Denominator | Included / reason |
|---|---|---|---|---|---|
| `T1` | `record:v2.1:t1:hvg-flavor-seurat` | `workflow-gold:v2.1:hvg-flavor-seurat` | `B2`, `B3` | `denominator:T1:development-parent` | `true` |
| `T1` | `record:v2.1:t1:hvg-flavor-seurat-v3` | `workflow-gold:v2.1:hvg-flavor-seurat-v3` | `B2`, `B3` | `denominator:T1:development-parent` | `true` |
| `T1` | `record:v2.1:t1:hvg-flavor-default-seurat` | `workflow-gold:v2.1:hvg-flavor-default-seurat` | `B2`, `B3` | `denominator:T1:development-parent` | `true` |
| `T2` | `record:v2.1:t2:hvg-flavor-seurat` | `requirement-gold-set:v2.1:hvg-flavor-seurat` | `B1`, `B2`, `B3` | `denominator:T2:development-parent` | `true` |
| `T2` | `record:v2.1:t2:hvg-flavor-seurat-v3` | `requirement-gold-set:v2.1:hvg-flavor-seurat-v3` | `B1`, `B2`, `B3` | `denominator:T2:development-parent` | `true` |
| `T2` | `record:v2.1:t2:hvg-flavor-default-seurat` | `requirement-gold-set:v2.1:hvg-flavor-default-seurat` | `B1`, `B2`, `B3` | `denominator:T2:development-parent` | `true` |
| `T3` | `record:v2.1:t3:hvg-input` | `decision:v2.1:hvg-input` | `B2`, `B3` | `denominator:T3:development-parent` | `true` |
| `T4` | `record:v2.1:t4:pbmc3k-raw-core` | `path:pbmc3k:raw-to-scanpy-core` | `B2`, `B3` | `denominator:T4:development-parent` | `true` |

**Mutations**
- None.

### 2.6 `scenario:v2.1:singler-reference-compatibility`

- **Scientific question:** Is the query/reference pair sufficiently aligned and biologically suitable for SingleR?
- **Task family:** `cell_type_annotation`
- **Why it exists:** reference requirement; feature alignment; biological applicability.
- **Origin:** NEW_DEVELOPMENT; study `UNASSIGNED`; dataset `scientific-state:singler-query-reference-pair`; source group `singler-2.14.1`.
- **Review risks:** `UNKNOWN_SHOULD_REMAIN_UNKNOWN`, `SCOPE_AMBIGUOUS`.

**WorkflowGold**

- `workflow-gold:v2.1:singler-reference-compatibility`
  - required final states: `candidate_cell_type_labels`
  - required prerequisites: `reference_expression`, `reference_labels`, `shared_features`, `biologically_applicable_reference`
  - forbidden operations: `annotation_with_unaligned_reference`
  - optional operations: `pruned_labels`
  - allowed alternatives: `annotation -> SingleR::SingleR`
  - terminal states: `completed`, `blocked`, `clarification_required`

**RequirementGold**

| Requirement set / requirement | State | Action | Criticality | Resolution | Draft rationale |
|---|---|---|---|---|---|
| `requirement-gold-set:v2.1:singler-reference-compatibility` / `requirement-gold:singler-reference-compatibility:query-expression` | `SATISFIED` | `CLARIFY` | `hard` | `none` | Query expression is present. |
| `requirement-gold-set:v2.1:singler-reference-compatibility` / `requirement-gold:singler-reference-compatibility:reference-expression` | `SATISFIED` | `CLARIFY` | `hard` | `none` | Reference expression is present. |
| `requirement-gold-set:v2.1:singler-reference-compatibility` / `requirement-gold:singler-reference-compatibility:reference-labels` | `SATISFIED` | `CLARIFY` | `hard` | `none` | Reference labels are present. |
| `requirement-gold-set:v2.1:singler-reference-compatibility` / `requirement-gold:singler-reference-compatibility:shared-features` | `SATISFIED` | `CLARIFY` | `hard` | `none` | A non-empty feature intersection exists. |
| `requirement-gold-set:v2.1:singler-reference-compatibility` / `requirement-gold:singler-reference-compatibility:biological-applicability` | `UNKNOWN` | `CLARIFY` | `hard` | `ask_user` | Reference suitability for this tissue/context is not yet adjudicated. |

**EvidenceGold / exact independent provenance**

| EvidenceGold | Proposition | Owner | Scope/version | Provenance | EvidenceGap |
|---|---|---|---|---|---|
| `evidence-gold:v2.1:singler-reference-compatibility:query-input` | SingleR accepts query expression including raw-count query input. | `ScientificKG` | SingleR 2.14.1 / `2.14.1` | `uat-authoritative-span:singler.interface`; source `source-work unresolved in span artifact`; revision `source-revision:bioconductor:SingleR:2.14.1`; locator `SingleR/R/SingleR.R#L1-L14`; wording: Returns the best annotation for each cell in a test dataset, given a labelled reference dataset in the same feature space. test A numeric matrix of single-cell expression values where rows are genes and columns are cells. ref A numeric matrix of (usually normalized and log-transformed) expression values from a reference dataset.<br>`uat-authoritative-span:singler.raw_query`; source `source-work unresolved in span artifact`; revision `source-revision:bioconductor:SingleR:2.14.1`; locator `SingleR/R/classifySingleR.R#L63-L65`; wording: In practice, the raw counts (for UMI data) or the transcript counts (for read count data) can also be used without normalization and log-transformation. Any monotonic transformation will have no effect the calculation of the correlation values other than for some minor differences due to numerical precision. | — |
| `evidence-gold:v2.1:singler-reference-compatibility:reference-expression` | SingleR requires reference expression profiles. | `ScientificKG` | SingleR 2.14.1 / `2.14.1` | `uat-authoritative-span:singler.reference_state`; source `source-work unresolved in span artifact`; revision `source-revision:bioconductor:SingleR:2.14.1`; locator `SingleR/R/trainSingleR.R#L74-L99`; wording: This function uses a training data set to select interesting features and construct nearest neighbor indices in rank space. The automatic marker detection identifies genes that are differentially expressed between pairs of labels in the reference dataset. The expression values are expected to be log-transformed and normalized. Classification with classifySingleR assumes that the test dataset contains all marker genes that were detected from the reference. | — |
| `evidence-gold:v2.1:singler-reference-compatibility:reference-labels` | Reference labels are required to train/use the SingleR reference. | `ScientificKG` | SingleR 2.14.1 / `2.14.1` | `uat-authoritative-span:singler.reference_labels`; source `source-work unresolved in span artifact`; revision `source-revision:bioconductor:SingleR:2.14.1`; locator `SingleR/R/trainSingleR.R#L3-L12`; wording: Train the SingleR classifier on one or more reference datasets with known labels. ref A numeric matrix of expression values where rows are genes and columns are reference samples (individual cells or bulk samples). labels A character vector or factor of known labels for all samples in ref. | — |
| `evidence-gold:v2.1:singler-reference-compatibility:shared-features` | Query and reference must have a usable feature intersection. | `ScientificKG` | SingleR 2.14.1 / `2.14.1` | `uat-authoritative-span:singler.feature_intersection`; source `source-work unresolved in span artifact`; revision `source-revision:bioconductor:SingleR:2.14.1`; locator `SingleR/R/SingleR.R#L35-L38`; wording: This function is just a convenient wrapper around trainSingleR and classifySingleR. The function will automatically restrict the analysis to the intersection of the genes in both ref and test. If this intersection is empty (e.g., because the two datasets use different gene annotations), an error will be raised. | — |
| `evidence-gold:v2.1:singler-reference-compatibility:reference-choice` | Reference choice materially affects annotation; the reference should cover expected labels and a similar technology or protocol is preferred. | `ScientificKG` | SingleRBook 3.22 classic-mode reference choice / `3.22` | `gold-span:singler:reference-choice:3.22`; source `source-work:bioconductor:SingleRBook`; revision `source-revision:SingleRBook:3.22`; locator `Chapter 2, section 2.5 Choice of reference`; wording: Unsurprisingly, the choice of reference has a major impact on the annotation results. We need to pick a reference that contains a superset of the labels that we expect to be present in our test dataset. We would also prefer a reference that is generated from a similar technology or protocol as our test dataset. | — |

**Nested records / baselines / denominators**

| Track | Record | Gold | Baselines | Denominator | Included / reason |
|---|---|---|---|---|---|
| `G0` | `record:v2.1:g0:singler-reference-compatibility` | `semantic-gold:v2.1:singler-reference-compatibility` | `B0`, `B3` | `denominator:G0:development-parent` | `true` |
| `T2` | `record:v2.1:t2:singler-reference-compatibility` | `requirement-gold-set:v2.1:singler-reference-compatibility` | `B1`, `B2`, `B3` | `denominator:T2:development-parent` | `true` |
| `T3` | `record:v2.1:t3:singler-reference` | `decision:v2.1:singler-reference` | `B2`, `B3` | `denominator:T3:development-parent` | `true` |
| `T4` | `record:v2.1:t4:pancreas-reference-annotation` | `path:pancreas:reference-annotation` | `B2`, `B3` | `denominator:T4:development-candidate-not-frozen` | `false / CANDIDATE_REAL_DATA_NOT_FROZEN` |
| `T5` | `record:v2.1:t5:singler-reference-suitability` | `acquisition:v2.1:singler-reference-suitability` | `B3`, `B4` | `denominator:T5:development-parent` | `true` |
| `T6` | `record:v2.1:t6:singler-reference-suitability` | `learning-episode:v2.1:singler-reference-suitability` | `S0`, `S1`, `S2` | `denominator:T6:development-parent` | `true` |
| `T7` | `record:v2.1:t7:missing-provenance` | `governance:v2.1:missing-provenance` | `B4` | `denominator:T7:development-parent` | `true` |
| `T8` | `record:v2.1:t8:hidden-query-leak` | `mutation:v2.1:hidden-query-leak` | `B3` | `denominator:T8:development-parent` | `true` |

**Mutations**
- `mutation:v2.1:hidden-query-leak` -> `HIDDEN_QUERY_LEAK`; parent `record:v2.1:t6:singler-reference-suitability`.

### 2.7 `scenario:v2.1:celltypist-model-feature-alignment`

- **Scientific question:** Does CellTypist have compatible normalized input, a resolved model artifact, and an evaluated feature alignment?
- **Task family:** `cell_type_annotation`
- **Why it exists:** input state; reference model; feature alignment.
- **Origin:** NEW_DEVELOPMENT; study `UNASSIGNED`; dataset `scientific-state:celltypist-query`; source group `celltypist-1.7.1`.
- **Review risks:** `OWNER_AMBIGUOUS`, `VERSION_AMBIGUOUS`.

**WorkflowGold**

- `workflow-gold:v2.1:celltypist-model-feature-alignment`
  - required final states: `candidate_cell_type_labels`
  - required prerequisites: `log_normalized_expression`, `resolved_model_artifact`, `feature_alignment_report`
  - forbidden operations: `annotation_with_incompatible_model`
  - optional operations: `majority_voting`
  - allowed alternatives: `annotation -> celltypist.annotate`
  - terminal states: `completed`, `blocked`, `clarification_required`

**RequirementGold**

| Requirement set / requirement | State | Action | Criticality | Resolution | Draft rationale |
|---|---|---|---|---|---|
| `requirement-gold-set:v2.1:celltypist-model-feature-alignment` / `requirement-gold:celltypist-model-feature-alignment:log-normalized-expression` | `SATISFIED` | `BLOCK` | `hard` | `none` | Expected normalized input is available. |
| `requirement-gold-set:v2.1:celltypist-model-feature-alignment` / `requirement-gold:celltypist-model-feature-alignment:model-artifact` | `MISSING` | `BLOCK` | `hard` | `provide_resource` | The actual selected model artifact identity, version and hash have not been resolved by the runtime contract. |
| `requirement-gold-set:v2.1:celltypist-model-feature-alignment` / `requirement-gold:celltypist-model-feature-alignment:feature-alignment-report` | `MISSING` | `BLOCK` | `hard` | `provide_resource` | Feature alignment with the resolved model has not been evaluated. |

**EvidenceGold / exact independent provenance**

| EvidenceGold | Proposition | Owner | Scope/version | Provenance | EvidenceGap |
|---|---|---|---|---|---|
| `evidence-gold:v2.1:celltypist-model-feature-alignment:normalized-input` | CellTypist 1.7.1 expects normalized logarithmized expression for AnnData input. | `ScientificKG` | CellTypist 1.7.1 annotate input / `1.7.1` | `gold-span:celltypist:normalized-input:1.7.1`; source `source-work:celltypist:official-readme`; revision `source-revision:celltypist:1.7.1:fe357564`; locator `README.md#L166-L170`; wording: CellTypist requires a logarithmised and normalised expression matrix stored in the `AnnData` (log1p normalised expression to 10,000 counts per cell). Within the `AnnData`, please provide all genes to ensure maximal overlap with genes in the model. | — |
| `evidence-gold:v2.1:celltypist-model-feature-alignment:feature-overlap-guidance` | Providing all genes maximizes overlap with features in the CellTypist model. | `ScientificKG` | CellTypist 1.7.1 feature-overlap guidance / `1.7.1` | `gold-span:celltypist:normalized-input:1.7.1`; source `source-work:celltypist:official-readme`; revision `source-revision:celltypist:1.7.1:fe357564`; locator `README.md#L166-L170`; wording: CellTypist requires a logarithmised and normalised expression matrix stored in the `AnnData` (log1p normalised expression to 10,000 counts per cell). Within the `AnnData`, please provide all genes to ensure maximal overlap with genes in the model. | — |
| `evidence-gold:v2.1:celltypist-model-feature-alignment:default-model` | When annotate is called without a model argument, CellTypist 1.7.1 defaults to Immune_All_Low.pkl. | `ToolContract` | CellTypist 1.7.1 annotate API default / `1.7.1` | `gold-span:celltypist:default-model:1.7.1`; source `source-work:celltypist:annotate`; revision `source-revision:celltypist:1.7.1:fe357564`; locator `celltypist/annotate.py#L7-L31`; wording: model: Optional[Union[str, Model]] = None<br>Model used to predict the input cells. Default to using the `'Immune_All_Low.pkl'` model. | — |
| `evidence-gold:v2.1:celltypist-model-feature-alignment:resolved-model-artifact` | The actual selected model artifact identity, version and content hash are unresolved for this runtime scenario. | `ToolContract` | selected runtime model artifact / `runtime` | runtime/non-scientific: citation abstention | — |
| `evidence-gold:v2.1:celltypist-model-feature-alignment:model-feature-alignment` | Feature alignment against the resolved model artifact has not yet been computed for this runtime scenario. | `ToolContract` | selected runtime model artifact and query feature set / `runtime` | runtime/non-scientific: citation abstention | — |

**Nested records / baselines / denominators**

| Track | Record | Gold | Baselines | Denominator | Included / reason |
|---|---|---|---|---|---|
| `G0` | `record:v2.1:g0:celltypist-model-feature-alignment` | `semantic-gold:v2.1:celltypist-model-feature-alignment` | `B0`, `B3` | `denominator:G0:development-parent` | `true` |
| `T2` | `record:v2.1:t2:celltypist-model-feature-alignment` | `requirement-gold-set:v2.1:celltypist-model-feature-alignment` | `B1`, `B2`, `B3` | `denominator:T2:development-parent` | `true` |
| `T3` | `record:v2.1:t3:celltypist-model` | `decision:v2.1:celltypist-model` | `B2`, `B3` | `denominator:T3:development-parent` | `true` |

**Mutations**
- None.

### 2.8 `scenario:v2.1:scvelo-layer-availability`

- **Scientific question:** Are the required spliced/unspliced measurements available for an RNA-velocity task?
- **Task family:** `rna_velocity`
- **Why it exists:** modality requirement; missing input; evidence gap.
- **Origin:** NEW_DEVELOPMENT; study `UNASSIGNED`; dataset `scientific-state:scvelo-layer-availability`; source group `scvelo-0.3.3`.
- **Review risks:** `SCOPE_AMBIGUOUS`.

**WorkflowGold**

- `workflow-gold:v2.1:scvelo-layer-availability`
  - required final states: `velocity_representation`
  - required prerequisites: `spliced_counts`, `unspliced_counts`
  - forbidden operations: `velocity_without_required_measurements`
  - optional operations: `moments`
  - allowed alternatives: `rna_velocity -> scvelo.velocity`
  - terminal states: `completed`, `blocked`, `clarification_required`

**RequirementGold**

| Requirement set / requirement | State | Action | Criticality | Resolution | Draft rationale |
|---|---|---|---|---|---|
| `requirement-gold-set:v2.1:scvelo-layer-availability` / `requirement-gold:scvelo-layer-availability:spliced-counts` | `MISSING` | `BLOCK` | `hard` | `provide_resource` | Spliced measurements are absent. |
| `requirement-gold-set:v2.1:scvelo-layer-availability` / `requirement-gold:scvelo-layer-availability:unspliced-counts` | `MISSING` | `BLOCK` | `hard` | `provide_resource` | Unspliced measurements are absent. |

**EvidenceGold / exact independent provenance**

| EvidenceGold | Proposition | Owner | Scope/version | Provenance | EvidenceGap |
|---|---|---|---|---|---|
| `evidence-gold:v2.1:scvelo-layer-availability:layer-requirement` | The selected canonical scVelo velocity workflow requires identified spliced and unspliced count matrices in AnnData layers. | `ScientificKG` | scVelo 0.3.3 canonical velocity workflow / `0.3.3` | `gold-span:scvelo:spliced-unspliced-input:0.3.3`; source `source-work:scvelo:official-docs`; revision `source-revision:scvelo:0.3.3:22b6e7e6`; locator `docs/source/getting_started.rst#L7-L9,L26-L28`; wording: First of all, the input data for scVelo are two count matrices of pre-mature (unspliced) and mature (spliced) abundances. Additional data layers where spliced and unspliced counts are stored (`adata.layers`). | — |

**Nested records / baselines / denominators**

| Track | Record | Gold | Baselines | Denominator | Included / reason |
|---|---|---|---|---|---|
| `G0` | `record:v2.1:g0:scvelo-layer-availability` | `semantic-gold:v2.1:scvelo-layer-availability` | `B0`, `B3` | `denominator:G0:development-parent` | `true` |
| `T1` | `record:v2.1:t1:scvelo-layer-availability` | `workflow-gold:v2.1:scvelo-layer-availability` | `B2`, `B3` | `denominator:T1:development-parent` | `true` |
| `T3` | `record:v2.1:t3:scvelo-input` | `decision:v2.1:scvelo-input` | `B2`, `B3` | `denominator:T3:development-parent` | `true` |
| `T5` | `record:v2.1:t5:scvelo-layer-requirement` | `acquisition:v2.1:scvelo-layer-requirement` | `B3`, `B4` | `denominator:T5:development-parent` | `true` |
| `T6` | `record:v2.1:t6:scvelo-layer-requirement` | `learning-episode:v2.1:scvelo-layer-requirement` | `S0`, `S1`, `S2` | `denominator:T6:development-parent` | `true` |
| `T7` | `record:v2.1:t7:candidate-trusted-conflation` | `governance:v2.1:candidate-trusted-conflation` | `B4` | `denominator:T7:development-parent` | `true` |
| `T8` | `record:v2.1:t8:candidate-as-trusted` | `mutation:v2.1:candidate-as-trusted` | `B3` | `denominator:T8:development-parent` | `true` |

**Mutations**
- `mutation:v2.1:candidate-as-trusted` -> `EPISTEMIC_STATUS_CONFLATION`; parent `record:v2.1:t3:scvelo-input`.

### 2.9 `scenario:v2.1:mofa2-sample-alignment`

- **Scientific question:** Are multi-omic matrices aligned on the same or explicitly overlapping samples for MOFA2?
- **Task family:** `multi_omics_integration`
- **Why it exists:** multimodal input; sample alignment; clarification.
- **Origin:** NEW_DEVELOPMENT; study `UNASSIGNED`; dataset `scientific-state:mofa2-sample-alignment`; source group `mofa2-docs-ec2ee6d`.
- **Review risks:** `SCOPE_AMBIGUOUS`.

**WorkflowGold**

- `workflow-gold:v2.1:mofa2-sample-alignment`
  - required final states: `multiomics_latent_factors`
  - required prerequisites: `multiple_omics_matrices`, `same_or_overlapping_samples_supported`, `explicit_sample_identity_alignment`
  - forbidden operations: `silent_sample_identity_coercion`
  - optional operations: —
  - allowed alternatives: `multiomics_factor_analysis -> MOFA2.train/mofapy2.train`
  - terminal states: `completed`, `blocked`, `clarification_required`

**RequirementGold**

| Requirement set / requirement | State | Action | Criticality | Resolution | Draft rationale |
|---|---|---|---|---|---|
| `requirement-gold-set:v2.1:mofa2-sample-alignment` / `requirement-gold:mofa2-sample-alignment:multiple-views` | `SATISFIED` | `CLARIFY` | `hard` | `none` | Two omics matrices are supplied. |
| `requirement-gold-set:v2.1:mofa2-sample-alignment` / `requirement-gold:mofa2-sample-alignment:sample-alignment` | `UNKNOWN` | `CLARIFY` | `hard` | `ask_user` | MOFA2 scientifically permits overlapping sample sets, but the runtime identity mapping across the supplied matrices has not been verified. |

**EvidenceGold / exact independent provenance**

| EvidenceGold | Proposition | Owner | Scope/version | Provenance | EvidenceGap |
|---|---|---|---|---|---|
| `evidence-gold:v2.1:mofa2-sample-alignment:overlapping-samples-supported` | MOFA2 accepts multiple omics matrices measured on the same or overlapping sets of samples. | `ScientificKG` | MOFA2 official documentation at ec2ee6d / `ec2ee6d` | `gold-span:mofa2:input-output:ec2ee6d`; source `source-work:mofa2:official-docs`; revision `source-revision:mofa2:gh-pages:ec2ee6d`; locator `index.md#L8`; wording: Given several data matrices with measurements of multiple -omics data types on the same or on overlapping sets of samples, MOFA infers an interpretable low-dimensional representation in terms of a few latent factors. | — |
| `evidence-gold:v2.1:mofa2-sample-alignment:sample-identity-alignment` | The explicit sample-identity mapping across the supplied runtime matrices has not yet been verified. | `RepresentationLedger` | current multi-omics dataset instances / `runtime` | runtime/non-scientific: citation abstention | — |
| `evidence-gold:v2.1:mofa2-sample-alignment:latent-output` | MOFA2 infers a small number of interpretable latent factors. | `ScientificKG` | MOFA2 official documentation at ec2ee6d / `ec2ee6d` | `gold-span:mofa2:input-output:ec2ee6d`; source `source-work:mofa2:official-docs`; revision `source-revision:mofa2:gh-pages:ec2ee6d`; locator `index.md#L8`; wording: Given several data matrices with measurements of multiple -omics data types on the same or on overlapping sets of samples, MOFA infers an interpretable low-dimensional representation in terms of a few latent factors. | — |

**Nested records / baselines / denominators**

| Track | Record | Gold | Baselines | Denominator | Included / reason |
|---|---|---|---|---|---|
| `G0` | `record:v2.1:g0:mofa2-sample-alignment` | `semantic-gold:v2.1:mofa2-sample-alignment` | `B0`, `B3` | `denominator:G0:development-parent` | `true` |
| `T1` | `record:v2.1:t1:mofa2-sample-alignment` | `workflow-gold:v2.1:mofa2-sample-alignment` | `B2`, `B3` | `denominator:T1:development-parent` | `true` |
| `T3` | `record:v2.1:t3:mofa2-input` | `decision:v2.1:mofa2-input` | `B2`, `B3` | `denominator:T3:development-parent` | `true` |
| `T7` | `record:v2.1:t7:decision-without-change-set` | `governance:v2.1:decision-without-change-set` | `B4` | `denominator:T7:development-parent` | `true` |
| `T8` | `record:v2.1:t8:split-crossing-derived-record` | `mutation:v2.1:split-crossing-derived-record` | `B3` | `denominator:T8:development-parent` | `true` |

**Mutations**
- `mutation:v2.1:split-crossing-derived-record` -> `SPLIT_INHERITANCE_VIOLATION`; parent `record:v2.1:t1:mofa2-sample-alignment`.

## 3. Learning episodes

### `learning-episode:v2.1:soupx-input-semantics`

- original query: What do SoupX tod and toc input tables contain?
- hidden related query: A dataset contains A) an unfiltered droplet-by-gene matrix and B) a filtered cell-by-gene matrix. For SoupChannel construction, which artifact should populate tod, which should populate toc, and what is missing if only B is available?
- S0 -> S1: evidence `source-artifact:sha256:dabbfdf10c0ab46efee927026f77494e1df096999742f86705b91dcd0b1dac19` added; no structured candidate.
- S1 -> S2: same evidence retained; candidate `claim-revision:cp6:7005e7aaf1f910d6:1` added.
- isolation: hidden query absent from claim-construction-visible queries = `True`.

### `learning-episode:v2.1:singler-reference-suitability`

- original query: What inputs does SingleR need for reference-based annotation?
- hidden related query: Should a reference from an unrelated tissue be accepted without clarification?
- S0 -> S1: evidence `gold-span:singler:reference-choice:3.22` added; no structured candidate.
- S1 -> S2: same evidence retained; candidate `candidate-claim:v2.1:singler-reference-suitability` added.
- isolation: hidden query absent from claim-construction-visible queries = `True`.

### `learning-episode:v2.1:scvelo-layer-requirement`

- original query: Which measurements are required for this scVelo velocity workflow?
- hidden related query: Can the same workflow run when only total expression is present?
- S0 -> S1: evidence `source-artifact:scvelo:0.3.3:22b6e7e6` added; no structured candidate.
- S1 -> S2: same evidence retained; candidate `candidate-claim:v2.1:scvelo-layer-requirement` added.
- isolation: hidden query absent from claim-construction-visible queries = `True`.

## 4. Real-data maturity

| Class | Study | Artifact/checksum status | Workflow paths |
|---|---|---|---|
| `FROZEN_REAL_DATA` | `study:pbmc3k-anchor` | `existing_local_versioned_inputs` / `existing_frozen_hashes` | `path:pbmc3k:raw-to-scanpy-core`, `path:pbmc3k:processed-reuse` |
| `CANDIDATE_REAL_DATA` | `study:pancreas-reference-annotation-candidate` | `candidate_not_acquired` / `pending_selection` | `path:pancreas:reference-annotation` |
| `CANDIDATE_REAL_DATA` | `study:pancreas-batch-integration-candidate` | `candidate_not_acquired` / `pending_selection` | `path:pancreas:batch-aware-state-assessment` |

The two pancreas paths remain excluded from the scored T4 denominator with `CANDIDATE_REAL_DATA_NOT_FROZEN`. Scientific development scenarios are not assigned to a fictitious all-purpose pancreas study.

## 5. Review conclusion

All nine parent scenarios and required nested checklist entries were approved by the project owner. Scientific provenance remains source-bound and candidate knowledge is not promoted. This approval is not an independent external expert review.

`SEED_V0_FREEZE = PASS`

`MIDTERM_CORE_SEED_V0_FROZEN = YES`
