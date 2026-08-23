from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from typing import List, Sequence, Tuple

from core.canonical_task_ontology import (
    TASK_BY_ID as CANONICAL_TASK_BY_ID,
    canonical_task_for_category,
    canonical_task_for_text,
)


@dataclass(frozen=True)
class OntologyTerm:
    canonical_id: str
    label: str
    original_value: str
    matched_rule: str


TASK_RULES: Sequence[Tuple[str, str, Sequence[str]]] = (
    ("doublet_detection", "doublet detection", (r"doublet", r"multiplet", r"双联体")),
    (
        "batch_correction",
        "batch integration",
        (
            r"batch.*correction",
            r"batch effect",
            r"batch[_ -]?integrat",
            r"integrat(?:e|ing|ion).*batch",
            r"\bharmony\b",
            r"\bscanorama\b",
            r"批次.*(?:校正|整合|集成)",
        ),
    ),
    ("cell_type_annotation", "cell type annotation", (r"cell[- ]?type", r"cell annotation", r"cell classification", r"cell type prediction", r"细胞.*注释", r"细胞.*分类")),
    ("data_integration", "data integration", (r"data integration", r"multi[- ]?omics integration", r"multimodal integration", r"数据整合", r"数据集成")),
    ("dimensionality_reduction", "dimensionality reduction", (r"dimensionality", r"dimension reduction", r"manifold learning", r"降维")),
    ("differential_expression", "differential expression", (r"differential expression", r"差异表达")),
    ("trajectory_inference", "trajectory inference", (r"trajectory", r"pseudotime", r"lineage inference", r"cell fate", r"轨迹", r"拟时序")),
    ("rna_velocity", "RNA velocity", (r"rna velocity", r"velocity", r"rna.*速率")),
    ("clustering", "clustering", (r"clustering", r"cluster analysis", r"聚类")),
    ("quality_control", "quality control", (r"quality control", r"data quality", r"质量控制")),
    ("preprocessing", "preprocessing", (r"preprocessing", r"data processing", r"数据预处理")),
    ("normalization", "normalization", (r"normalization", r"normalisation", r"归一化", r"标准化")),
    ("visualization", "visualization", (r"visuali[sz]ation", r"interactive exploration", r"可视化")),
    ("feature_selection", "feature selection", (r"feature selection", r"gene selection", r"variable gene", r"特征选择")),
    ("feature_extraction", "feature extraction", (r"feature extraction", r"feature learning", r"特征提取")),
    ("marker_gene_identification", "marker gene identification", (r"marker gene", r"marker identification", r"标记基因")),
    ("gene_regulatory_network", "gene regulatory network inference", (r"gene regulatory", r"regulatory network", r"\bgrn\b")),
    ("cell_cell_communication", "cell-cell communication", (r"cell[- ]cell communication", r"cell[- ]cell interaction", r"intercellular communication", r"细胞.*通讯")),
    ("imputation", "imputation", (r"imputation", r"dropout correction", r"插补")),
    ("denoising", "denoising", (r"denois", r"noise reduction", r"去噪")),
    ("spatial_mapping", "spatial mapping", (r"spatial mapping", r"spatial deconvolution", r"空间映射")),
    ("spatial_analysis", "spatial analysis", (r"spatial analysis", r"spatial transcript", r"空间.*分析")),
    ("deconvolution", "deconvolution", (r"deconvolution", r"解卷积")),
    ("pathway_enrichment", "pathway and enrichment analysis", (r"pathway", r"enrichment", r"gene set")),
    ("simulation", "data simulation", (r"simulation", r"data generation", r"synthetic data", r"模拟")),
    ("demultiplexing", "demultiplexing", (r"demultiplex", r"hashing", r"拆分")),
    ("alternative_splicing", "alternative splicing", (r"alternative splicing", r"isoform", r"transcript usage")),
    ("alternative_polyadenylation", "alternative polyadenylation", (r"polyadenylation", r"\bapa\b")),
    ("variant_calling", "variant calling", (r"variant calling", r"mutation detection")),
    ("network_analysis", "network analysis", (r"network analysis", r"network construction", r"co-expression")),
    ("benchmarking", "benchmarking", (r"benchmark", r"comparison")),
)

TASK_PARENT = {
    "batch_correction": "data_integration",
    "normalization": "preprocessing",
    "quality_control": "preprocessing",
    "feature_selection": "preprocessing",
    "marker_gene_identification": "differential_expression",
    "rna_velocity": "trajectory_inference",
    "spatial_mapping": "spatial_analysis",
    "denoising": "preprocessing",
    "imputation": "preprocessing",
}


CATALOG_CATEGORY_TASKS = {
    "Alignment": "sequence alignment",
    "AlleleSpecific": "allele-specific analysis",
    "AlternativeSplicing": "alternative splicing",
    "Assembly": "transcriptome assembly",
    "CellCycle": "cell cycle analysis",
    "Classification": "cell type annotation",
    "Clustering": "clustering",
    "DifferentialExpression": "differential expression",
    "DimensionalityReduction": "dimensionality reduction",
    "GeneFiltering": "feature selection",
    "GeneNetworks": "gene regulatory network inference",
    "GeneSets": "pathway and enrichment analysis",
    "Haplotypes": "haplotype analysis",
    "Immune": "immune analysis",
    "Imputation": "imputation",
    "Integration": "data integration",
    "Interactive": "interactive exploration",
    "MarkerGenes": "marker gene identification",
    "Modality": "modality analysis",
    "Normalisation": "normalization",
    "Ordering": "trajectory inference",
    "Perturbations": "perturbation analysis",
    "QualityControl": "quality control",
    "Quantification": "expression quantification",
    "RareCells": "rare cell detection",
    "Simulation": "data simulation",
    "StemCells": "stem cell analysis",
    "Transformation": "data transformation",
    "UMIs": "UMI processing",
    "VariableGenes": "feature selection",
    "Variants": "variant calling",
    "Visualisation": "visualization",
}

MODALITY_RULES: Sequence[Tuple[str, str, Sequence[str]]] = (
    ("scrna_seq", "scRNA-seq", (r"single[- ]cell rna", r"scrna", r"snrna")),
    ("scatac_seq", "scATAC-seq", (r"scatac", r"single[- ]cell atac")),
    ("spatial_transcriptomics", "spatial transcriptomics", (r"spatial transcript",)),
    ("cite_seq", "CITE-seq", (r"cite[- ]?seq", r"protein expression")),
    ("multiome", "single-cell multiome", (r"multiome", r"rna\+atac", r"multi[- ]?omics", r"multimodal")),
    ("bulk_rna_seq", "bulk RNA-seq", (r"bulk rna",)),
    ("rna_seq", "RNA-seq", (r"^rna[- ]?seq$",)),
    ("scdna_seq", "scDNA-seq", (r"scdna", r"single[- ]cell dna")),
    ("vdj_seq", "VDJ-seq", (r"vdj", r"tcr[- ]?seq", r"bcr[- ]?seq", r"airr")),
    ("cytometry", "cytometry", (r"cytof", r"flow cytometry", r"cytometry")),
    ("proteomics", "proteomics", (r"proteomic",)),
    ("metabolomics", "metabolomics", (r"metabolomic",)),
    ("methylation", "DNA methylation", (r"methylation",)),
    ("genomics", "genomics", (r"wgs", r"wes", r"dna[- ]?seq", r"genomic")),
    ("imaging", "imaging", (r"imaging", r"image")),
)

ALGORITHM_FAMILY_RULES: Sequence[Tuple[str, str, Sequence[str]]] = (
    ("graph_neural_network", "graph neural network", (r"graph neural", r"\bgnn\b", r"图神经网络")),
    ("variational_autoencoder", "variational autoencoder", (r"variational autoencoder", r"\bvae\b", r"变分自编码")),
    ("autoencoder", "autoencoder", (r"autoencoder", r"自编码器")),
    ("neural_network", "neural network", (r"neural network", r"deep learning", r"\bmlp\b", r"神经网络", r"深度学习")),
    ("optimal_transport", "optimal transport", (r"optimal transport", r"最优传输")),
    ("matrix_factorization", "matrix factorization", (r"matrix factori", r"\bnmf\b", r"non-negative matrix", r"矩阵分解")),
    ("bayesian_model", "Bayesian model", (r"bayesian", r"贝叶斯")),
    ("probabilistic_model", "probabilistic model", (r"probabilistic", r"概率模型")),
    ("graph_algorithm", "graph algorithm", (r"graph-based", r"graph algorithm", r"图算法", r"图结构")),
    ("nearest_neighbors", "nearest-neighbor method", (r"nearest neighbor", r"\bknn\b", r"近邻")),
    ("random_forest", "random forest", (r"random forest", r"随机森林")),
    ("support_vector_machine", "support vector machine", (r"support vector", r"\bsvm\b", r"支持向量")),
    ("regression", "regression model", (r"regression", r"回归")),
    ("clustering_algorithm", "clustering algorithm", (r"clustering", r"community detection", r"聚类")),
    ("markov_model", "Markov model", (r"markov", r"马尔可夫")),
    ("topic_model", "topic model", (r"topic model", r"主题模型")),
    ("dynamical_system", "dynamical system", (r"dynamical system", r"ordinary differential", r"动力系统")),
    ("ensemble_method", "ensemble method", (r"ensemble", r"集成学习")),
)


def normalize_task(value: str) -> OntologyTerm:
    canonical = canonical_task_for_text(value)
    if canonical is not None:
        return OntologyTerm(
            canonical.task_id,
            canonical.label,
            str(value or "").strip(),
            f"canonical_task_v2:{canonical.task_id}",
        )
    return _normalize_with_rules(value, TASK_RULES, prefix="task")


def catalog_category_task(value: str) -> OntologyTerm | None:
    task = canonical_task_for_category(value)
    if task is None:
        return None
    return OntologyTerm(
        task.task_id,
        task.label,
        str(value or "").strip(),
        f"canonical_catalog_category:{value.strip()}",
    )


def normalize_modality(value: str) -> OntologyTerm:
    return _normalize_with_rules(value, MODALITY_RULES, prefix="modality")


def normalize_language_values(value: str) -> List[OntologyTerm]:
    parts = _split_platform_values(value)
    result: List[OntologyTerm] = []
    seen = set()
    aliases = {
        "python": ("python", "Python"), "r": ("r", "R"), "c++": ("cpp", "C++"),
        "cpp": ("cpp", "C++"), "c": ("c", "C"), "matlab": ("matlab", "MATLAB"),
        "javascript": ("javascript", "JavaScript"), "typescript": ("typescript", "TypeScript"),
        "shell": ("shell", "Shell"), "bash": ("shell", "Shell"), "julia": ("julia", "Julia"),
        "java": ("java", "Java"), "rust": ("rust", "Rust"), "perl": ("perl", "Perl"),
        "stan": ("stan", "Stan"), "docker": ("docker", "Docker"),
        "snakemake": ("snakemake", "Snakemake"), "nextflow": ("nextflow", "Nextflow"),
        "groovy": ("groovy", "Groovy"),
        "pythong": ("python", "Python"), "cython": ("cython", "Cython"),
        "csharp": ("csharp", "C#"), "kotlin": ("kotlin", "Kotlin"),
        "glsl": ("glsl", "GLSL"), "scala": ("scala", "Scala"),
        "f#": ("fsharp", "F#"), "go": ("go", "Go"),
        "haskell": ("haskell", "Haskell"), "css": ("css", "CSS"),
        "fortran": ("fortran", "Fortran"), "awk": ("awk", "Awk"),
        "mathematica": ("mathematica", "Mathematica"),
    }
    for part in parts:
        key = _normalized_text(part)
        canonical_id, label = aliases.get(key, (_slug(key), part.strip()))
        if canonical_id not in seen:
            seen.add(canonical_id)
            result.append(OntologyTerm(canonical_id, label, part.strip(), "language_alias"))
    return result


def normalize_platform_values(value: str) -> List[Tuple[str, OntologyTerm]]:
    runtime_aliases = {
        "docker": ("docker", "Docker"),
        "singularity": ("singularity", "Singularity"),
        "virtualbox": ("virtualbox", "VirtualBox"),
        "aws": ("aws", "AWS"),
        "dotnet": ("dotnet", ".NET"),
    }
    result: List[Tuple[str, OntologyTerm]] = []
    for part in _split_platform_values(value):
        key = _normalized_text(part)
        if key in runtime_aliases:
            canonical_id, label = runtime_aliases[key]
            result.append(
                (
                    "RuntimePlatform",
                    OntologyTerm(canonical_id, label, part, "runtime_platform_alias"),
                )
            )
            continue
        language = normalize_language_values(part)[0]
        result.append(("Language", language))
    return result


def normalize_hardware(value: str) -> OntologyTerm:
    text = _normalized_text(value)
    if "gpu" in text:
        return OntologyTerm("gpu", "GPU", value, "hardware_gpu")
    if "cpu" in text:
        return OntologyTerm("cpu", "CPU", value, "hardware_cpu")
    if any(term in text for term in ("hpc", "cluster", "distributed")):
        return OntologyTerm("distributed_compute", "distributed compute", value, "hardware_distributed")
    if "cloud" in text:
        return OntologyTerm("cloud", "cloud compute", value, "hardware_cloud")
    return OntologyTerm(_slug(text), value.strip(), value, "hardware_fallback")


def normalize_resolution(value: str) -> OntologyTerm:
    text = _normalized_text(value)
    aliases = {
        "cellular": ("cell", "cell"), "molecular": ("molecule", "molecule"),
        "transcriptomic": ("transcriptome", "transcriptome"),
        "transcriptional": ("transcriptome", "transcriptome"),
        "gene-level": ("gene", "gene"), "transcript-level": ("transcript", "transcript"),
        "pathway-level": ("pathway", "pathway"), "systems level": ("system", "system"),
        "system-level": ("system", "system"), "population-level": ("population", "population"),
    }
    fallback_id = _slug(text)
    canonical_id, label = aliases.get(
        text,
        (fallback_id, value.strip() if fallback_id.startswith("term_") else fallback_id.replace("_", " ")),
    )
    return OntologyTerm(canonical_id, label, value, "resolution_alias")


def infer_algorithm_families(value: str, *, limit: int = 5) -> List[OntologyTerm]:
    text = _normalized_text(value)
    matches: List[OntologyTerm] = []
    seen = set()
    for canonical_id, label, patterns in ALGORITHM_FAMILY_RULES:
        if any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns):
            if canonical_id == "autoencoder" and "variational_autoencoder" in seen:
                continue
            if canonical_id == "neural_network" and "graph_neural_network" in seen:
                continue
            seen.add(canonical_id)
            matches.append(OntologyTerm(canonical_id, label, value, f"algorithm_keyword:{canonical_id}"))
            if len(matches) >= limit:
                break
    return matches


def task_parent(canonical_id: str) -> str | None:
    canonical = CANONICAL_TASK_BY_ID.get(canonical_id)
    if canonical is not None:
        return canonical.parent_task_id
    return TASK_PARENT.get(canonical_id)


def task_label(canonical_id: str) -> str:
    canonical = CANONICAL_TASK_BY_ID.get(canonical_id)
    if canonical is not None:
        return canonical.label
    for rule_id, label, _ in TASK_RULES:
        if rule_id == canonical_id:
            return label
    return canonical_id.replace("_", " ")


def _normalize_with_rules(value: str, rules, *, prefix: str) -> OntologyTerm:
    clean = " ".join(str(value or "").split())
    text = _normalized_text(clean)
    for canonical_id, label, patterns in rules:
        if any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns):
            return OntologyTerm(canonical_id, label, clean, f"{prefix}_rule:{canonical_id}")
    canonical_id = _slug(text)
    label = clean if canonical_id.startswith("term_") else canonical_id.replace("_", " ")
    return OntologyTerm(canonical_id, label or "unknown", clean, f"{prefix}_fallback")


def _normalized_text(value: str) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold().strip()
    return re.sub(r"\s+", " ", text)


def _split_platform_values(value: str) -> List[str]:
    protected = re.sub(r"c\+\+", "__CPP__", value or "", flags=re.IGNORECASE)
    return [
        part.replace("__CPP__", "C++").strip()
        for part in re.split(r"[/,;+|]", protected)
        if part.strip()
    ]


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", value.casefold()).strip("_")
    if any(ord(character) > 127 for character in value):
        digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:10]
        return f"{slug}_{digest}".strip("_")[:80]
    if slug:
        return slug[:80]
    return "term_" + hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]
