# Scientific KG v1 — Consolidated Inventory

Frozen baseline: `25d0cff7e13a537d9e051e2976a87b4fcf6419c6`.

This is an inventory view, not a canonical promotion. All scientific claims and relations remain in their original frozen candidate layers. Trusted status applies only to source-verified evidence spans; promoted scientific claims remain **0**.

## 1. Frozen layers

| Layer | Role | Entities | Claims | Relations | Evidence | Gaps |
| --- | --- | --- | --- | --- | --- | --- |
| uat_decision_rule_correction | corrected_candidate_overlay | 53 | 25 | 29 | 32 | 0 |
| scientific_kg_v1_core | v1_core_candidate | 204 | 236 | 171 | 87 | 5 |
| content_expansion_v1 | broad_coverage_reference | 123 | 92 | 38 | 32 | 72 |
| scanpy_core_reference_slice | reference_implementation_superseded_by_corrected_slice | 31 | 27 | 18 | 19 | 0 |

> Physical totals retain overlapping records across layers. No unreviewed identity deduplication or semantic merge was performed.

## 2. Entity inventory

### All consolidated graph node types

| Node type | Physical records |
| --- | --- |
| ApplicabilityScope | 98 |
| AtomicClaimRevision | 380 |
| EvidenceGap | 77 |
| EvidenceReference | 32 |
| EvidenceSpan | 170 |
| InputPort | 92 |
| Limitation | 17 |
| Method | 65 |
| MethodVariant | 23 |
| Operator | 69 |
| OperatorRevision | 69 |
| OutputPort | 71 |
| Package | 39 |
| PackageRelease | 26 |
| ParameterDefinition | 17 |
| ReferencedObject | 11 |
| RepresentationConstraint | 107 |
| RepresentationType | 98 |
| Requirement | 104 |
| ScientificTask | 48 |
| SoftwareProject | 38 |

### Domain entity records

| Entity type | Physical records |
| --- | --- |
| Limitation | 17 |
| Method | 65 |
| MethodVariant | 23 |
| Operator | 69 |
| OperatorRevision | 69 |
| Package | 39 |
| PackageRelease | 26 |
| ParameterDefinition | 17 |
| ScientificTask | 48 |
| SoftwareProject | 38 |

Representation types: **98**; constraints: **107**; Method→OperatorRevision→Port chains: **69**.

## 3. Relation inventory

### All consolidated graph edge predicates

| Predicate | Physical edges |
| --- | --- |
| BELONGS_TO_PACKAGE | 69 |
| BELONGS_TO_PROJECT | 39 |
| BOUND_TO_PACKAGE_RELEASE | 69 |
| CAN_FEED | 80 |
| CONSTRAINS_TYPE | 107 |
| CONSUMES | 105 |
| HAS_INPUT_PORT | 92 |
| HAS_OUTPUT_PORT | 71 |
| HAS_REQUIREMENT | 104 |
| IMPLEMENTS_METHOD | 69 |
| IMPLEMENTS_METHOD_VARIANT | 21 |
| OUTPUT_REPRESENTATION_TYPE | 71 |
| PRODUCES | 71 |
| REQUIRES_CONSTRAINT | 106 |
| REVISION_OF_OPERATOR | 69 |
| REVISION_OF_PACKAGE | 26 |
| SUBJECT_OF_CLAIM | 380 |
| SUPPORTS | 481 |
| VARIANT_OF_METHOD | 23 |
| accepts_optional_representation | 1 |
| accepts_representation | 3 |
| has_key_parameter | 17 |
| has_limitation | 21 |
| implemented_in_release | 44 |
| implements_method | 54 |
| implements_method_variant | 16 |
| key_parameter | 6 |
| produces | 75 |
| project_guardrail | 1 |
| project_profile_requires | 1 |
| requires_representation | 22 |
| requires_representation_constraint | 79 |
| supports_task | 36 |

### Derived graph relations

| Predicate | Physical records |
| --- | --- |
| CAN_FEED | 80 |
| CONSUMES | 105 |
| PRODUCES | 71 |

### Atomic claim predicates

| Predicate | Claims |
| --- | --- |
| accepts_optional_representation | 1 |
| accepts_representation | 6 |
| has_key_parameter | 17 |
| has_limitation | 21 |
| implemented_in_release | 44 |
| implements_method | 54 |
| implements_method_variant | 16 |
| key_parameter | 6 |
| produces | 75 |
| project_guardrail | 1 |
| project_profile_requires | 1 |
| requires_compatibility | 1 |
| requires_representation | 22 |
| requires_representation_constraint | 79 |
| supports_task | 36 |

## 4. Ecosystem and task coverage

Ecosystems represented (22): CellRank, CellTypist, DoubletFinder, Harmony, MIMOSCA, MOFA2, Scanorama, Scanpy, Scrublet, Seurat, SingleR, Slingshot, SoupX, WOT, cell2location, edgeR, moscot, pySCENIC, scDblFinder, scVelo, scvi-tools, tradeSeq.

Scientific tasks represented (30): RNA velocity inference, ambient RNA contamination correction, ambient RNA contamination removal, batch integration, cell and gene quality filtering, cell-fate mapping, cell-type annotation, cellular fate mapping, differential analysis, differential expression analysis, dimensionality reduction, doublet detection, embedding visualization, feature selection, gene-regulatory network inference, graph clustering, graph embedding, highly variable feature selection, library-size normalization, low-dimensional embedding, multi-omics factor analysis, multi-omics integration, neighbor graph construction, neighborhood graph construction, perturbation-aware regulatory-network analysis, probabilistic latent representation learning, reference-based cell-type annotation, single-cell quality control, spatial cell-type deconvolution, trajectory and pseudotime inference.

The v1 Core target is the 14-ecosystem `scientific_kg_v1_core` layer. The broader 19-ecosystem expansion remains a deferred coverage reference, while the UAT slice carries corrected candidate semantics for Scanpy, Harmony, Scrublet and SingleR.

## 5. Method → Operator → representations

### uat_decision_rule_correction

| Ecosystem | Method | Operator revision | Inputs | Outputs |
| --- | --- | --- | --- | --- |
| Scanpy | method:hvg_selection, method-variant:hvg.dispersion, method-variant:hvg.count | operator-revision:scanpy.pp.highly_variable_genes:1.11.2:uat-corrected | expression → representation-constraint:uat:hvg-counts, representation-constraint:uat:hvg-log | hvg_mask → representation-type:hvg_mask |
| Scanpy | method:pca, method-variant:pca.sckg-scaled-hvg-profile | operator-revision:scanpy.pp.pca:1.11.2:uat-corrected | expression → representation-constraint:uat:pca-expression; optional_feature_mask → representation-constraint:uat:pca-hvg-mask | pca_coordinates → representation-type:pca_coordinates |
| Scanpy | method:neighbor_graph_construction | operator-revision:scanpy.pp.neighbors:1.11.2:uat-corrected | X_or_obsm_representation → representation-constraint:uat:neighbors-embedding, representation-constraint:uat:neighbors-pca, representation-constraint:uat:neighbors-x | neighbor_graph → representation-type:neighbor_graph |
| Scanpy | method:umap | operator-revision:scanpy.tl.umap:1.11.2:uat-corrected | neighbor_graph_with_settings → representation-constraint:uat:neighbor-graph-reuse | umap_coordinates → representation-type:umap_coordinates |
| Scanpy | method:leiden | operator-revision:scanpy.tl.leiden:1.11.2:uat-corrected | neighbor_connectivities_or_adjacency → representation-constraint:uat:leiden-adjacency, representation-constraint:uat:leiden-neighbor-graph | cluster_labels → representation-type:cluster_labels |
| Harmony | method:harmony_integration, method-variant:harmony.pca-default, method-variant:harmony.generic-embedding | operator-revision:harmony.RunHarmony:2.0.5:uat-corrected | cell_embedding → representation-constraint:uat:harmony-generic, representation-constraint:uat:harmony-pca; batch_covariates → representation-constraint:uat:harmony-covariates | corrected_cell_embedding → representation-type:cell_embedding |
| Scrublet | method:scrublet | operator-revision:scrublet.Scrublet.scrub_doublets:0.2.3:uat-corrected | raw_counts_per_capture_unit → representation-constraint:uat:scrublet-raw | doublet_scores_and_calls → representation-type:doublet_assessment |
| SingleR | method:singler_annotation | operator-revision:SingleR::SingleR:2.14.1:uat-corrected | query_expression → representation-constraint:uat:singler-query-log, representation-constraint:uat:singler-query-raw; reference_expression → representation-constraint:uat:singler-reference-expression; reference_labels → representation-constraint:uat:singler-reference-labels | predicted_and_pruned_labels → representation-type:cell_type_labels |

### scientific_kg_v1_core

| Ecosystem | Method | Operator revision | Inputs | Outputs |
| --- | --- | --- | --- | --- |
| Scanpy | method:cell_filtering | operator-revision:scanpy.scanpy_pp_filter_cells:1.11.2 | raw_counts_input → representation-constraint:v1-core:scanpy:scanpy_pp_filter_cells:input1 | filtered_counts_output → representation-type:filtered_counts |
| Scanpy | method:total_count_normalization | operator-revision:scanpy.scanpy_pp_normalize_total:1.11.2 | filtered_counts_input → representation-constraint:v1-core:scanpy:scanpy_pp_normalize_total:input1 | normalized_counts_output → representation-type:normalized_counts |
| Scanpy | method:log_transform | operator-revision:scanpy.scanpy_pp_log1p:1.11.2 | normalized_counts_input → representation-constraint:v1-core:scanpy:scanpy_pp_log1p:input1 | log_expression_output → representation-type:log_expression |
| Scanpy | method:hvg_selection | operator-revision:scanpy.scanpy_pp_highly_variable_genes:1.11.2 | log_expression_input → representation-constraint:v1-core:scanpy:scanpy_pp_highly_variable_genes:input1 | hvg_mask_output → representation-type:hvg_mask |
| Scanpy | method:pca | operator-revision:scanpy.scanpy_pp_pca:1.11.2 | log_expression_input → representation-constraint:v1-core:scanpy:scanpy_pp_pca:input1 | pca_coordinates_output → representation-type:pca_coordinates |
| Scanpy | method:neighbor_graph_construction | operator-revision:scanpy.scanpy_pp_neighbors:1.11.2 | pca_coordinates_input → representation-constraint:v1-core:scanpy:scanpy_pp_neighbors:input1 | neighbor_graph_output → representation-type:neighbor_graph |
| Scanpy | method:umap | operator-revision:scanpy.scanpy_tl_umap:1.11.2 | neighbor_graph_input → representation-constraint:v1-core:scanpy:scanpy_tl_umap:input1 | umap_coordinates_output → representation-type:umap_coordinates |
| Scanpy | method:leiden | operator-revision:scanpy.scanpy_tl_leiden:1.11.2 | neighbor_graph_input → representation-constraint:v1-core:scanpy:scanpy_tl_leiden:input1 | cluster_labels_output → representation-type:cluster_labels |
| Scanpy | method:group_differential_testing | operator-revision:scanpy.scanpy_tl_rank_genes_groups:1.11.2 | log_expression_input → representation-constraint:v1-core:scanpy:scanpy_tl_rank_genes_groups:input1; cluster_labels_input → representation-constraint:v1-core:scanpy:scanpy_tl_rank_genes_groups:input2 | marker_statistics_output → representation-type:marker_statistics |
| Seurat | method:total_count_normalization | operator-revision:seurat.seurat__normalizedata:5.5.1 | filtered_counts_input → representation-constraint:v1-core:seurat:seurat__normalizedata:input1 | log_expression_output → representation-type:log_expression |
| Seurat | method:hvg_selection | operator-revision:seurat.seurat__findvariablefeatures:5.5.1 | log_expression_input → representation-constraint:v1-core:seurat:seurat__findvariablefeatures:input1 | hvg_mask_output → representation-type:hvg_mask |
| Seurat | method:pca | operator-revision:seurat.seurat__runpca:5.5.1 | log_expression_input → representation-constraint:v1-core:seurat:seurat__runpca:input1 | pca_coordinates_output → representation-type:pca_coordinates |
| Seurat | method:neighbor_graph_construction | operator-revision:seurat.seurat__findneighbors:5.5.1 | pca_coordinates_input → representation-constraint:v1-core:seurat:seurat__findneighbors:input1 | neighbor_graph_output → representation-type:neighbor_graph |
| Seurat | method:leiden | operator-revision:seurat.seurat__findclusters:5.5.1 | neighbor_graph_input → representation-constraint:v1-core:seurat:seurat__findclusters:input1 | cluster_labels_output → representation-type:cluster_labels |
| Seurat | method:group_differential_testing | operator-revision:seurat.seurat__findmarkers:5.5.1 | log_expression_input → representation-constraint:v1-core:seurat:seurat__findmarkers:input1; cluster_labels_input → representation-constraint:v1-core:seurat:seurat__findmarkers:input2 | marker_statistics_output → representation-type:marker_statistics |
| Harmony | method:harmony_integration | operator-revision:harmony.harmony__runharmony:2.0.5 | pca_coordinates_input → representation-constraint:v1-core:harmony:harmony__runharmony:input1; batch_covariates_input → representation-constraint:v1-core:harmony:harmony__runharmony:input2 | integrated_coordinates_output → representation-type:integrated_coordinates |
| scvi-tools | method:scvi | operator-revision:scvi_tools.scvi_model_scvi_setup_anndata:1.5.0.post1 | raw_counts_input → representation-constraint:v1-core:scvi_tools:scvi_model_scvi_setup_anndata:input1; batch_covariates_input → representation-constraint:v1-core:scvi_tools:scvi_model_scvi_setup_anndata:input2 | registered_anndata_output → representation-type:registered_anndata |
| scvi-tools | method:scvi | operator-revision:scvi_tools.scvi_model_scvi_train:1.5.0.post1 | registered_anndata_input → representation-constraint:v1-core:scvi_tools:scvi_model_scvi_train:input1 | trained_scvi_model_output → representation-type:trained_scvi_model |
| scvi-tools | method:scvi | operator-revision:scvi_tools.scvi_model_scvi_get_latent_representation:1.5.0.post1 | trained_scvi_model_input → representation-constraint:v1-core:scvi_tools:scvi_model_scvi_get_latent_representation:input1 | integrated_coordinates_output → representation-type:integrated_coordinates |
| scvi-tools | method:totalvi | operator-revision:scvi_tools.scvi_model_totalvi_setup_anndata:1.5.0.post1 | raw_counts_input → representation-constraint:v1-core:scvi_tools:scvi_model_totalvi_setup_anndata:input1; protein_counts_input → representation-constraint:v1-core:scvi_tools:scvi_model_totalvi_setup_anndata:input2; batch_covariates_input → representation-constraint:v1-core:scvi_tools:scvi_model_totalvi_setup_anndata:input3 | registered_multimodal_anndata_output → representation-type:registered_multimodal_anndata |
| scvi-tools | method:totalvi | operator-revision:scvi_tools.scvi_model_totalvi_train:1.5.0.post1 | registered_multimodal_anndata_input → representation-constraint:v1-core:scvi_tools:scvi_model_totalvi_train:input1 | trained_totalvi_model_output → representation-type:trained_totalvi_model |
| scvi-tools | method:totalvi | operator-revision:scvi_tools.scvi_model_totalvi_get_latent_representation:1.5.0.post1 | trained_totalvi_model_input → representation-constraint:v1-core:scvi_tools:scvi_model_totalvi_get_latent_representation:input1 | integrated_coordinates_output → representation-type:integrated_coordinates |
| Scrublet | method:scrublet | operator-revision:scrublet.scrublet_scrublet_scrub_doublets:0.2.3 | raw_counts_input → representation-constraint:v1-core:scrublet:scrublet_scrublet_scrub_doublets:input1 | doublet_scores_output → representation-type:doublet_scores |
| SoupX | method:ambient_contamination_estimation | operator-revision:soupx.soupx__autoestcont:1.6.2 | raw_counts_input → representation-constraint:v1-core:soupx:soupx__autoestcont:input1; cluster_labels_input → representation-constraint:v1-core:soupx:soupx__autoestcont:input2 | contamination_model_output → representation-type:contamination_model |
| SoupX | method:ambient_count_correction | operator-revision:soupx.soupx__adjustcounts:1.6.2 | raw_counts_input → representation-constraint:v1-core:soupx:soupx__adjustcounts:input1; contamination_model_input → representation-constraint:v1-core:soupx:soupx__adjustcounts:input2 | corrected_counts_output → representation-type:corrected_counts |
| CellTypist | method:celltypist_annotation | operator-revision:celltypist.celltypist_annotate:1.7.1 | log_expression_input → representation-constraint:v1-core:celltypist:celltypist_annotate:input1 | cell_type_labels_output → representation-type:cell_type_labels |
| SingleR | method:singler_annotation | operator-revision:singler.singler__singler:2.14.1 | log_expression_input → representation-constraint:v1-core:singler:singler__singler:input1; reference_expression_input → representation-constraint:v1-core:singler:singler__singler:input2 | cell_type_labels_output → representation-type:cell_type_labels |
| edgeR | method:negative_binomial_de | operator-revision:edger.edger__dgelist:4.10.5 | pseudobulk_counts_input → representation-constraint:v1-core:edger:edger__dgelist:input1 | edger_dge_output → representation-type:edger_dge |
| edgeR | method:negative_binomial_de | operator-revision:edger.edger__calcnormfactors:4.10.5 | edger_dge_input → representation-constraint:v1-core:edger:edger__calcnormfactors:input1 | edger_dge_output → representation-type:edger_dge |
| edgeR | method:negative_binomial_de | operator-revision:edger.edger__glmqlfit:4.10.5 | edger_dge_input → representation-constraint:v1-core:edger:edger__glmqlfit:input1; design_matrix_input → representation-constraint:v1-core:edger:edger__glmqlfit:input2 | de_model_output → representation-type:de_model |
| edgeR | method:negative_binomial_de | operator-revision:edger.edger__glmqlftest:4.10.5 | de_model_input → representation-constraint:v1-core:edger:edger__glmqlftest:input1; design_matrix_input → representation-constraint:v1-core:edger:edger__glmqlftest:input2 | marker_statistics_output → representation-type:marker_statistics |
| Slingshot | method:slingshot_trajectory | operator-revision:slingshot.slingshot__slingshot:2.20.0 | reduced_coordinates_input → representation-constraint:v1-core:slingshot:slingshot__slingshot:input1; cluster_labels_input → representation-constraint:v1-core:slingshot:slingshot__slingshot:input2 | lineage_pseudotime_output → representation-type:lineage_pseudotime |
| scVelo | method:rna_velocity | operator-revision:scvelo.scvelo_pp_moments:0.3.4 | spliced_unspliced_input → representation-constraint:v1-core:scvelo:scvelo_pp_moments:input1; neighbor_graph_input → representation-constraint:v1-core:scvelo:scvelo_pp_moments:input2 | moments_output → representation-type:moments |
| scVelo | method:rna_velocity | operator-revision:scvelo.scvelo_tl_velocity:0.3.4 | moments_input → representation-constraint:v1-core:scvelo:scvelo_tl_velocity:input1 | velocity_vectors_output → representation-type:velocity_vectors |
| scVelo | method:rna_velocity | operator-revision:scvelo.scvelo_tl_velocity_graph:0.3.4 | velocity_vectors_input → representation-constraint:v1-core:scvelo:scvelo_tl_velocity_graph:input1; neighbor_graph_input → representation-constraint:v1-core:scvelo:scvelo_tl_velocity_graph:input2 | transition_matrix_output → representation-type:transition_matrix |
| CellRank | method:velocity_fate_mapping | operator-revision:cellrank.cellrank_kernels_velocitykernel_compute_transition_matrix:2.3.2 | velocity_vectors_input → representation-constraint:v1-core:cellrank:cellrank_kernels_velocitykernel_compute_transition_matrix:input1; neighbor_graph_input → representation-constraint:v1-core:cellrank:cellrank_kernels_velocitykernel_compute_transition_matrix:input2 | transition_matrix_output → representation-type:transition_matrix |
| CellRank | method:gpcca_fate_mapping | operator-revision:cellrank.cellrank_estimators_gpcca_compute_macrostates:2.3.2 | transition_matrix_input → representation-constraint:v1-core:cellrank:cellrank_estimators_gpcca_compute_macrostates:input1 | macrostates_output → representation-type:macrostates |
| CellRank | method:gpcca_fate_mapping | operator-revision:cellrank.cellrank_estimators_gpcca_compute_fate_probabilities:2.3.2 | transition_matrix_input → representation-constraint:v1-core:cellrank:cellrank_estimators_gpcca_compute_fate_probabilities:input1; macrostates_input → representation-constraint:v1-core:cellrank:cellrank_estimators_gpcca_compute_fate_probabilities:input2 | fate_probabilities_output → representation-type:fate_probabilities |
| MOFA2 | method:mofa | operator-revision:mofa2.mofa2__create_mofa:1.22.1 | multiomics_matrices_input → representation-constraint:v1-core:mofa2:mofa2__create_mofa:input1 | mofa_model_config_output → representation-type:mofa_model_config |
| MOFA2 | method:mofa | operator-revision:mofa2.mofa2__prepare_mofa:1.22.1 | mofa_model_config_input → representation-constraint:v1-core:mofa2:mofa2__prepare_mofa:input1 | mofa_prepared_model_output → representation-type:mofa_prepared_model |
| MOFA2 | method:mofa | operator-revision:mofa2.mofa2__run_mofa:1.22.1 | mofa_prepared_model_input → representation-constraint:v1-core:mofa2:mofa2__run_mofa:input1 | latent_factors_output → representation-type:latent_factors |
| pySCENIC | method:grn_inference | operator-revision:pyscenic.pyscenic_grn:0.12.1 | gene_expression_input → representation-constraint:v1-core:pyscenic:pyscenic_grn:input1 | grn_adjacencies_output → representation-type:grn_adjacencies |
| pySCENIC | method:motif_pruning | operator-revision:pyscenic.pyscenic_ctx:0.12.1 | grn_adjacencies_input → representation-constraint:v1-core:pyscenic:pyscenic_ctx:input1 | regulons_output → representation-type:regulons |
| pySCENIC | method:regulon_activity_scoring | operator-revision:pyscenic.pyscenic_aucell:0.12.1 | gene_expression_input → representation-constraint:v1-core:pyscenic:pyscenic_aucell:input1; regulons_input → representation-constraint:v1-core:pyscenic:pyscenic_aucell:input2 | regulon_activity_output → representation-type:regulon_activity |

## 6. Cross-tool compatibility

| Layer | Source | Relation | Target | Claim provenance |
| --- | --- | --- | --- | --- |
| uat_decision_rule_correction | operator-revision:harmony.RunHarmony:2.0.5:uat-corrected | CAN_FEED | operator-revision:scanpy.pp.neighbors:1.11.2:uat-corrected | claim-revision:uat:harmony-output:v1, claim-revision:uat:neighbors-input:v1 |
| scientific_kg_v1_core | operator-revision:scanpy.scanpy_tl_leiden:1.11.2 | CAN_FEED | operator-revision:seurat.seurat__findmarkers:5.5.1 |  |
| scientific_kg_v1_core | operator-revision:scanpy.scanpy_tl_leiden:1.11.2 | CAN_FEED | operator-revision:soupx.soupx__autoestcont:1.6.2 |  |
| scientific_kg_v1_core | operator-revision:scanpy.scanpy_tl_leiden:1.11.2 | CAN_FEED | operator-revision:slingshot.slingshot__slingshot:2.20.0 |  |
| scientific_kg_v1_core | operator-revision:seurat.seurat__findclusters:5.5.1 | CAN_FEED | operator-revision:scanpy.scanpy_tl_rank_genes_groups:1.11.2 |  |
| scientific_kg_v1_core | operator-revision:seurat.seurat__findclusters:5.5.1 | CAN_FEED | operator-revision:soupx.soupx__autoestcont:1.6.2 |  |
| scientific_kg_v1_core | operator-revision:seurat.seurat__findclusters:5.5.1 | CAN_FEED | operator-revision:slingshot.slingshot__slingshot:2.20.0 |  |
| scientific_kg_v1_core | operator-revision:scanpy.scanpy_pp_filter_cells:1.11.2 | CAN_FEED | operator-revision:seurat.seurat__normalizedata:5.5.1 |  |
| scientific_kg_v1_core | operator-revision:scanpy.scanpy_pp_log1p:1.11.2 | CAN_FEED | operator-revision:seurat.seurat__findvariablefeatures:5.5.1 |  |
| scientific_kg_v1_core | operator-revision:scanpy.scanpy_pp_log1p:1.11.2 | CAN_FEED | operator-revision:seurat.seurat__runpca:5.5.1 |  |
| scientific_kg_v1_core | operator-revision:scanpy.scanpy_pp_log1p:1.11.2 | CAN_FEED | operator-revision:seurat.seurat__findmarkers:5.5.1 |  |
| scientific_kg_v1_core | operator-revision:scanpy.scanpy_pp_log1p:1.11.2 | CAN_FEED | operator-revision:celltypist.celltypist_annotate:1.7.1 |  |
| scientific_kg_v1_core | operator-revision:scanpy.scanpy_pp_log1p:1.11.2 | CAN_FEED | operator-revision:singler.singler__singler:2.14.1 |  |
| scientific_kg_v1_core | operator-revision:seurat.seurat__normalizedata:5.5.1 | CAN_FEED | operator-revision:scanpy.scanpy_pp_highly_variable_genes:1.11.2 |  |
| scientific_kg_v1_core | operator-revision:seurat.seurat__normalizedata:5.5.1 | CAN_FEED | operator-revision:scanpy.scanpy_pp_pca:1.11.2 |  |
| scientific_kg_v1_core | operator-revision:seurat.seurat__normalizedata:5.5.1 | CAN_FEED | operator-revision:scanpy.scanpy_tl_rank_genes_groups:1.11.2 |  |
| scientific_kg_v1_core | operator-revision:seurat.seurat__normalizedata:5.5.1 | CAN_FEED | operator-revision:celltypist.celltypist_annotate:1.7.1 |  |
| scientific_kg_v1_core | operator-revision:seurat.seurat__normalizedata:5.5.1 | CAN_FEED | operator-revision:singler.singler__singler:2.14.1 |  |
| scientific_kg_v1_core | operator-revision:scanpy.scanpy_pp_neighbors:1.11.2 | CAN_FEED | operator-revision:seurat.seurat__findclusters:5.5.1 |  |
| scientific_kg_v1_core | operator-revision:scanpy.scanpy_pp_neighbors:1.11.2 | CAN_FEED | operator-revision:scvelo.scvelo_pp_moments:0.3.4 |  |
| scientific_kg_v1_core | operator-revision:scanpy.scanpy_pp_neighbors:1.11.2 | CAN_FEED | operator-revision:scvelo.scvelo_tl_velocity_graph:0.3.4 |  |
| scientific_kg_v1_core | operator-revision:scanpy.scanpy_pp_neighbors:1.11.2 | CAN_FEED | operator-revision:cellrank.cellrank_kernels_velocitykernel_compute_transition_matrix:2.3.2 |  |
| scientific_kg_v1_core | operator-revision:seurat.seurat__findneighbors:5.5.1 | CAN_FEED | operator-revision:scanpy.scanpy_tl_umap:1.11.2 |  |
| scientific_kg_v1_core | operator-revision:seurat.seurat__findneighbors:5.5.1 | CAN_FEED | operator-revision:scanpy.scanpy_tl_leiden:1.11.2 |  |
| scientific_kg_v1_core | operator-revision:seurat.seurat__findneighbors:5.5.1 | CAN_FEED | operator-revision:scvelo.scvelo_pp_moments:0.3.4 |  |
| scientific_kg_v1_core | operator-revision:seurat.seurat__findneighbors:5.5.1 | CAN_FEED | operator-revision:scvelo.scvelo_tl_velocity_graph:0.3.4 |  |
| scientific_kg_v1_core | operator-revision:seurat.seurat__findneighbors:5.5.1 | CAN_FEED | operator-revision:cellrank.cellrank_kernels_velocitykernel_compute_transition_matrix:2.3.2 |  |
| scientific_kg_v1_core | operator-revision:scanpy.scanpy_pp_pca:1.11.2 | CAN_FEED | operator-revision:seurat.seurat__findneighbors:5.5.1 |  |
| scientific_kg_v1_core | operator-revision:scanpy.scanpy_pp_pca:1.11.2 | CAN_FEED | operator-revision:harmony.harmony__runharmony:2.0.5 |  |
| scientific_kg_v1_core | operator-revision:seurat.seurat__runpca:5.5.1 | CAN_FEED | operator-revision:scanpy.scanpy_pp_neighbors:1.11.2 |  |
| scientific_kg_v1_core | operator-revision:seurat.seurat__runpca:5.5.1 | CAN_FEED | operator-revision:harmony.harmony__runharmony:2.0.5 |  |
| scientific_kg_v1_core | operator-revision:scvelo.scvelo_tl_velocity_graph:0.3.4 | CAN_FEED | operator-revision:cellrank.cellrank_estimators_gpcca_compute_macrostates:2.3.2 |  |
| scientific_kg_v1_core | operator-revision:scvelo.scvelo_tl_velocity_graph:0.3.4 | CAN_FEED | operator-revision:cellrank.cellrank_estimators_gpcca_compute_fate_probabilities:2.3.2 |  |
| scientific_kg_v1_core | operator-revision:scvelo.scvelo_tl_velocity:0.3.4 | CAN_FEED | operator-revision:cellrank.cellrank_kernels_velocitykernel_compute_transition_matrix:2.3.2 |  |
| content_expansion_v1 | operator-revision:harmony.run_harmony:source-snapshot | CAN_FEED | operator-revision:scanpy.pp.neighbors:1.11.2 | claim-revision:content-expansion:05b88d8934c8713ac68e2fa4:v1, claim-revision:scanpy-core:scanpy-pp-neighbors-requires_representation_constraint-5:candidate-1 |

## 7. Evidence and status

| Status | Count |
| --- | --- |
| Promoted/trusted scientific claims | 0 |
| Candidate claims | 380 |
| Candidate derived relations | 256 |
| Trusted source-evidence spans | 119 |
| Other source-bound evidence candidates | 32 |
| Evidence SUPPORTS edges | 481 |
| Explicit EvidenceGaps | 77 |
| Deferred/reference-layer nodes | 456 |

## 8. Representative subgraphs

### preprocessing

| Ecosystem | Method | Operator | Input ports | Output representations |
| --- | --- | --- | --- | --- |
| Scanpy | method:hvg_selection, method-variant:hvg.dispersion, method-variant:hvg.count | operator-revision:scanpy.pp.highly_variable_genes:1.11.2:uat-corrected | expression | representation-type:hvg_mask |
| Scanpy | method:pca, method-variant:pca.sckg-scaled-hvg-profile | operator-revision:scanpy.pp.pca:1.11.2:uat-corrected | expression, optional_feature_mask | representation-type:pca_coordinates |
| Scanpy | method:neighbor_graph_construction | operator-revision:scanpy.pp.neighbors:1.11.2:uat-corrected | X_or_obsm_representation | representation-type:neighbor_graph |

### integration

| Ecosystem | Method | Operator | Input ports | Output representations |
| --- | --- | --- | --- | --- |
| Scanpy | method:neighbor_graph_construction | operator-revision:scanpy.pp.neighbors:1.11.2:uat-corrected | X_or_obsm_representation | representation-type:neighbor_graph |
| Harmony | method:harmony_integration, method-variant:harmony.pca-default, method-variant:harmony.generic-embedding | operator-revision:harmony.RunHarmony:2.0.5:uat-corrected | cell_embedding, batch_covariates | representation-type:cell_embedding |

### annotation

| Ecosystem | Method | Operator | Input ports | Output representations |
| --- | --- | --- | --- | --- |
| SingleR | method:singler_annotation | operator-revision:SingleR::SingleR:2.14.1:uat-corrected | query_expression, reference_expression, reference_labels | representation-type:cell_type_labels |

### trajectory

| Ecosystem | Method | Operator | Input ports | Output representations |
| --- | --- | --- | --- | --- |
| Slingshot | method:slingshot_trajectory | operator-revision:slingshot.slingshot__slingshot:2.20.0 | reduced_coordinates_input, cluster_labels_input | representation-type:lineage_pseudotime |
| scVelo | method:rna_velocity | operator-revision:scvelo.scvelo_pp_moments:0.3.4 | spliced_unspliced_input, neighbor_graph_input | representation-type:moments |
| scVelo | method:rna_velocity | operator-revision:scvelo.scvelo_tl_velocity:0.3.4 | moments_input | representation-type:velocity_vectors |
| scVelo | method:rna_velocity | operator-revision:scvelo.scvelo_tl_velocity_graph:0.3.4 | velocity_vectors_input, neighbor_graph_input | representation-type:transition_matrix |
| CellRank | method:velocity_fate_mapping | operator-revision:cellrank.cellrank_kernels_velocitykernel_compute_transition_matrix:2.3.2 | velocity_vectors_input, neighbor_graph_input | representation-type:transition_matrix |
| CellRank | method:gpcca_fate_mapping | operator-revision:cellrank.cellrank_estimators_gpcca_compute_macrostates:2.3.2 | transition_matrix_input | representation-type:macrostates |
| CellRank | method:gpcca_fate_mapping | operator-revision:cellrank.cellrank_estimators_gpcca_compute_fate_probabilities:2.3.2 | transition_matrix_input, macrostates_input | representation-type:fate_probabilities |

### multi_omics

| Ecosystem | Method | Operator | Input ports | Output representations |
| --- | --- | --- | --- | --- |
| scvi-tools | method:totalvi | operator-revision:scvi_tools.scvi_model_totalvi_setup_anndata:1.5.0.post1 | raw_counts_input, protein_counts_input, batch_covariates_input | representation-type:registered_multimodal_anndata |
| scvi-tools | method:totalvi | operator-revision:scvi_tools.scvi_model_totalvi_train:1.5.0.post1 | registered_multimodal_anndata_input | representation-type:trained_totalvi_model |
| scvi-tools | method:totalvi | operator-revision:scvi_tools.scvi_model_totalvi_get_latent_representation:1.5.0.post1 | trained_totalvi_model_input | representation-type:integrated_coordinates |
| MOFA2 | method:mofa | operator-revision:mofa2.mofa2__create_mofa:1.22.1 | multiomics_matrices_input | representation-type:mofa_model_config |
| MOFA2 | method:mofa | operator-revision:mofa2.mofa2__prepare_mofa:1.22.1 | mofa_model_config_input | representation-type:mofa_prepared_model |
| MOFA2 | method:mofa | operator-revision:mofa2.mofa2__run_mofa:1.22.1 | mofa_prepared_model_input | representation-type:latent_factors |

### regulatory

| Ecosystem | Method | Operator | Input ports | Output representations |
| --- | --- | --- | --- | --- |
| pySCENIC | method:grn_inference | operator-revision:pyscenic.pyscenic_grn:0.12.1 | gene_expression_input | representation-type:grn_adjacencies |
| pySCENIC | method:motif_pruning | operator-revision:pyscenic.pyscenic_ctx:0.12.1 | grn_adjacencies_input | representation-type:regulons |
| pySCENIC | method:regulon_activity_scoring | operator-revision:pyscenic.pyscenic_aucell:0.12.1 | gene_expression_input, regulons_input | representation-type:regulon_activity |

## Machine-readable graph

`data/evidence_candidates/scientific_kg_v1_inventory/scientific_kg_v1_consolidated_graph.json`

The graph includes all frozen layer records, structural identity/port edges, AtomicClaim links, derived relations, evidence SUPPORTS links, EvidenceGaps and representative subgraph views.
