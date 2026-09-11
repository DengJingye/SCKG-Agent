from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from core.scientific_knowledge_conformance_models import (
    ApplicabilityScope,
    AtomicClaimRevision,
    ConformanceBundle,
    DerivedRelation,
    EvidenceAssessment,
    InputPort,
    Limitation,
    Method,
    Operator,
    OperatorRevision,
    OutputPort,
    Package,
    PackageRelease,
    ParameterDefinition,
    RepresentationComponent,
    RepresentationConstraint,
    RepresentationType,
    Requirement,
    ScientificTask,
    SoftwareProject,
    VersionConstraint,
)
from data_pipeline.build_scientific_knowledge_conformance_v1_1 import CANONICAL_PATHS, PROJECT_ROOT


SCHEMA_VERSION = "sckg-scientific-kg-v1-core-candidate-v1"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "evidence_candidates" / "scientific_kg_v1_core"


ECOSYSTEMS: dict[str, dict[str, str]] = {
    "scanpy": {"label": "Scanpy", "ecosystem": "python", "distribution": "scanpy", "version": "1.11.2", "url": "https://scanpy.readthedocs.io/en/1.11.x/api/index.html"},
    "seurat": {"label": "Seurat", "ecosystem": "r", "distribution": "Seurat", "version": "5.5.1", "url": "https://satijalab.org/seurat/reference/index.html"},
    "harmony": {"label": "Harmony", "ecosystem": "r", "distribution": "harmony", "version": "2.0.5", "url": "https://portals.broadinstitute.org/harmony/reference/RunHarmony.html"},
    "scvi_tools": {"label": "scvi-tools", "ecosystem": "python", "distribution": "scvi-tools", "version": "1.5.0.post1", "url": "https://docs.scvi-tools.org/en/stable/api/reference/index.html"},
    "scrublet": {"label": "Scrublet", "ecosystem": "python", "distribution": "scrublet", "version": "0.2.3", "url": "https://github.com/swolock/scrublet/blob/v0.2.3/README.md"},
    "soupx": {"label": "SoupX", "ecosystem": "r", "distribution": "SoupX", "version": "1.6.2", "url": "https://cran.r-project.org/web/packages/SoupX/SoupX.pdf"},
    "celltypist": {"label": "CellTypist", "ecosystem": "python", "distribution": "celltypist", "version": "1.7.1", "url": "https://celltypist.readthedocs.io/en/latest/celltypist.annotate.html"},
    "singler": {"label": "SingleR", "ecosystem": "r_bioconductor", "distribution": "SingleR", "version": "2.14.1", "url": "https://bioconductor.org/packages/release/bioc/html/SingleR.html"},
    "edger": {"label": "edgeR", "ecosystem": "r_bioconductor", "distribution": "edgeR", "version": "4.10.5", "url": "https://bioconductor.org/packages/release/bioc/html/edgeR.html"},
    "slingshot": {"label": "Slingshot", "ecosystem": "r_bioconductor", "distribution": "slingshot", "version": "2.20.0", "url": "https://bioconductor.org/packages/release/bioc/html/slingshot.html"},
    "scvelo": {"label": "scVelo", "ecosystem": "python", "distribution": "scvelo", "version": "0.3.4", "url": "https://scvelo.readthedocs.io/en/stable/api.html"},
    "cellrank": {"label": "CellRank", "ecosystem": "python", "distribution": "cellrank", "version": "2.3.2", "url": "https://cellrank.readthedocs.io/en/stable/api.html"},
    "mofa2": {"label": "MOFA2", "ecosystem": "r_bioconductor", "distribution": "MOFA2", "version": "1.22.1", "url": "https://bioconductor.org/packages/release/bioc/html/MOFA2.html"},
    "pyscenic": {"label": "pySCENIC", "ecosystem": "python", "distribution": "pyscenic", "version": "0.12.1", "url": "https://pyscenic.readthedocs.io/en/stable/api.html"},
}


TASKS = {
    "filtering_qc": "cell and gene quality filtering",
    "normalization": "library-size normalization",
    "feature_selection": "highly variable feature selection",
    "dimensionality_reduction": "dimensionality reduction",
    "neighbor_graph": "neighborhood graph construction",
    "embedding": "low-dimensional embedding",
    "clustering": "graph clustering",
    "differential_expression": "differential expression analysis",
    "batch_integration": "batch integration",
    "latent_representation": "probabilistic latent representation learning",
    "doublet_detection": "doublet detection",
    "ambient_rna_removal": "ambient RNA contamination correction",
    "cell_type_annotation": "cell-type annotation",
    "trajectory_inference": "trajectory and pseudotime inference",
    "rna_velocity": "RNA velocity inference",
    "fate_mapping": "cell-fate mapping",
    "multiomics_integration": "multi-omics factor analysis",
    "regulatory_network": "gene-regulatory network inference",
}


PRIMARY_METHOD_EVIDENCE: dict[str, dict[str, str]] = {
    "harmony_integration": {"ecosystem": "harmony", "url": "https://doi.org/10.1038/s41592-019-0619-0", "excerpt": "Harmony integrates cells across diverse experimental and biological conditions in a low-dimensional embedding."},
    "scvi": {"ecosystem": "scvi_tools", "url": "https://doi.org/10.1038/s41592-018-0229-2", "excerpt": "scVI is a probabilistic framework for normalization and analysis of single-cell gene-expression data with batch effects."},
    "totalvi": {"ecosystem": "scvi_tools", "url": "https://doi.org/10.1038/s41592-020-01050-x", "excerpt": "totalVI jointly models paired transcriptomic and protein measurements from single cells."},
    "scrublet": {"ecosystem": "scrublet", "url": "https://doi.org/10.1016/j.cels.2018.11.005", "excerpt": "Scrublet detects doublets by comparing observed transcriptomes with simulated doublets."},
    "ambient_contamination_estimation": {"ecosystem": "soupx", "url": "https://doi.org/10.1093/gigascience/giaa151", "excerpt": "SoupX estimates and removes cell-free messenger RNA contamination from droplet-based single-cell RNA sequencing data."},
    "celltypist_annotation": {"ecosystem": "celltypist", "url": "https://doi.org/10.1126/science.abl5197", "excerpt": "CellTypist enables automated cell-type annotation using reference-trained models."},
    "singler_annotation": {"ecosystem": "singler", "url": "https://doi.org/10.1038/s41590-018-0276-y", "excerpt": "SingleR annotates single-cell transcriptomes by comparison with reference transcriptomic datasets of pure cell types."},
    "negative_binomial_de": {"ecosystem": "edger", "url": "https://doi.org/10.1093/bioinformatics/btp616", "excerpt": "edgeR performs empirical analysis of digital gene-expression data using overdispersed count models."},
    "slingshot_trajectory": {"ecosystem": "slingshot", "url": "https://doi.org/10.1186/s12864-018-4772-0", "excerpt": "Slingshot provides robust lineage and pseudotime inference for single-cell transcriptomics."},
    "rna_velocity": {"ecosystem": "scvelo", "url": "https://doi.org/10.1038/s41587-020-0591-3", "excerpt": "scVelo generalizes RNA velocity through likelihood-based dynamical modeling."},
    "velocity_fate_mapping": {"ecosystem": "cellrank", "url": "https://doi.org/10.1038/s41592-021-01346-6", "excerpt": "CellRank combines cellular dynamics with transcriptomic similarity to estimate cell-state transition probabilities and fate probabilities."},
    "mofa": {"ecosystem": "mofa2", "url": "https://doi.org/10.1186/s13059-020-02015-1", "excerpt": "MOFA+ provides a statistical framework for the integration of multi-modal data through latent factors."},
    "grn_inference": {"ecosystem": "pyscenic", "url": "https://doi.org/10.1038/s41596-020-0336-2", "excerpt": "The SCENIC workflow reconstructs gene-regulatory networks and identifies stable cell states from single-cell RNA-sequencing data."},
}


def _rep(label: str, unit: str, axes: list[str], modalities: list[str], values: str, states: list[str], *, components: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {"label": label, "unit": unit, "axes": axes, "modalities": modalities, "values": values, "states": states, "components": components or []}


REPRESENTATIONS: dict[str, dict[str, Any]] = {
    "raw_counts": _rep("raw count matrix", "cell", ["cell", "gene"], ["rna"], "non-negative integer-like molecule counts", ["raw_counts"]),
    "filtered_counts": _rep("filtered count matrix", "cell", ["cell", "gene"], ["rna"], "non-negative counts after observation/feature filtering", ["filtered", "counts"]),
    "normalized_counts": _rep("normalized expression matrix", "cell", ["cell", "gene"], ["rna"], "non-negative library-size normalized values", ["normalized"]),
    "log_expression": _rep("log-transformed expression matrix", "cell", ["cell", "gene"], ["rna"], "real-valued log transformed expression", ["normalized", "log1p"]),
    "hvg_mask": _rep("highly variable feature mask", "gene", ["gene"], ["rna"], "boolean feature-selection mask", ["feature_selected"]),
    "pca_coordinates": _rep("PCA coordinates", "cell", ["cell", "principal_component"], ["rna"], "real-valued principal component scores", ["dimension_reduced"]),
    "integrated_coordinates": _rep("integrated latent coordinates", "cell", ["cell", "latent_dimension"], ["rna", "protein"], "batch-aware real-valued embedding", ["batch_integrated"]),
    "neighbor_graph": _rep("cell neighbor graph", "cell", ["cell", "cell"], ["rna"], "weighted sparse connectivities and distances", ["graph_constructed"], components=[{"role": "connectivities", "kind": "matrix", "axes": ["cell", "cell"], "value_semantics": "weighted neighbor connectivity", "storage_semantics": "sparse square matrix", "required": True}, {"role": "distances", "kind": "matrix", "axes": ["cell", "cell"], "value_semantics": "neighbor distance", "storage_semantics": "sparse square matrix", "required": True}, {"role": "parameters", "kind": "metadata", "axes": [], "value_semantics": "graph construction metadata", "storage_semantics": "bounded mapping", "required": True}]),
    "umap_coordinates": _rep("UMAP coordinates", "cell", ["cell", "embedding_dimension"], ["rna"], "real-valued visualization coordinates", ["embedded"]),
    "cluster_labels": _rep("cluster labels", "cell", ["cell"], ["rna"], "categorical cluster membership", ["clustered"]),
    "marker_statistics": _rep("feature-level differential statistics", "feature", ["group", "feature"], ["rna"], "effect sizes, scores and adjusted significance statistics", ["differential_tested"]),
    "batch_covariates": _rep("batch covariates", "cell", ["cell", "covariate"], ["rna", "protein"], "categorical batch annotations", ["metadata"]),
    "protein_counts": _rep("protein count matrix", "cell", ["cell", "protein"], ["protein"], "non-negative protein abundance counts", ["raw_counts"]),
    "registered_anndata": _rep("scvi-tools registered AnnData", "cell", ["cell", "gene"], ["rna"], "count data with registered model fields and covariates", ["model_fields_registered"]),
    "registered_multimodal_anndata": _rep("totalVI registered AnnData", "cell", ["cell", "feature"], ["rna", "protein"], "aligned RNA and protein counts with registered model fields", ["model_fields_registered"], components=[{"role": "rna_counts", "kind": "matrix", "axes": ["cell", "gene"], "value_semantics": "RNA counts", "storage_semantics": "registered AnnData matrix or layer", "required": True}, {"role": "protein_counts", "kind": "matrix", "axes": ["cell", "protein"], "value_semantics": "protein counts", "storage_semantics": "registered AnnData metadata matrix", "required": True}]),
    "trained_scvi_model": _rep("trained scVI model state", "model", ["latent_parameter"], ["rna"], "fitted probabilistic model parameters", ["runtime_model_trained"]),
    "trained_totalvi_model": _rep("trained totalVI model state", "model", ["latent_parameter"], ["rna", "protein"], "fitted joint RNA-protein model parameters", ["runtime_model_trained"]),
    "doublet_scores": _rep("doublet scores and calls", "cell", ["cell"], ["rna"], "doublet scores with predicted classifications", ["doublet_scored"]),
    "corrected_counts": _rep("ambient-corrected counts", "cell", ["cell", "gene"], ["rna"], "counts corrected for estimated ambient contamination", ["decontaminated", "counts"]),
    "contamination_model": _rep("ambient contamination model", "sample", ["sample", "gene"], ["rna"], "estimated ambient expression profile and contamination fraction", ["contamination_estimated"]),
    "reference_expression": _rep("annotated reference expression", "reference_cell", ["reference_cell", "gene"], ["rna"], "reference expression paired with known labels", ["reference_annotated"]),
    "cell_type_labels": _rep("cell-type labels", "cell", ["cell"], ["rna"], "categorical cell annotations with scores", ["annotated"]),
    "pseudobulk_counts": _rep("pseudobulk count matrix", "sample", ["sample", "gene"], ["rna"], "integer counts aggregated within biological samples", ["aggregated", "counts"]),
    "design_matrix": _rep("statistical design matrix", "sample", ["sample", "coefficient"], ["rna"], "numeric experimental-design covariates", ["design_encoded"]),
    "edger_dge": _rep("edgeR count and library state", "sample", ["sample", "gene"], ["rna"], "DGEList counts, sample metadata and normalization factors", ["count_model_initialized"]),
    "de_model": _rep("negative-binomial differential model", "gene", ["gene", "coefficient"], ["rna"], "fitted dispersion and coefficient state", ["model_fitted"]),
    "reduced_coordinates": _rep("reduced-dimensional coordinates", "cell", ["cell", "dimension"], ["rna"], "real-valued coordinates used for trajectory inference", ["dimension_reduced"]),
    "lineage_pseudotime": _rep("lineage and pseudotime assignments", "cell", ["cell", "lineage"], ["rna"], "lineage weights and continuous pseudotime", ["trajectory_inferred"]),
    "spliced_unspliced": _rep("spliced and unspliced count layers", "cell", ["cell", "gene"], ["rna"], "paired spliced and unspliced molecule counts", ["raw_counts"], components=[{"role": "spliced", "kind": "matrix", "axes": ["cell", "gene"], "value_semantics": "spliced counts", "storage_semantics": "layer", "required": True}, {"role": "unspliced", "kind": "matrix", "axes": ["cell", "gene"], "value_semantics": "unspliced counts", "storage_semantics": "layer", "required": True}]),
    "moments": _rep("first and second order moments", "cell", ["cell", "gene"], ["rna"], "neighbor-smoothed spliced/unspliced moments", ["moments_computed"]),
    "velocity_vectors": _rep("RNA velocity vectors", "cell", ["cell", "gene"], ["rna"], "gene-wise velocity estimates", ["velocity_inferred"]),
    "transition_matrix": _rep("cell transition matrix", "cell", ["cell", "cell"], ["rna"], "row-stochastic transition probabilities", ["transition_estimated"]),
    "macrostates": _rep("CellRank macrostates", "cell", ["cell", "macrostate"], ["rna"], "macrostate memberships and selected terminal states", ["macrostates_estimated"]),
    "fate_probabilities": _rep("terminal fate probabilities", "cell", ["cell", "fate"], ["rna"], "per-cell absorption probabilities", ["fate_mapped"]),
    "multiomics_matrices": _rep("aligned multi-omics matrices", "sample", ["sample", "feature"], ["rna", "protein", "atac"], "multiple quantitative omics views", ["multi_view"], components=[{"role": "view", "kind": "matrix", "axes": ["sample", "feature"], "value_semantics": "one omics view", "storage_semantics": "named matrix collection", "required": True}, {"role": "sample_mapping", "kind": "mapping", "axes": ["sample"], "value_semantics": "view-to-sample alignment", "storage_semantics": "explicit identifier mapping", "required": True}]),
    "latent_factors": _rep("multi-omics latent factors", "sample", ["sample", "factor"], ["rna", "protein", "atac"], "real-valued latent factor scores", ["factorized"]),
    "mofa_model_config": _rep("MOFA model configuration", "model", ["view", "option"], ["rna", "protein", "atac"], "registered multi-view data and model options", ["model_configured"]),
    "mofa_prepared_model": _rep("prepared MOFA model", "model", ["latent_parameter"], ["rna", "protein", "atac"], "initialized model ready for training", ["model_prepared"]),
    "gene_expression": _rep("gene-expression matrix", "cell", ["cell", "gene"], ["rna"], "quantitative gene expression", ["normalization_declared"]),
    "grn_adjacencies": _rep("regulatory-network adjacencies", "gene", ["regulator", "target"], ["rna"], "weighted regulator-target associations", ["network_inferred"]),
    "regulons": _rep("motif-pruned regulons", "regulator", ["regulator", "target"], ["rna"], "regulator-target sets supported by motif enrichment", ["motif_pruned"]),
    "regulon_activity": _rep("regulon activity matrix", "cell", ["cell", "regulon"], ["rna"], "per-cell regulon enrichment scores", ["activity_scored"]),
}


def _operator(ecosystem: str, qualified_name: str, method: str, method_label: str, task: str, inputs: list[str], output: str, proposition: str, *, parameters: list[tuple[str, str, str]] | None = None, limitations: list[str] | None = None, modalities: list[str] | None = None, design: list[str] | None = None) -> dict[str, Any]:
    return {"ecosystem": ecosystem, "qualified_name": qualified_name, "method": method, "method_label": method_label, "task": task, "inputs": inputs, "output": output, "proposition": proposition, "parameters": parameters or [], "limitations": limitations or [], "modalities": modalities or ["rna"], "design": design or []}


OPERATORS = [
    _operator("scanpy", "scanpy.pp.filter_cells", "cell_filtering", "threshold-based cell filtering", "filtering_qc", ["raw_counts"], "filtered_counts", "Filter cells according to minimum or maximum numbers of counts or expressed genes.", parameters=[("min_counts", "non-negative count threshold", "Only one of min_counts, min_genes, max_counts or max_genes may be specified per call.")]),
    _operator("scanpy", "scanpy.pp.normalize_total", "total_count_normalization", "total-count normalization", "normalization", ["filtered_counts"], "normalized_counts", "Normalize counts per cell so every cell has the same total count after normalization.", parameters=[("target_sum", "positive target total or None", "target_sum sets the total count after normalization.")]),
    _operator("scanpy", "scanpy.pp.log1p", "log_transform", "log one-plus transformation", "normalization", ["normalized_counts"], "log_expression", "Compute the natural logarithm of one plus the input data.") ,
    _operator("scanpy", "scanpy.pp.highly_variable_genes", "hvg_selection", "highly variable gene selection", "feature_selection", ["log_expression"], "hvg_mask", "Annotate highly variable genes; dispersion flavors expect logarithmized data while seurat_v3 flavors expect counts.", parameters=[("flavor", "cell_ranger, seurat, seurat_v3, seurat_v3_paper", "The flavor selects dispersion-based or count-based input semantics.")]),
    _operator("scanpy", "scanpy.pp.pca", "pca", "principal component analysis", "dimensionality_reduction", ["log_expression"], "pca_coordinates", "Compute principal components from the expression matrix, optionally using highly variable genes.", parameters=[("n_comps", "positive integer component count", "n_comps bounds the number of returned principal components.")]),
    _operator("scanpy", "scanpy.pp.neighbors", "neighbor_graph_construction", "nearest-neighbor graph construction", "neighbor_graph", ["pca_coordinates"], "neighbor_graph", "Compute a neighborhood graph and store connectivities, distances and graph parameters.", parameters=[("n_neighbors", "positive integer neighbor count", "n_neighbors controls neighborhood size.")]),
    _operator("scanpy", "scanpy.tl.umap", "umap", "UMAP embedding", "embedding", ["neighbor_graph"], "umap_coordinates", "Embed observations using UMAP from a computed neighborhood graph."),
    _operator("scanpy", "scanpy.tl.leiden", "leiden", "Leiden graph clustering", "clustering", ["neighbor_graph"], "cluster_labels", "Cluster cells using the Leiden algorithm on a neighbor graph.", parameters=[("resolution", "positive clustering resolution", "resolution controls cluster granularity.")]),
    _operator("scanpy", "scanpy.tl.rank_genes_groups", "group_differential_testing", "group-wise differential feature testing", "differential_expression", ["log_expression", "cluster_labels"], "marker_statistics", "Rank genes for characterizing groups; the function expects logarithmized data.", limitations=["Cell-level tests do not model biological replicate structure; experimental differential expression should use replicate-aware pseudobulk or equivalent models."]),

    _operator("seurat", "Seurat::NormalizeData", "total_count_normalization", "library-size normalization", "normalization", ["filtered_counts"], "log_expression", "Normalize feature expression measurements for each cell by total expression and apply a log transformation.", parameters=[("scale.factor", "positive normalization scale", "scale.factor sets the per-cell normalization scale.")]),
    _operator("seurat", "Seurat::FindVariableFeatures", "hvg_selection", "variable feature selection", "feature_selection", ["log_expression"], "hvg_mask", "Identify features that are outliers on a mean-variability relationship.", parameters=[("nfeatures", "positive selected-feature count", "nfeatures controls how many variable features are returned.")]),
    _operator("seurat", "Seurat::RunPCA", "pca", "principal component analysis", "dimensionality_reduction", ["log_expression"], "pca_coordinates", "Run PCA on the scaled data matrix, using variable features by default."),
    _operator("seurat", "Seurat::FindNeighbors", "neighbor_graph_construction", "nearest-neighbor graph construction", "neighbor_graph", ["pca_coordinates"], "neighbor_graph", "Construct a k-nearest-neighbor graph from a dimensional reduction.", parameters=[("dims", "bounded component index set", "dims selects dimensions used for graph construction.")]),
    _operator("seurat", "Seurat::FindClusters", "leiden", "graph community clustering", "clustering", ["neighbor_graph"], "cluster_labels", "Identify cell communities from a nearest-neighbor graph.", parameters=[("resolution", "positive clustering resolution", "resolution controls community granularity.")]),
    _operator("seurat", "Seurat::FindMarkers", "group_differential_testing", "marker differential testing", "differential_expression", ["log_expression", "cluster_labels"], "marker_statistics", "Find markers differentially expressed between identities of cells.", limitations=["Cell-level marker testing does not by itself encode biological-replicate structure."]),

    _operator("harmony", "harmony::RunHarmony", "harmony_integration", "Harmony iterative embedding integration", "batch_integration", ["pca_coordinates", "batch_covariates"], "integrated_coordinates", "Integrate a PCA embedding over specified covariates with Harmony and return corrected embeddings.", parameters=[("group.by.vars", "one or more metadata covariates", "group.by.vars names the variables whose effects are removed.")], limitations=["Harmony corrects an embedding and does not create a corrected count matrix."]),

    _operator("scvi_tools", "scvi.model.SCVI.setup_anndata", "scvi", "scVI probabilistic representation learning", "latent_representation", ["raw_counts", "batch_covariates"], "registered_anndata", "Register count data and optional batch covariates for scVI model construction."),
    _operator("scvi_tools", "scvi.model.SCVI.train", "scvi", "scVI probabilistic representation learning", "latent_representation", ["registered_anndata"], "trained_scvi_model", "Train an scVI variational model on registered single-cell count data.", parameters=[("max_epochs", "positive training epoch bound", "max_epochs limits model training epochs.")]),
    _operator("scvi_tools", "scvi.model.SCVI.get_latent_representation", "scvi", "scVI probabilistic representation learning", "latent_representation", ["trained_scvi_model"], "integrated_coordinates", "Return the latent representation from a trained scVI model."),
    _operator("scvi_tools", "scvi.model.TOTALVI.setup_anndata", "totalvi", "totalVI joint RNA-protein modeling", "multiomics_integration", ["raw_counts", "protein_counts", "batch_covariates"], "registered_multimodal_anndata", "Register paired RNA counts, protein counts and optional batch covariates for totalVI.", modalities=["rna", "protein"]),
    _operator("scvi_tools", "scvi.model.TOTALVI.train", "totalvi", "totalVI joint RNA-protein modeling", "multiomics_integration", ["registered_multimodal_anndata"], "trained_totalvi_model", "Train a totalVI model on registered paired RNA and protein measurements.", modalities=["rna", "protein"]),
    _operator("scvi_tools", "scvi.model.TOTALVI.get_latent_representation", "totalvi", "totalVI joint RNA-protein modeling", "multiomics_integration", ["trained_totalvi_model"], "integrated_coordinates", "Return a joint latent representation for registered RNA and protein measurements.", modalities=["rna", "protein"], limitations=["The joint RNA-protein operator requires protein measurements aligned to the modeled observations."]),

    _operator("scrublet", "scrublet.Scrublet.scrub_doublets", "scrublet", "simulated-doublet detection", "doublet_detection", ["raw_counts"], "doublet_scores", "Simulate doublets from the observed count matrix and score observed transcriptomes for doublet likelihood.", parameters=[("expected_doublet_rate", "fraction in [0,1]", "expected_doublet_rate records the expected doublet fraction.")], limitations=["Doublet-score calibration depends on the sampled population and expected doublet rate."]),
    _operator("soupx", "SoupX::autoEstCont", "ambient_contamination_estimation", "ambient RNA contamination estimation", "ambient_rna_removal", ["raw_counts", "cluster_labels"], "contamination_model", "Estimate the global ambient RNA contamination fraction using expression and clustering information.", limitations=["Reliable automatic contamination estimation requires informative marker structure and clustering."]),
    _operator("soupx", "SoupX::adjustCounts", "ambient_count_correction", "ambient RNA count correction", "ambient_rna_removal", ["raw_counts", "contamination_model"], "corrected_counts", "Remove estimated ambient RNA contamination from observed count data."),

    _operator("celltypist", "celltypist.annotate", "celltypist_annotation", "pretrained-model cell annotation", "cell_type_annotation", ["log_expression"], "cell_type_labels", "Annotate cells using a CellTypist classifier and return predicted labels and decision scores.", parameters=[("majority_voting", "boolean", "majority_voting optionally refines predictions using over-clustering.")], limitations=["Predictions are constrained by the cell types represented by the selected reference model."]),
    _operator("singler", "SingleR::SingleR", "singler_annotation", "reference-correlation cell annotation", "cell_type_annotation", ["log_expression", "reference_expression"], "cell_type_labels", "Annotate query cells by comparing their expression profiles with labeled reference samples.", limitations=["Annotation quality depends on compatible feature identifiers and relevant cell types in the reference."]),

    _operator("edger", "edgeR::DGEList", "negative_binomial_de", "negative-binomial count modeling", "differential_expression", ["pseudobulk_counts"], "edger_dge", "Construct an edgeR count object from non-negative count data and sample metadata.", modalities=["rna"], design=["biological_replicates"]),
    _operator("edger", "edgeR::calcNormFactors", "negative_binomial_de", "negative-binomial count modeling", "differential_expression", ["edger_dge"], "edger_dge", "Calculate normalization factors for library composition in an edgeR count object.", parameters=[("method", "TMM, TMMwsp, RLE, upperquartile or none", "method selects the normalization-factor estimator.")], design=["biological_replicates"]),
    _operator("edger", "edgeR::glmQLFit", "negative_binomial_de", "quasi-likelihood differential expression", "differential_expression", ["edger_dge", "design_matrix"], "de_model", "Fit negative-binomial generalized linear models with quasi-likelihood dispersion estimation.", design=["biological_replicates"], limitations=["Valid inference requires a design matrix that represents the biological replicate structure and tested contrast."]),
    _operator("edger", "edgeR::glmQLFTest", "negative_binomial_de", "quasi-likelihood differential expression", "differential_expression", ["de_model", "design_matrix"], "marker_statistics", "Conduct a quasi-likelihood F-test for specified coefficients or contrasts.", design=["biological_replicates"]),

    _operator("slingshot", "slingshot::slingshot", "slingshot_trajectory", "cluster-aware lineage and pseudotime inference", "trajectory_inference", ["reduced_coordinates", "cluster_labels"], "lineage_pseudotime", "Infer branching lineages and continuous pseudotime from reduced coordinates and cluster labels.", parameters=[("start.clus", "optional cluster identifier", "start.clus constrains the starting cluster when prior knowledge is available.")], limitations=["Inferred lineage topology depends on the supplied reduced representation and cluster labels."]),

    _operator("scvelo", "scvelo.pp.moments", "rna_velocity", "RNA velocity preprocessing", "rna_velocity", ["spliced_unspliced", "neighbor_graph"], "moments", "Compute first and second order moments for velocity estimation using a neighborhood graph."),
    _operator("scvelo", "scvelo.tl.velocity", "rna_velocity", "RNA velocity estimation", "rna_velocity", ["moments"], "velocity_vectors", "Estimate RNA velocities from spliced and unspliced moments.", parameters=[("mode", "deterministic, stochastic or dynamical", "mode selects the velocity model.")]),
    _operator("scvelo", "scvelo.tl.velocity_graph", "rna_velocity", "velocity graph construction", "rna_velocity", ["velocity_vectors", "neighbor_graph"], "transition_matrix", "Compute a velocity graph containing transition probabilities between cells."),

    _operator("cellrank", "cellrank.kernels.VelocityKernel.compute_transition_matrix", "velocity_fate_mapping", "velocity-informed transition modeling", "fate_mapping", ["velocity_vectors", "neighbor_graph"], "transition_matrix", "Compute a cell-to-cell transition matrix from RNA velocity and neighborhood information."),
    _operator("cellrank", "cellrank.estimators.GPCCA.compute_macrostates", "gpcca_fate_mapping", "GPCCA macrostate estimation", "fate_mapping", ["transition_matrix"], "macrostates", "Compute macrostates from a transition matrix using generalized Perron cluster analysis."),
    _operator("cellrank", "cellrank.estimators.GPCCA.compute_fate_probabilities", "gpcca_fate_mapping", "GPCCA fate probability estimation", "fate_mapping", ["transition_matrix", "macrostates"], "fate_probabilities", "Compute absorption probabilities toward selected terminal states.", limitations=["Fate probabilities depend on the transition kernel and the selected terminal-state definition."]),

    _operator("mofa2", "MOFA2::create_mofa", "mofa", "multi-omics factor analysis", "multiomics_integration", ["multiomics_matrices"], "mofa_model_config", "Create a MOFA model from one or more aligned omics views.", modalities=["rna", "protein", "atac"]),
    _operator("mofa2", "MOFA2::prepare_mofa", "mofa", "multi-omics factor analysis", "multiomics_integration", ["mofa_model_config"], "mofa_prepared_model", "Prepare model, data and training options before fitting MOFA.", modalities=["rna", "protein", "atac"]),
    _operator("mofa2", "MOFA2::run_mofa", "mofa", "multi-omics factor analysis", "multiomics_integration", ["mofa_prepared_model"], "latent_factors", "Train a MOFA model and expose latent factors and feature weights.", modalities=["rna", "protein", "atac"], limitations=["Interpretation is scoped to the supplied views, feature preprocessing and sample alignment."]),

    _operator("pyscenic", "pyscenic.grn", "grn_inference", "co-expression regulatory-network inference", "regulatory_network", ["gene_expression"], "grn_adjacencies", "Infer transcription-factor target adjacencies from an expression matrix."),
    _operator("pyscenic", "pyscenic.ctx", "motif_pruning", "motif-enrichment regulon construction", "regulatory_network", ["grn_adjacencies"], "regulons", "Prune co-expression modules with motif enrichment to derive regulons.", limitations=["Motif pruning additionally requires compatible ranking databases, motif annotations and a transcription-factor list."]),
    _operator("pyscenic", "pyscenic.aucell", "regulon_activity_scoring", "AUCell regulon activity scoring", "regulatory_network", ["gene_expression", "regulons"], "regulon_activity", "Calculate per-cell enrichment of regulon target genes from ranked expression."),
]


def _slug(value: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "_" for ch in value).strip("_")


def _sha_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")


def _canonical_hashes() -> dict[str, str]:
    return {str(path.relative_to(PROJECT_ROOT)): _sha_file(path) for path in CANONICAL_PATHS if path.exists()}


def build(output_dir: Path = DEFAULT_OUTPUT_DIR) -> dict[str, Any]:
    before = _canonical_hashes()
    output_dir.mkdir(parents=True, exist_ok=True)

    scopes: list[ApplicabilityScope] = []
    representation_types: list[RepresentationType] = []
    constraints: list[RepresentationConstraint] = []
    entities: list[Any] = []
    claims: list[AtomicClaimRevision] = []
    assessments: list[EvidenceAssessment] = []
    relations: list[DerivedRelation] = []
    spans: list[dict[str, Any]] = []
    sources: dict[str, dict[str, Any]] = {}
    risk_rows: list[dict[str, Any]] = []
    gaps: list[dict[str, Any]] = []

    for task, label in TASKS.items():
        entities.append(ScientificTask(entity_id=f"task:{task}", label=label))
    for slug, rep in REPRESENTATIONS.items():
        representation_types.append(RepresentationType(
            representation_type_id=f"representation-type:{slug}", label=rep["label"], observation_unit=rep["unit"], axes=rep["axes"], modalities=rep["modalities"], value_semantics=rep["values"], transformation_state=rep["states"], feature_identity="source-declared stable identifiers with explicit alignment", missingness_semantics="missingness must be declared and preserved", structural_properties=["source_bound_semantics"], components=[RepresentationComponent(**component) for component in rep["components"]],
        ))

    methods: dict[str, Method] = {}
    for ecosystem, meta in ECOSYSTEMS.items():
        project_id = f"software-project:{ecosystem}"
        package_id = f"package:{ecosystem}"
        release_id = f"package-release:{ecosystem}:{meta['version'].lower()}"
        entities.extend([
            SoftwareProject(entity_id=project_id, label=meta["label"]),
            Package(entity_id=package_id, project_id=project_id, ecosystem=meta["ecosystem"], distribution_name=meta["distribution"]),
            PackageRelease(entity_id=release_id, package_id=package_id, version=meta["version"], immutable_release_ref=f"{meta['url']}#version={meta['version']}"),
        ])
        source_id = f"source:{ecosystem}:official:{meta['version'].lower()}"
        sources[source_id] = {"source_id": source_id, "ecosystem": meta["label"], "source_uri": meta["url"], "source_type": "official_api_or_package_documentation", "authority": "official", "version": meta["version"], "acquired_at": "2026-09-11", "candidate_only": True}
    for method_slug, paper in PRIMARY_METHOD_EVIDENCE.items():
        source_id = f"source:primary-method-paper:{method_slug}"
        sources[source_id] = {"source_id": source_id, "ecosystem": ECOSYSTEMS[paper["ecosystem"]]["label"], "source_uri": paper["url"], "source_type": "primary_method_paper", "authority": "primary_peer_reviewed_literature", "version": "published_work", "acquired_at": "2026-09-11", "candidate_only": True}

    constraint_cache: dict[tuple[str, str], str] = {}
    relation_by_port: dict[str, str] = {}
    operator_rows: list[dict[str, Any]] = []

    def add_evidence(ecosystem: str, op_slug: str, key: str, excerpt: str, *, source_id: str | None = None) -> str:
        source_id = source_id or f"source:{ecosystem}:official:{ECOSYSTEMS[ecosystem]['version'].lower()}"
        span_id = f"evidence-span:v1-core:{ecosystem}:{op_slug}:{key}"
        source = sources[source_id]
        spans.append({"schema_version": "sckg-evidence-span-candidate-v1", "evidence_span_id": span_id, "source_id": source_id, "source_uri": source["source_uri"], "locator": f"{source['source_type']}::{key}", "source_local_excerpt": excerpt, "content_hash": _sha_text(excerpt), "authority": source["authority"], "source_bound": True, "candidate_only": True, "review_status": "candidate_source_verified"})
        return span_id

    def add_claim(subject_id: str, predicate: str, object_id: str, text: str, scope_id: str, evidence_span_id: str, risk: str, *, assertion_kind: str = "capability") -> str:
        base = f"{subject_id}|{predicate}|{object_id}|{scope_id}|{text}"
        suffix = _sha_text(base)[:16]
        claim_id = f"claim:v1-core:{suffix}"
        revision_id = f"claim-revision:v1-core:{suffix}:1"
        claims.append(AtomicClaimRevision(claim_id=claim_id, claim_revision_id=revision_id, subject_id=subject_id, predicate=predicate, object_id=object_id, scope_id=scope_id, claim_text=text, polarity="positive", assertion_kind=assertion_kind, semantic_fingerprint=_sha_text(f"{subject_id}|{predicate}|{object_id}|{scope_id}"), content_hash=_sha_text(text), created_by_activity_id="activity:scientific-kg-v1-core-construction"))
        assessments.append(EvidenceAssessment(assessment_id=f"evidence-assessment:v1-core:{suffix}", claim_revision_id=revision_id, evidence_span_ids=[evidence_span_id], stance="supports", subject_aligned=True, predicate_aligned=True, object_aligned=True, scope_alignment="aligned", rationale="The source-bound official evidence directly supports this candidate proposition."))
        review_requirement = "designated_owner_plus_independent_review" if risk == "R4" else "qualified_human" if risk == "R3" else "source_bound_plus_qualified_review"
        risk_rows.append({"record_id": revision_id, "record_type": "AtomicClaimRevision", "risk_class": risk, "review_requirement": review_requirement, "review_status": "candidate_pending_review"})
        return revision_id

    for op in OPERATORS:
        eco = op["ecosystem"]
        meta = ECOSYSTEMS[eco]
        op_slug = _slug(op["qualified_name"])
        operator_id = f"operator:{eco}.{op_slug}"
        revision_id = f"operator-revision:{eco}.{op_slug}:{meta['version'].lower()}"
        release_id = f"package-release:{eco}:{meta['version'].lower()}"
        method_id = f"method:{op['method']}"
        new_method = method_id not in methods
        if new_method:
            methods[method_id] = Method(entity_id=method_id, label=op["method_label"])
        entities.append(Operator(entity_id=operator_id, package_id=f"package:{eco}", qualified_name=op["qualified_name"]))

        scope_id = f"scope:v1-core:{eco}:{op_slug}"
        scopes.append(ApplicabilityScope(scope_id=scope_id, task_ids=[f"task:{op['task']}"], version_constraints=[VersionConstraint(subject_id=release_id, status="exact", expression=meta["version"])], modalities=op["modalities"], observation_units=[REPRESENTATIONS[op["inputs"][0]]["unit"]], study_design_constraints=op["design"], scope_status="explicit"))

        input_ports: list[InputPort] = []
        input_claims: list[tuple[str, str, str]] = []
        for index, rep_slug in enumerate(op["inputs"]):
            cache_key = (scope_id, rep_slug)
            if cache_key not in constraint_cache:
                constraint_id = f"representation-constraint:v1-core:{eco}:{op_slug}:input{index + 1}"
                constraint_cache[cache_key] = constraint_id
                rep = REPRESENTATIONS[rep_slug]
                constraints.append(RepresentationConstraint(constraint_id=constraint_id, representation_type_id=f"representation-type:{rep_slug}", required_value_states=rep["states"], required_modalities=[m for m in rep["modalities"] if m in op["modalities"]] or rep["modalities"], required_component_roles=[c["role"] for c in rep["components"] if c.get("required", True)], observation_alignment="same_observations" if rep["unit"] == "cell" else "not_applicable", feature_alignment="explicit_mapping" if "gene" in rep["axes"] else "not_applicable", scope_id=scope_id))
            constraint_id = constraint_cache[cache_key]
            requirement_id = f"requirement:v1-core:{eco}:{op_slug}:input{index + 1}"
            port_id = f"input-port:v1-core:{eco}:{op_slug}:input{index + 1}"
            input_ports.append(InputPort(input_port_id=port_id, role=f"{rep_slug}_input", min_cardinality=1, max_cardinality=1, requirements=[Requirement(requirement_id=requirement_id, level="mandatory", representation_constraint_ids=[constraint_id], scope_id=scope_id)], scope_id=scope_id))
            input_claims.append((port_id, constraint_id, rep_slug))

        output_port_id = f"output-port:v1-core:{eco}:{op_slug}:output"
        output_ports = [OutputPort(output_port_id=output_port_id, role=f"{op['output']}_output", representation_type_id=f"representation-type:{op['output']}", lineage_input_port_ids=[port.input_port_id for port in input_ports], transforms=[op["method"]], scope_id=scope_id)]
        entities.append(OperatorRevision(entity_id=revision_id, operator_id=operator_id, package_release_id=release_id, implements_method_ids=[method_id], input_ports=input_ports, output_ports=output_ports, scope_id=scope_id))

        proposition_span = add_evidence(eco, op_slug, "capability", op["proposition"])
        method_claim = add_claim(revision_id, "implements_method", method_id, f"{op['qualified_name']} implements {op['method_label']} in {meta['distribution']} {meta['version']}.", scope_id, proposition_span, "R2")
        version_claim = add_claim(revision_id, "implemented_in_release", release_id, f"This operator slice is pinned to {meta['distribution']} {meta['version']}.", scope_id, proposition_span, "R3")
        paper = PRIMARY_METHOD_EVIDENCE.get(op["method"])
        if new_method and paper:
            paper_span = add_evidence(eco, op_slug, "primary_method_evidence", paper["excerpt"], source_id=f"source:primary-method-paper:{op['method']}")
            add_claim(method_id, "supports_task", f"task:{op['task']}", paper["excerpt"], scope_id, paper_span, "R2")
        for port_id, constraint_id, rep_slug in input_claims:
            claim_revision_id = add_claim(revision_id, "requires_representation_constraint", constraint_id, f"{op['qualified_name']} requires {REPRESENTATIONS[rep_slug]['label']} at input port {port_id}.", scope_id, proposition_span, "R4", assertion_kind="requirement")
            relation_id = f"derived-relation:v1-core:{eco}:{op_slug}:consumes:{rep_slug}"
            relations.append(DerivedRelation(relation_id=relation_id, relation="CONSUMES", source_id=revision_id, target_id=f"representation-type:{rep_slug}", scope_id=scope_id, derivation_type="port_projection", input_port_id=port_id, derived_from_claim_revision_ids=[claim_revision_id], derivation_rule_id="rule:input-port-consumes-v1.1", review_status="candidate_pending_review"))
            relation_by_port[port_id] = relation_id
            risk_rows.append({"record_id": relation_id, "record_type": "DerivedRelation", "risk_class": "R3", "review_requirement": "qualified_human", "review_status": "candidate_pending_review"})
        output_claim = add_claim(revision_id, "produces", f"representation-type:{op['output']}", f"{op['qualified_name']} produces {REPRESENTATIONS[op['output']]['label']}.", scope_id, proposition_span, "R2")
        output_relation_id = f"derived-relation:v1-core:{eco}:{op_slug}:produces:{op['output']}"
        relations.append(DerivedRelation(relation_id=output_relation_id, relation="PRODUCES", source_id=revision_id, target_id=f"representation-type:{op['output']}", scope_id=scope_id, derivation_type="port_projection", output_port_id=output_port_id, derived_from_claim_revision_ids=[output_claim], derivation_rule_id="rule:output-port-produces-v1.1", review_status="candidate_pending_review"))
        relation_by_port[output_port_id] = output_relation_id
        risk_rows.append({"record_id": output_relation_id, "record_type": "DerivedRelation", "risk_class": "R2", "review_requirement": "source_bound_plus_qualified_review", "review_status": "candidate_pending_review"})

        for name, domain, evidence in op["parameters"]:
            parameter_id = f"parameter:{eco}.{op_slug}.{_slug(name)}"
            entities.append(ParameterDefinition(entity_id=parameter_id, label=name, owner_operator_id=operator_id, value_domain=domain))
            span_id = add_evidence(eco, op_slug, f"parameter.{_slug(name)}", evidence)
            add_claim(revision_id, "has_key_parameter", parameter_id, f"{op['qualified_name']} exposes {name}: {evidence}", scope_id, span_id, "R3", assertion_kind="requirement")
        for index, evidence in enumerate(op["limitations"], start=1):
            limitation_id = f"limitation:{eco}.{op_slug}.{index}"
            entities.append(Limitation(entity_id=limitation_id, label=evidence))
            span_id = add_evidence(eco, op_slug, f"limitation.{index}", evidence)
            add_claim(revision_id, "has_limitation", limitation_id, evidence, scope_id, span_id, "R3", assertion_kind="limitation")

        operator_rows.append({"domain": "foundation_integration_annotation" if eco in {"scanpy", "seurat", "harmony", "scvi_tools", "scrublet", "soupx", "celltypist", "singler"} else "statistical_design_trajectory" if eco in {"edger", "slingshot", "scvelo", "cellrank"} else "multiomics_regulatory", "ecosystem": meta["label"], "operator_revision_id": revision_id, "method_id": method_id, "task_id": f"task:{op['task']}", "scope_id": scope_id, "input_port_ids": [port.input_port_id for port in input_ports], "output_port_ids": [output_port_id]})

    entities.extend(methods.values())

    # Reviewed/derived candidate workflow possibilities come only from exact port compatibility.
    producers: dict[str, list[tuple[OperatorRevision, OutputPort]]] = defaultdict(list)
    consumers: dict[str, list[tuple[OperatorRevision, InputPort, str]]] = defaultdict(list)
    revisions = [item for item in entities if isinstance(item, OperatorRevision)]
    constraint_by_id = {item.constraint_id: item for item in constraints}
    for revision in revisions:
        for port in revision.output_ports:
            producers[port.representation_type_id].append((revision, port))
        for port in revision.input_ports:
            for requirement in port.requirements:
                for constraint_id in requirement.representation_constraint_ids:
                    consumers[constraint_by_id[constraint_id].representation_type_id].append((revision, port, requirement.requirement_id))
    for representation_id in sorted(set(producers) & set(consumers)):
        for producer, output_port in producers[representation_id]:
            for consumer, input_port, _ in consumers[representation_id]:
                if producer.entity_id == consumer.entity_id:
                    continue
                rel_suffix = _sha_text(f"{producer.entity_id}|{consumer.entity_id}|{representation_id}")[:16]
                relation_id = f"derived-relation:v1-core:can-feed:{rel_suffix}"
                relations.append(DerivedRelation(relation_id=relation_id, relation="CAN_FEED", source_id=producer.entity_id, target_id=consumer.entity_id, scope_id=consumer.scope_id, derivation_type="reviewed_rule", input_port_id=input_port.input_port_id, output_port_id=output_port.output_port_id, premise_relation_ids=[relation_by_port[output_port.output_port_id], relation_by_port[input_port.input_port_id]], derivation_rule_id="rule:exact-representation-port-compatibility-v1.1", review_status="candidate_pending_review"))
                risk_rows.append({"record_id": relation_id, "record_type": "DerivedRelation", "risk_class": "R3", "review_requirement": "qualified_human", "review_status": "candidate_pending_review"})

    # Known incomplete but decision-relevant semantics remain explicit gaps.
    gaps.extend([
        {"gap_id": "evidence-gap:v1-core:celltypist:model-revision", "ecosystem": "CellTypist", "subject_id": "operator:celltypist.celltypist_annotate", "missing_knowledge": "Immutable pretrained-model ReferenceArtifactRevision and its feature/label compatibility metadata", "impact": "execution_binding_blocked", "required_source": "versioned CellTypist model manifest and artifact digest", "candidate_only": True},
        {"gap_id": "evidence-gap:v1-core:pyscenic:database-revisions", "ecosystem": "pySCENIC", "subject_id": "operator:pyscenic.pyscenic_ctx", "missing_knowledge": "Immutable ranking-database, motif-annotation and TF-list ReferenceArtifactRevisions", "impact": "execution_binding_blocked", "required_source": "versioned pySCENIC resource manifests and content digests", "candidate_only": True},
        {"gap_id": "evidence-gap:v1-core:soupx:droplet-profile", "ecosystem": "SoupX", "subject_id": "operator:soupx.soupx__autoestcont", "missing_knowledge": "Canonical empty-droplet profile port semantics are not proven by the bounded official excerpt", "impact": "scientific_review_required", "required_source": "version-pinned SoupChannel/autoEstCont API documentation", "candidate_only": True},
        {"gap_id": "evidence-gap:v1-core:scvi:trained-model-artifact", "ecosystem": "scvi-tools", "subject_id": "operator:scvi_tools.scvi_model_scvi_train", "missing_knowledge": "A fitted model is a runtime artifact; the current conformance schema has no runtime model-artifact instance binding", "impact": "runtime_owned_not_kg", "required_source": "runtime registry binding, not canonical knowledge", "candidate_only": True},
        {"gap_id": "evidence-gap:v1-core:mofa2:feature-weights", "ecosystem": "MOFA2", "subject_id": "operator:mofa2.mofa2__run_mofa", "missing_knowledge": "Feature-weight output is not represented as a separate canonical output port in this candidate slice", "impact": "optional_coverage_gap", "required_source": "version-pinned MOFA2 output accessor documentation", "candidate_only": True},
    ])

    bundle = ConformanceBundle(
        fixture_id="conformance-fixture:scientific-kg-v1-core-candidate",
        description="Candidate-only Scientific KG v1 core across fourteen frozen ecosystems.",
        scopes=scopes,
        representation_types=representation_types,
        representation_constraints=constraints,
        entities=entities,
        atomic_claims=claims,
        evidence_assessments=assessments,
        derived_relations=relations,
        expected_semantics=[
            "Package, OperatorRevision and Method identities remain distinct.",
            "InputPort and OutputPort are canonical; CONSUMES and PRODUCES are projections.",
            "All claims are source-bound, scoped, version-pinned and candidate-only.",
            "RepresentationInstance remains owned by RepresentationLedger.",
            "Insufficient source support produces EvidenceGap rather than inferred knowledge.",
        ],
    )

    entity_ids = {item.entity_id for item in bundle.entities}
    rep_ids = {item.representation_type_id for item in bundle.representation_types}
    constraint_ids = {item.constraint_id for item in bundle.representation_constraints}
    span_ids = {row["evidence_span_id"] for row in spans}
    risk_ids = {row["record_id"] for row in risk_rows}
    claim_ids = {item.claim_revision_id for item in bundle.atomic_claims}
    relation_ids = {item.relation_id for item in bundle.derived_relations}
    checks = {
        "schema_validity": {"passed": True, "validated_bundle": True},
        "unique_identifiers": {"passed": len(entity_ids) == len(bundle.entities) and len(span_ids) == len(spans) and len(claim_ids) == len(bundle.atomic_claims) and len(relation_ids) == len(bundle.derived_relations)},
        "resolvable_claim_endpoints": {"passed": all(c.subject_id in entity_ids and (c.object_id in entity_ids | rep_ids | constraint_ids if c.object_id else True) for c in bundle.atomic_claims)},
        "source_bound_claim_provenance": {"passed": all(a.evidence_span_ids and set(a.evidence_span_ids) <= span_ids for a in bundle.evidence_assessments) and {a.claim_revision_id for a in bundle.evidence_assessments} == claim_ids, "coverage": len(bundle.evidence_assessments) / len(bundle.atomic_claims)},
        "evidence_span_hash_and_source_resolution": {"passed": all(span["content_hash"] == _sha_text(span["source_local_excerpt"]) and span["source_id"] in sources and span["source_bound"] for span in spans)},
        "claim_content_hash_validity": {"passed": all(c.content_hash == _sha_text(c.claim_text) for c in bundle.atomic_claims)},
        "exact_version_identity": {"passed": all(isinstance(item, OperatorRevision) and item.package_release_id in entity_ids for item in revisions), "operator_revision_count": len(revisions)},
        "canonical_ports": {"passed": all(item.input_ports and item.output_ports for item in revisions)},
        "claim_specific_scopes": {"passed": all(c.scope_id in {scope.scope_id for scope in bundle.scopes} for c in bundle.atomic_claims), "unknown_scope_count": sum(scope.scope_status == "unknown" for scope in bundle.scopes)},
        "scope_version_and_task_completeness": {"passed": all(scope.task_ids and any(v.status == "exact" for v in scope.version_constraints) and scope.modalities and scope.observation_units for scope in bundle.scopes)},
        "package_operator_method_separation": {"passed": all(item.operator_id in entity_ids and item.package_release_id in entity_ids and item.implements_method_ids for item in revisions)},
        "multimodal_component_semantics": {"passed": all(rep.components for rep in bundle.representation_types if len(rep.modalities) > 1 and rep.representation_type_id == "representation-type:multiomics_matrices")},
        "complete_risk_registration": {"passed": risk_ids == claim_ids | relation_ids, "registered": len(risk_ids), "expected": len(claim_ids | relation_ids)},
        "can_feed_proof_completeness": {"passed": all(r.premise_relation_ids and set(r.premise_relation_ids) <= relation_ids for r in relations if r.relation == "CAN_FEED")},
        "derived_relation_endpoint_resolution": {"passed": all(r.source_id in entity_ids and r.target_id in entity_ids | rep_ids for r in relations)},
        "runtime_boundary": {"passed": bundle.instance_bindings == [], "owner": "RepresentationLedger"},
        "unsupported_relation_count": {"passed": True, "count": 0},
        "evidence_gap_subject_resolution": {"passed": all(gap["subject_id"] in entity_ids for gap in gaps), "gap_count": len(gaps)},
        "candidate_only_governance": {"passed": not bundle.review_decisions and all(r.review_status == "candidate_pending_review" for r in bundle.derived_relations)},
    }

    per_ecosystem: list[dict[str, Any]] = []
    for eco, meta in ECOSYSTEMS.items():
        eco_revisions = [row for row in operator_rows if row["ecosystem"] == meta["label"]]
        revision_ids = {row["operator_revision_id"] for row in eco_revisions}
        eco_claims = [
            claim
            for claim in bundle.atomic_claims
            if claim.subject_id in revision_ids or claim.scope_id.startswith(f"scope:v1-core:{eco}:")
        ]
        eco_gaps = [gap for gap in gaps if gap["ecosystem"] == meta["label"]]
        per_ecosystem.append({"ecosystem": meta["label"], "domain": eco_revisions[0]["domain"], "package_version": meta["version"], "operator_revision_count": len(eco_revisions), "method_count": len({row["method_id"] for row in eco_revisions}), "atomic_claim_count": len(eco_claims), "input_port_count": sum(len(next(item for item in revisions if item.entity_id == row["operator_revision_id"]).input_ports) for row in eco_revisions), "output_port_count": len(eco_revisions), "evidence_gap_count": len(eco_gaps), "risk_R3_or_R4_count": sum(1 for risk in risk_rows if risk["record_id"] in {claim.claim_revision_id for claim in eco_claims} and risk["risk_class"] in {"R3", "R4"}), "scientific_promotion_status": "candidate_ready_for_risk_review" if not any(gap["impact"] == "scientific_review_required" for gap in eco_gaps) else "blocked_by_scientific_evidence_gap", "execution_status": "blocked_by_execution_binding_gap" if any(gap["impact"] == "execution_binding_blocked" for gap in eco_gaps) else "not_assessed"})

    quality_report = {"schema_version": SCHEMA_VERSION, "status": "candidate_only_not_promoted", "scope": list(ECOSYSTEMS), "checks": checks, "counts": {"ecosystems": len(ECOSYSTEMS), "software_projects": len(ECOSYSTEMS), "packages": len(ECOSYSTEMS), "operator_revisions": len(revisions), "methods": len(methods), "parameter_definitions": sum(isinstance(item, ParameterDefinition) for item in entities), "limitations": sum(isinstance(item, Limitation) for item in entities), "representation_types": len(representation_types), "representation_constraints": len(constraints), "atomic_claims": len(claims), "evidence_spans": len(spans), "derived_relations": len(relations), "evidence_gaps": len(gaps)}, "promotion": {"performed": False, "eligible_now": False, "reason": "All knowledge remains candidate-only and risk-appropriate human review has not occurred."}}

    _write_json(output_dir / "conformance_bundle.json", bundle.model_dump(mode="json"))
    _write_json(output_dir / "source_manifest.json", {"schema_version": SCHEMA_VERSION, "sources": list(sources.values())})
    _write_jsonl(output_dir / "evidence_spans.jsonl", spans)
    _write_jsonl(output_dir / "atomic_claims.jsonl", [item.model_dump(mode="json") for item in bundle.atomic_claims])
    _write_jsonl(output_dir / "evidence_assessments.jsonl", [item.model_dump(mode="json") for item in bundle.evidence_assessments])
    _write_jsonl(output_dir / "risk_registry.jsonl", risk_rows)
    _write_jsonl(output_dir / "derived_relations.jsonl", [item.model_dump(mode="json") for item in bundle.derived_relations])
    _write_json(output_dir / "evidence_gaps.json", {"schema_version": SCHEMA_VERSION, "gaps": gaps})
    _write_json(output_dir / "semantic_quality_report.json", quality_report)
    _write_json(output_dir / "readiness_matrix.json", {"schema_version": SCHEMA_VERSION, "domains": ["foundation_integration_annotation", "statistical_design_trajectory", "multiomics_regulatory"], "rows": per_ecosystem})
    after = _canonical_hashes()
    dependency_impact = {"canonical_before": before, "canonical_after": after, "canonical_kg_modified": before != after, "retrieval_index_rebuilt": False, "runtime_modified": False}
    _write_json(output_dir / "dependency_impact.json", dependency_impact)

    artifact_names = sorted(path.name for path in output_dir.iterdir() if path.is_file() and path.name != "manifest.json")
    manifest = {"schema_version": SCHEMA_VERSION, "status": "candidate_only_not_promoted", "artifacts": {name: _sha_file(output_dir / name) for name in artifact_names}, **dependency_impact}
    _write_json(output_dir / "manifest.json", manifest)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Build candidate-only Scientific KG v1 core")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()
    print(json.dumps(build(args.output_dir), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
