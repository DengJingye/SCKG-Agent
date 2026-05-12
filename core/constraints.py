from typing import Any, Dict, List, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from core.task_ontology import (
    TASK_VOCAB,
    refine_task_label,
    task_family,
)


UNKNOWN = "Unknown"

CONSTRAINT_FIELDS = [
    "task",
    "modality",
    "platform",
    "data_object",
    "scale",
    "noise",
    "hardware",
    "species",
    "output_goal",
    "strictness",
]

MODALITY_VOCAB = {
    "scRNA-seq",
    "scATAC-seq",
    "Spatial Transcriptomics",
    "Spatial Metabolomics",
    "CITE-seq",
    "scRNA-seq+scATAC-seq",
    "long-read scRNA-seq",
    "Nanopore",
    UNKNOWN,
}

SCALE_VOCAB = {"small", "medium", "large", "very_large", UNKNOWN}
NOISE_VOCAB = {"low", "medium", "high", UNKNOWN}
STRICTNESS_VOCAB = {"strict", "balanced", "exploratory", UNKNOWN}

TaskName = Literal[
    "QC",
    "Normalization",
    "Batch Correction",
    "Data Integration",
    "Clustering",
    "Cell Type Annotation",
    "Trajectory Inference",
    "Differential Expression",
    "Doublet Detection",
    "Ambient RNA Removal",
    "RNA Velocity",
    "Spatial Deconvolution",
    "Trajectory Differential Expression",
    "Perturbation Differential Expression",
    "Foundation Model Representation",
    "Optimal Transport Trajectory",
    "DTU Analysis",
    "Isoform Quantification",
    "Multiome Integration",
    "Workflow Planning",
    "Workflow Compatibility",
    "Unknown",
]

ModalityName = Literal[
    "scRNA-seq",
    "scATAC-seq",
    "Spatial Transcriptomics",
    "Spatial Metabolomics",
    "CITE-seq",
    "scRNA-seq+scATAC-seq",
    "long-read scRNA-seq",
    "Nanopore",
    "Unknown",
]

ScaleLevel = Literal["small", "medium", "large", "very_large", "Unknown"]
NoiseLevel = Literal["low", "medium", "high", "Unknown"]
StrictnessLevel = Literal["strict", "balanced", "exploratory", "Unknown"]
ConstraintResolutionState = Literal["resolved", "partial_resolved", "needs_clarification"]
ConstraintSource = Literal["explicit", "inferred", "pending"]


def _as_string(value: Any, default: str = UNKNOWN) -> str:
    if value is None:
        return default
    if isinstance(value, str):
        stripped = value.strip()
        return stripped if stripped else default
    return str(value)


def _as_list(value: Any) -> List[str]:
    if value is None:
        return [UNKNOWN]
    if isinstance(value, list):
        cleaned = [_as_string(item) for item in value if _as_string(item) != UNKNOWN]
        return cleaned or [UNKNOWN]
    if isinstance(value, str):
        parts = [part.strip() for part in value.replace("，", ",").split(",")]
        cleaned = [part for part in parts if part]
        return cleaned or [UNKNOWN]
    return [_as_string(value)]


class ResearchConstraints(BaseModel):
    """Stable scientific constraint object extracted from a user query."""

    model_config = ConfigDict(extra="ignore")

    task: TaskName = UNKNOWN
    task_family: str = UNKNOWN
    modality: ModalityName = UNKNOWN
    platform: str = UNKNOWN
    data_object: str = UNKNOWN
    scale: ScaleLevel = UNKNOWN
    noise: NoiseLevel = UNKNOWN
    hardware: List[str] = Field(default_factory=lambda: [UNKNOWN])
    species: str = UNKNOWN
    output_goal: str = UNKNOWN
    strictness: StrictnessLevel = "balanced"
    valid_constraint_count: int = 0
    needs_human_clarification: bool = True
    clarification_state: ConstraintResolutionState = "needs_clarification"
    constraint_sources: Dict[str, ConstraintSource] = Field(default_factory=dict)
    known_constraints: List[str] = Field(default_factory=list)
    inferred_constraints: List[str] = Field(default_factory=list)
    pending_constraints: List[str] = Field(default_factory=list)
    clarification_questions: List[str] = Field(default_factory=list)
    constraint_warnings: List[str] = Field(default_factory=list)

    @field_validator("hardware", mode="before")
    @classmethod
    def normalize_hardware(cls, value: Any) -> List[str]:
        return _as_list(value)

    def to_state_dict(self) -> Dict[str, Any]:
        return self.model_dump()


def _choose_vocab(value: Any, vocab: set[str], default: str = UNKNOWN) -> str:
    text = _as_string(value, default)
    if text in vocab:
        return text
    lower_map = {item.lower(): item for item in vocab}
    return lower_map.get(text.lower(), default)


def _fallback_from_query(query: str) -> Dict[str, Any]:
    query_lower = query.lower()
    fallback = {
        "task": UNKNOWN,
        "modality": UNKNOWN,
        "platform": UNKNOWN,
        "data_object": UNKNOWN,
        "scale": UNKNOWN,
        "noise": UNKNOWN,
        "hardware": [UNKNOWN],
        "species": UNKNOWN,
        "output_goal": UNKNOWN,
        "strictness": "balanced",
    }

    transfer_context = any(term in query_lower for term in [
        "借鉴",
        "迁移",
        "可迁移",
        "没有现成",
        "没有成熟",
        "no direct tool",
        "no mature tool",
        "method transfer",
    ])

    task_rules = [
        ("Foundation Model Representation", ["niche-aware representation", "niche-aware", "context-aware representation", "context aware representation"]),
        ("QC", ["rare artifact", "artifact detection", "质量问题", "异常识别"]),
        ("Doublet Detection", ["doublet", "doublets", "multiplet", "multiplets", "双细胞", "复细胞"]),
        ("Ambient RNA Removal", ["ambient rna", "ambientrna", "decontam", "decontamination", "contamination", "环境rna", "环境 rna", "背景rna", "背景 rna", "污染", "污染去除"]),
        ("RNA Velocity", ["rna velocity", "velocity", "velocyto", "spliced", "unspliced", "速度", "rna速率", "rna 速率", "动态转录"]),
        ("Spatial Deconvolution", ["spatial deconvolution", "deconvolution", "spot", "spots", "visium", "cell abundance", "cell type composition", "细胞组成", "细胞类型组成", "空间反卷积", "空间映射", "空间和单细胞", "空间数据和单细胞", "空间转录组和单细胞参考", "空间和时间"]),
        ("Trajectory Differential Expression", ["trajectory differential expression", "trajectory de", "lineage de", "lineage 变化", "pseudotime de", "拟时序差异", "轨迹差异", "变化的基因", "fdr"]),
        ("Perturbation Differential Expression", ["perturbation differential expression", "perturbation response", "perturb-seq", "perturbseq", "treatment vs control", "treated vs control", "before and after treatment", "pre-post treatment", "mimosca", "扰动差异", "扰动响应", "扰动实验", "处理前后", "干预前后", "给药前后", "处理组", "对照组"]),
        ("Foundation Model Representation", ["foundation model", "representation learning", "single-cell foundation", "基础模型", "表示学习"]),
        ("Optimal Transport Trajectory", ["optimal transport", "waddington", "transport trajectory", "最优传输"]),
        ("Multiome Integration", ["multiome", "multi-omics", "multiomics", "rna and atac", "rna 和 atac", "rna和atac", "joint representation", "joint embedding", "joint latent", "联合表示", "联合嵌入", "多组学整合", "多组学", "多模态整合", "两个模态"]),
        ("DTU Analysis", ["dtu", "transcript usage", "转录本使用"]),
        ("Isoform Quantification", ["isoform", "异构体", "转录本定量"]),
        ("Trajectory Inference", ["trajectory", "pseudotime", "轨迹", "拟时序"]),
        ("Cell Type Annotation", ["annotation", "cell type", "注释", "细胞类型"]),
        ("Data Integration", ["integration", "batch", "整合", "批次", "batch correction"]),
        ("Clustering", ["clustering", "cluster", "聚类"]),
        ("Differential Expression", ["deg", "differential expression", "差异表达", "处理前后", "扰动实验", "扰动"]),
        ("QC", ["qc", "quality control", "质控"]),
        ("Normalization", ["normalization", "normalize", "归一化"]),
    ]
    for task, keywords in task_rules:
        if any(keyword in query_lower for keyword in keywords):
            fallback["task"] = task
            break

    if transfer_context and any(term in query_lower for term in ["质量问题", "异常识别", "rare artifact", "artifact detection"]):
        fallback["task"] = "QC"

    output_goal_by_task = {
        "QC": "filtered high-quality cells",
        "Normalization": "normalized expression matrix",
        "Batch Correction": "batch-corrected representation",
        "Data Integration": "integrated representation",
        "Clustering": "cell clusters",
        "Cell Type Annotation": "cell type labels",
        "Trajectory Inference": "pseudotime or trajectory",
        "Differential Expression": "differentially expressed genes",
        "Doublet Detection": "doublet calls or multiplet risk scores",
        "Ambient RNA Removal": "decontaminated expression matrix",
        "RNA Velocity": "RNA velocity vectors or dynamic cell-state transitions",
        "Spatial Deconvolution": "cell type abundance estimates in spatial spots",
        "Trajectory Differential Expression": "genes varying along pseudotime or lineages",
        "Perturbation Differential Expression": "perturbation-associated expression effects with evidence caveats",
        "Foundation Model Representation": "foundation-model embeddings or representation comparison",
        "Optimal Transport Trajectory": "time-resolved transport map or developmental trajectory",
        "Multiome Integration": "joint embedding and cross-modality clusters",
        "DTU Analysis": "differential transcript usage",
        "Isoform Quantification": "isoform abundance estimates",
    }
    if fallback["task"] in output_goal_by_task:
        fallback["output_goal"] = output_goal_by_task[fallback["task"]]

    modality_rules = [
        ("long-read scRNA-seq", ["nanopore", "pacbio", "long-read", "长读长"]),
        ("scRNA-seq+scATAC-seq", ["multiome", "multi-omics", "multiomics", "rna and atac", "rna 和 atac", "rna和atac", "scrna-seq+scatac-seq", "scrna+scatac", "rna/atac", "多组学"]),
        ("scATAC-seq", ["scatac", "atac"]),
        ("Spatial Metabolomics", ["空间代谢", "spatial metabolomics"]),
        ("Spatial Transcriptomics", ["空间转录", "spatial transcriptomics", "spots", "空间数据"]),
        ("Spatial Transcriptomics", ["visium", "spot"]),
        ("CITE-seq", ["cite-seq", "adt"]),
        ("scRNA-seq", ["scrna", "single-cell rna", "单细胞 rna", "单细胞rna"]),
    ]
    for modality, keywords in modality_rules:
        if any(keyword in query_lower for keyword in keywords):
            fallback["modality"] = modality
            break

    if fallback["modality"] == UNKNOWN and fallback["task"] in {
        "Spatial Deconvolution",
    }:
        fallback["modality"] = "Spatial Transcriptomics"

    if "空间" in query or "spatial" in query_lower:
        if fallback["task"] in {"Ambient RNA Removal", "Foundation Model Representation"}:
            fallback["modality"] = "Spatial Transcriptomics"

    if fallback["modality"] == UNKNOWN and fallback["task"] == "QC":
        fallback["modality"] = "scRNA-seq"

    if fallback["modality"] == UNKNOWN and fallback["task"] in {
        "Doublet Detection",
        "Ambient RNA Removal",
        "RNA Velocity",
        "Trajectory Differential Expression",
        "Perturbation Differential Expression",
        "Foundation Model Representation",
        "Optimal Transport Trajectory",
        "Trajectory Inference",
        "Differential Expression",
        "Cell Type Annotation",
        "Multiome Integration",
    }:
        fallback["modality"] = "scRNA-seq"

    if fallback["task"] == "Multiome Integration":
        fallback["modality"] = "scRNA-seq+scATAC-seq"

    if "nanopore" in query_lower:
        fallback["platform"] = "Nanopore"
    elif "pacbio" in query_lower:
        fallback["platform"] = "PacBio"
    elif "10x" in query_lower:
        fallback["platform"] = "10x Genomics"
    elif "multiome" in query_lower or fallback["task"] == "Multiome Integration":
        fallback["platform"] = "10x Multiome" if "10x" in query_lower else fallback["platform"]
    elif "smart-seq2" in query_lower or "smartseq2" in query_lower:
        fallback["platform"] = "Smart-seq2"

    if "h5ad" in query_lower or "anndata" in query_lower:
        fallback["data_object"] = "AnnData/h5ad"
    elif "seurat" in query_lower:
        fallback["data_object"] = "SeuratObject"
    elif "fastq" in query_lower or "bam" in query_lower:
        fallback["data_object"] = "FASTQ/BAM"

    no_gpu_terms = ["没有 gpu", "无 gpu", "no gpu", "without gpu"]
    if any(term in query_lower for term in no_gpu_terms) and "cpu" in query_lower:
        fallback["hardware"] = ["CPU"]
    elif "gpu" in query_lower:
        fallback["hardware"] = ["GPU"]
    elif "cpu" in query_lower:
        fallback["hardware"] = ["CPU"]

    if "human" in query_lower or "pbmc" in query_lower or "人" in query:
        fallback["species"] = "Human"
    if "mouse" in query_lower or "小鼠" in query:
        fallback["species"] = "Mouse" if fallback["species"] == UNKNOWN else "Human+Mouse"

    if any(term in query_lower for term in ["million", "百万", "100万"]):
        fallback["scale"] = "very_large"
    elif any(term in query_lower for term in ["万", "large", "大规模"]):
        fallback["scale"] = "large"
    elif "pbmc" in query_lower:
        fallback["scale"] = "medium"

    if any(word in query for word in ["高噪声", "低质量", "掉零", "噪声很重"]):
        fallback["noise"] = "high"
    if any(word in query_lower for word in [
        "exploratory",
        "method transfer",
        "transfer",
        "no direct tool",
        "no mature tool",
        "no existing tool",
        "借鉴",
        "想探索",
        "迁移",
        "可迁移",
        "创新",
        "找不到",
        "没有现成",
        "没有成熟",
    ]):
        fallback["strictness"] = "exploratory"
    elif any(word in query_lower for word in ["复现", "可复现", "不能乱猜", "不要猜", "硬件限制"]):
        fallback["strictness"] = "strict"

    return fallback


def _has_value(value: Any) -> bool:
    return value not in (None, "", UNKNOWN, [UNKNOWN], [])


def _clarification_question(field: str) -> str:
    questions = {
        "task": "请明确主要分析任务，例如 integration、clustering、annotation、trajectory 或 DTU。",
        "modality": "请明确数据模态，例如 scRNA-seq、scATAC-seq、spatial、CITE-seq 或 long-read scRNA-seq。",
        "platform": "请明确实验或测序平台，例如 10x、Smart-seq2、Nanopore 或 PacBio。",
        "data_object": "请明确输入数据对象或文件格式，例如 h5ad、SeuratObject、FASTQ/BAM 或 fragments。",
        "scale": "请提供大致数据规模，例如细胞数、spot 数或样本数。",
        "noise": "请说明数据质量或噪声水平，例如 dropout、批次效应或低质量细胞是否严重。",
        "hardware": "请说明可用硬件，例如 CPU、GPU 或高内存服务器。",
        "species": "请说明物种，例如 human、mouse 或 cross-species。",
        "output_goal": "请说明最终希望得到的分析产物，例如 clusters、cell labels、pseudotime 或 isoform-level DTU。",
        "strictness": "请说明推荐风格：严格可复现、平衡推荐，还是探索性迁移。",
    }
    return questions.get(field, f"请补充约束字段：{field}。")


def _resolution_state(valid_count: int, pending: List[str]) -> ConstraintResolutionState:
    if valid_count >= 7 and len(pending) <= 3:
        return "resolved"
    if valid_count >= 4:
        return "partial_resolved"
    return "needs_clarification"


def parse_research_constraints(
    raw_constraints: Dict[str, Any],
    user_query: str = "",
) -> ResearchConstraints:
    """Normalize LLM output into a typed research-constraint object."""
    raw_constraints = raw_constraints or {}
    fallback = _fallback_from_query(user_query)
    normalized: Dict[str, Any] = {}
    warnings: List[str] = []
    sources: Dict[str, ConstraintSource] = {}

    for field in CONSTRAINT_FIELDS:
        value = raw_constraints.get(field, fallback[field])
        if field == "hardware":
            normalized[field] = _as_list(value)
        elif field == "task":
            selected = _choose_vocab(value, TASK_VOCAB)
            normalized[field] = selected if selected != UNKNOWN else fallback[field]
        elif field == "modality":
            selected = _choose_vocab(value, MODALITY_VOCAB)
            normalized[field] = selected if selected != UNKNOWN else fallback[field]
        elif field == "scale":
            selected = _choose_vocab(value, SCALE_VOCAB)
            normalized[field] = selected if selected != UNKNOWN else fallback[field]
        elif field == "noise":
            selected = _choose_vocab(value, NOISE_VOCAB)
            normalized[field] = selected if selected != UNKNOWN else fallback[field]
        elif field == "strictness":
            selected = _choose_vocab(value, STRICTNESS_VOCAB, "balanced")
            normalized[field] = selected if selected != UNKNOWN else fallback[field]
        else:
            normalized[field] = _as_string(value)

    normalized["task"] = refine_task_label(
        normalized.get("task", UNKNOWN),
        user_query,
        normalized.get("output_goal", ""),
    )
    normalized["task_family"] = task_family(normalized["task"])

    for field in CONSTRAINT_FIELDS:
        value = normalized[field]
        if value == UNKNOWN or value == [UNKNOWN]:
            warnings.append(f"Missing or unknown constraint: {field}")
            sources[field] = "pending"
        elif _has_value(raw_constraints.get(field)):
            sources[field] = "explicit"
        elif _has_value(fallback.get(field)):
            sources[field] = "inferred"
        else:
            sources[field] = "pending"

    normalized["valid_constraint_count"] = sum(
        1
        for field in CONSTRAINT_FIELDS
        if normalized[field] != UNKNOWN and normalized[field] != [UNKNOWN]
    )
    known_constraints = [
        field for field, source in sources.items() if source == "explicit"
    ]
    inferred_constraints = [
        field for field, source in sources.items() if source == "inferred"
    ]
    pending_constraints = [
        field for field, source in sources.items() if source == "pending"
    ]
    state = _resolution_state(normalized["valid_constraint_count"], pending_constraints)
    normalized["needs_human_clarification"] = state == "needs_clarification"
    normalized["clarification_state"] = state
    normalized["constraint_sources"] = sources
    normalized["known_constraints"] = known_constraints
    normalized["inferred_constraints"] = inferred_constraints
    normalized["pending_constraints"] = pending_constraints
    normalized["clarification_questions"] = [
        _clarification_question(field) for field in pending_constraints
    ]
    normalized["constraint_warnings"] = warnings
    return ResearchConstraints.model_validate(normalized)


def normalize_constraints(raw_constraints: Dict[str, Any], user_query: str = "") -> Dict[str, Any]:
    """Normalize LLM output into a stable research-constraint state dict."""
    return parse_research_constraints(raw_constraints, user_query=user_query).to_state_dict()
