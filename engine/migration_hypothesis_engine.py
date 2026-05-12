from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from core.models import EvidenceBundle, MigrationPath, derived_evidence
from core.settings import get_settings


PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROFILE_PATH = PROJECT_ROOT / "data" / "evidence_candidates" / "tool_algorithm_profiles.tsv"
REVIEW_PACKET_PATH = PROJECT_ROOT / "data" / "evidence_candidates" / "migration_hypothesis_review_packet.tsv"


@dataclass(frozen=True)
class AlgorithmProfile:
    tool_name: str
    algorithm_family: str
    model_assumption: str
    distance_metric: str
    optimization_objective: str
    input_object: str
    output_object: str
    supported_task: str
    supported_modality: str
    transferable_mechanism: str
    known_limitations: str
    review_status: str
    reviewer_notes: str


@dataclass(frozen=True)
class MigrationReview:
    query_id: str
    target_task: str
    target_modality: str
    source_tool: str
    source_task: str
    transferable_mechanism: str
    vector_similarity: str
    graph_jaccard: str
    io_compatibility: str
    compatibility_gaps: str
    risk_level: str
    candidate_decision: str
    reviewer_decision: str
    reviewer_notes: str


TOOL_MECHANISM_TERMS: dict[str, tuple[str, ...]] = {
    "tradeSeq": (
        "smooth",
        "spline",
        "gam",
        "dose",
        "response curve",
        "pseudotime",
        "lineage",
        "lineage probability",
        "ordered",
        "continuous",
        "trajectory",
        "branch",
        "response shape",
        "平滑",
        "样条",
        "剂量",
        "浓度",
        "响应曲线",
        "连续",
        "伪时间",
        "分支",
    ),
    "MIMOSCA": (
        "perturbation",
        "treatment",
        "control",
        "ko",
        "crispr",
        "linear",
        "additive",
        "coefficient",
        "处理",
        "对照",
        "扰动",
        "线性",
        "加性",
        "系数",
    ),
    "SoupX": (
        "ambient",
        "contamination",
        "background",
        "off-tissue",
        "empty",
        "subtraction",
        "背景",
        "污染",
        "组织外",
        "空白",
        "扣除",
    ),
    "Scrublet": (
        "simulated",
        "synthetic",
        "positive",
        "artifact",
        "anomaly",
        "neighbor",
        "doublet",
        "index hopping",
        "模拟",
        "人工阳性",
        "伪影",
        "异常",
        "邻域",
        "双细胞",
    ),
    "DoubletFinder": (
        "simulated",
        "synthetic",
        "positive",
        "artifact",
        "anomaly",
        "neighbor",
        "doublet",
        "模拟",
        "人工阳性",
        "伪影",
        "异常",
        "邻域",
        "双细胞",
    ),
    "moscot": (
        "fused",
        "gromov",
        "wasserstein",
        "cost matrix",
        "joint cost",
        "spatial",
        "temporal",
        "mapping",
        "optimal transport",
        "融合代价",
        "联合代价",
        "成本矩阵",
        "代价矩阵",
        "空间",
        "时间",
        "映射",
        "最优传输",
    ),
    "wot": (
        "time series",
        "dense time",
        "temporal",
        "transport",
        "development",
        "时间序列",
        "发育",
        "最优传输",
    ),
    "MOFA2": (
        "multi-view",
        "multiomics",
        "multi-omics",
        "matched",
        "latent",
        "factor",
        "view",
        "drift",
        "共同因子",
        "多组学",
        "matched",
        "隐变量",
        "潜在因子",
        "因子漂移",
    ),
    "Harmony": (
        "embedding-level",
        "embedding correction",
        "batch",
        "alignment",
        "fast alignment",
        "pca",
        "跨样本对齐",
        "批次校正",
        "embedding",
        "嵌入",
    ),
    "Seurat": (
        "anchor",
        "wnn",
        "cross-modal",
        "multi-view",
        "alignment",
        "anchor",
        "跨模态",
        "多模态",
        "对齐",
    ),
    "scvi-tools": (
        "vae",
        "latent",
        "probabilistic",
        "uncertainty",
        "batch",
        "隐变量",
        "概率",
        "不确定性",
        "批次",
    ),
    "CellRank": (
        "transition kernel",
        "fate",
        "absorption",
        "terminal state",
        "probability matrix",
        "转移概率",
        "状态转移",
        "命运",
        "吸收",
        "终态",
    ),
    "cell2location": (
        "deconvolution",
        "mixture",
        "abundance",
        "spatial",
        "reference",
        "posterior",
        "混合",
        "反卷积",
        "丰度",
        "空间",
        "参考",
        "后验",
    ),
    "scGPT": (
        "foundation",
        "embedding",
        "feature extractor",
        "representation",
        "drift",
        "zero-shot",
        "大模型",
        "表征",
        "嵌入",
        "特征提取",
        "位移",
        "漂移",
    ),
    "CellPLM": (
        "foundation",
        "embedding",
        "feature extractor",
        "representation",
        "drift",
        "大模型",
        "表征",
        "嵌入",
        "特征提取",
        "位移",
        "漂移",
    ),
    "nicheformer": (
        "niche",
        "microenvironment",
        "spatial context",
        "spatial neighborhood",
        "微环境",
        "空间邻域",
        "niche",
        "表征",
    ),
    "SingleR": (
        "reference",
        "annotation",
        "label",
        "correlation",
        "atlas",
        "参考",
        "注释",
        "标签",
        "相关性",
        "图谱",
    ),
    "CellTypist": (
        "reference",
        "annotation",
        "label",
        "classifier",
        "atlas",
        "参考",
        "注释",
        "标签",
        "分类器",
        "图谱",
    ),
}


TASK_TRANSFER_PRIORS: dict[str, dict[str, float]] = {
    "Perturbation Differential Expression": {"MIMOSCA": 0.9, "tradeSeq": 0.88, "MOFA2": 0.55, "scGPT": 0.48},
    "Trajectory Differential Expression": {"tradeSeq": 0.9, "MIMOSCA": 0.55, "CellRank": 0.45},
    "Ambient RNA Removal": {"SoupX": 0.9},
    "Spatial Deconvolution": {"cell2location": 0.9, "nicheformer": 0.35},
    "Optimal Transport Trajectory": {"moscot": 0.9, "wot": 0.6},
    "Multiome Integration": {"MOFA2": 0.9, "Seurat": 0.62, "scvi-tools": 0.58, "moscot": 0.52},
    "Data Integration": {"Harmony": 0.88, "Seurat": 0.7, "scvi-tools": 0.62},
    "Foundation Model Representation": {"scGPT": 0.9, "CellPLM": 0.82, "nicheformer": 0.72},
    "QC": {"Scrublet": 0.86, "DoubletFinder": 0.82},
    "Doublet Detection": {"Scrublet": 0.9, "DoubletFinder": 0.88},
    "Cell Type Annotation": {"SingleR": 0.86, "CellTypist": 0.86},
    "Trajectory Inference": {"CellRank": 0.9, "scVelo": 0.65, "moscot": 0.55, "wot": 0.5},
    "RNA Velocity": {"scVelo": 0.9},
}


def _query_context(constraints: Dict[str, Any]) -> str:
    parts = [
        str(constraints.get("migration_query_text", "")),
        str(constraints.get("output_goal", "")),
        str(constraints.get("task", "")),
        str(constraints.get("modality", "")),
        " ".join(str(item) for item in constraints.get("migration_intent_reasons", []) or []),
    ]
    return _normalize_text(" ".join(parts))


def _term_score(terms: tuple[str, ...], context: str) -> float:
    if not terms or not context:
        return 0.0
    hits = 0
    for term in terms:
        if _normalize_text(term) in context:
            hits += 1
    if hits == 0:
        return 0.0
    return min(1.0, 0.25 + hits * 0.2)


def _task_transfer_prior(profile: AlgorithmProfile, constraints: Dict[str, Any]) -> float:
    task = constraints.get("task", "Unknown")
    return TASK_TRANSFER_PRIORS.get(task, {}).get(profile.tool_name, 0.0)


def _mechanism_query_score(
    profile: AlgorithmProfile,
    review: MigrationReview | None,
    constraints: Dict[str, Any],
) -> float:
    context = _query_context(constraints)
    profile_text = _normalize_text(
        " ".join(
            [
                profile.algorithm_family,
                profile.model_assumption,
                profile.optimization_objective,
                profile.transferable_mechanism,
                profile.known_limitations,
                review.transferable_mechanism if review else "",
                review.reviewer_notes if review else "",
            ]
        )
    )
    terms = TOOL_MECHANISM_TERMS.get(profile.tool_name, ())
    lexical = _term_score(terms, context)
    overlap = 0.0
    context_terms = {token for token in context.replace(";", " ").split() if len(token) >= 4}
    if context_terms:
        profile_terms = {token for token in profile_text.replace(";", " ").split() if len(token) >= 4}
        overlap = min(1.0, len(context_terms.intersection(profile_terms)) / max(3, len(context_terms)))
    return min(1.0, max(lexical, overlap))


def _read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def _to_float(value: str | float | None, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        if isinstance(value, float):
            return value
        mapped = {"high": 0.85, "partial": 0.55, "medium": 0.55, "low": 0.25, "pending": default}
        if value in mapped:
            return mapped[value]
        if value == "pending":
            return default
        return float(value)
    except Exception:
        return default


def _normalize_text(text: str) -> str:
    return (text or "").strip().lower()


def _load_profiles() -> dict[str, AlgorithmProfile]:
    profiles: dict[str, AlgorithmProfile] = {}
    for row in _read_tsv(PROFILE_PATH):
        profile = AlgorithmProfile(
            tool_name=row.get("tool_name", ""),
            algorithm_family=row.get("algorithm_family", ""),
            model_assumption=row.get("model_assumption", ""),
            distance_metric=row.get("distance_metric", ""),
            optimization_objective=row.get("optimization_objective", ""),
            input_object=row.get("input_object", ""),
            output_object=row.get("output_object", ""),
            supported_task=row.get("supported_task", ""),
            supported_modality=row.get("supported_modality", ""),
            transferable_mechanism=row.get("transferable_mechanism", ""),
            known_limitations=row.get("known_limitations", ""),
            review_status=row.get("review_status", ""),
            reviewer_notes=row.get("reviewer_notes", ""),
        )
        profiles[profile.tool_name] = profile
    return profiles


def _load_reviews() -> dict[str, list[MigrationReview]]:
    reviews: dict[str, list[MigrationReview]] = {}
    for row in _read_tsv(REVIEW_PACKET_PATH):
        review = MigrationReview(
            query_id=row.get("query_id", ""),
            target_task=row.get("target_task", ""),
            target_modality=row.get("target_modality", ""),
            source_tool=row.get("source_tool", ""),
            source_task=row.get("source_task", ""),
            transferable_mechanism=row.get("transferable_mechanism", ""),
            vector_similarity=row.get("vector_similarity", ""),
            graph_jaccard=row.get("graph_jaccard", ""),
            io_compatibility=row.get("io_compatibility", ""),
            compatibility_gaps=row.get("compatibility_gaps", ""),
            risk_level=row.get("risk_level", ""),
            candidate_decision=row.get("candidate_decision", ""),
            reviewer_decision=row.get("reviewer_decision", ""),
            reviewer_notes=row.get("reviewer_notes", ""),
        )
        reviews.setdefault(review.source_tool, []).append(review)
    return reviews


def _profile_mechanism_score(profile: AlgorithmProfile, constraints: Dict[str, Any]) -> float:
    target_task = _normalize_text(constraints.get("task", ""))
    target_modality = _normalize_text(constraints.get("modality", ""))
    supported_task = _normalize_text(profile.supported_task)
    supported_modality = _normalize_text(profile.supported_modality)
    score = 0.0
    if target_task and supported_task and target_task == supported_task:
        score += 0.5
    if target_task and supported_task and target_task in supported_task:
        score += 0.35
    if target_modality and supported_modality and target_modality in supported_modality:
        score += 0.15
    score = max(score, _task_transfer_prior(profile, constraints))
    return min(score, 1.0)


def _profile_i_o_compatibility(profile: AlgorithmProfile, constraints: Dict[str, Any]) -> float:
    target_modality = _normalize_text(constraints.get("modality", ""))
    input_object = _normalize_text(profile.input_object)
    output_object = _normalize_text(profile.output_object)
    score = 0.0
    if target_modality and target_modality in input_object:
        score += 0.5
    if target_modality and target_modality in output_object:
        score += 0.1
    if any(token in input_object for token in ("anndata", "expression matrix", "count matrix", "seuratobject")):
        score += 0.4
    return min(score, 1.0)


def _profile_novelty_relevance(review: MigrationReview) -> float:
    decision = _normalize_text(review.reviewer_decision)
    if decision == "accept_exploratory":
        return 1.0
    if decision == "revise_mechanism":
        return 0.35
    if decision == "needs_more_evidence":
        return 0.2
    return 0.0


def _risk_penalty(risk_level: str, profile: AlgorithmProfile) -> float:
    risk = _normalize_text(risk_level)
    penalty = {"low": 0.05, "medium": 0.12, "high": 0.2, "exploratory": 0.15, "unknown": 0.1}.get(risk, 0.1)
    if "must never replace" in _normalize_text(profile.known_limitations):
        penalty += 0.05
    return min(penalty, 0.35)


def _compatibility_gaps(profile: AlgorithmProfile, compatibility_gaps: str) -> list[str]:
    gaps = [gap.strip() for gap in compatibility_gaps.split(";") if gap.strip()]
    if not gaps:
        gaps = [item.strip() for item in profile.known_limitations.split(";") if item.strip()]
    return gaps


def _review_relevance(review: MigrationReview, constraints: Dict[str, Any]) -> float:
    target_task = _normalize_text(constraints.get("task", ""))
    target_modality = _normalize_text(constraints.get("modality", ""))
    review_task = _normalize_text(review.target_task)
    review_modality = _normalize_text(review.target_modality)
    score = 0.0
    if target_task and review_task:
        if target_task == review_task:
            score += 0.65
        elif target_task in review_task or review_task in target_task:
            score += 0.45
        elif "spatial" in target_task and "spatial" in review_task:
            score += 0.35
        elif "multiome" in target_task and any(term in review_task for term in ("multi", "modality", "view")):
            score += 0.35
        elif target_task == "qc" and any(term in review_task for term in ("artifact", "doublet")):
            score += 0.35
        elif target_task == "ambient rna removal" and "contamination" in review_task:
            score += 0.35
        elif target_task == "foundation model representation" and "foundation" in review_task:
            score += 0.35
    if target_modality and review_modality:
        if target_modality == review_modality:
            score += 0.25
        elif target_modality in review_modality or review_modality in target_modality:
            score += 0.15
        elif "spatial" in target_modality and "spatial" in review_modality:
            score += 0.15
        elif "multi" in target_modality and "multi" in review_modality:
            score += 0.15
    return min(score, 1.0)


def _select_review(
    reviews: dict[str, list[MigrationReview]],
    profile: AlgorithmProfile,
    constraints: Dict[str, Any],
) -> MigrationReview | None:
    candidates = reviews.get(profile.tool_name, [])
    accepted = [
        review for review in candidates
        if _normalize_text(review.reviewer_decision) == "accept_exploratory"
    ]
    if accepted:
        best = max(accepted, key=lambda review: _review_relevance(review, constraints))
        return best if _review_relevance(best, constraints) >= 0.35 else None
    if any(_normalize_text(review.reviewer_decision) == "revise_mechanism" for review in candidates):
        return None
    return None


def _has_revise_block(reviews: dict[str, list[MigrationReview]], tool_name: str) -> bool:
    tool_reviews = reviews.get(tool_name, [])
    has_revise = any(_normalize_text(review.reviewer_decision) == "revise_mechanism" for review in tool_reviews)
    has_accept = any(_normalize_text(review.reviewer_decision) == "accept_exploratory" for review in tool_reviews)
    return has_revise and not has_accept


def _profile_fallback_relevance(
    profile: AlgorithmProfile,
    constraints: Dict[str, Any],
    expected_tools: list[str],
    review: MigrationReview | None = None,
) -> float:
    if profile.tool_name in expected_tools:
        return 0.65
    return max(
        _profile_mechanism_score(profile, constraints),
        _task_transfer_prior(profile, constraints),
        _mechanism_query_score(profile, review, constraints),
    )


def build_migration_hypotheses(
    constraints: Dict[str, Any],
    expected_source_tools: Optional[Iterable[str]] = None,
    top_k: int = 3,
) -> List[MigrationPath]:
    profiles = _load_profiles()
    reviews = _load_reviews()
    target_task = constraints.get("task", "Unknown")
    target_modality = constraints.get("modality", "Unknown")
    expected = list(expected_source_tools or [])

    ranked: List[MigrationPath] = []
    has_expected_tools = bool(expected)
    for tool_name in expected or list(profiles.keys()):
        profile = profiles.get(tool_name)
        if profile is None:
            continue
        if _has_revise_block(reviews, profile.tool_name):
            continue
        review = _select_review(reviews, profile, constraints)

        base_relevance = _profile_fallback_relevance(profile, constraints, expected, review)
        if not has_expected_tools and base_relevance < 0.35:
            continue
        transfer_prior = _task_transfer_prior(profile, constraints)
        if not has_expected_tools and review is None and transfer_prior < 0.5:
            continue
        if not has_expected_tools and review is None and base_relevance < 0.5:
            continue

        mechanism_score = _mechanism_query_score(profile, review, constraints)
        vector_similarity = max(
            _profile_mechanism_score(profile, constraints),
            base_relevance,
            mechanism_score,
        )
        graph_jaccard = 0.0
        if review and _normalize_text(review.graph_jaccard) not in {"", "pending"}:
            graph_jaccard = _to_float(review.graph_jaccard)
        else:
            if _normalize_text(profile.supported_task) == _normalize_text(target_task):
                graph_jaccard = 0.35
            elif transfer_prior >= 0.5:
                graph_jaccard = 0.28
            elif mechanism_score >= 0.55:
                graph_jaccard = 0.22
            else:
                graph_jaccard = 0.18
        io_compatibility = _to_float(
            review.io_compatibility if review else None,
            default=_profile_i_o_compatibility(profile, constraints),
        )
        evidence_support = 0.65 if profile.review_status == "profile_validated" else 0.35
        novelty_relevance = _profile_novelty_relevance(review) if review else max(
            0.65 if profile.tool_name in expected else 0.25,
            min(0.75, 0.25 + 0.35 * transfer_prior + 0.25 * mechanism_score),
        )
        risk_level = review.risk_level if review else "exploratory"
        risk_penalty = _risk_penalty(risk_level, profile)
        score = (
            0.35 * vector_similarity
            + 0.25 * graph_jaccard
            + 0.20 * io_compatibility
            + 0.10 * evidence_support
            + 0.10 * novelty_relevance
            - risk_penalty
        )
        score = max(0.0, min(1.0, score))
        evidence = EvidenceBundle(
            items=[
                derived_evidence(
                    evidence_id=f"migration:{tool_name}:{target_task}:profile",
                    metric_name="migration_plausibility_score",
                    metric_value=score,
                    extraction_method="engine.migration_hypothesis_engine.build_migration_hypotheses",
                    source_title=f"Migration hypothesis for {tool_name} -> {target_task}",
                    confidence=0.55,
                    kg_version=get_settings().kg_version,
                    graph_layer="experimental",
                    evidence_strength="exploratory",
                    use_for=["retrieval"],
                )
            ],
            missing_evidence=[
                "structured_algorithm_compatibility" if graph_jaccard == 0 else "",
                "full_benchmark_validation",
            ],
        )
        evidence.missing_evidence = [item for item in evidence.missing_evidence if item]
        ranked.append(
            MigrationPath(
                tool_name=tool_name,
                score=score,
                cos_sim=vector_similarity,
                features=profile.transferable_mechanism,
                risk_level=risk_level or "exploratory",
                evidence=evidence,
                limitations=[
                    profile.known_limitations,
                    review.reviewer_notes if review else "Profile-only exploratory candidate; no migration-vector review packet row yet.",
                ],
                source_task=profile.supported_task,
                target_task=target_task,
                transferable_mechanism=profile.transferable_mechanism,
                graph_jaccard=graph_jaccard,
                io_compatibility=io_compatibility,
                evidence_support=evidence_support,
                novelty_relevance=novelty_relevance,
                risk_penalty=risk_penalty,
                compatibility_gaps=_compatibility_gaps(
                    profile,
                    review.compatibility_gaps if review else profile.known_limitations,
                ),
            )
        )

    ranked.sort(key=lambda item: item.score, reverse=True)
    return ranked[:top_k]
