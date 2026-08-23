from __future__ import annotations

import re
import unicodedata
from typing import Dict, Iterable, Optional, Tuple

from core.knowledge_intelligence_models import CanonicalTaskDefinition


CANONICAL_TASKS: Tuple[CanonicalTaskDefinition, ...] = (
    CanonicalTaskDefinition(
        task_id="quality_control",
        label="quality control",
        aliases=["qc", "filtering", "data quality", "质量控制", "过滤低质量细胞"],
        stage_order=1,
        expected_input_types=["raw_or_processed_anndata"],
        expected_output_types=["quality_controlled_anndata"],
    ),
    CanonicalTaskDefinition(
        task_id="doublet_detection",
        label="doublet detection",
        aliases=[
            "doublet",
            "doublets",
            "multiplet",
            "multiplets",
            "doublet calling",
            "双联体",
            "双细胞",
            "双细胞检测",
            "双细胞识别",
        ],
        stage_order=2,
        parent_task_id="quality_control",
        preceding_task_ids=["quality_control"],
        expected_input_types=["raw_count_anndata"],
        expected_output_types=["doublet_scores", "doublet_labels"],
    ),
    CanonicalTaskDefinition(
        task_id="ambient_rna_removal",
        label="ambient RNA removal",
        aliases=["ambient rna", "decontamination", "soupx", "decontx", "背景 rna", "环境 rna"],
        stage_order=3,
        parent_task_id="quality_control",
        preceding_task_ids=["quality_control"],
        expected_input_types=["raw_count_anndata"],
        expected_output_types=["decontaminated_counts"],
    ),
    CanonicalTaskDefinition(
        task_id="normalization",
        label="normalization and feature selection",
        aliases=["normalization", "normalisation", "feature selection", "variable genes", "归一化", "高变基因"],
        stage_order=4,
        preceding_task_ids=["doublet_detection", "ambient_rna_removal"],
        expected_input_types=["quality_controlled_counts"],
        expected_output_types=["normalized_expression", "selected_features"],
    ),
    CanonicalTaskDefinition(
        task_id="batch_integration",
        label="batch integration",
        aliases=[
            "batch correction",
            "batch effect",
            "batch effects",
            "batch effect removal",
            "data integration",
            "integrate batches",
            "integrating batches",
            "batch integrate",
            "批次校正",
            "批次整合",
        ],
        stage_order=5,
        preceding_task_ids=["normalization"],
        expected_input_types=["normalized_expression", "batch_labels"],
        expected_output_types=["integrated_embedding"],
    ),
    CanonicalTaskDefinition(
        task_id="clustering",
        label="clustering",
        aliases=["cluster analysis", "community detection", "聚类"],
        stage_order=6,
        preceding_task_ids=["normalization", "batch_integration"],
        expected_input_types=["cell_embedding"],
        expected_output_types=["cluster_labels"],
    ),
    CanonicalTaskDefinition(
        task_id="cell_type_annotation",
        label="cell type annotation",
        aliases=["cell annotation", "cell classification", "cell type identification", "celltypist", "singler", "细胞类型注释", "细胞分类"],
        stage_order=7,
        preceding_task_ids=["clustering"],
        expected_input_types=["expression_matrix", "reference_or_model"],
        expected_output_types=["cell_type_labels"],
    ),
    CanonicalTaskDefinition(
        task_id="differential_expression",
        label="marker and differential expression",
        aliases=["differential expression", "marker genes", "marker identification", "差异表达", "标记基因"],
        stage_order=8,
        preceding_task_ids=["clustering", "cell_type_annotation"],
        expected_input_types=["expression_matrix", "group_labels"],
        expected_output_types=["ranked_genes", "statistical_results"],
    ),
    CanonicalTaskDefinition(
        task_id="trajectory_inference",
        label="trajectory and pseudotime",
        aliases=["trajectory inference", "pseudotime", "lineage inference", "cell fate", "拟时序", "轨迹分析"],
        stage_order=9,
        preceding_task_ids=["clustering"],
        expected_input_types=["cell_embedding", "cell_state_labels"],
        expected_output_types=["trajectory_graph", "pseudotime"],
    ),
    CanonicalTaskDefinition(
        task_id="rna_velocity",
        label="RNA velocity and fate",
        aliases=["rna velocity", "velocyto", "spliced unspliced", "rna 速率"],
        stage_order=10,
        parent_task_id="trajectory_inference",
        preceding_task_ids=["trajectory_inference"],
        expected_input_types=["spliced_unspliced_counts"],
        expected_output_types=["velocity_vectors", "fate_probabilities"],
    ),
    CanonicalTaskDefinition(
        task_id="cell_cell_communication",
        label="cell-cell communication",
        aliases=["cell communication", "cell-cell interaction", "ligand receptor", "细胞通讯", "配体受体"],
        stage_order=11,
        preceding_task_ids=["cell_type_annotation"],
        expected_input_types=["expression_matrix", "cell_type_labels"],
        expected_output_types=["interaction_network"],
    ),
    CanonicalTaskDefinition(
        task_id="gene_regulatory_network",
        label="gene regulatory network",
        aliases=["gene regulatory network inference", "grn", "regulatory network", "基因调控网络"],
        stage_order=12,
        preceding_task_ids=["normalization"],
        expected_input_types=["expression_matrix"],
        expected_output_types=["regulatory_network"],
    ),
    CanonicalTaskDefinition(
        task_id="multimodal_integration",
        label="multimodal integration",
        aliases=["multiome integration", "multimodal", "rna atac integration", "多组学整合", "多模态整合"],
        stage_order=13,
        preceding_task_ids=["normalization"],
        expected_input_types=["multiple_modalities"],
        expected_output_types=["joint_representation"],
    ),
    CanonicalTaskDefinition(
        task_id="spatial_mapping",
        label="spatial mapping and deconvolution",
        aliases=["spatial mapping", "spatial deconvolution", "空间映射", "空间解卷积"],
        stage_order=14,
        preceding_task_ids=["cell_type_annotation"],
        expected_input_types=["spatial_expression", "single_cell_reference"],
        expected_output_types=["spatial_cell_abundance"],
    ),
    CanonicalTaskDefinition(
        task_id="perturbation_analysis",
        label="perturbation analysis",
        aliases=["perturb-seq", "perturbation response", "treatment response", "扰动分析", "干预响应"],
        stage_order=15,
        preceding_task_ids=["normalization"],
        expected_input_types=["perturbation_expression", "perturbation_labels"],
        expected_output_types=["perturbation_effects"],
    ),
)

TASK_BY_ID: Dict[str, CanonicalTaskDefinition] = {
    item.task_id: item for item in CANONICAL_TASKS
}

CATEGORY_TO_TASK_ID = {
    "QualityControl": "quality_control",
    "UMIs": "quality_control",
    "RareCells": "quality_control",
    "Normalisation": "normalization",
    "GeneFiltering": "normalization",
    "VariableGenes": "normalization",
    "Integration": "batch_integration",
    "Clustering": "clustering",
    "Classification": "cell_type_annotation",
    "MarkerGenes": "differential_expression",
    "DifferentialExpression": "differential_expression",
    "Ordering": "trajectory_inference",
    "GeneNetworks": "gene_regulatory_network",
    "Perturbations": "perturbation_analysis",
}

TOOL_TASK_IDS = {
    "scrublet": ("doublet_detection",),
    "scdblfinder": ("doublet_detection",),
    "doubletfinder": ("doublet_detection",),
    "harmony": ("batch_integration",),
    "scanorama": ("batch_integration",),
    "seurat": ("normalization", "batch_integration", "clustering", "multimodal_integration"),
    "scanpy": ("quality_control", "normalization", "clustering", "differential_expression"),
    "scvitools": ("batch_integration", "multimodal_integration"),
    "celltypist": ("cell_type_annotation",),
    "singler": ("cell_type_annotation",),
    "cell2location": ("spatial_mapping",),
    "scvelo": ("rna_velocity",),
    "cellrank": ("trajectory_inference", "rna_velocity"),
    "mofa2": ("multimodal_integration",),
    "moscot": ("trajectory_inference", "spatial_mapping"),
    "tradeseq": ("differential_expression", "trajectory_inference"),
}


def canonical_task(task_id: str) -> CanonicalTaskDefinition:
    return TASK_BY_ID[task_id]


def canonical_task_for_text(value: str) -> Optional[CanonicalTaskDefinition]:
    normalized = _normalize(value)
    if not normalized:
        return None
    direct = normalized.replace(" ", "_")
    if direct in TASK_BY_ID:
        return TASK_BY_ID[direct]
    matches = []
    for item in CANONICAL_TASKS:
        candidates = (item.label, item.task_id.replace("_", " "), *item.aliases)
        for alias in candidates:
            alias_text = _normalize(alias)
            if alias_text and _contains_phrase(normalized, alias_text):
                matches.append((len(alias_text), -item.stage_order, item))
                break
    return max(matches, default=(0, 0, None))[2]


def canonical_task_for_category(category: str) -> Optional[CanonicalTaskDefinition]:
    task_id = CATEGORY_TO_TASK_ID.get(str(category or "").strip())
    return TASK_BY_ID.get(task_id) if task_id else None


def canonical_task_ids_for_tool(tool_name: str) -> Tuple[str, ...]:
    return TOOL_TASK_IDS.get(_normalize_tool(tool_name), ())


def is_canonical_task_id(value: str) -> bool:
    return str(value or "").strip() in TASK_BY_ID


def is_junk_task_label(value: str) -> bool:
    text = str(value or "").strip()
    if not text:
        return True
    if canonical_task_for_text(text):
        return False
    normalized = _normalize(text)
    if re.fullmatch(r"[a-f0-9]{8,}", normalized.replace(" ", "")):
        return True
    if re.search(r"(?:^|[_-])[a-f0-9]{8,}(?:$|[_-])", text.casefold()):
        return True
    if re.search(r"\b(?:utr|isoform|transcript)[_-]?\d+[_-][a-f0-9]{6,}\b", text.casefold()):
        return True
    return False


def task_workflow_edges() -> Iterable[tuple[str, str, str]]:
    for item in CANONICAL_TASKS:
        for preceding in item.preceding_task_ids:
            if preceding in TASK_BY_ID:
                yield preceding, item.task_id, "PRECEDES"
                yield item.task_id, preceding, "REQUIRES_OUTPUT_OF"


def _normalize(value: str) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    text = re.sub(r"[_/]+", " ", text)
    text = re.sub(r"[^a-z0-9\u4e00-\u9fff+.-]+", " ", text)
    return " ".join(text.split())


def _normalize_tool(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())


def _contains_phrase(text: str, phrase: str) -> bool:
    if any("\u4e00" <= character <= "\u9fff" for character in phrase):
        return phrase in text
    return bool(re.search(rf"(?<![a-z0-9]){re.escape(phrase)}(?![a-z0-9])", text))
