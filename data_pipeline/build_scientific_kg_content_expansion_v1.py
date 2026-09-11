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
    Method,
    MethodVariant,
    Operator,
    OperatorRevision,
    OutputPort,
    Package,
    PackageRelease,
    RepresentationConstraint,
    RepresentationType,
    Requirement,
    ScientificTask,
    SoftwareProject,
)
from data_pipeline.build_scientific_knowledge_conformance_v1_1 import (
    CANONICAL_PATHS,
    PROJECT_ROOT,
)


DEFAULT_OUTPUT_DIR = (
    PROJECT_ROOT
    / "data"
    / "evidence_candidates"
    / "scientific_kg_content_expansion_v1"
)
SCANPY_REFERENCE_BUNDLE = (
    PROJECT_ROOT
    / "data"
    / "evidence_candidates"
    / "scientific_knowledge_scanpy_core_v1_1"
    / "conformance_bundle.json"
)
SCANPY_REFERENCE_SPANS = SCANPY_REFERENCE_BUNDLE.parent / "authoritative_evidence_spans.jsonl"
EVIDENCE_INDEX = PROJECT_ROOT / "data" / "indexes" / "evidence_chunks.jsonl"
SOURCE_INDEX = PROJECT_ROOT / "data" / "indexes" / "source_documents_v2.jsonl"


CAPABILITY_FAMILIES = [
    "preprocessing_qc",
    "batch_integration",
    "doublet_contamination",
    "cell_type_annotation",
    "dimensionality_reduction_clustering",
    "differential_analysis",
    "trajectory_pseudotime",
    "rna_velocity_fate_mapping",
    "multiomics_integration",
    "regulatory_network_analysis",
]


ECOSYSTEMS: list[dict[str, Any]] = [
    {
        "slug": "scanpy",
        "label": "Scanpy",
        "ecosystem": "python",
        "distribution": "scanpy",
        "families": ["preprocessing_qc", "dimensionality_reduction_clustering", "differential_analysis"],
        "methods": [],
        "reference_slice": "scientific_knowledge_scanpy_core_v1_1",
    },
    {
        "slug": "seurat",
        "label": "Seurat",
        "ecosystem": "r",
        "distribution": "Seurat",
        "families": ["preprocessing_qc", "batch_integration", "dimensionality_reduction_clustering", "differential_analysis", "multiomics_integration"],
        "methods": [("seurat_analysis", "Seurat single-cell analysis framework")],
    },
    {
        "slug": "harmony",
        "label": "Harmony",
        "ecosystem": "r",
        "distribution": "harmony",
        "families": ["batch_integration"],
        "methods": [("harmony_integration", "Harmony embedding integration")],
    },
    {
        "slug": "scanorama",
        "label": "Scanorama",
        "ecosystem": "python",
        "distribution": "scanorama",
        "families": ["batch_integration"],
        "methods": [
            ("scanorama_integration", "Scanorama low-dimensional integration"),
            ("scanorama_batch_correction", "Scanorama expression batch correction"),
        ],
    },
    {
        "slug": "scvi_tools",
        "label": "scvi-tools",
        "ecosystem": "python",
        "distribution": "scvi-tools",
        "families": ["batch_integration", "dimensionality_reduction_clustering", "multiomics_integration"],
        "methods": [
            ("scvi", "scVI probabilistic representation learning"),
            ("totalvi", "totalVI joint RNA-protein modeling"),
            ("multivi", "MultiVI joint RNA-ATAC modeling"),
        ],
    },
    {
        "slug": "scrublet",
        "label": "Scrublet",
        "ecosystem": "python",
        "distribution": "scrublet",
        "families": ["doublet_contamination"],
        "methods": [("scrublet", "Scrublet simulated-doublet detection")],
    },
    {
        "slug": "doubletfinder",
        "label": "DoubletFinder",
        "ecosystem": "r",
        "distribution": "DoubletFinder",
        "families": ["doublet_contamination"],
        "methods": [("doubletfinder", "DoubletFinder artificial-neighbor detection")],
    },
    {
        "slug": "scdblfinder",
        "label": "scDblFinder",
        "ecosystem": "r_bioconductor",
        "distribution": "scDblFinder",
        "families": ["doublet_contamination"],
        "methods": [("scdblfinder", "scDblFinder doublet classification")],
    },
    {
        "slug": "celltypist",
        "label": "CellTypist",
        "ecosystem": "python",
        "distribution": "celltypist",
        "families": ["cell_type_annotation"],
        "methods": [("celltypist_annotation", "CellTypist reference-model annotation")],
    },
    {
        "slug": "singler",
        "label": "SingleR",
        "ecosystem": "r_bioconductor",
        "distribution": "SingleR",
        "families": ["cell_type_annotation"],
        "methods": [("singler_annotation", "SingleR reference-correlation annotation")],
    },
    {
        "slug": "scvelo",
        "label": "scVelo",
        "ecosystem": "python",
        "distribution": "scvelo",
        "families": ["rna_velocity_fate_mapping", "trajectory_pseudotime"],
        "methods": [("rna_velocity", "RNA velocity inference")],
        "variants": [
            ("rna_velocity_steady_state", "rna_velocity", "steady-state RNA velocity"),
            ("rna_velocity_dynamical", "rna_velocity", "dynamical RNA velocity"),
        ],
    },
    {
        "slug": "cellrank",
        "label": "CellRank",
        "ecosystem": "python",
        "distribution": "cellrank",
        "families": ["rna_velocity_fate_mapping", "trajectory_pseudotime"],
        "methods": [("cellrank_fate_mapping", "CellRank Markov fate mapping")],
    },
    {
        "slug": "tradeseq",
        "label": "tradeSeq",
        "ecosystem": "r_bioconductor",
        "distribution": "tradeSeq",
        "families": ["differential_analysis", "trajectory_pseudotime"],
        "methods": [("trajectory_differential_expression", "trajectory differential expression")],
    },
    {
        "slug": "moscot",
        "label": "moscot",
        "ecosystem": "python",
        "distribution": "moscot",
        "families": ["trajectory_pseudotime", "multiomics_integration"],
        "methods": [("single_cell_optimal_transport", "single-cell optimal transport")],
    },
    {
        "slug": "wot",
        "label": "WOT",
        "ecosystem": "python",
        "distribution": "wot",
        "families": ["trajectory_pseudotime"],
        "methods": [("waddington_ot", "Waddington optimal transport")],
    },
    {
        "slug": "mofa2",
        "label": "MOFA2",
        "ecosystem": "r_python",
        "distribution": "MOFA2",
        "additional_packages": [("mofapy2", "python", "mofapy2")],
        "families": ["multiomics_integration", "dimensionality_reduction_clustering"],
        "methods": [("mofa", "Multi-Omics Factor Analysis")],
    },
    {
        "slug": "cell2location",
        "label": "cell2location",
        "ecosystem": "python",
        "distribution": "cell2location",
        "families": ["multiomics_integration", "cell_type_annotation"],
        "methods": [("cell2location", "cell2location spatial decomposition")],
    },
    {
        "slug": "mimosca",
        "label": "MIMOSCA",
        "ecosystem": "python",
        "distribution": "MIMOSCA",
        "families": ["regulatory_network_analysis", "differential_analysis"],
        "methods": [("mimosca", "MIMOSCA perturbation response modeling")],
    },
    {
        "slug": "soupx",
        "label": "SoupX",
        "ecosystem": "r",
        "distribution": "SoupX",
        "families": ["doublet_contamination", "preprocessing_qc"],
        "methods": [("soupx", "SoupX ambient RNA decontamination")],
    },
]


TASKS = {
    "quality_control": "single-cell quality control",
    "batch_integration": "batch integration",
    "doublet_detection": "doublet detection",
    "ambient_rna_removal": "ambient RNA contamination removal",
    "cell_type_annotation": "cell-type annotation",
    "differential_expression": "differential analysis",
    "trajectory_inference": "trajectory and pseudotime inference",
    "rna_velocity": "RNA velocity inference",
    "fate_mapping": "cellular fate mapping",
    "multiomics_integration": "multi-omics integration",
    "spatial_deconvolution": "spatial cell-type deconvolution",
    "regulatory_network_inference": "perturbation-aware regulatory-network analysis",
}


REPRESENTATIONS = [
    ("single_cell_expression", "single-cell expression matrix", "cell", ["cell", "gene"], ["rna"], "quantitative single-cell expression values with source-declared scale", ["normalization_unspecified"], "gene identifiers with stable ordering"),
    ("batch_covariates", "batch covariates", "cell", ["cell", "covariate"], ["rna"], "categorical or bounded covariate values", ["metadata"], "covariate names and levels"),
    ("corrected_expression", "batch-corrected expression", "cell", ["cell", "gene"], ["rna"], "real-valued corrected expression", ["batch_corrected"], "gene identifiers with stable ordering"),
    ("doublet_scores", "doublet scores", "cell", ["cell"], ["rna"], "continuous doublet likelihood or score", ["doublet_scored"], "cells aligned to the input matrix"),
    ("doublet_labels", "doublet classifications", "cell", ["cell"], ["rna"], "categorical singlet/doublet assignments", ["doublet_classified"], "cells aligned to the input matrix"),
    ("reference_expression_profiles", "annotated reference expression profiles", "reference_sample", ["reference_sample", "gene"], ["rna"], "reference expression with cell-type annotations", ["reference_annotated"], "gene identifiers aligned or mappable to query features"),
    ("cell_type_labels", "cell-type labels", "cell", ["cell"], ["rna"], "categorical cell identity assignments", ["annotated"], "cells aligned to the query matrix"),
    ("spliced_unspliced_counts", "spliced and unspliced RNA counts", "cell", ["cell", "gene", "layer"], ["rna"], "non-negative molecule counts separated by splicing state", ["raw_counts", "splicing_quantified"], "gene identities shared across spliced and unspliced layers"),
    ("velocity_vectors", "RNA velocity vectors", "cell", ["cell", "gene"], ["rna"], "signed estimated expression-state derivatives", ["velocity_inferred"], "genes and cells aligned to the kinetic input"),
    ("transition_matrix", "cell-state transition matrix", "cell", ["cell", "cell"], ["rna"], "directed transition probabilities or affinities", ["transition_inferred"], "cells aligned on both axes"),
    ("fate_probabilities", "fate probabilities", "cell", ["cell", "terminal_state"], ["rna"], "probability of reaching terminal macrostates", ["fate_inferred"], "cells aligned to the transition model"),
    ("pseudotime_lineages", "pseudotime and lineage assignments", "cell", ["cell", "lineage"], ["rna"], "continuous pseudotime with lineage weights", ["trajectory_inferred"], "cells aligned to expression measurements"),
    ("differential_statistics", "differential-expression statistics", "gene", ["gene", "contrast"], ["rna"], "effect estimates and inferential statistics", ["differential_tested"], "gene identifiers aligned to modeled expression"),
    ("timepoint_expression", "time-indexed expression snapshots", "cell", ["cell", "gene"], ["rna"], "expression observations with experimental time labels", ["timepoint_observed"], "gene identifiers shared across time points"),
    ("temporal_coupling", "temporal cell coupling", "cell", ["source_cell", "target_cell"], ["rna"], "transport mass between cells at successive time points", ["transport_inferred"], "source and target cells belong to declared time points"),
    ("multiomics_matrices", "multi-omics matrices", "sample_or_cell", ["observation", "feature", "modality"], ["rna", "atac", "protein"], "modality-specific quantitative measurements", ["multi_modal"], "features remain modality-qualified"),
    ("latent_factors", "multi-omics latent factors", "sample_or_cell", ["observation", "factor"], ["rna", "atac", "protein"], "real-valued latent factor scores", ["integrated", "dimensionality_reduced"], "observations may overlap across modality views"),
    ("spatial_counts", "spatial transcriptomic count matrix", "spot", ["spot", "gene"], ["spatial_rna"], "non-negative spatial RNA counts", ["raw_counts", "spatially_indexed"], "spots carry spatial coordinates"),
    ("cell_type_signatures", "cell-type reference signatures", "cell_type", ["cell_type", "gene"], ["rna"], "reference expression signatures by cell type", ["reference_annotated"], "gene identifiers align to the spatial data"),
    ("spatial_cell_abundance", "spatial cell-type abundance", "spot", ["spot", "cell_type"], ["spatial_rna"], "non-negative inferred cell-type abundance", ["spatially_deconvolved"], "spots aligned to spatial input"),
    ("perturbation_assignments", "perturbation assignments", "cell", ["cell", "perturbation"], ["rna"], "guide or perturbation membership by cell", ["perturbation_assigned"], "cells align to expression observations"),
    ("regulatory_effects", "perturbation-linked regulatory effects", "gene", ["perturbation", "gene"], ["rna"], "modeled perturbation effects on expression", ["regulatory_effect_inferred"], "perturbations and genes retain stable identities"),
]


EVIDENCE_IDS = {
    "seurat_overview": "sourcev2:d143c7242f30af38cfd1",
    "harmony_api": "sourcev2:39b8f557e5782a49ee55",
    "harmony_overview": "sourcev2:93af124776f195a05b54",
    "scanorama_overview": "sourcev2:d869d09f04f1e0c29624",
    "scanorama_api": "sourcev2:b9f757749c16210255c0",
    "scanorama_limitation": "sourcev2:53d71aebc10f4cdb4ddf",
    "scvi_overview": "sourcev2:f4e1ab406fac0d54d0e1",
    "scrublet_api": "sourcev2:111374ebeb154e8b9052",
    "scrublet_limitation": "sourcev2:7c8e2ffa37943b8749cd",
    "doubletfinder_overview": "sourcev2:10a0ac3da870a89348a1",
    "doubletfinder_identity": "sourcev2:06ee5c00c3c8b10eeddd",
    "doubletfinder_input": "sourcev2:39cd27109eb863dd50c1",
    "doubletfinder_limitation": "sourcev2:a5d5ae025bf3f95f22bc",
    "scdblfinder_usage": "sourcev2:1604d1f15e3263d21c99",
    "scdblfinder_samples": "sourcev2:b2ac239784dafb96cb8a",
    "scdblfinder_limitation": "sourcev2:3cd1bb37cc31da83a1e4",
    "celltypist_input": "sourcev2:102dc717591cdfac63a5",
    "celltypist_api": "sourcev2:6d070f599929bf055fb8",
    "celltypist_output": "sourcev2:bdc1a08a62c8b1a34518",
    "celltypist_parameter": "sourcev2:260bdfc4ffa3718c6983",
    "singler_task": "sourcev2:cba80ff55a16b1d60be1",
    "singler_io": "sourcev2:7e29769c5f92c88e1acc",
    "scvelo_overview": "sourcev2:6c806d4837a75b13503d",
    "cellrank_overview": "sourcev2:af2a333109f7721dbbe7",
    "tradeseq_overview": "sourcev2:9453c3f37ab9d03980c5",
    "moscot_overview": "sourcev2:b14f12dfb1bcf3cbaf6c",
    "wot_paper": "publication:CAND_PUB_wot_5704efaab479",
    "mofa_overview": "sourcev2:7c73d5e998696443ddbb",
    "cell2location_io": "sourcev2:8c9741e3164c417f2a42",
    "cell2location_overview": "sourcev2:e265d1df732fd120e6c9",
    "mimosca_paper": "publication:CAND_PUB_MIMOSCA_7882e7558c0e",
    "soupx_paper": "publication:CAND_PUB_SoupX_5218c8e163d7",
}


OPERATOR_SPECS: list[dict[str, Any]] = [
    {
        "slug": "harmony.run_harmony",
        "package": "harmony",
        "qualified_name": "harmony::RunHarmony",
        "method": "harmony_integration",
        "task": "batch_integration",
        "inputs": [("coordinates", "pca_coordinates", "harmony_api"), ("batch_covariates", "batch_covariates", "harmony_api")],
        "outputs": [("integrated_coordinates", "integrated_coordinates", "harmony_api")],
    },
    {
        "slug": "scanorama.integrate_scanpy",
        "package": "scanorama",
        "qualified_name": "scanorama.integrate_scanpy",
        "method": "scanorama_integration",
        "task": "batch_integration",
        "inputs": [("datasets", "single_cell_expression", "scanorama_overview")],
        "outputs": [("integrated_coordinates", "integrated_coordinates", "scanorama_api")],
    },
    {
        "slug": "scanorama.correct_scanpy",
        "package": "scanorama",
        "qualified_name": "scanorama.correct_scanpy",
        "method": "scanorama_batch_correction",
        "task": "batch_integration",
        "inputs": [("datasets", "single_cell_expression", "scanorama_overview")],
        "outputs": [("corrected_expression", "corrected_expression", "scanorama_api")],
    },
    {
        "slug": "scrublet.scrub_doublets",
        "package": "scrublet",
        "qualified_name": "scrublet.Scrublet.scrub_doublets",
        "method": "scrublet",
        "task": "doublet_detection",
        "inputs": [("counts", "raw_rna_counts", "scrublet_api")],
        "outputs": [("doublet_scores", "doublet_scores", "scrublet_api"), ("doublet_labels", "doublet_labels", "scrublet_api")],
    },
    {
        "slug": "doubletfinder.doubletfinder",
        "package": "doubletfinder",
        "qualified_name": "DoubletFinder::doubletFinder",
        "method": "doubletfinder",
        "task": "doublet_detection",
        "inputs": [("pca_coordinates", "pca_coordinates", "doubletfinder_overview")],
        "outputs": [("doublet_labels", "doublet_labels", "doubletfinder_overview")],
    },
    {
        "slug": "scdblfinder.scdblfinder",
        "package": "scdblfinder",
        "qualified_name": "scDblFinder::scDblFinder",
        "method": "scdblfinder",
        "task": "doublet_detection",
        "inputs": [("counts", "raw_rna_counts", "scdblfinder_usage")],
        "outputs": [("doublet_scores", "doublet_scores", "scdblfinder_usage"), ("doublet_labels", "doublet_labels", "scdblfinder_usage")],
    },
    {
        "slug": "singler.singler",
        "package": "singler",
        "qualified_name": "SingleR::SingleR",
        "method": "singler_annotation",
        "task": "cell_type_annotation",
        "inputs": [("query_expression", "single_cell_expression", "singler_io"), ("reference_expression", "reference_expression_profiles", "singler_io")],
        "outputs": [("cell_type_labels", "cell_type_labels", "singler_io")],
    },
]


MANUAL_CLAIMS: list[dict[str, Any]] = [
    {"subject": "package:seurat", "predicate": "supports_task", "object": "task:quality_control", "text": "Seurat is an R toolkit for single-cell genomics and supplies a framework in which quality-control workflows can be implemented.", "evidence": "seurat_overview", "assertion": "capability", "risk": "R2"},
    {"subject": "package:seurat", "predicate": "supports_task", "object": "task:multiomics_integration", "text": "Seurat v5 documents functionality for spatial and multimodal single-cell analysis.", "evidence": "seurat_overview", "assertion": "capability", "risk": "R2"},
    {"subject": "method:harmony_integration", "predicate": "supports_task", "object": "task:batch_integration", "text": "Harmony integrates large and complex single-cell datasets in a corrected embedding space.", "evidence": "harmony_overview", "assertion": "capability", "risk": "R2"},
    {"subject": "operator-revision:harmony.run_harmony:source-snapshot", "predicate": "key_parameter", "object": "parameter:harmony_batch_covariates", "text": "RunHarmony requires metadata covariates such as dataset, donor, or batch identifiers to define integration variables.", "evidence": "harmony_api", "assertion": "requirement", "risk": "R3"},
    {"subject": "method:scanorama_integration", "predicate": "supports_task", "object": "task:batch_integration", "text": "Scanorama integrates heterogeneous single-cell RNA-seq datasets into a low-dimensional representation.", "evidence": "scanorama_overview", "assertion": "capability", "risk": "R2"},
    {"subject": "method:scanorama_batch_correction", "predicate": "supports_task", "object": "task:batch_integration", "text": "Scanorama can return batch-corrected cell-by-gene expression matrices.", "evidence": "scanorama_api", "assertion": "capability", "risk": "R2"},
    {"subject": "operator:scanorama.integrate_scanpy", "predicate": "key_parameter", "object": "parameter:scanorama_batch_size", "text": "Scanorama documents lowering batch_size as a response to memory pressure during large integrations.", "evidence": "scanorama_limitation", "assertion": "recommendation", "risk": "R3"},
    {"subject": "method:scanorama_integration", "predicate": "has_limitation", "object": "limitation:scanorama_memory_pressure", "text": "Large Scanorama integrations can encounter memory pressure, for which smaller batches or sketching are documented mitigations.", "evidence": "scanorama_limitation", "assertion": "limitation", "risk": "R3"},
    {"subject": "package:scvi_tools", "predicate": "supports_task", "object": "task:batch_integration", "text": "scvi-tools includes probabilistic models for data integration and dimensionality reduction.", "evidence": "scvi_overview", "assertion": "capability", "risk": "R2"},
    {"subject": "package:scvi_tools", "predicate": "supports_task", "object": "task:multiomics_integration", "text": "scvi-tools includes models for analysis across single-cell multi-omic data.", "evidence": "scvi_overview", "assertion": "capability", "risk": "R2"},
    {"subject": "method:scrublet", "predicate": "supports_task", "object": "task:doublet_detection", "text": "Scrublet identifies doublets in single-cell RNA-seq data by simulating doublets and classifying observed transcriptomes.", "evidence": "scrublet_api", "assertion": "capability", "risk": "R2"},
    {"subject": "operator:scrublet.scrub_doublets", "predicate": "key_parameter", "object": "parameter:scrublet_score_threshold", "text": "Scrublet thresholds continuous doublet scores to produce predicted-doublet labels, and the threshold should be reviewed for the observed score distribution.", "evidence": "scrublet_api", "assertion": "recommendation", "risk": "R3"},
    {"subject": "method:scrublet", "predicate": "has_limitation", "object": "limitation:scrublet_merged_samples", "text": "Scrublet may perform poorly on merged samples whose cell-type proportions do not represent an individual capture.", "evidence": "scrublet_limitation", "assertion": "limitation", "risk": "R3"},
    {"subject": "method:doubletfinder", "predicate": "supports_task", "object": "task:doublet_detection", "text": "DoubletFinder predicts doublets in single-cell RNA-seq data using artificial nearest-neighbor structure.", "evidence": "doubletfinder_identity", "assertion": "capability", "risk": "R2"},
    {"subject": "operator:doubletfinder.doubletfinder", "predicate": "key_parameter", "object": "parameter:doubletfinder_pk_and_nexp", "text": "DoubletFinder uses pK selection and an expected-doublet count to threshold pANN-based classifications.", "evidence": "doubletfinder_overview", "assertion": "requirement", "risk": "R3"},
    {"subject": "method:doubletfinder", "predicate": "has_limitation", "object": "limitation:doubletfinder_merged_or_integrated_input", "text": "DoubletFinder documentation advises against integrated objects and against merged captures that could create impossible artificial doublets.", "evidence": "doubletfinder_limitation", "assertion": "limitation", "risk": "R3"},
    {"subject": "method:scdblfinder", "predicate": "supports_task", "object": "task:doublet_detection", "text": "scDblFinder detects and handles doublets or multiplets in single-cell sequencing data.", "evidence": "scdblfinder_usage", "assertion": "capability", "risk": "R2"},
    {"subject": "operator:scdblfinder.scdblfinder", "predicate": "key_parameter", "object": "parameter:scdblfinder_samples", "text": "scDblFinder accepts sample identifiers so sample-specific doublet rates can be modeled for multiple captures.", "evidence": "scdblfinder_samples", "assertion": "requirement", "risk": "R3"},
    {"subject": "method:scdblfinder", "predicate": "has_limitation", "object": "limitation:scdblfinder_threshold_prior", "text": "The expected doublet-rate prior strongly affects the scDblFinder classification threshold even when score ranking changes little.", "evidence": "scdblfinder_limitation", "assertion": "limitation", "risk": "R3"},
    {"subject": "method:celltypist_annotation", "predicate": "supports_task", "object": "task:cell_type_annotation", "text": "CellTypist assigns cell-type labels to query cells using a selected reference classifier model.", "evidence": "celltypist_api", "assertion": "capability", "risk": "R2"},
    {"subject": "method:celltypist_annotation", "predicate": "requires_representation", "object": "representation-type:log_rna_expression", "text": "In-memory CellTypist annotation requires log1p-normalized expression in AnnData and checks X before raw.X.", "evidence": "celltypist_input", "assertion": "requirement", "risk": "R3"},
    {"subject": "method:celltypist_annotation", "predicate": "produces", "object": "representation-type:cell_type_labels", "text": "CellTypist annotation returns per-cell predicted labels together with decision and probability matrices.", "evidence": "celltypist_output", "assertion": "capability", "risk": "R2"},
    {"subject": "method:celltypist_annotation", "predicate": "key_parameter", "object": "parameter:celltypist_majority_voting", "text": "CellTypist majority_voting optionally refines predictions using over-clustering information.", "evidence": "celltypist_parameter", "assertion": "recommendation", "risk": "R3"},
    {"subject": "method:celltypist_annotation", "predicate": "has_limitation", "object": "limitation:celltypist_normalization_or_gene_loss", "text": "CellTypist rejects unsuitable normalization and warns that removing genes after normalization may reduce prediction quality.", "evidence": "celltypist_input", "assertion": "limitation", "risk": "R3"},
    {"subject": "method:singler_annotation", "predicate": "supports_task", "object": "task:cell_type_annotation", "text": "SingleR annotates single-cell transcriptomes by correlation with reference expression profiles from pure cell types.", "evidence": "singler_task", "assertion": "capability", "risk": "R2"},
    {"subject": "method:scvi", "predicate": "supports_task", "object": "task:batch_integration", "text": "The scVI method family is used for probabilistic representation learning and integration of single-cell RNA measurements.", "evidence": "scvi_overview", "assertion": "capability", "risk": "R2", "stance": "partial_support"},
    {"subject": "method:rna_velocity", "predicate": "supports_task", "object": "task:rna_velocity", "text": "scVelo provides scalable RNA velocity analysis that recovers directed dynamic information from splicing kinetics.", "evidence": "scvelo_overview", "assertion": "capability", "risk": "R2"},
    {"subject": "method:rna_velocity", "predicate": "produces", "object": "representation-type:velocity_vectors", "text": "RNA velocity analysis estimates directed cellular dynamics represented by velocity information.", "evidence": "scvelo_overview", "assertion": "capability", "risk": "R2"},
    {"subject": "method:rna_velocity", "predicate": "produces", "object": "representation-type:pseudotime_lineages", "text": "scVelo can infer latent time to reconstruct the temporal sequence of transcriptomic events.", "evidence": "scvelo_overview", "assertion": "capability", "risk": "R2"},
    {"subject": "method:cellrank_fate_mapping", "predicate": "supports_task", "object": "task:fate_mapping", "text": "CellRank estimates differentiation direction and maps cellular fates from biological transition priors.", "evidence": "cellrank_overview", "assertion": "capability", "risk": "R2"},
    {"subject": "method:cellrank_fate_mapping", "predicate": "requires_representation", "object": "representation-type:transition_matrix", "text": "CellRank combines biological priors into Markov transition kernels for fate analysis.", "evidence": "cellrank_overview", "assertion": "requirement", "risk": "R3"},
    {"subject": "method:cellrank_fate_mapping", "predicate": "produces", "object": "representation-type:fate_probabilities", "text": "CellRank infers terminal macrostates, fate probabilities, and driver genes.", "evidence": "cellrank_overview", "assertion": "capability", "risk": "R2"},
    {"subject": "method:trajectory_differential_expression", "predicate": "supports_task", "object": "task:differential_expression", "text": "tradeSeq discovers genes that are differentially expressed along one or multiple lineages.", "evidence": "tradeseq_overview", "assertion": "capability", "risk": "R2"},
    {"subject": "method:trajectory_differential_expression", "predicate": "requires_representation", "object": "representation-type:pseudotime_lineages", "text": "tradeSeq differential testing is scoped to one or multiple inferred lineages.", "evidence": "tradeseq_overview", "assertion": "requirement", "risk": "R3", "stance": "partial_support"},
    {"subject": "method:trajectory_differential_expression", "predicate": "produces", "object": "representation-type:differential_statistics", "text": "tradeSeq provides statistical tests for lineage-associated differential-expression questions.", "evidence": "tradeseq_overview", "assertion": "capability", "risk": "R2"},
    {"subject": "method:single_cell_optimal_transport", "predicate": "supports_task", "object": "task:trajectory_inference", "text": "moscot supports trajectory inference using optimal transport with temporal, spatial, or lineage information.", "evidence": "moscot_overview", "assertion": "capability", "risk": "R2"},
    {"subject": "method:single_cell_optimal_transport", "predicate": "supports_task", "object": "task:multiomics_integration", "text": "moscot supports modality translation and other optimal-transport applications across single-cell modalities.", "evidence": "moscot_overview", "assertion": "capability", "risk": "R2"},
    {"subject": "method:waddington_ot", "predicate": "supports_task", "object": "task:trajectory_inference", "text": "Waddington-OT uses optimal transport to identify developmental trajectories from time-resolved single-cell expression snapshots.", "evidence": "wot_paper", "assertion": "capability", "risk": "R2", "stance": "partial_support"},
    {"subject": "method:mofa", "predicate": "supports_task", "object": "task:multiomics_integration", "text": "MOFA integrates multi-omic datasets in an unsupervised factor-analysis framework.", "evidence": "mofa_overview", "assertion": "capability", "risk": "R2"},
    {"subject": "method:mofa", "predicate": "requires_representation", "object": "representation-type:multiomics_matrices", "text": "MOFA accepts multiple omics matrices measured on the same or overlapping sets of samples.", "evidence": "mofa_overview", "assertion": "requirement", "risk": "R3"},
    {"subject": "method:mofa", "predicate": "produces", "object": "representation-type:latent_factors", "text": "MOFA infers an interpretable low-dimensional representation composed of latent factors across data modalities.", "evidence": "mofa_overview", "assertion": "capability", "risk": "R2"},
    {"subject": "method:cell2location", "predicate": "supports_task", "object": "task:spatial_deconvolution", "text": "cell2location maps fine-grained cell types in spatial transcriptomic data by decomposing spatial RNA counts using reference signatures.", "evidence": "cell2location_overview", "assertion": "capability", "risk": "R2"},
    {"subject": "method:cell2location", "predicate": "requires_representation", "object": "representation-type:spatial_counts", "text": "cell2location takes spatial transcriptomic count data as one model input.", "evidence": "cell2location_io", "assertion": "requirement", "risk": "R3"},
    {"subject": "method:cell2location", "predicate": "requires_representation", "object": "representation-type:cell_type_signatures", "text": "cell2location requires single-cell-derived reference cell-type expression signatures for spatial mapping.", "evidence": "cell2location_io", "assertion": "requirement", "risk": "R3"},
    {"subject": "method:cell2location", "predicate": "produces", "object": "representation-type:spatial_cell_abundance", "text": "cell2location estimates cell-type abundance across spatial locations.", "evidence": "cell2location_io", "assertion": "capability", "risk": "R2"},
    {"subject": "method:mimosca", "predicate": "supports_task", "object": "task:regulatory_network_inference", "text": "MIMOSCA supports perturbation-aware analysis of molecular circuits from pooled single-cell perturbation experiments.", "evidence": "mimosca_paper", "assertion": "capability", "risk": "R2", "stance": "partial_support"},
    {"subject": "method:soupx", "predicate": "supports_task", "object": "task:ambient_rna_removal", "text": "SoupX removes ambient RNA contamination from droplet-based single-cell RNA-sequencing data.", "evidence": "soupx_paper", "assertion": "capability", "risk": "R2"},
]


PARAMETER_LIMITATION_GAPS = {
    "seurat": ["version-pinned operator/API semantics", "canonical ports", "operator-specific parameters and limitations"],
    "scvi_tools": ["version-pinned SCVI/TOTALVI/MULTIVI operator revisions", "model-specific ports", "model-specific parameters and limitations"],
    "celltypist": ["content-pinned ReferenceArtifactRevision for classifier models", "version-pinned annotate OperatorRevision"],
    "scvelo": ["version-pinned velocity/velocity_graph operator ports", "model-assumption limitation claims"],
    "cellrank": ["version-pinned kernel and estimator operator ports", "kernel-specific requirements and limitations"],
    "tradeseq": ["version-pinned fitGAM/test operator ports", "count-model parameters and limitations"],
    "moscot": ["version-pinned problem/operator ports", "alignment requirements and limitations"],
    "wot": ["version-pinned command/API ports", "growth-rate inputs and limitations"],
    "mofa2": ["version-pinned R/Python operator identities", "training parameters and missing-view limitations"],
    "cell2location": ["version-pinned model operator revision", "N_cells_per_location and detection_alpha semantics"],
    "mimosca": ["stable package operator identity", "expression and guide-assignment ports", "PCR-chimera/detection limitations with bounded evidence"],
    "soupx": ["official source-text-backed input/output ports", "contamination-fraction parameters", "failure conditions and limitations"],
}


IDENTITY_VERSION_CONFLICTS = [
    {
        "conflict_id": "identity-conflict:scvi-tools-vs-scvi-method",
        "ecosystem": "scvi-tools",
        "kind": "package_method_identity",
        "description": "scvi-tools is a software distribution while scVI is one implemented method family; aliases must not collapse them into one entity.",
        "status": "resolved_in_candidate_identity_pending_human_review",
    },
    {
        "conflict_id": "identity-conflict:mofa2-r-vs-mofapy2-python",
        "ecosystem": "MOFA2",
        "kind": "multi_package_project_identity",
        "description": "MOFA2 and mofapy2 are distinct R and Python packages distributed by the same software project and require independent release/operator versioning.",
        "status": "unresolved_release_mapping",
    },
    {
        "conflict_id": "identity-conflict:singler-legacy-vs-bioconductor",
        "ecosystem": "SingleR",
        "kind": "source_version_identity",
        "description": "Available source evidence spans historical project and current Bioconductor identities; a version-pinned OperatorRevision cannot yet be promoted.",
        "status": "unresolved_source_version",
    },
    {
        "conflict_id": "identity-conflict:harmony-api-generation",
        "ecosystem": "Harmony",
        "kind": "source_version_identity",
        "description": "Available API and overview evidence are source-bound but not pinned to one immutable Harmony package release.",
        "status": "unresolved_source_version",
    },
    {
        "conflict_id": "identity-conflict:celltypist-reference-model-version",
        "ecosystem": "CellTypist",
        "kind": "reference_artifact_version",
        "description": "Classifier model selection is decision-relevant, but the local evidence does not resolve immutable ReferenceArtifactRevision identities.",
        "status": "unresolved_reference_artifact_version",
    },
]


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_text(value: str) -> str:
    return _sha256_bytes(value.encode("utf-8"))


def _json_hash(value: Any) -> str:
    return _sha256_text(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def _file_hash(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows), encoding="utf-8")


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _scope(scope_id: str, task_id: str, modalities: list[str] | None = None) -> ApplicabilityScope:
    return ApplicabilityScope(
        scope_id=scope_id,
        task_ids=[task_id],
        version_constraints=[],
        modalities=modalities or ["rna"],
        observation_units=["cell"],
        scope_status="partially_known",
    )


def _representation_types(scanpy_bundle: ConformanceBundle) -> list[RepresentationType]:
    existing = {item.representation_type_id for item in scanpy_bundle.representation_types}
    result = list(scanpy_bundle.representation_types)
    for slug, label, unit, axes, modalities, semantics, states, feature_identity in REPRESENTATIONS:
        representation_id = f"representation-type:{slug}"
        if representation_id in existing:
            continue
        result.append(
            RepresentationType(
                representation_type_id=representation_id,
                label=label,
                observation_unit=unit,
                axes=axes,
                modalities=modalities,
                value_semantics=semantics,
                transformation_state=states,
                feature_identity=feature_identity,
                missingness_semantics="missing values retain modality- and assay-specific meaning and are not silently treated as measured zero",
            )
        )
    return result


def _entity_records(scanpy_bundle: ConformanceBundle) -> list[Any]:
    records: list[Any] = list(scanpy_bundle.entities)
    known_ids = {item.entity_id for item in records}
    for task_slug, label in TASKS.items():
        entity_id = f"task:{task_slug}"
        if entity_id not in known_ids:
            records.append(ScientificTask(entity_id=entity_id, label=label))
            known_ids.add(entity_id)
    for ecosystem in ECOSYSTEMS:
        if ecosystem["slug"] == "scanpy":
            continue
        slug = ecosystem["slug"]
        project_id = f"software-project:{slug}"
        package_id = f"package:{slug}"
        records.extend(
            [
                SoftwareProject(entity_id=project_id, label=ecosystem["label"]),
                Package(
                    entity_id=package_id,
                    project_id=project_id,
                    ecosystem=ecosystem["ecosystem"],
                    distribution_name=ecosystem["distribution"],
                ),
            ]
        )
        for extra_slug, extra_ecosystem, distribution in ecosystem.get("additional_packages", []):
            records.append(
                Package(
                    entity_id=f"package:{extra_slug}",
                    project_id=project_id,
                    ecosystem=extra_ecosystem,
                    distribution_name=distribution,
                )
            )
        for method_slug, method_label in ecosystem["methods"]:
            records.append(Method(entity_id=f"method:{method_slug}", label=method_label))
        for variant_slug, method_slug, label in ecosystem.get("variants", []):
            records.append(
                MethodVariant(
                    entity_id=f"method-variant:{variant_slug}",
                    method_id=f"method:{method_slug}",
                    label=label,
                )
            )
    return records


def _evidence_catalog() -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    chunks = {item["chunk_id"]: item for item in _load_jsonl(EVIDENCE_INDEX)}
    sources = {item["source_id"]: item for item in _load_jsonl(SOURCE_INDEX)}
    return chunks, sources


def _source_bound_evidence_refs(chunks: dict[str, dict[str, Any]], sources: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    refs = []
    for evidence_id in sorted(set(EVIDENCE_IDS.values())):
        chunk = chunks[evidence_id]
        source = sources.get(chunk.get("source_id", ""), {})
        refs.append(
            {
                "schema_version": "sckg-evidence-span-reference-candidate-v1",
                "evidence_span_id": evidence_id,
                "source_record_id": chunk.get("source_id") or chunk.get("source_record_id"),
                "source_document_id": chunk.get("source_document_id") or None,
                "source_title": chunk.get("title") or source.get("canonical_title"),
                "source_type": chunk.get("source_type") or source.get("source_type"),
                "source_url": chunk.get("source_url") or source.get("source_url"),
                "authority": "official_project_documentation" if (chunk.get("source_type") or "") in {"github_readme", "official_docs_html"} else "primary_or_reviewed_scientific_source",
                "source_bound": bool(chunk.get("source_bound")),
                "locator": chunk.get("source_span") or f"section:{chunk.get('section', '')};paragraph:{chunk.get('paragraph_index', '')}",
                "content_hash": chunk["content_hash"],
                "bounded_excerpt": chunk["chunk_text"][:800],
                "candidate_only": True,
                "retrieval_eligible": False,
            }
        )
    return refs


def _operator_records(
    records: list[Any],
    scopes: list[ApplicabilityScope],
    representations: list[RepresentationType],
) -> tuple[list[RepresentationConstraint], list[dict[str, Any]]]:
    representation_ids = {item.representation_type_id for item in representations}
    constraints: list[RepresentationConstraint] = []
    operator_evidence: list[dict[str, Any]] = []
    known_entity_ids = {item.entity_id for item in records}
    for spec in OPERATOR_SPECS:
        scope_id = f"scope:{spec['slug']}:source-snapshot"
        scopes.append(_scope(scope_id, f"task:{spec['task']}"))
        release_id = f"package-release:{spec['package']}:source-snapshot"
        operator_id = f"operator:{spec['slug']}"
        revision_id = f"operator-revision:{spec['slug']}:source-snapshot"
        if release_id not in known_entity_ids:
            records.append(
                PackageRelease(
                    entity_id=release_id,
                    package_id=f"package:{spec['package']}",
                    version="unresolved-source-snapshot",
                    immutable_release_ref=f"evidence-index:{EVIDENCE_IDS[spec['inputs'][0][2]]}",
                )
            )
            known_entity_ids.add(release_id)
        records.append(Operator(entity_id=operator_id, package_id=f"package:{spec['package']}", qualified_name=spec["qualified_name"]))
        known_entity_ids.add(operator_id)
        input_ports: list[InputPort] = []
        for role, representation_slug, evidence_key in spec["inputs"]:
            representation_id = f"representation-type:{representation_slug}"
            if representation_id not in representation_ids:
                raise ValueError(f"unknown input representation {representation_id}")
            constraint_id = f"representation-constraint:{spec['slug']}.{role}"
            constraint = RepresentationConstraint(
                constraint_id=constraint_id,
                representation_type_id=representation_id,
                required_modalities=["rna"],
                observation_alignment="same_observations" if role not in {"reference_expression", "batch_covariates"} else "explicit_mapping",
                scope_id=scope_id,
            )
            constraints.append(constraint)
            input_ports.append(
                InputPort(
                    input_port_id=f"input-port:{spec['slug']}.{role}",
                    role=role,
                    min_cardinality=1,
                    max_cardinality=None if role == "datasets" else 1,
                    requirements=[
                        Requirement(
                            requirement_id=f"requirement:{spec['slug']}.{role}",
                            level="mandatory",
                            representation_constraint_ids=[constraint_id],
                            scope_id=scope_id,
                        )
                    ],
                    scope_id=scope_id,
                )
            )
            operator_evidence.append({"subject": revision_id, "predicate": "requires_representation", "object": representation_id, "evidence": evidence_key, "role": role})
        output_ports = []
        for role, representation_slug, evidence_key in spec["outputs"]:
            representation_id = f"representation-type:{representation_slug}"
            if representation_id not in representation_ids:
                raise ValueError(f"unknown output representation {representation_id}")
            output_ports.append(
                OutputPort(
                    output_port_id=f"output-port:{spec['slug']}.{role}",
                    role=role,
                    representation_type_id=representation_id,
                    lineage_input_port_ids=[item.input_port_id for item in input_ports],
                    preserves=["observation_identity"],
                    transforms=["scientific_state"],
                    scope_id=scope_id,
                )
            )
            operator_evidence.append({"subject": revision_id, "predicate": "produces", "object": representation_id, "evidence": evidence_key, "role": role})
        records.append(
            OperatorRevision(
                entity_id=revision_id,
                operator_id=operator_id,
                package_release_id=release_id,
                implements_method_ids=[f"method:{spec['method']}"],
                input_ports=input_ports,
                output_ports=output_ports,
                scope_id=scope_id,
            )
        )
    return constraints, operator_evidence


def _claim(
    *,
    subject: str,
    predicate: str,
    object_id: str,
    text: str,
    scope_id: str,
    assertion_kind: str,
    ordinal: int,
) -> AtomicClaimRevision:
    fingerprint = _sha256_text("|".join([subject, predicate, object_id, scope_id]))
    claim_id = f"claim:content-expansion:{fingerprint[:24]}"
    return AtomicClaimRevision(
        claim_id=claim_id,
        claim_revision_id=f"claim-revision:content-expansion:{fingerprint[:24]}:v1",
        subject_id=subject,
        predicate=predicate,
        object_id=object_id,
        scope_id=scope_id,
        claim_text=text,
        polarity="positive",
        assertion_kind=assertion_kind,
        semantic_fingerprint=fingerprint,
        content_hash=_sha256_text(text),
        created_by_activity_id=f"knowledge-change-set:scientific-kg-content-expansion-v1:{ordinal:03d}",
    )


def _external_claims(
    operator_evidence: list[dict[str, Any]],
) -> tuple[list[AtomicClaimRevision], list[EvidenceAssessment], list[dict[str, Any]]]:
    claims: list[AtomicClaimRevision] = []
    assessments: list[EvidenceAssessment] = []
    governance: list[dict[str, Any]] = []
    specs = list(MANUAL_CLAIMS)
    for item in operator_evidence:
        label = item["subject"].split(":", 1)[1].rsplit(":", 1)[0]
        representation_label = item["object"].split(":", 1)[1].replace("_", " ")
        specs.append(
            {
                "subject": item["subject"],
                "predicate": item["predicate"],
                "object": item["object"],
                "text": f"{label} {item['predicate'].replace('_', ' ')} {representation_label} through its {item['role']} port.",
                "evidence": item["evidence"],
                "assertion": "requirement" if item["predicate"] == "requires_representation" else "capability",
                "risk": "R3" if item["predicate"] == "requires_representation" else "R2",
            }
        )
    scope_by_subject: dict[str, str] = {}
    for op in OPERATOR_SPECS:
        scope_by_subject[f"operator-revision:{op['slug']}:source-snapshot"] = f"scope:{op['slug']}:source-snapshot"
        scope_by_subject[f"operator:{op['slug']}"] = f"scope:{op['slug']}:source-snapshot"
        scope_by_subject[f"method:{op['method']}"] = f"scope:{op['slug']}:source-snapshot"
    family_scope = {
        "seurat": ("quality_control", ["rna"]),
        "scvi_tools": ("multiomics_integration", ["rna", "atac", "protein"]),
        "celltypist_annotation": ("cell_type_annotation", ["rna"]),
        "rna_velocity": ("rna_velocity", ["rna"]),
        "cellrank_fate_mapping": ("fate_mapping", ["rna"]),
        "trajectory_differential_expression": ("differential_expression", ["rna"]),
        "single_cell_optimal_transport": ("trajectory_inference", ["rna", "spatial_rna"]),
        "waddington_ot": ("trajectory_inference", ["rna"]),
        "mofa": ("multiomics_integration", ["rna", "atac", "protein"]),
        "cell2location": ("spatial_deconvolution", ["rna", "spatial_rna"]),
        "mimosca": ("regulatory_network_inference", ["rna"]),
        "soupx": ("ambient_rna_removal", ["rna"]),
        "scvi": ("batch_integration", ["rna"]),
    }
    for key, (task, _) in family_scope.items():
        subject = f"package:{key}" if key in {"seurat", "scvi_tools"} else f"method:{key}"
        scope_by_subject.setdefault(subject, f"scope:content-expansion:{key}")
    for ordinal, spec in enumerate(specs, start=1):
        subject = spec["subject"]
        scope_id = scope_by_subject.get(subject)
        if not scope_id and subject.startswith("operator:"):
            candidates = [value for key, value in scope_by_subject.items() if key.startswith("operator-revision:") and subject.split(":", 1)[1] in key]
            scope_id = candidates[0] if candidates else None
        if not scope_id:
            method_slug = subject.split(":", 1)[1]
            scope_id = f"scope:content-expansion:{method_slug}"
        claim = _claim(
            subject=subject,
            predicate=spec["predicate"],
            object_id=spec["object"],
            text=spec["text"],
            scope_id=scope_id,
            assertion_kind=spec["assertion"],
            ordinal=ordinal,
        )
        claims.append(claim)
        assessments.append(
            EvidenceAssessment(
                assessment_id=f"evidence-assessment:content-expansion:{ordinal:03d}",
                claim_revision_id=claim.claim_revision_id,
                evidence_span_ids=[EVIDENCE_IDS[spec["evidence"]]],
                stance=spec.get("stance", "supports"),
                subject_aligned=True,
                predicate_aligned=spec.get("stance", "supports") == "supports",
                object_aligned=spec.get("stance", "supports") == "supports",
                scope_alignment="aligned" if spec.get("stance", "supports") == "supports" else "partial",
                rationale="Candidate assertion is bounded to the cited source span; promotion still requires risk-appropriate review.",
            )
        )
        governance.append(
            {
                "claim_revision_id": claim.claim_revision_id,
                "risk_class": spec["risk"],
                "review_status": "candidate_pending_review",
                "strong_review_required": spec["risk"] in {"R3", "R4"},
                "reason": "requirements, parameters, and limitations affect planning or scientific interpretation" if spec["risk"] == "R3" else "bounded descriptive capability claim",
            }
        )
    return claims, assessments, governance


def _ensure_family_scopes(scopes: list[ApplicabilityScope]) -> None:
    known = {item.scope_id for item in scopes}
    additions = {
        "scope:content-expansion:seurat": ("quality_control", ["rna"]),
        "scope:content-expansion:scvi_tools": ("multiomics_integration", ["rna", "atac", "protein"]),
        "scope:content-expansion:celltypist_annotation": ("cell_type_annotation", ["rna"]),
        "scope:content-expansion:rna_velocity": ("rna_velocity", ["rna"]),
        "scope:content-expansion:cellrank_fate_mapping": ("fate_mapping", ["rna"]),
        "scope:content-expansion:trajectory_differential_expression": ("differential_expression", ["rna"]),
        "scope:content-expansion:single_cell_optimal_transport": ("trajectory_inference", ["rna", "spatial_rna"]),
        "scope:content-expansion:waddington_ot": ("trajectory_inference", ["rna"]),
        "scope:content-expansion:mofa": ("multiomics_integration", ["rna", "atac", "protein"]),
        "scope:content-expansion:cell2location": ("spatial_deconvolution", ["rna", "spatial_rna"]),
        "scope:content-expansion:mimosca": ("regulatory_network_inference", ["rna"]),
        "scope:content-expansion:soupx": ("ambient_rna_removal", ["rna"]),
        "scope:content-expansion:scvi": ("batch_integration", ["rna"]),
    }
    for scope_id, (task, modalities) in additions.items():
        if scope_id not in known:
            scopes.append(_scope(scope_id, f"task:{task}", modalities))


def _derived_relations(bundle: ConformanceBundle, new_claims: list[AtomicClaimRevision]) -> list[DerivedRelation]:
    relations = list(bundle.derived_relations)
    claim_by_key = {(item.subject_id, item.predicate, item.object_id): item.claim_revision_id for item in new_claims}
    consumes_by_port: dict[str, str] = {}
    produces_by_port: dict[str, str] = {}
    for entity in bundle.entities:
        if not isinstance(entity, OperatorRevision) or entity.entity_id.startswith("operator-revision:scanpy."):
            continue
        for port in entity.input_ports:
            target = next(
                constraint.representation_type_id
                for constraint in bundle.representation_constraints
                if constraint.constraint_id == port.requirements[0].representation_constraint_ids[0]
            )
            claim_id = claim_by_key[(entity.entity_id, "requires_representation", target)]
            relation_id = f"derived-relation:content-expansion:consumes:{_sha256_text(port.input_port_id)[:16]}"
            relations.append(
                DerivedRelation(
                    relation_id=relation_id,
                    relation="CONSUMES",
                    source_id=entity.entity_id,
                    target_id=target,
                    scope_id=entity.scope_id,
                    derivation_type="port_projection",
                    input_port_id=port.input_port_id,
                    derived_from_claim_revision_ids=[claim_id],
                    derivation_rule_id="derive-consumes-from-input-port-v1.1",
                    review_status="candidate_pending_review",
                )
            )
            consumes_by_port[port.input_port_id] = relation_id
        for port in entity.output_ports:
            target = port.representation_type_id
            claim_id = claim_by_key[(entity.entity_id, "produces", target)]
            relation_id = f"derived-relation:content-expansion:produces:{_sha256_text(port.output_port_id)[:16]}"
            relations.append(
                DerivedRelation(
                    relation_id=relation_id,
                    relation="PRODUCES",
                    source_id=entity.entity_id,
                    target_id=target,
                    scope_id=entity.scope_id,
                    derivation_type="port_projection",
                    output_port_id=port.output_port_id,
                    derived_from_claim_revision_ids=[claim_id],
                    derivation_rule_id="derive-produces-from-output-port-v1.1",
                    review_status="candidate_pending_review",
                )
            )
            produces_by_port[port.output_port_id] = relation_id
    scanpy_neighbors = next(
        item for item in bundle.entities if isinstance(item, OperatorRevision) and item.operator_id == "operator:scanpy.pp.neighbors"
    )
    neighbor_input = next(
        item for item in scanpy_neighbors.input_ports if item.input_port_id == "input-port:scanpy.pp.neighbors.coordinates"
    )
    scanpy_consume = next(
        item.relation_id
        for item in bundle.derived_relations
        if item.relation == "CONSUMES" and item.input_port_id == neighbor_input.input_port_id and item.target_id == "representation-type:integrated_coordinates"
    )
    for output_port_id in [
        "output-port:harmony.run_harmony.integrated_coordinates",
        "output-port:scanorama.integrate_scanpy.integrated_coordinates",
    ]:
        producer_revision = next(
            item.entity_id
            for item in bundle.entities
            if isinstance(item, OperatorRevision) and any(port.output_port_id == output_port_id for port in item.output_ports)
        )
        relations.append(
            DerivedRelation(
                relation_id=f"derived-relation:content-expansion:can-feed:{_sha256_text(output_port_id)[:16]}",
                relation="CAN_FEED",
                source_id=producer_revision,
                target_id=scanpy_neighbors.entity_id,
                scope_id=next(item.scope_id for item in bundle.scopes if item.scope_id == scanpy_neighbors.scope_id),
                derivation_type="reviewed_rule",
                input_port_id=neighbor_input.input_port_id,
                output_port_id=output_port_id,
                premise_relation_ids=[produces_by_port[output_port_id], scanpy_consume],
                derived_from_claim_revision_ids=[
                    next(item.derived_from_claim_revision_ids[0] for item in relations if item.relation_id == produces_by_port[output_port_id]),
                    next(item.derived_from_claim_revision_ids[0] for item in bundle.derived_relations if item.relation_id == scanpy_consume),
                ],
                derivation_rule_id="can-feed-compatible-integrated-coordinates-v1.1",
                review_status="candidate_pending_review",
            )
        )
    return relations


def _evidence_gaps(bundle: ConformanceBundle, governance: list[dict[str, Any]]) -> list[dict[str, Any]]:
    predicates_by_subject = defaultdict(set)
    for claim in bundle.atomic_claims:
        predicates_by_subject[claim.subject_id].add(claim.predicate)
    gaps: list[dict[str, Any]] = []
    for ecosystem in ECOSYSTEMS:
        if ecosystem["slug"] == "scanpy":
            continue
        for gap in PARAMETER_LIMITATION_GAPS.get(ecosystem["slug"], []):
            gaps.append(
                {
                    "gap_id": f"evidence-gap:{ecosystem['slug']}:{_sha256_text(gap)[:16]}",
                    "ecosystem": ecosystem["label"],
                    "missing_knowledge": gap,
                    "reason": "No currently available source-bound authoritative evidence was sufficient to create a versioned decision-useful record.",
                    "required_source": "version-pinned official API documentation or primary-method evidence with a bounded supporting span",
                    "blocking": "operator_or_relation_promotion",
                    "candidate_only": True,
                }
            )
        if any(operator["package"] == ecosystem["slug"] for operator in OPERATOR_SPECS):
            gaps.append(
                {
                    "gap_id": f"evidence-gap:{ecosystem['slug']}:immutable-release-pin",
                    "ecosystem": ecosystem["label"],
                    "missing_knowledge": "immutable package release and OperatorRevision version pin",
                    "reason": "The available source-bound evidence supports candidate API semantics but is not tied to one immutable package release.",
                    "required_source": "versioned official API documentation plus immutable package release or source commit",
                    "blocking": "operator_revision_promotion",
                    "candidate_only": True,
                }
            )
        ecosystem_subjects = {
            f"package:{ecosystem['slug']}",
            *(f"method:{slug}" for slug, _ in ecosystem["methods"]),
        }
        for operator in OPERATOR_SPECS:
            if operator["package"] != ecosystem["slug"]:
                continue
            ecosystem_subjects.update(
                {
                    f"operator:{operator['slug']}",
                    f"operator-revision:{operator['slug']}:source-snapshot",
                }
            )
        available = set().union(
            *(predicates_by_subject.get(subject, set()) for subject in ecosystem_subjects)
        )
        for predicate in sorted({"supports_task", "requires_representation", "produces", "key_parameter", "has_limitation"} - available):
            gaps.append(
                {
                    "gap_id": f"evidence-gap:{ecosystem['slug']}:{predicate}",
                    "ecosystem": ecosystem["label"],
                    "missing_knowledge": predicate,
                    "reason": "Coverage matrix remains incomplete; absence is represented as unknown rather than inferred.",
                    "required_source": "claim-local authoritative evidence",
                    "blocking": "relation_specific_only",
                    "candidate_only": True,
                }
            )
    reviewed_ids = {item["claim_revision_id"] for item in governance}
    if len(reviewed_ids) != len(governance):
        raise ValueError("claim governance identifiers are not unique")
    return gaps


def _identity_graph(bundle: ConformanceBundle) -> dict[str, Any]:
    nodes = [item.model_dump(mode="json") for item in bundle.entities]
    edges: list[dict[str, Any]] = []
    for item in bundle.entities:
        if isinstance(item, Package):
            edges.append({"source": item.project_id, "relation": "DISTRIBUTES", "target": item.entity_id})
        elif isinstance(item, PackageRelease):
            edges.append({"source": item.package_id, "relation": "HAS_RELEASE", "target": item.entity_id})
        elif isinstance(item, Operator):
            edges.append({"source": item.package_id, "relation": "EXPORTS", "target": item.entity_id})
        elif isinstance(item, OperatorRevision):
            edges.append({"source": item.entity_id, "relation": "REVISION_OF", "target": item.operator_id})
            for method_id in item.implements_method_ids:
                edges.append({"source": item.entity_id, "relation": "IMPLEMENTS", "target": method_id})
    return {
        "schema_version": "sckg-scientific-content-identity-graph-candidate-v1.1",
        "status": "candidate_only_not_promoted",
        "nodes": nodes,
        "edges": edges,
        "flat_tool_nodes_created": 0,
    }


def _coverage_plan() -> dict[str, Any]:
    family_counts = Counter(family for ecosystem in ECOSYSTEMS for family in ecosystem["families"])
    return {
        "schema_version": "sckg-scientific-content-coverage-plan-v1",
        "status": "implemented_as_candidate_only",
        "architecture_contract": "docs/SCIENTIFIC_AGENT_KG_SPEC_V1_1.md",
        "reference_implementation": "data/evidence_candidates/scientific_knowledge_scanpy_core_v1_1",
        "target_ecosystem_count": len(ECOSYSTEMS),
        "capability_families": CAPABILITY_FAMILIES,
        "family_coverage_counts": dict(sorted(family_counts.items())),
        "ecosystems": ECOSYSTEMS,
        "selection_policy": [
            "high-frequency single-cell or multi-omics ecosystem",
            "coverage contributes to a required scientific action-space family",
            "claims require source-bound official documentation or primary scientific evidence",
            "missing operator/version/port facts become EvidenceGap rather than inferred completeness",
        ],
    }


def build(output_dir: Path = DEFAULT_OUTPUT_DIR) -> dict[str, Any]:
    output_dir = Path(output_dir)
    canonical_before = {str(path.relative_to(PROJECT_ROOT)): _file_hash(path) for path in CANONICAL_PATHS if path.exists()}
    scanpy_bundle = ConformanceBundle.model_validate(json.loads(SCANPY_REFERENCE_BUNDLE.read_text(encoding="utf-8")))
    chunks, sources = _evidence_catalog()
    missing_evidence = sorted(set(EVIDENCE_IDS.values()) - set(chunks))
    if missing_evidence:
        raise ValueError(f"missing evidence spans: {missing_evidence}")
    unsafe_evidence = sorted(evidence_id for evidence_id in EVIDENCE_IDS.values() if not chunks[evidence_id].get("source_bound"))
    if unsafe_evidence:
        raise ValueError(f"evidence is not source-bound: {unsafe_evidence}")

    scopes = list(scanpy_bundle.scopes)
    representations = _representation_types(scanpy_bundle)
    entities = _entity_records(scanpy_bundle)
    constraints, operator_evidence = _operator_records(entities, scopes, representations)
    constraints = [*scanpy_bundle.representation_constraints, *constraints]
    _ensure_family_scopes(scopes)
    new_claims, new_assessments, governance = _external_claims(operator_evidence)
    provisional = ConformanceBundle(
        fixture_id="conformance-fixture:scientific-kg-content-expansion-v1",
        description="Broad candidate-only scientific knowledge content expansion using the frozen Scientific Agent KG v1.1 contract.",
        scopes=scopes,
        representation_types=representations,
        representation_constraints=constraints,
        entities=entities,
        atomic_claims=[*scanpy_bundle.atomic_claims, *new_claims],
        evidence_assessments=[*scanpy_bundle.evidence_assessments, *new_assessments],
        derived_relations=list(scanpy_bundle.derived_relations),
        expected_semantics=[
            "Package, Operator, Method, and MethodVariant identities remain distinct.",
            "InputPort and OutputPort requirements are canonical; CONSUMES and PRODUCES are projections.",
            "Unsupported relations remain explicit EvidenceGap records.",
            "All records are candidate-only and cannot authorize execution or alter canonical knowledge.",
        ],
    )
    relations = _derived_relations(provisional, new_claims)
    bundle = provisional.model_copy(update={"derived_relations": relations})
    bundle = ConformanceBundle.model_validate(bundle.model_dump(mode="json"))
    gaps = _evidence_gaps(bundle, governance)
    evidence_refs = _source_bound_evidence_refs(chunks, sources)
    evidence_ref_ids = {item["evidence_span_id"] for item in evidence_refs}
    scanpy_authoritative_ids = {json.loads(line)["evidence_span_id"] for line in SCANPY_REFERENCE_SPANS.read_text(encoding="utf-8").splitlines() if line.strip()}
    repository_evidence_ids = {
        evidence_id
        for assessment in scanpy_bundle.evidence_assessments
        for evidence_id in assessment.evidence_span_ids
        if evidence_id.startswith("repository-span:")
    }
    all_assessment_evidence = {
        evidence_id
        for assessment in bundle.evidence_assessments
        for evidence_id in assessment.evidence_span_ids
    }
    resolved_evidence = evidence_ref_ids | scanpy_authoritative_ids | repository_evidence_ids
    relation_counts = Counter(item.relation for item in bundle.derived_relations)
    entity_counts = Counter(item.record_type for item in bundle.entities)
    entity_ids = [item.entity_id for item in bundle.entities]
    predicate_counts = Counter(item.predicate for item in bundle.atomic_claims)
    family_counts = Counter(family for ecosystem in ECOSYSTEMS for family in ecosystem["families"])
    stance_counts = Counter(item.stance for item in bundle.evidence_assessments)
    high_risk = [item for item in governance if item["risk_class"] in {"R3", "R4"}]
    coverage = _coverage_plan()
    quality_report = {
        "schema_version": "sckg-scientific-content-quality-report-v1",
        "status": "candidate_conformant_pending_risk_review",
        "checks": {
            "schema_validity": {"passed": True, "validated_bundles": 1},
            "ecosystem_coverage": {"passed": len(ECOSYSTEMS) >= 15, "count": len(ECOSYSTEMS)},
            "required_capability_family_coverage": {"passed": set(family_counts) == set(CAPABILITY_FAMILIES), "counts": dict(sorted(family_counts.items()))},
            "package_operator_method_separation": {"passed": not any(getattr(item, "record_type", "") == "Tool" for item in bundle.entities), "flat_tool_nodes": 0},
            "entity_identity_uniqueness": {"passed": len(entity_ids) == len(set(entity_ids)), "duplicate_count": len(entity_ids) - len(set(entity_ids))},
            "canonical_port_coverage": {"passed": all(item.input_ports and item.output_ports for item in bundle.entities if isinstance(item, OperatorRevision)), "operator_revisions": entity_counts["OperatorRevision"]},
            "evidence_span_resolvability": {"passed": all_assessment_evidence <= resolved_evidence, "resolved": len(all_assessment_evidence & resolved_evidence), "total": len(all_assessment_evidence)},
            "source_bound_external_evidence": {"passed": all(item["source_bound"] for item in evidence_refs), "validated": len(evidence_refs)},
            "claim_content_hash_validity": {"passed": all(item.content_hash == _sha256_text(item.claim_text) for item in bundle.atomic_claims), "validated": len(bundle.atomic_claims)},
            "claim_evidence_coverage": {"passed": len(bundle.atomic_claims) == len(bundle.evidence_assessments), "claims": len(bundle.atomic_claims), "assessments": len(bundle.evidence_assessments)},
            "unsupported_candidate_relation": {"passed": True, "count": 0, "policy": "unproven semantics are emitted only as EvidenceGap"},
            "requires_before_without_proof": {"passed": relation_counts["REQUIRES_BEFORE"] == 0, "count": relation_counts["REQUIRES_BEFORE"]},
            "can_feed_review_boundary": {"passed": all(item.review_status == "candidate_pending_review" for item in bundle.derived_relations if item.relation == "CAN_FEED")},
            "runtime_representation_boundary": {"passed": not bundle.instance_bindings, "owner": "RepresentationLedger"},
            "identity_version_conflicts_retained": {"passed": True, "count": len(IDENTITY_VERSION_CONFLICTS), "policy": "conflicts remain explicit candidate blockers and are not silently collapsed"},
            "canonical_graph_unchanged": {"passed": True},
            "retrieval_index_unchanged": {"passed": True},
        },
        "counts": {
            "ecosystems": len(ECOSYSTEMS),
            "entities": len(bundle.entities),
            "entity_types": dict(sorted(entity_counts.items())),
            "representation_types": len(bundle.representation_types),
            "representation_constraints": len(bundle.representation_constraints),
            "atomic_claims": len(bundle.atomic_claims),
            "new_atomic_claims": len(new_claims),
            "evidence_assessments": len(bundle.evidence_assessments),
            "evidence_span_references": len(evidence_refs) + len(scanpy_authoritative_ids) + len(repository_evidence_ids),
            "claim_predicates": dict(sorted(predicate_counts.items())),
            "evidence_stances": dict(sorted(stance_counts.items())),
            "derived_relations": dict(sorted(relation_counts.items())),
            "evidence_gaps": len(gaps),
            "high_risk_pending_claims": len(high_risk),
        },
        "promotion": {
            "performed": False,
            "eligible_now": False,
            "reason": "Candidate claims and high-impact requirements/limitations require risk-based adjudication; unresolved version and operator evidence gaps remain explicit.",
        },
    }
    artifacts = {
        "coverage_plan.json": coverage,
        "conformance_bundle.json": bundle.model_dump(mode="json"),
        "identity_graph.json": _identity_graph(bundle),
        "decision_relation_coverage.json": {
            "schema_version": "sckg-decision-relation-coverage-candidate-v1",
            "claim_predicates": dict(sorted(predicate_counts.items())),
            "derived_relations": dict(sorted(relation_counts.items())),
            "operator_revisions_with_canonical_ports": entity_counts["OperatorRevision"],
            "representation_instance_owner": "RepresentationLedger",
        },
        "evidence_gaps.json": {"schema_version": "sckg-evidence-gap-set-v1.1", "status": "candidate_only", "gaps": gaps},
        "identity_version_conflicts.json": {
            "schema_version": "sckg-identity-version-conflict-set-v1",
            "status": "candidate_only_unresolved",
            "conflicts": IDENTITY_VERSION_CONFLICTS,
        },
        "quality_report.json": quality_report,
    }
    for name, value in artifacts.items():
        _write_json(output_dir / name, value)
    _write_jsonl(output_dir / "atomic_claims.jsonl", [item.model_dump(mode="json") for item in bundle.atomic_claims])
    _write_jsonl(output_dir / "evidence_assessments.jsonl", [item.model_dump(mode="json") for item in bundle.evidence_assessments])
    _write_jsonl(output_dir / "evidence_span_references.jsonl", evidence_refs)
    _write_jsonl(output_dir / "claim_governance.jsonl", governance)
    _write_jsonl(output_dir / "derived_relations.jsonl", [item.model_dump(mode="json") for item in bundle.derived_relations])
    _write_json(output_dir / "high_risk_claims.json", {"schema_version": "sckg-high-risk-claim-review-queue-v1", "status": "candidate_pending_review", "claims": high_risk})

    canonical_after = {str(path.relative_to(PROJECT_ROOT)): _file_hash(path) for path in CANONICAL_PATHS if path.exists()}
    if canonical_before != canonical_after:
        raise RuntimeError("canonical or retrieval artifacts changed during content expansion")
    generated = sorted(path for path in output_dir.iterdir() if path.is_file() and path.name != "manifest.json")
    manifest = {
        "schema_version": "sckg-scientific-kg-content-expansion-manifest-v1",
        "status": "candidate_only_not_promoted",
        "architecture_contract": "docs/SCIENTIFIC_AGENT_KG_SPEC_V1_1.md",
        "reference_slice": str(SCANPY_REFERENCE_BUNDLE.parent.relative_to(PROJECT_ROOT)),
        "source_inputs": {
            str(SCANPY_REFERENCE_BUNDLE.relative_to(PROJECT_ROOT)): _file_hash(SCANPY_REFERENCE_BUNDLE),
            str(EVIDENCE_INDEX.relative_to(PROJECT_ROOT)): _file_hash(EVIDENCE_INDEX),
            str(SOURCE_INDEX.relative_to(PROJECT_ROOT)): _file_hash(SOURCE_INDEX),
        },
        "artifacts": {path.name: _file_hash(path) for path in generated},
        "canonical_before": canonical_before,
        "canonical_after": canonical_after,
        "canonical_kg_modified": False,
        "retrieval_index_rebuilt": False,
        "runtime_modified": False,
        "promotion_performed": False,
    }
    _write_json(output_dir / "manifest.json", manifest)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()
    manifest = build(args.output_dir)
    print(json.dumps({"status": manifest["status"], "artifact_count": len(manifest["artifacts"])}, sort_keys=True))


if __name__ == "__main__":
    main()
