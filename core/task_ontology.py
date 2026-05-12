from __future__ import annotations

from typing import Iterable, List


COARSE_TASKS = {
    "QC",
    "Normalization",
    "Batch Correction",
    "Data Integration",
    "Clustering",
    "Cell Type Annotation",
    "Trajectory Inference",
    "Differential Expression",
    "DTU Analysis",
    "Isoform Quantification",
    "Multiome Integration",
    "Workflow Planning",
    "Workflow Compatibility",
}

FINE_TASKS = {
    "Doublet Detection",
    "Ambient RNA Removal",
    "RNA Velocity",
    "Spatial Deconvolution",
    "Trajectory Differential Expression",
    "Perturbation Differential Expression",
    "Foundation Model Representation",
    "Optimal Transport Trajectory",
}

TASK_VOCAB = COARSE_TASKS | FINE_TASKS | {"Unknown"}

TASK_FAMILY_BY_TASK = {
    "Doublet Detection": "QC",
    "Ambient RNA Removal": "QC",
    "RNA Velocity": "Trajectory Inference",
    "Spatial Deconvolution": "Cell Type Annotation",
    "Trajectory Differential Expression": "Differential Expression",
    "Perturbation Differential Expression": "Differential Expression",
    "Foundation Model Representation": "Data Integration",
    "Optimal Transport Trajectory": "Trajectory Inference",
    "Batch Correction": "Data Integration",
}

TASK_QUERY_EXPANSIONS = {
    "Spatial Deconvolution": ["Spatial Mapping", "Cell Type Annotation"],
    "Trajectory Differential Expression": ["Differential Expression", "Trajectory Inference"],
    "Perturbation Differential Expression": ["Differential Expression", "Perturbation Analysis", "Multi-condition Analysis"],
    "Foundation Model Representation": ["Representation Learning", "Interpretability", "Data Integration", "Multiome Integration"],
    "Optimal Transport Trajectory": ["Optimal Transport", "Trajectory Inference", "Spatial Mapping"],
    "Batch Correction": ["Data Integration"],
}

TASK_KEYWORD_RULES = [
    ("Doublet Detection", ("doublet", "doublets", "multiplet", "multiplets", "scrublet", "doubletfinder")),
    (
        "Ambient RNA Removal",
        ("ambient rna", "ambientrna", "soupx", "decontam", "decontamination", "contamination", "污染", "污染去除", "背景 rna", "背景rna", "环境 rna", "环境rna"),
    ),
    ("RNA Velocity", ("rna velocity", "velocity", "velocyto", "scvelo", "spliced", "unspliced", "剪接", "未剪接", "动态转录")),
    (
        "Spatial Deconvolution",
        ("spatial deconvolution", "cell2location", "deconvolution", "spatial mapping", "spot mapping", "cell abundance", "cell type composition", "细胞组成", "细胞类型组成", "空间和单细胞", "空间数据和单细胞"),
    ),
    (
        "Trajectory Differential Expression",
        ("trajectory differential expression", "lineage de", "pseudotime de", "tradeseq", "trajectory de", "lineage 变化", "沿着不同 lineage", "fdr", "变化的基因"),
    ),
    (
        "Perturbation Differential Expression",
        (
            "perturbation differential expression",
            "perturbation response",
            "perturb-seq",
            "perturbseq",
            "treatment vs control",
            "treated vs control",
            "before and after treatment",
            "pre-post treatment",
            "mimosca",
            "扰动差异",
            "扰动响应",
            "扰动实验",
            "处理前后",
            "干预前后",
            "给药前后",
            "处理组",
            "对照组",
        ),
    ),
    (
        "Foundation Model Representation",
        ("foundation model", "representation learning", "scgpt", "cellplm", "geneformer"),
    ),
    ("Optimal Transport Trajectory", ("optimal transport", "moscot", "wot", "transport trajectory")),
]

TOOL_TASK_HINTS = {
    "cellrank": ["Trajectory Inference"],
    "cellplm": ["Foundation Model Representation", "Data Integration"],
    "celltypist": ["Cell Type Annotation"],
    "doubletfinder": ["Doublet Detection", "QC"],
    "harmony": ["Data Integration"],
    "mofa": ["Multiome Integration", "Data Integration"],
    "mofa2": ["Multiome Integration", "Data Integration"],
    "mimosca": ["Perturbation Differential Expression", "Differential Expression"],
    "moscot": ["Optimal Transport Trajectory", "Trajectory Inference"],
    "nicheformer": ["Foundation Model Representation"],
    "scanpy": ["QC", "Normalization", "Data Integration", "Clustering", "Trajectory Inference", "Differential Expression"],
    "scgpt": ["Foundation Model Representation", "Data Integration"],
    "scib": ["Data Integration"],
    "scrublet": ["Doublet Detection", "QC"],
    "seurat": ["Data Integration", "QC", "Clustering", "Multiome Integration"],
    "seuratextend": ["Data Integration", "Cell Type Annotation"],
    "singler": ["Cell Type Annotation"],
    "soupx": ["Ambient RNA Removal", "QC"],
    "scvelo": ["RNA Velocity", "Trajectory Inference"],
    "tradeseq": ["Trajectory Differential Expression", "Differential Expression"],
    "velociraptor": ["RNA Velocity", "Trajectory Inference"],
    "wot": ["Optimal Transport Trajectory", "Trajectory Inference"],
    "cell2location": ["Spatial Deconvolution"],
    "scvi-tools": ["Data Integration", "Multiome Integration"],
}

TOOL_CANONICAL_NAMES = {
    "cellrank": "CellRank",
    "cellplm": "CellPLM",
    "celltypist": "CellTypist",
    "doubletfinder": "DoubletFinder",
    "harmony": "Harmony",
    "mofa": "MOFA",
    "mofa2": "MOFA2",
    "mimosca": "MIMOSCA",
    "moscot": "moscot",
    "nicheformer": "nicheformer",
    "scanpy": "Scanpy",
    "scgpt": "scGPT",
    "scib": "scIB",
    "scrublet": "Scrublet",
    "seurat": "Seurat",
    "seuratextend": "SeuratExtend",
    "singler": "SingleR",
    "soupx": "SoupX",
    "scvelo": "scVelo",
    "tradeseq": "tradeSeq",
    "velociraptor": "velociraptor",
    "wot": "wot",
    "cell2location": "cell2location",
    "scvi-tools": "scvi-tools",
}


def normalize_task_label(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return "Unknown"
    normalized = _alias_map().get(text.lower(), text)
    return normalized if normalized in TASK_VOCAB else text


def task_family(task: str) -> str:
    normalized = normalize_task_label(task)
    return TASK_FAMILY_BY_TASK.get(normalized, normalized)


def refine_task_label(task: str, query_text: str, output_goal: str = "") -> str:
    normalized = normalize_task_label(task)
    haystack = f"{query_text} {output_goal}".lower()
    transfer_context = any(
        term in haystack
        for term in (
            "借鉴",
            "迁移",
            "可迁移",
            "没有现成",
            "没有成熟",
            "no direct tool",
            "no mature tool",
            "method transfer",
        )
    )
    if transfer_context and any(
        term in haystack
        for term in ("质量问题", "异常识别", "rare artifact", "artifact detection")
    ):
        return "QC"
    for fine_task, keywords in TASK_KEYWORD_RULES:
        if not any(keyword in haystack for keyword in keywords):
            continue
        family = task_family(fine_task)
        if normalized in {"Unknown", family, fine_task} or normalized in COARSE_TASKS:
            return fine_task
    return normalized


def build_task_query_terms(task: str, family: str | None = None) -> List[str]:
    normalized = normalize_task_label(task)
    terms = [normalized]
    for expanded in TASK_QUERY_EXPANSIONS.get(normalized, []):
        if expanded not in terms:
            terms.append(expanded)
    derived_family = family or task_family(normalized)
    if derived_family and derived_family not in terms:
        terms.append(derived_family)
    return terms


def task_alignment_score(query_terms: Iterable[str], matched_tasks: Iterable[str]) -> float:
    matched = [normalize_task_label(item) for item in matched_tasks if item]
    if not matched:
        return 0.0
    normalized_terms = [normalize_task_label(item) for item in query_terms if item]
    if not normalized_terms:
        return 0.0
    best = 0.0
    for idx, term in enumerate(normalized_terms):
        if term in matched:
            best = max(best, 1.0 - idx * 0.4)
    if best > 0:
        return best
    return 0.25 if matched else 0.0


def tool_task_hints(tool_name: str) -> List[str]:
    hints = TOOL_TASK_HINTS.get((tool_name or "").lower(), [])
    return _dedupe_list(hints)


def iter_tool_task_hints() -> List[tuple[str, List[str]]]:
    return [
        (TOOL_CANONICAL_NAMES.get(key, key), _dedupe_list(hints))
        for key, hints in TOOL_TASK_HINTS.items()
    ]


def _alias_map() -> dict[str, str]:
    return {
        "batch correction": "Batch Correction",
        "cell type annotation": "Cell Type Annotation",
        "clustering": "Clustering",
        "data integration": "Data Integration",
        "differential expression": "Differential Expression",
        "doublet detection": "Doublet Detection",
        "doublet detection.": "Doublet Detection",
        "dtu analysis": "DTU Analysis",
        "foundation model representation": "Foundation Model Representation",
        "isoform quantification": "Isoform Quantification",
        "multiome integration": "Multiome Integration",
        "normalization": "Normalization",
        "optimal transport trajectory": "Optimal Transport Trajectory",
        "perturbation differential expression": "Perturbation Differential Expression",
        "perturbation response": "Perturbation Differential Expression",
        "perturbation analysis": "Perturbation Differential Expression",
        "qc": "QC",
        "rna velocity": "RNA Velocity",
        "spatial deconvolution": "Spatial Deconvolution",
        "trajectory differential expression": "Trajectory Differential Expression",
        "trajectory inference": "Trajectory Inference",
        "workflow compatibility": "Workflow Compatibility",
        "workflow planning": "Workflow Planning",
        "ambient rna removal": "Ambient RNA Removal",
        "ambient rna decontamination": "Ambient RNA Removal",
        "batch effect removal": "Batch Correction",
        "decontamination": "Ambient RNA Removal",
        "doublet": "Doublet Detection",
        "doublets": "Doublet Detection",
        "foundation model": "Foundation Model Representation",
        "optimal transport": "Optimal Transport Trajectory",
        "perturb-seq": "Perturbation Differential Expression",
        "perturbseq": "Perturbation Differential Expression",
        "representation learning": "Foundation Model Representation",
        "single-cell foundation model": "Foundation Model Representation",
    }


def _dedupe_list(items: Iterable[str]) -> List[str]:
    deduped: List[str] = []
    seen = set()
    for item in items:
        if item in seen:
            continue
        deduped.append(item)
        seen.add(item)
    return deduped
