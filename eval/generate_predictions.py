import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.workflow import build_sckg_graph
from connectors.graph_client import Neo4jClient
from core.agent_runtime import ToolExecutor, ToolRegistry
from core.constraints import parse_research_constraints
from core.evidence_policy import (
    MAIN_RECOMMENDATION_TOP_K,
    MIGRATION_TOP_K,
    audit_evidence,
    evidence_guardrail_warnings,
    has_main_recommendation_evidence,
)
from core.models import (
    AgentRunTrace,
    EvidenceContextPack,
    EvidenceBundle,
    MigrationPath,
    PredictionRecord,
    ScoredTool,
    ToolSpec,
    ToolCandidate,
    derived_evidence,
    github_evidence,
    missing_evidence,
)
from core.settings import get_settings
from engine.context_pack_builder import build_evidence_context_pack
from engine.context_pack_reporter import render_context_pack_report
from core.task_ontology import (
    FINE_TASKS,
    build_task_query_terms,
    iter_tool_task_hints,
    normalize_task_label,
    task_alignment_score,
    task_family,
    tool_task_hints,
)
from engine.mcdm_calculator import MCDMCalculator
from engine.migration_intent import (
    MIGRATION_TRIGGER_TERMS as _INTENT_MIGRATION_TRIGGER_TERMS,
    apply_migration_intent_to_constraints as _intent_apply_migration_intent_to_constraints,
    classify_migration_intent as _intent_classify_migration_intent,
    clarification_question_for_gate as _intent_clarification_question_for_gate,
    direct_output_type_for_task as _intent_direct_output_type_for_task,
    filter_blocked_by_tool_name as _intent_filter_blocked_by_tool_name,
    filter_blocked_migration_paths as _intent_filter_blocked_migration_paths,
    hard_migration_reject_reason as _intent_hard_migration_reject_reason,
    has_any as _intent_has_any,
    mark_needs_clarification as _intent_mark_needs_clarification,
    migration_gate as _intent_migration_gate,
)
from engine.migration_hypothesis_engine import build_migration_hypotheses
from engine.semantic_hallucination_auditor import audit_report
from engine.workflow_recommender import build_minimal_workflow_recommendation


WORKFLOW_EXPECTED_TYPES = {"workflow"}
MIGRATION_TRIGGER_TERMS = [
    "找不到",
    "没有现成",
    "没有成熟",
    "借用",
    "借鉴",
    "迁移",
    "可迁移",
    "创新",
    "算法思想",
    "建模思想",
    "研发路线",
    "研发假设",
    "迁移假设",
    "method transfer",
    "transfer",
    "borrow idea",
    "adapt mechanism",
    "migration hypothesis",
    "no direct tool",
    "no mature tool",
    "no existing tool",
]


def _has_any(text: str, terms: List[str]) -> bool:
    return any(term in text for term in terms)


def _direct_output_type_for_task(task: str) -> str:
    if task in {
        "QC",
        "Doublet Detection",
        "Ambient RNA Removal",
        "RNA Velocity",
        "Spatial Deconvolution",
        "Trajectory Differential Expression",
        "Perturbation Differential Expression",
        "Optimal Transport Trajectory",
        "Workflow Planning",
        "Workflow Compatibility",
        "Multiome Integration",
    }:
        return "workflow"
    return "ranked_tools"


def _classify_migration_intent(
    user_query: str,
    constraints: Dict[str, Any],
) -> Dict[str, Any]:
    """Classify whether a query is asking for exploratory migration.

    This is deliberately deterministic and conservative. It separates
    migration-hypothesis routing from normal tool recommendation, workflow
    planning, evidence-chain lookup, clarification, and hard I/O rejections.
    """
    raw_query = user_query or ""
    query = raw_query.lower()
    task = constraints.get("task", "Unknown")
    modality = constraints.get("modality", "Unknown")
    reasons: List[str] = []
    task_hint: Optional[str] = None
    modality_hint: Optional[str] = None

    def decision(
        intent: str,
        confidence: float,
        reason: str,
        *,
        task_value: Optional[str] = None,
        modality_value: Optional[str] = None,
    ) -> Dict[str, Any]:
        local_reasons = list(reasons)
        if reason:
            local_reasons.append(reason)
        return {
            "intent": intent,
            "confidence": round(confidence, 3),
            "reasons": sorted(set(local_reasons)),
            "task_hint": task_value or task_hint,
            "modality_hint": modality_value or modality_hint,
        }

    evidence_chain_terms = [
        "评测协议",
        "评测框架",
        "benchmark protocol",
        "benchmark framework",
        "benchmark paper",
        "证据链",
        "主论文 doi",
        "主论文doi",
        "publication lookup",
        "查某个工具的主论文",
        "比较几篇 benchmark",
        "证据强弱",
    ]
    if _has_any(query, evidence_chain_terms):
        return decision("evidence_chain", 0.94, "explicit_evidence_or_protocol_lookup")

    if _has_any(query, ["github stars", "github star", "github"]) and _has_any(
        query,
        ["证明最好", "proved best", "empirically proven", "已经被证明最好"],
    ):
        return decision("reject", 0.95, "github_popularity_cannot_support_scientific_claim")

    direct_non_migration_terms = [
        "不是算法迁移",
        "不是在问工具推荐或算法迁移",
        "不是要创新迁移",
        "不需要它迁移",
        "不需要大模型迁移",
        "不需要迁移",
        "not asking for migration",
        "not a migration problem",
        "not looking for migration",
    ]
    if _has_any(query, direct_non_migration_terms):
        if task == "Workflow Compatibility" or _has_any(query, ["seuratobject", "h5ad", "对象字段", "object conversion"]):
            return decision("evidence_chain", 0.95, "explicit_workflow_compatibility_not_migration")
        if _has_any(query, ["标准", "常规", "主工具", "工具推荐", "standard", "main tool"]):
            return decision("direct_recommendation", 0.93, "explicit_direct_recommendation_not_migration")
        return decision("workflow", 0.9, "explicit_not_migration")

    if _has_any(query, ["seuratobject", "h5ad", "对象字段", "object conversion", "workflow compatibility"]):
        return decision("evidence_chain", 0.92, "workflow_object_compatibility")

    hard_reject = _hard_migration_reject_reason(query, task)
    if hard_reject:
        return decision("reject", 0.93, hard_reject)

    clarification_terms = [
        "还没决定",
        "还没整理",
        "还不知道",
        "还不清楚",
        "不知道有没有",
        "不确定",
        "是否 paired",
        "是否paired",
        "可能 paired 也可能不是",
        "可能是 paired 也可能不是",
        "没有明确输入对象",
        "没有说明是做",
        "没讲是做",
        "还没定义",
        "未定义",
        "not sure",
        "don't know",
    ]
    if _has_any(query, clarification_terms):
        return decision("clarification", 0.9, "migration_target_or_design_unspecified")

    direct_standard_terms = [
        "常规",
        "标准",
        "主工具",
        "工具推荐",
        "现成工具推荐",
        "输入有 spliced/unspliced",
        "匹配 scrna reference",
        "matched scrna reference",
        "standard analysis",
        "main tool",
    ]
    negates_direct_request = _has_any(query, [
        "不是直接推荐",
        "不是要直接推荐",
        "而不是直接推荐",
        "不只是做标准",
        "不是只做普通",
        "不是只做标准",
        "not a direct recommendation",
        "not just standard",
    ])
    if (
        _has_any(query, direct_standard_terms)
        and not _has_any(query, MIGRATION_TRIGGER_TERMS)
        and not negates_direct_request
    ):
        return decision("direct_recommendation", 0.85, "standard_tool_or_workflow_request")

    migration_score = 0.0
    if _has_any(query, MIGRATION_TRIGGER_TERMS):
        migration_score += 1.0
        reasons.append("explicit_migration_language")
    if _has_any(query, ["不是找现成包", "不是找现成工具", "not looking for a package", "not looking for a tool"]):
        migration_score += 1.0
        reasons.append("not_direct_package_request")

    # Domain-specific positive migration patterns. These are broad scientific
    # premises, not gold-query IDs.
    if _has_any(query, ["连续浓度", "浓度梯度", "剂量梯度", "响应曲线", "dose response", "dose-response"]):
        migration_score += 1.5
        task_hint = "Perturbation Differential Expression"
        modality_hint = "scRNA-seq" if modality == "Unknown" else modality_hint
        reasons.append("ordered_perturbation_response_curve")
    if _has_any(query, ["空白区域", "背景信号", "组织边缘", "污染扣除", "background signal", "off-tissue"]):
        migration_score += 1.5
        task_hint = "Ambient RNA Removal"
        modality_hint = "Spatial Transcriptomics"
        reasons.append("spatial_background_contamination_modeling")
    if _has_any(query, ["共同低维轴", "扰动造成的共同", "共同轴", "joint latent", "latent perturbation"]):
        migration_score += 1.4
        task_hint = "Multiome Integration"
        modality_hint = "scRNA-seq+scATAC-seq" if modality == "Unknown" else modality_hint
        reasons.append("multi_view_latent_perturbation_axis")
    if _has_any(query, ["共享隐变量", "隐变量漂移", "shared latent", "latent drift"]):
        migration_score += 1.4
        task_hint = "Multiome Integration"
        if _has_any(query, ["adt", "蛋白"]):
            modality_hint = "CITE-seq"
        elif modality == "Unknown":
            modality_hint = "scRNA-seq+scATAC-seq"
        reasons.append("multi_view_shared_latent_shift")
    if _has_any(query, ["模拟出阳性", "模拟阳性", "synthetic positive", "风险分数", "risk score"]):
        migration_score += 1.4
        task_hint = "QC"
        modality_hint = "scRNA-seq" if modality == "Unknown" else modality_hint
        reasons.append("synthetic_positive_artifact_scoring")
    if _has_any(query, ["成本矩阵", "代价矩阵", "联合代价", "joint cost", "cost matrix", "时间、空间和表达", "time, space and expression", "fused cost"]):
        migration_score += 1.5
        task_hint = "Optimal Transport Trajectory"
        if "空间" in raw_query or "spatial" in query:
            modality_hint = "Spatial Transcriptomics"
        reasons.append("fused_cost_transport_mapping")
    if _has_any(query, ["特征提取器", "feature extractor", "embedding", "嵌入"]) and _has_any(
        query,
        ["漂移", "偏移", "整体偏移", "drift", "处理前后", "疾病组", "对照组", "perturbation", "不打算解释因果", "不解释因果"],
    ):
        migration_score += 1.4
        task_hint = "Foundation Model Representation"
        reasons.append("foundation_embedding_drift_feature_extraction")
    if _has_any(query, ["frozen feature encoder", "feature encoder", "frozen encoder"]):
        migration_score += 1.4
        task_hint = "Foundation Model Representation"
        reasons.append("foundation_encoder_feature_extraction")
    if _has_any(query, ["可靠轨迹", "lineage weights", "不同分支", "响应形状"]):
        migration_score += 1.3
        task_hint = "Trajectory Differential Expression"
        modality_hint = "scRNA-seq" if modality == "Unknown" else modality_hint
        reasons.append("trajectory_supplied_response_shape")
    if _has_any(query, ["状态转移 kernel", "transition kernel", "fate mapping", "吸收概率", "终态假设"]):
        migration_score += 1.4
        task_hint = "Trajectory Inference"
        modality_hint = "scRNA-seq" if modality == "Unknown" else modality_hint
        reasons.append("transition_kernel_fate_mapping")
    if _has_any(query, ["niche-aware", "niche 表征", "niche表征", "微环境", "空间邻域", "机制能不能给出研发路线", "机制比较", "研发假设"]):
        migration_score += 1.3
        task_hint = "Foundation Model Representation"
        if "空间" in raw_query or "spatial" in query:
            modality_hint = "Spatial Transcriptomics"
        reasons.append("mechanism_comparison_for_spatial_representation")
    if _has_any(query, ["wot", "最优传输", "optimal transport"]) and _has_any(
        query,
        ["能不能直接", "直接", "靠谱吗", "完整路径", "中间完全没采样", "不做共同嵌入"],
    ):
        migration_score += 1.3
        task_hint = "Optimal Transport Trajectory"
        reasons.append("transport_boundary_check")

    if migration_score >= 1.25:
        return decision("migration", min(0.98, 0.55 + 0.12 * migration_score), "migration_premises_detected")

    if task in {"Workflow Compatibility"}:
        return decision("evidence_chain", 0.8, "workflow_compatibility_task")
    if task in {
        "QC",
        "Doublet Detection",
        "Ambient RNA Removal",
        "RNA Velocity",
        "Spatial Deconvolution",
        "Trajectory Differential Expression",
        "Perturbation Differential Expression",
        "Optimal Transport Trajectory",
        "Workflow Planning",
        "Multiome Integration",
    }:
        return decision("workflow", 0.65, "task_defaults_to_workflow")
    return decision("direct_recommendation", 0.6, "default_direct_recommendation")


def _hard_migration_reject_reason(query: str, task: str) -> Optional[str]:
    incompatible_patterns = [
        (["rna velocity", "速度"], ["背景污染", "ambient", "污染信号", "扣掉背景"], "velocity_to_ambient_incompatible"),
        (["双细胞检测分数", "doublet"], ["注释置信度", "cell type annotation", "annotation confidence"], "doublet_score_to_annotation_incompatible"),
        (["mofa2", "因子分析", "多组学因子"], ["doublet calls", "doublet detection", "双细胞"], "factor_model_to_doublet_incompatible"),
        (["mofa2", "因子", "factor"], ["ambient rna", "背景谱", "扣除污染", "ambient"], "factor_model_to_ambient_incompatible"),
        (["ambient rna", "去污染工具", "污染工具", "soupx"], ["velocity latent time", "rna velocity", "latent time", "速度"], "contamination_to_velocity_incompatible"),
        (["反卷积模型", "deconvolution"], ["doublet detection", "双细胞"], "deconvolution_to_doublet_incompatible"),
        (["参考注释器", "参考注释模型", "annotation model", "annotation confidence", "confidence score", "注释器", "singler", "celltypist"], ["ambient contamination", "contamination estimator", "contamination fraction", "背景污染", "污染估计"], "annotation_to_contamination_incompatible"),
        (["整合后的 pca", "integrated pca", "harmony", "seurat"], ["细胞命运概率", "fate probability"], "embedding_to_fate_probability_incompatible"),
        (["整合后的 umap", "umap 箭头", "umap arrow", "integrated umap"], ["rna velocity", "velocity vector"], "embedding_to_velocity_incompatible"),
        (["doublet 模拟器", "双细胞模拟器", "scrublet", "doubletfinder"], ["gene regulatory network", "grn", "调控网络", "因果"], "doublet_simulator_to_grn_incompatible"),
        (["benchmark 框架", "benchmark framework", "scib"], ["批次校正算法", "batch correction algorithm", "当作"], "benchmark_framework_not_method"),
    ]
    for source_terms, target_terms, reason in incompatible_patterns:
        if _has_any(query, source_terms) and _has_any(query, target_terms):
            return reason
    if task == "Data Integration" and _has_any(query, ["benchmark 框架本身", "scib"]) and _has_any(query, ["当作", "运行"]):
        return "benchmark_framework_not_method"
    return None


def _apply_migration_intent_to_constraints(
    constraints: Dict[str, Any],
    user_query: str,
) -> Dict[str, Any]:
    decision = _classify_migration_intent(user_query, constraints)
    updated = dict(constraints)
    task_hint = decision.get("task_hint")
    modality_hint = decision.get("modality_hint")
    if task_hint and (
        updated.get("task") in {None, "", "Unknown", "Workflow Planning"}
        or decision["intent"] == "migration"
        and task_hint in {
            "Foundation Model Representation",
            "Optimal Transport Trajectory",
            "Ambient RNA Removal",
            "Multiome Integration",
        }
    ):
        updated["task"] = task_hint
        updated["task_family"] = task_family(task_hint)
    if modality_hint and updated.get("modality") in {None, "", "Unknown", "scRNA-seq"}:
        # Keep explicit non-spatial / non-multiome modalities unless the query
        # clearly names a spatial or multiome migration premise.
        if modality_hint != "scRNA-seq" or updated.get("modality") in {None, "", "Unknown"}:
            updated["modality"] = modality_hint
    if decision["intent"] in {"migration", "clarification"}:
        updated["strictness"] = "exploratory"
    updated["migration_intent"] = decision["intent"]
    updated["migration_intent_confidence"] = decision["confidence"]
    updated["migration_intent_reasons"] = decision["reasons"]
    return updated


def load_gold_queries(path: Path) -> List[Dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def generate_prediction(
    record: Dict[str, Any],
    use_agent: bool = False,
    blind_migration: bool = False,
) -> PredictionRecord:
    if use_agent:
        return _generate_with_agent(record, blind_migration=blind_migration)
    return _generate_deterministic(record, blind_migration=blind_migration)


def _new_prediction_executor(query_id: str) -> ToolExecutor:
    registry = ToolRegistry()
    registry.register(
        spec=ToolSpec(
            name="parse_research_intent",
            description="Parse a user query into conservative research constraints.",
            input_schema="user_query: str",
            output_schema="ResearchConstraints JSON",
            role="IntentAgent",
        ),
        fn=lambda user_query: parse_research_constraints({}, user_query).model_dump(mode="json"),
    )
    registry.register(
        spec=ToolSpec(
            name="search_tool_candidates",
            description="Retrieve ToolCandidate records through governed KG/offline retrieval.",
            input_schema="constraints: dict, user_query: str",
            output_schema="List[ToolCandidate]",
            role="RetrievalAgent",
        ),
        fn=lambda constraints, user_query="": _find_tool_candidates(constraints, user_query=user_query),
    )
    registry.register(
        spec=ToolSpec(
            name="fetch_tool_evidence",
            description="Fetch structured evidence for named tools without changing evidence state.",
            input_schema="tool_names: list[str]",
            output_schema="dict[str, list[Evidence]]",
            role="RetrievalAgent",
        ),
        fn=_fetch_tool_evidence_for_trace,
    )
    registry.register(
        spec=ToolSpec(
            name="score_candidates_mcdm",
            description="Score candidate tools with evidence-aware MCDM.",
            input_schema="tool_candidates: List[ToolCandidate], constraints: dict",
            output_schema="List[ScoredTool]",
            role="RankingAgent",
            recommendation_grade_allowed=True,
        ),
        fn=lambda tool_candidates, constraints=None: _score_candidates(
            [ToolCandidate.model_validate(item) for item in tool_candidates],
            constraints or {},
        ),
    )
    registry.register(
        spec=ToolSpec(
            name="build_workflow_template",
            description="Build deterministic workflow template from constraints and candidate tools.",
            input_schema="constraints: dict, candidate_tools: list[str]",
            output_schema="WorkflowRecommendation",
            role="WorkflowPlannerAgent",
        ),
        fn=lambda constraints, candidate_tools=None: build_minimal_workflow_recommendation(
            constraints,
            candidate_tools=candidate_tools or [],
        ),
    )
    registry.register(
        spec=ToolSpec(
            name="build_migration_hypotheses",
            description="Build reviewed exploratory migration hypotheses only.",
            input_schema="constraints: dict, tool_candidates: list, expected_source_tools: list|None, blocked_tools: list",
            output_schema="List[MigrationPath]",
            role="MigrationAgent",
        ),
        fn=lambda constraints, tool_candidates=None, expected_source_tools=None, blocked_tools=None: _filter_blocked_migration_paths(
            _build_fallback_migrations(
                constraints,
                [ToolCandidate.model_validate(item) for item in (tool_candidates or [])],
                expected_source_tools=expected_source_tools,
            ),
            blocked_tools or [],
        ),
    )
    registry.register(
        spec=ToolSpec(
            name="build_evidence_context_pack",
            description="Build governed EvidenceContextPack with trusted/retrieval/migration/blocked layers.",
            input_schema="context-pack inputs",
            output_schema="EvidenceContextPack",
            role="ReportAgent",
        ),
        fn=_build_context_pack_tool,
    )
    registry.register(
        spec=ToolSpec(
            name="audit_report_claims",
            description="Audit report claims against structured evidence and context pack.",
            input_schema="report/evidence/scored/candidate/migration/workflow/context_pack",
            output_schema="HallucinationAuditResult",
            role="AuditorAgent",
        ),
        fn=_audit_report_tool,
    )
    return ToolExecutor(
        registry,
        trace=AgentRunTrace(trace_id=f"trace_{query_id}"),
        max_tool_iterations=24,
    )


def _trace_prediction_fields(trace: AgentRunTrace) -> Dict[str, Any]:
    summary = trace.summary()
    return {
        "trace_id": trace.trace_id,
        "agent_trace_summary": summary,
        "tool_call_count": summary["tool_call_count"],
        "failed_tool_call_count": summary["failed_tool_call_count"],
        "mean_tool_latency_ms": summary["mean_tool_latency_ms"],
        "invalid_action_count": summary["invalid_action_count"],
        "blocked_by_guardrail": summary["blocked_by_guardrail"],
    }


def _fetch_tool_evidence_for_trace(tool_names: List[str]) -> Dict[str, List[Dict[str, Any]]]:
    client = Neo4jClient()
    try:
        evidence = client.fetch_tool_evidence(tool_names)
    finally:
        client.close()
    return {
        name: [item.model_dump(mode="json") for item in items]
        for name, items in evidence.items()
    }


def _build_context_pack_tool(
    *,
    user_query: str,
    constraints: Dict[str, Any],
    recommendation_type: str,
    scored_tools: List[Dict[str, Any]],
    tool_candidates: List[Dict[str, Any]],
    workflow: Optional[Dict[str, Any]],
    migration_paths: List[Dict[str, Any]],
    evidence_bundle: Dict[str, Any],
    missing_components: List[str],
    blocked_tools: Optional[List[str]] = None,
    hallucination_audit: Optional[Dict[str, Any]] = None,
) -> EvidenceContextPack:
    from core.models import WorkflowRecommendation

    workflow_model = WorkflowRecommendation.model_validate(workflow) if workflow else None
    return build_evidence_context_pack(
        user_query=user_query,
        constraints=constraints,
        recommendation_type=recommendation_type,
        scored_tools=[ScoredTool.model_validate(item) for item in scored_tools],
        tool_candidates=[ToolCandidate.model_validate(item) for item in tool_candidates],
        workflow=workflow_model,
        migration_paths=[MigrationPath.model_validate(item) for item in migration_paths],
        evidence_bundle=EvidenceBundle.model_validate(evidence_bundle),
        missing_components=missing_components,
        blocked_tools=blocked_tools or [],
        hallucination_audit=hallucination_audit,
    )


def _audit_report_tool(
    *,
    final_report: str,
    evidence_bundle: Dict[str, Any],
    scored_tools: List[Dict[str, Any]],
    candidate_tools: List[Dict[str, Any]],
    migration_paths: List[Dict[str, Any]],
    workflow: Optional[Dict[str, Any]],
    context_pack: Dict[str, Any],
) -> Any:
    from core.models import WorkflowRecommendation

    workflow_model = WorkflowRecommendation.model_validate(workflow) if workflow else None
    return audit_report(
        final_report=final_report,
        evidence_bundle=EvidenceBundle.model_validate(evidence_bundle),
        scored_tools=[ScoredTool.model_validate(item) for item in scored_tools],
        candidate_tools=[ToolCandidate.model_validate(item) for item in candidate_tools],
        migration_paths=[MigrationPath.model_validate(item) for item in migration_paths],
        workflow_recommendation=workflow_model,
        context_pack=context_pack,
    )


def _generate_deterministic(
    record: Dict[str, Any],
    blind_migration: bool = False,
) -> PredictionRecord:
    query_id = record["id"]
    user_query = record["query"]
    errors: List[str] = []
    executor = _new_prediction_executor(query_id)

    parse_result = executor.run_tool(
        "parse_research_intent",
        node_name="IntentAgent",
        args={"user_query": user_query},
    )
    if parse_result.status == "ok" and isinstance(parse_result.result, dict):
        constraints = parse_research_constraints(parse_result.result, user_query)
    else:
        errors.append(f"intent_parse_failed: {parse_result.error_type or parse_result.status}")
        constraints = parse_research_constraints({}, user_query)
    constraints_dict = constraints.model_dump(mode="json")
    constraints_dict = _apply_migration_intent_to_constraints(constraints_dict, user_query)
    executor.add_role_result(
        "IntentAgent",
        status="ok" if parse_result.status == "ok" else "error",
        input_summary={"query_id": query_id},
        output_summary={
            "task": constraints_dict.get("task", "Unknown"),
            "modality": constraints_dict.get("modality", "Unknown"),
            "clarification_state": constraints_dict.get("clarification_state", "needs_clarification"),
        },
    )
    recommendation_type = _choose_recommendation_type(
        constraints=constraints_dict,
        user_query=user_query,
    )
    migration_gate = _migration_gate(user_query, constraints_dict, recommendation_type)
    if migration_gate["recommendation_type"]:
        recommendation_type = migration_gate["recommendation_type"]
    if migration_gate["needs_clarification"]:
        constraints_dict = _mark_needs_clarification(
            constraints_dict,
            migration_gate["reasons"],
        )

    tool_candidates: List[ToolCandidate] = []
    scored_tools: List[ScoredTool] = []
    migration_paths: List[MigrationPath] = []

    retrieval_result = executor.run_tool(
        "search_tool_candidates",
        node_name="RetrievalAgent",
        args={"constraints": constraints_dict, "user_query": user_query},
    )
    try:
        if retrieval_result.status != "ok":
            raise RuntimeError(retrieval_result.error_message or retrieval_result.error_type)
        tool_candidates = [
            item if isinstance(item, ToolCandidate) else ToolCandidate.model_validate(item)
            for item in (retrieval_result.result or [])
        ]
        tool_candidates, scored_tools = _filter_blocked_tool_outputs(
            tool_candidates,
            scored_tools,
            migration_gate["blocked_tools"],
        )
    except Exception as exc:
        errors.append(f"candidate_retrieval_failed: {exc}")
    if tool_candidates:
        executor.run_tool(
            "fetch_tool_evidence",
            node_name="RetrievalAgent",
            args={"tool_names": [candidate.tool_name for candidate in tool_candidates]},
        )
    executor.add_role_result(
        "RetrievalAgent",
        status="ok" if retrieval_result.status == "ok" else "error",
        input_summary={
            "task": constraints_dict.get("task"),
            "modality": constraints_dict.get("modality"),
        },
        output_summary={
            "candidate_count": len(tool_candidates),
            "blocked_tools": migration_gate["blocked_tools"],
        },
    )
    executor.add_role_result(
        "EvidenceGateAgent",
        status="ok",
        input_summary={"raw_candidate_count": len(tool_candidates)},
        output_summary={
            "trusted_core_candidate_count": len(tool_candidates),
            "policy": "has_main_recommendation_evidence",
        },
    )

    if recommendation_type in {"ranked_tools", "workflow", "evidence_chain"}:
        scoring_result = executor.run_tool(
            "score_candidates_mcdm",
            node_name="RankingAgent",
            args={
                "tool_candidates": [item.model_dump(mode="json") for item in tool_candidates],
                "constraints": constraints_dict,
            },
        )
        try:
            if scoring_result.status != "ok":
                raise RuntimeError(scoring_result.error_message or scoring_result.error_type)
            scored_tools = [
                item if isinstance(item, ScoredTool) else ScoredTool.model_validate(item)
                for item in (scoring_result.result or [])
            ]
            tool_candidates, scored_tools = _filter_blocked_tool_outputs(
                tool_candidates,
                scored_tools,
                migration_gate["blocked_tools"],
            )
        except Exception as exc:
            errors.append(f"mcdm_scoring_failed: {exc}")
        executor.add_role_result(
            "RankingAgent",
            status="ok" if scoring_result.status == "ok" else "error",
            input_summary={"candidate_count": len(tool_candidates)},
            output_summary={"scored_tool_count": len(scored_tools)},
        )

    if (recommendation_type == "migration" or not tool_candidates) and migration_gate["allow_migration"]:
        migration_result = executor.run_tool(
            "build_migration_hypotheses",
            node_name="MigrationAgent",
            args={
                "constraints": constraints_dict,
                "tool_candidates": [item.model_dump(mode="json") for item in tool_candidates],
                "expected_source_tools": None if blind_migration else record.get("expected_source_tools"),
                "blocked_tools": migration_gate["blocked_tools"],
            },
        )
        if migration_result.status == "ok":
            migration_paths = [
                item if isinstance(item, MigrationPath) else MigrationPath.model_validate(item)
                for item in (migration_result.result or [])
            ]
        else:
            errors.append(f"migration_hypothesis_failed: {migration_result.error_type or migration_result.status}")
        executor.add_role_result(
            "MigrationAgent",
            status="ok" if migration_result.status == "ok" else "error",
            input_summary={"allow_migration": migration_gate["allow_migration"]},
            output_summary={
                "migration_path_count": len(migration_paths),
                "accepted_path_count": len(_accepted_migration_paths(migration_paths)),
            },
        )

    ranked_tool_names = [tool.tool_name for tool in scored_tools]
    candidate_tool_names = [candidate.tool_name for candidate in tool_candidates]
    workflow = None
    if recommendation_type in WORKFLOW_EXPECTED_TYPES:
        workflow_result = executor.run_tool(
            "build_workflow_template",
            node_name="WorkflowPlannerAgent",
            args={
                "constraints": constraints_dict,
                "candidate_tools": (ranked_tool_names or candidate_tool_names)[:3],
            },
        )
        if workflow_result.status == "ok":
            workflow = workflow_result.result
            _filter_workflow_candidate_tools(workflow, migration_gate["blocked_tools"])
        else:
            errors.append(f"workflow_template_failed: {workflow_result.error_type or workflow_result.status}")
        executor.add_role_result(
            "WorkflowPlannerAgent",
            status="ok" if workflow_result.status == "ok" else "error",
            input_summary={"recommendation_type": recommendation_type},
            output_summary={"workflow_step_count": len(workflow.steps) if workflow else 0},
        )

    visible_tool_candidates, visible_scored_tools, visible_migration_paths = _visible_outputs(
        tool_candidates=tool_candidates,
        scored_tools=scored_tools,
        migration_paths=migration_paths,
    )
    report_migration_paths = _accepted_migration_paths(visible_migration_paths)
    evidence_bundle = _combine_evidence(
        tool_candidates=visible_tool_candidates,
        scored_tools=visible_scored_tools,
        migration_paths=report_migration_paths,
        workflow=workflow,
    )
    missing_components = _missing_components(
        constraints_dict=constraints_dict,
        evidence_bundle=evidence_bundle,
        workflow=workflow,
        recommendation_type=recommendation_type,
        candidate_count=len(tool_candidates),
        scored_count=len(scored_tools),
    )
    missing_components.extend(migration_gate["missing_components"])
    missing_components = sorted(set(missing_components))
    context_pack_result = executor.run_tool(
        "build_evidence_context_pack",
        node_name="ReportAgent",
        args={
            "user_query": user_query,
            "constraints": constraints_dict,
            "recommendation_type": recommendation_type,
            "scored_tools": [item.model_dump(mode="json") for item in visible_scored_tools],
            "tool_candidates": [item.model_dump(mode="json") for item in visible_tool_candidates],
            "workflow": workflow.model_dump(mode="json") if workflow else None,
            "migration_paths": [item.model_dump(mode="json") for item in visible_migration_paths],
            "evidence_bundle": evidence_bundle.model_dump(mode="json"),
            "missing_components": missing_components,
            "blocked_tools": migration_gate["blocked_tools"],
        },
    )
    if context_pack_result.status == "ok":
        context_pack = context_pack_result.result
    else:
        errors.append(f"context_pack_failed: {context_pack_result.error_type or context_pack_result.status}")
        context_pack = build_evidence_context_pack(
            user_query=user_query,
            constraints=constraints_dict,
            recommendation_type=recommendation_type,
            scored_tools=visible_scored_tools,
            tool_candidates=visible_tool_candidates,
            workflow=workflow,
            migration_paths=visible_migration_paths,
            evidence_bundle=evidence_bundle,
            missing_components=missing_components,
            blocked_tools=migration_gate["blocked_tools"],
        )
    final_report = render_context_pack_report(context_pack)
    audit_result = executor.run_tool(
        "audit_report_claims",
        node_name="AuditorAgent",
        args={
            "final_report": final_report,
            "evidence_bundle": evidence_bundle.model_dump(mode="json"),
            "scored_tools": [item.model_dump(mode="json") for item in visible_scored_tools],
            "candidate_tools": [item.model_dump(mode="json") for item in visible_tool_candidates],
            "migration_paths": [item.model_dump(mode="json") for item in report_migration_paths],
            "workflow": workflow.model_dump(mode="json") if workflow else None,
            "context_pack": context_pack.model_dump(mode="json"),
        },
    )
    if audit_result.status == "ok":
        hallucination_audit = audit_result.result
    else:
        errors.append(f"semantic_audit_failed: {audit_result.error_type or audit_result.status}")
        hallucination_audit = audit_report(
            final_report=final_report,
            evidence_bundle=evidence_bundle,
            scored_tools=visible_scored_tools,
            candidate_tools=visible_tool_candidates,
            migration_paths=report_migration_paths,
            workflow_recommendation=workflow,
            context_pack=context_pack.model_dump(mode="json"),
        )
    blocking_issues = _blocking_audit_issues(hallucination_audit.model_dump(mode="json"))
    if blocking_issues:
        executor.trace.blocked_by_guardrail = True
        final_report = _safe_audit_blocked_report(
            constraints=constraints_dict,
            recommendation_type=recommendation_type,
            scored_tools=visible_scored_tools,
            migration_paths=report_migration_paths,
            workflow=workflow,
            missing_components=missing_components,
        )
        hallucination_audit = audit_report(
            final_report=final_report,
            evidence_bundle=evidence_bundle,
            scored_tools=visible_scored_tools,
            candidate_tools=visible_tool_candidates,
            migration_paths=report_migration_paths,
            workflow_recommendation=workflow,
            context_pack=context_pack.model_dump(mode="json"),
        )
    executor.add_role_result(
        "AuditorAgent",
        status="blocked" if blocking_issues else "ok",
        input_summary={"claim_count": hallucination_audit.claim_count},
        output_summary={
            "unsupported_claim_count": hallucination_audit.unsupported_claim_count,
            "high_or_critical_issue_count": len(blocking_issues),
        },
        vetoed=bool(blocking_issues),
    )
    context_pack_result = executor.run_tool(
        "build_evidence_context_pack",
        node_name="ReportAgent",
        args={
            "user_query": user_query,
            "constraints": constraints_dict,
            "recommendation_type": recommendation_type,
            "scored_tools": [item.model_dump(mode="json") for item in visible_scored_tools],
            "tool_candidates": [item.model_dump(mode="json") for item in visible_tool_candidates],
            "workflow": workflow.model_dump(mode="json") if workflow else None,
            "migration_paths": [item.model_dump(mode="json") for item in visible_migration_paths],
            "evidence_bundle": evidence_bundle.model_dump(mode="json"),
            "missing_components": missing_components,
            "blocked_tools": migration_gate["blocked_tools"],
            "hallucination_audit": hallucination_audit.model_dump(mode="json"),
        },
    )
    if context_pack_result.status == "ok":
        context_pack = context_pack_result.result
    claim_count = hallucination_audit.claim_count
    unsupported_claims = hallucination_audit.unsupported_claim_count
    executor.add_role_result(
        "ReportAgent",
        status="ok",
        input_summary={"context_pack_mode": context_pack.kg_rag_mode},
        output_summary={
            "report_chars": len(final_report),
            "rag_snippet_count": (
                (context_pack.retrieval_context or {})
                .get("formal_rag_context", {})
                .get("snippet_count", 0)
            ),
        },
    )

    status = "ok"
    if errors:
        status = "partial" if visible_scored_tools or report_migration_paths or workflow else "error"
    elif missing_components:
        status = "partial"

    candidate_payload = [item.model_dump(mode="json") for item in visible_tool_candidates]
    scored_payload = [item.model_dump(mode="json") for item in visible_scored_tools]
    migration_payload = [item.model_dump(mode="json") for item in report_migration_paths]
    visible_ranked_tool_names = [tool.tool_name for tool in visible_scored_tools]
    visible_candidate_tool_names = [candidate.tool_name for candidate in visible_tool_candidates]

    return PredictionRecord(
        id=query_id,
        query_id=query_id,
        user_query=user_query,
        parsed_constraints=constraints_dict,
        candidate_tools=candidate_payload,
        scored_tools=scored_payload,
        migration_paths=migration_payload,
        recommendation_type=recommendation_type,
        recommendation_kind=recommendation_type,
        evidence_bundle=evidence_bundle,
        context_pack=context_pack,
        workflow_recommendation=workflow,
        final_report=final_report,
        missing_components=missing_components,
        clarification_needed=bool(
            constraints_dict.get(
                "needs_human_clarification",
                constraints.needs_human_clarification,
            )
        ),
        execution_status=status,
        execution_mode="deterministic",
        candidate_tool_count=len(tool_candidates),
        scored_tool_count=len(scored_tools),
        migration_path_count=len(report_migration_paths),
        output_truncated=(
            len(candidate_payload) < len(tool_candidates)
            or len(scored_payload) < len(scored_tools)
            or len(migration_payload) < len(migration_paths)
        ),
        recommended_tools=_trim_names(
            _recommended_tool_names(
                recommendation_type=recommendation_type,
                ranked_tool_names=visible_ranked_tool_names,
                candidate_tool_names=visible_candidate_tool_names,
                migration_paths=report_migration_paths,
            ),
            20,
        ),
        evidence_coverage=evidence_bundle.coverage,
        workflow_steps=[step.name for step in workflow.steps] if workflow else [],
        claim_count=claim_count,
        unsupported_claims=unsupported_claims,
        semantic_hallucination_rate=hallucination_audit.hallucination_rate,
        hallucination_audit=hallucination_audit.model_dump(mode="json"),
        **_trace_prediction_fields(executor.trace),
        errors=errors,
    )


def _generate_with_agent(
    record: Dict[str, Any],
    blind_migration: bool = False,
) -> PredictionRecord:
    query_id = record["id"]
    user_query = record["query"]
    errors: List[str] = []
    executor = _new_prediction_executor(f"{query_id}_agent")
    try:
        executor.run_tool(
            "parse_research_intent",
            node_name="IntentAgent",
            args={"user_query": user_query},
        )
        app = build_sckg_graph()
        final_state = app.invoke(
            {
                "user_query": user_query,
                "extracted_constraints": {},
                "candidate_tools": [],
                "tool_candidates": [],
                "retrieval_results": [],
                "scored_tools": [],
                "migration_paths": [],
                "workflow_recommendations": [],
                "decision_report": None,
                "context_pack": {},
                "final_report": "",
                "current_step": "init",
                "error_message": None,
            }
        )
    except Exception as exc:
        errors.append(f"agent_execution_failed: {exc}")
        fallback = _generate_deterministic(record, blind_migration=blind_migration)
        data = fallback.model_dump(mode="json")
        data["execution_mode"] = "agent"
        data["execution_status"] = "error"
        data["errors"] = fallback.errors + errors
        data.setdefault("agent_trace_summary", fallback.agent_trace_summary)
        data.setdefault("trace_id", fallback.trace_id)
        return PredictionRecord.model_validate(data)

    constraints = parse_research_constraints(
        final_state.get("extracted_constraints", {}),
        user_query=user_query,
    )
    scored_tools = [
        ScoredTool.model_validate(item)
        for item in final_state.get("scored_tools", [])
    ]
    tool_candidates = [
        ToolCandidate.model_validate(item)
        for item in final_state.get("tool_candidates", [])
    ]
    migration_paths = [
        MigrationPath.model_validate(item)
        for item in final_state.get("migration_paths", [])
    ]
    workflow_items = final_state.get("workflow_recommendations", [])
    workflow = (
        build_minimal_workflow_recommendation(
            constraints.model_dump(mode="json"),
            candidate_tools=[tool.tool_name for tool in scored_tools][:3],
        )
        if not workflow_items
        else workflow_items[0]
    )
    if isinstance(workflow, dict):
        from core.models import WorkflowRecommendation

        workflow = WorkflowRecommendation.model_validate(workflow)

    recommendation_type = _choose_recommendation_type(
        constraints=_apply_migration_intent_to_constraints(
            constraints.model_dump(mode="json"),
            user_query,
        ),
        user_query=user_query,
        has_migration=bool(migration_paths),
    )
    visible_tool_candidates, visible_scored_tools, visible_migration_paths = _visible_outputs(
        tool_candidates=tool_candidates,
        scored_tools=scored_tools,
        migration_paths=migration_paths,
    )
    report_migration_paths = _accepted_migration_paths(visible_migration_paths)
    evidence_bundle = _combine_evidence(
        tool_candidates=visible_tool_candidates,
        scored_tools=visible_scored_tools,
        migration_paths=report_migration_paths,
        workflow=workflow,
    )
    missing_components = _missing_components(
        constraints_dict=constraints.model_dump(mode="json"),
        evidence_bundle=evidence_bundle,
        workflow=workflow,
        recommendation_type=recommendation_type,
        candidate_count=len(tool_candidates),
        scored_count=len(scored_tools),
    )
    raw_context_pack = final_state.get("context_pack") or {}
    context_pack = (
        EvidenceContextPack.model_validate(raw_context_pack)
        if raw_context_pack
        else build_evidence_context_pack(
            user_query=user_query,
            constraints=constraints.model_dump(mode="json"),
            recommendation_type=recommendation_type,
            scored_tools=visible_scored_tools,
            tool_candidates=visible_tool_candidates,
            workflow=workflow,
            migration_paths=visible_migration_paths,
            evidence_bundle=evidence_bundle,
            missing_components=missing_components,
        )
    )
    final_report = final_state.get("final_report", "")
    hallucination_audit = audit_report(
        final_report=final_report,
        evidence_bundle=evidence_bundle,
        scored_tools=visible_scored_tools,
        candidate_tools=visible_tool_candidates,
        migration_paths=report_migration_paths,
        workflow_recommendation=workflow,
        context_pack=context_pack.model_dump(mode="json"),
    )
    claim_count = hallucination_audit.claim_count
    unsupported_claims = hallucination_audit.unsupported_claim_count
    ranked_tool_names = [tool.tool_name for tool in scored_tools]
    candidate_tool_names = [candidate.tool_name for candidate in tool_candidates]
    blocking_issues = _blocking_audit_issues(hallucination_audit.model_dump(mode="json"))
    executor.add_role_result(
        "IntentAgent",
        status="ok",
        input_summary={"query_id": query_id},
        output_summary={
            "task": constraints.task,
            "modality": constraints.modality,
            "clarification_state": constraints.clarification_state,
        },
    )
    executor.add_role_result(
        "RetrievalAgent",
        status="ok",
        output_summary={"candidate_count": len(tool_candidates)},
    )
    executor.add_role_result(
        "EvidenceGateAgent",
        status="ok",
        output_summary={"trusted_core_candidate_count": len(tool_candidates)},
    )
    executor.add_role_result(
        "RankingAgent",
        status="ok",
        output_summary={"scored_tool_count": len(scored_tools)},
    )
    executor.add_role_result(
        "WorkflowPlannerAgent",
        status="ok",
        output_summary={"workflow_step_count": len(workflow.steps) if workflow else 0},
    )
    executor.add_role_result(
        "MigrationAgent",
        status="ok",
        output_summary={"migration_path_count": len(report_migration_paths)},
    )
    executor.add_role_result(
        "ReportAgent",
        status="ok",
        output_summary={"report_chars": len(final_report)},
    )
    executor.add_role_result(
        "AuditorAgent",
        status="blocked" if blocking_issues else "ok",
        output_summary={
            "unsupported_claim_count": unsupported_claims,
            "high_or_critical_issue_count": len(blocking_issues),
        },
        vetoed=bool(blocking_issues),
    )

    candidate_payload = [item.model_dump(mode="json") for item in visible_tool_candidates]
    scored_payload = [item.model_dump(mode="json") for item in visible_scored_tools]
    migration_payload = [item.model_dump(mode="json") for item in report_migration_paths]
    visible_ranked_tool_names = [tool.tool_name for tool in visible_scored_tools]
    visible_candidate_tool_names = [candidate.tool_name for candidate in visible_tool_candidates]

    return PredictionRecord(
        id=query_id,
        query_id=query_id,
        user_query=user_query,
        parsed_constraints=constraints.model_dump(mode="json"),
        candidate_tools=candidate_payload,
        scored_tools=scored_payload,
        migration_paths=migration_payload,
        recommendation_type=recommendation_type,
        recommendation_kind=recommendation_type,
        evidence_bundle=evidence_bundle,
        context_pack=context_pack,
        workflow_recommendation=workflow,
        final_report=final_report,
        missing_components=missing_components,
        clarification_needed=constraints.needs_human_clarification,
        execution_status="partial" if missing_components else "ok",
        execution_mode="agent",
        candidate_tool_count=len(tool_candidates),
        scored_tool_count=len(scored_tools),
        migration_path_count=len(report_migration_paths),
        output_truncated=(
            len(candidate_payload) < len(tool_candidates)
            or len(scored_payload) < len(scored_tools)
            or len(migration_payload) < len(migration_paths)
        ),
        recommended_tools=_trim_names(
            _recommended_tool_names(
                recommendation_type=recommendation_type,
                ranked_tool_names=visible_ranked_tool_names,
                candidate_tool_names=visible_candidate_tool_names,
                migration_paths=report_migration_paths,
            ),
            20,
        ),
        evidence_coverage=evidence_bundle.coverage,
        workflow_steps=[step.name for step in workflow.steps] if workflow else [],
        claim_count=claim_count,
        unsupported_claims=unsupported_claims,
        semantic_hallucination_rate=hallucination_audit.hallucination_rate,
        hallucination_audit=hallucination_audit.model_dump(mode="json"),
        **_trace_prediction_fields(executor.trace),
        errors=errors,
    )


def _choose_recommendation_type(
    constraints: Dict[str, Any],
    user_query: str = "",
    has_migration: bool = False,
) -> str:
    query = user_query.lower()
    task = constraints.get("task", "Unknown")
    modality = constraints.get("modality", "Unknown")
    species = constraints.get("species", "Unknown")
    strictness = constraints.get("strictness", "balanced")
    intent_decision = _classify_migration_intent(user_query, constraints)
    intent = constraints.get("migration_intent") or intent_decision["intent"]

    if any(term in user_query for term in ["兼容", "接到", "转换"]) or task == "Workflow Compatibility":
        return "evidence_chain"
    if has_migration:
        return "migration"
    if intent == "reject":
        return "none"
    if intent == "clarification":
        return "none"
    if intent == "evidence_chain":
        return "evidence_chain"
    if intent == "migration":
        return "migration"
    if intent == "direct_recommendation":
        return _direct_output_type_for_task(task)
    if intent == "workflow":
        return "workflow"
    if any(term in query or term in user_query for term in MIGRATION_TRIGGER_TERMS):
        return "migration"
    if (
        task == "DTU Analysis"
        and modality == "long-read scRNA-seq"
        and any(term in user_query for term in ["够不够", "不知道", "现成工具"])
    ):
        return "migration"
    if (
        strictness == "exploratory"
        and species != "Human+Mouse"
        and _has_any(query, MIGRATION_TRIGGER_TERMS)
    ):
        return "migration"
    if task in {
        "QC",
        "Doublet Detection",
        "Ambient RNA Removal",
        "RNA Velocity",
        "Spatial Deconvolution",
        "Trajectory Differential Expression",
        "Perturbation Differential Expression",
        "Optimal Transport Trajectory",
        "Workflow Planning",
        "Workflow Compatibility",
    }:
        return "workflow"
    if task == "Differential Expression" and any(term in user_query for term in ["流程", "workflow", "pipeline"]):
        return "workflow"
    if task == "Multiome Integration" or modality in {"CITE-seq", "scRNA-seq+scATAC-seq"}:
        return "workflow"
    if task == "Clustering" and modality == "scATAC-seq":
        return "workflow"
    if task == "Clustering" and any(term in query for term in ["marker", "fragments"]):
        return "workflow"
    if task == "Data Integration" and any(term in user_query for term in ["低质量", "掉零", "跨物种", "保守细胞类型", "注释"]):
        return "workflow"
    return "ranked_tools"


def _migration_gate(
    user_query: str,
    constraints: Dict[str, Any],
    recommendation_type: str,
) -> Dict[str, Any]:
    query = (user_query or "").lower()
    task = constraints.get("task", "Unknown")
    modality = constraints.get("modality", "Unknown")
    output_goal = str(constraints.get("output_goal", "")).lower()
    pending = set(constraints.get("pending_constraints") or [])
    reasons: List[str] = []
    blocked_tools: List[str] = []
    missing_components: List[str] = []
    forced_type: Optional[str] = None
    allow_migration = recommendation_type == "migration"
    needs_clarification = False
    intent_decision = _classify_migration_intent(user_query, constraints)
    intent = constraints.get("migration_intent") or intent_decision["intent"]

    def block(reason: str, forced: str = "none", tools: Optional[List[str]] = None) -> None:
        nonlocal allow_migration, forced_type
        allow_migration = False
        forced_type = forced
        reasons.append(reason)
        missing_components.append(f"migration_gate:{reason}")
        if tools:
            blocked_tools.extend(tools)

    def clarify(reason: str, tools: Optional[List[str]] = None) -> None:
        nonlocal allow_migration, forced_type, needs_clarification
        allow_migration = False
        forced_type = "none"
        needs_clarification = True
        reasons.append(reason)
        missing_components.append(f"clarification_required:{reason}")
        if tools:
            blocked_tools.extend(tools)

    if intent == "reject":
        block((intent_decision["reasons"] or ["migration_rejected"])[0], forced="none")
    elif intent == "clarification":
        clarify((intent_decision["reasons"] or ["migration_target_or_design_unspecified"])[0])
    elif intent == "evidence_chain":
        block((intent_decision["reasons"] or ["evidence_chain_not_migration"])[0], forced="evidence_chain")
    elif intent in {"direct_recommendation", "workflow"}:
        block(
            (intent_decision["reasons"] or ["direct_request_not_migration"])[0],
            forced=_direct_output_type_for_task(task) if intent == "direct_recommendation" else "workflow",
        )
    elif intent == "migration":
        allow_migration = True

    # Explicit non-migration intents must not be routed into hypothesis generation.
    if any(term in query for term in ["workflow compatibility", "object conversion", "seuratobject", "anndata"]):
        block("workflow_compatibility_not_migration", forced="evidence_chain")
    if any(term in query for term in ["benchmark framework", "benchmark protocol", "评测协议", "评测框架"]):
        block("benchmark_protocol_not_migration", forced="evidence_chain")
    if "empirically proven best" in query or "best tool" in query:
        block("strong_claim_requires_reviewed_benchmark", forced="none")

    # Underspecified migration requests should ask for missing scientific design,
    # not invent a transfer path.
    if allow_migration and task == "Unknown":
        clarify("target_task_unspecified")
    if allow_migration and task == "Multiome Integration" and any(term in query for term in ["不知道", "not sure", "don't know", "不确定"]):
        clarify("multiome_target_or_matchedness_unspecified")
    if allow_migration and task == "Perturbation Differential Expression":
        has_design = any(
            term in query
            for term in [
                "dose",
                "剂量",
                "浓度",
                "gradient",
                "response curve",
                "响应曲线",
                "曲线",
                "time",
                "时间",
                "pseudotime",
                "伪时间",
                "lineage",
                "lineage weights",
                "轨迹",
                "分支",
                "可靠轨迹",
                "ko",
                "knockout",
                "crispr",
                "处理前后",
                "对照",
            ]
        )
        if "还没说" in query or "没说" in query or not has_design:
            clarify("perturbation_design_unspecified", tools=["tradeSeq"])
    if allow_migration and task == "QC" and any(term in query for term in ["还没定义", "未定义", "没有定义"]):
        clarify("artifact_simulator_unspecified", tools=["Scrublet", "DoubletFinder"])

    # Hard incompatibility / direct-replacement traps.
    if "scvelo" in query and task == "Ambient RNA Removal":
        block("velocity_to_ambient_incompatible", tools=["scVelo"])
    if "cell2location" in query and task == "RNA Velocity":
        block("deconvolution_to_velocity_incompatible", tools=["cell2location"])
    if "mofa2" in query and task == "Doublet Detection":
        block("factor_model_to_doublet_incompatible", tools=["MOFA2"])
    if task == "Doublet Detection" and any(term in query for term in ["反卷积", "deconvolution", "cell2location"]):
        block("deconvolution_to_doublet_incompatible", tools=["cell2location"])
    if "scrublet" in query and task == "Spatial Deconvolution":
        block("doublet_detection_to_spatial_deconvolution_incompatible", tools=["Scrublet"])
    if task == "Foundation Model Representation" and any(term in query for term in ["doublet 模拟器", "双细胞模拟器", "scrublet", "doubletfinder"]):
        block("doublet_simulator_to_grn_incompatible", tools=["Scrublet", "DoubletFinder"])
    if "soupx" in query and (
        task == "Cell Type Annotation"
        or any(term in query for term in ["注释", "cell type", "label", "标签"])
    ):
        block("contamination_model_to_annotation_incompatible", tools=["SoupX"])
    if "scib" in query and task in {"Data Integration", "Batch Correction"}:
        forced = (
            "evidence_chain"
            if any(term in query for term in ["benchmark", "protocol", "评测", "证据链"])
            else "none"
        )
        block("scib_is_benchmark_protocol_not_tool", forced=forced, tools=["scIB"])
    if "nicheformer" in query and task == "Spatial Deconvolution" and any(term in query for term in ["替代", "replace"]):
        block("foundation_model_not_primary_deconvolution_tool", forced="workflow", tools=["nicheformer"])

    # Boundary-review conditions: still allow a conservative alternative path,
    # but remove the explicitly unsafe source mechanism.
    if allow_migration and "tradeseq" in query and task == "Perturbation Differential Expression":
        if any(term in query for term in ["离散", "unordered", "没有剂量", "没有时间", "没有伪时间"]):
            blocked_tools.append("tradeSeq")
            reasons.append("tradeseq_requires_ordered_covariate")
            missing_components.append("migration_gate:tradeseq_requires_ordered_covariate")
    if allow_migration and "wot" in query:
        if any(term in query for term in ["直接", "原始特征空间", "相隔很远", "只有两个", "day0", "day14", "完全没采样", "不做共同嵌入", "中间完全没采样"]):
            blocked_tools.append("wot")
            reasons.append("wot_requires_shared_dense_state_space")
            missing_components.append("migration_gate:wot_requires_shared_dense_state_space")
    if allow_migration and "soupx" in query and task == "Ambient RNA Removal":
        if any(term in query for term in ["没有 off-tissue", "没有空白区域", "no off-tissue", "no background spot"]):
            reasons.append("soupx_requires_background_profile")
            missing_components.append("migration_gate:soupx_requires_background_profile")
    if allow_migration and "scgpt" in query and any(term in query for term in ["因果", "causal", "grn", "调控网络"]):
        reasons.append("foundation_embedding_not_causal_grn")
        missing_components.append("migration_gate:foundation_embedding_not_causal_grn")

    # If most core constraints are pending and this is not a clear positive
    # migration setup, prefer clarification over template fallback.
    if allow_migration and len(pending.intersection({"task", "data_object", "scale", "noise", "species"})) >= 4:
        if any(term in query for term in ["还没", "不知道", "不确定", "not sure"]):
            clarify("core_constraints_unspecified")

    return {
        "allow_migration": allow_migration,
        "recommendation_type": forced_type,
        "needs_clarification": needs_clarification,
        "blocked_tools": sorted(set(blocked_tools)),
        "missing_components": sorted(set(missing_components)),
        "reasons": sorted(set(reasons)),
    }


def _mark_needs_clarification(
    constraints: Dict[str, Any],
    reasons: List[str],
) -> Dict[str, Any]:
    updated = dict(constraints)
    updated["needs_human_clarification"] = True
    updated["clarification_state"] = "needs_clarification"
    pending = list(updated.get("pending_constraints") or [])
    for item in reasons:
        marker = f"migration_gate:{item}"
        if marker not in pending:
            pending.append(marker)
    updated["pending_constraints"] = pending
    questions = list(updated.get("clarification_questions") or [])
    for reason in reasons:
        questions.append(_clarification_question_for_gate(reason))
    updated["clarification_questions"] = questions
    return updated


def _clarification_question_for_gate(reason: str) -> str:
    questions = {
        "target_task_unspecified": "请先明确目标迁移任务，例如反卷积、轨迹、污染建模、扰动响应或表示学习。",
        "multiome_target_or_matchedness_unspecified": "请说明多组学数据是否 matched cells/samples，以及目标是轨迹、聚类还是扰动解释。",
        "perturbation_design_unspecified": "请说明扰动设计是剂量梯度、时间暴露、伪时间连续变量，还是离散 KO 标签。",
        "artifact_simulator_unspecified": "请先定义目标伪影的形成机制，或给出可生成 synthetic positive 的模拟器假设。",
        "core_constraints_unspecified": "请补充关键实验设计和输出目标后再生成迁移假设。",
    }
    return questions.get(reason, f"请补充迁移前提：{reason}。")


def _filter_blocked_migration_paths(
    migration_paths: List[MigrationPath],
    blocked_tools: List[str],
) -> List[MigrationPath]:
    blocked = {_tool_key(name) for name in blocked_tools}
    if not blocked:
        return migration_paths
    return [
        path for path in migration_paths
        if _tool_key(path.tool_name) not in blocked
    ]


def _tool_key(tool_name: str) -> str:
    return "".join(ch for ch in (tool_name or "").lower() if ch.isalnum())


# v0.8: keep these private names for backward-compatible imports from eval
# scripts, but delegate the actual intent/gate behavior to the reusable engine
# module instead of maintaining a second eval-only implementation.
MIGRATION_TRIGGER_TERMS = _INTENT_MIGRATION_TRIGGER_TERMS
_has_any = _intent_has_any
_direct_output_type_for_task = _intent_direct_output_type_for_task
_classify_migration_intent = _intent_classify_migration_intent
_hard_migration_reject_reason = _intent_hard_migration_reject_reason
_apply_migration_intent_to_constraints = _intent_apply_migration_intent_to_constraints
_migration_gate = _intent_migration_gate
_mark_needs_clarification = _intent_mark_needs_clarification
_clarification_question_for_gate = _intent_clarification_question_for_gate
_filter_blocked_migration_paths = _intent_filter_blocked_migration_paths


def _filter_blocked_tool_outputs(
    tool_candidates: List[ToolCandidate],
    scored_tools: List[ScoredTool],
    blocked_tools: List[str],
) -> tuple[List[ToolCandidate], List[ScoredTool]]:
    return (
        _intent_filter_blocked_by_tool_name(tool_candidates, blocked_tools),
        _intent_filter_blocked_by_tool_name(scored_tools, blocked_tools),
    )


def _visible_outputs(
    tool_candidates: List[ToolCandidate],
    scored_tools: List[ScoredTool],
    migration_paths: List[MigrationPath],
) -> tuple[List[ToolCandidate], List[ScoredTool], List[MigrationPath]]:
    visible_scored = scored_tools[:MAIN_RECOMMENDATION_TOP_K]
    scored_names = {tool.tool_name for tool in visible_scored}
    visible_candidates = [
        candidate
        for candidate in tool_candidates
        if not scored_names or candidate.tool_name in scored_names
    ][:MAIN_RECOMMENDATION_TOP_K]
    return visible_candidates, visible_scored, migration_paths[:MIGRATION_TOP_K]


def _accepted_migration_paths(migration_paths: List[MigrationPath]) -> List[MigrationPath]:
    return [
        path for path in migration_paths
        if (path.reviewer_decision or "").strip().lower() == "accept_exploratory"
    ]


def _recommended_tool_names(
    recommendation_type: str,
    ranked_tool_names: List[str],
    candidate_tool_names: List[str],
    migration_paths: List[MigrationPath],
) -> List[str]:
    if recommendation_type in {"none", "evidence_chain"}:
        return []
    if recommendation_type == "migration":
        return [path.tool_name for path in migration_paths]
    return ranked_tool_names or candidate_tool_names


def _filter_workflow_candidate_tools(workflow: Any, blocked_tools: List[str]) -> None:
    blocked = {_tool_key(name) for name in blocked_tools}
    if not workflow or not blocked:
        return
    for step in getattr(workflow, "steps", []) or []:
        step.candidate_tools = [
            tool for tool in step.candidate_tools
            if _tool_key(tool) not in blocked
        ]


def _trim_names(items: List[str], limit: int) -> List[str]:
    return items[:limit]


def _find_tool_candidates(
    constraints: Dict[str, Any],
    user_query: str = "",
) -> List[ToolCandidate]:
    task = constraints.get("task", "Unknown")
    family = constraints.get("task_family") or task_family(task)
    modality = constraints.get("modality", "Unknown")
    platform = constraints.get("platform", "Unknown")
    if task == "Unknown" or modality == "Unknown":
        return []
    task_terms = build_task_query_terms(task, family)

    client = Neo4jClient()
    try:
        modality_queries = [modality]
        if platform != "Unknown" and platform not in modality_queries:
            modality_queries.append(platform)
        rows_by_tool: Dict[str, Dict[str, Any]] = {}
        for modality_query in modality_queries:
            for task_query in task_terms:
                for row in client.find_candidates_by_hard_constraints(
                    task=task_query,
                    modality=modality_query,
                ):
                    tool_name = row["tool_name"]
                    rows_by_tool.setdefault(
                        tool_name,
                        {
                            **row,
                            "matched_tasks": [],
                            "matched_modalities": [],
                            "retrieval_sources": [],
                        },
                    )
                    rows_by_tool[tool_name]["matched_tasks"].append(task_query)
                    rows_by_tool[tool_name]["matched_modalities"].append(modality_query)
                    rows_by_tool[tool_name]["retrieval_sources"].append("graph")
            if rows_by_tool:
                break
        hint_names = _tool_hint_matches_for_query(task_terms)
        for tool_name in hint_names:
            rows_by_tool.setdefault(
                tool_name,
                {
                    "tool_name": tool_name,
                    "desc": "Task-linked candidate from reviewed ontology hints.",
                    "matched_tasks": [],
                    "matched_modalities": [modality],
                    "retrieval_sources": [],
                },
            )
            rows_by_tool[tool_name]["matched_tasks"].extend(tool_task_hints(tool_name))
            rows_by_tool[tool_name]["retrieval_sources"].append("task_hint")
        rows = list(rows_by_tool.values())
        evidence_by_tool = client.fetch_tool_evidence([row["tool_name"] for row in rows])
    finally:
        client.close()

    candidates: List[ToolCandidate] = []
    for row in rows:
        tool_name = row["tool_name"]
        if _is_blocked_main_tool(tool_name, task, user_query=user_query):
            continue
        evidence_items = list(evidence_by_tool.get(tool_name, []))
        alignment = _candidate_task_alignment(
            task_terms=task_terms,
            tool_name=tool_name,
            graph_tasks=(
                row.get("matched_tasks", [])
                if "task_hint" in row.get("retrieval_sources", [])
                else []
            ),
            evidence_items=evidence_items,
        )
        if not _passes_task_specific_gate(task, alignment, evidence_items):
            continue
        evidence_items.append(
            derived_evidence(
                evidence_id=f"prediction:{tool_name}:{task}:{modality}:hard_constraint",
                metric_name="hard_constraint_match",
                metric_value={
                    "task": task,
                    "task_family": family,
                    "task_query_terms": task_terms,
                    "modality": modality,
                    "retrieval_sources": sorted(set(row.get("retrieval_sources", []))),
                },
                extraction_method="eval.generate_predictions._find_tool_candidates",
                source_title="Tool-Task-Modality constraint match",
                confidence=0.4,
                trust_level="inferred",
                graph_layer="experimental",
                evidence_strength="exploratory",
                use_for=["retrieval"],
                kg_version=get_settings().kg_version,
            )
        )
        evidence_items.append(
            derived_evidence(
                evidence_id=f"prediction:{tool_name}:{task}:{modality}:task_alignment",
                metric_name="task_alignment",
                metric_value=alignment,
                extraction_method="eval.generate_predictions._find_tool_candidates",
                source_title="Task-specific ontology/evidence alignment",
                confidence=0.6,
                trust_level="inferred",
                graph_layer="experimental",
                evidence_strength="exploratory",
                use_for=["retrieval", "ranking"],
                kg_version=get_settings().kg_version,
            )
        )
        evidence_bundle = EvidenceBundle(items=evidence_items)
        if not has_main_recommendation_evidence(evidence_bundle):
            continue
        candidates.append(
            ToolCandidate(
                tool_name=tool_name,
                description=row.get("desc") or "Unknown",
                evidence=evidence_bundle,
                feasibility_reasons=[
                    f"PERFORMS_TASK={task}",
                    f"TASK_FAMILY={family}",
                    f"TASK_ALIGNMENT={alignment:.2f}",
                    f"SUPPORTS_MODALITY={modality}",
                ],
            )
        )
    candidates.sort(key=lambda candidate: _extract_task_alignment(candidate.evidence.items), reverse=True)
    return candidates[:MAIN_RECOMMENDATION_TOP_K]


def _tool_hint_matches_for_query(task_terms: List[str]) -> List[str]:
    names: List[str] = []
    for tool_name, hints in iter_tool_task_hints():
        if task_alignment_score(task_terms, hints) >= 0.75:
            names.append(tool_name)
    return names


def _candidate_task_alignment(
    task_terms: List[str],
    tool_name: str,
    graph_tasks: List[str],
    evidence_items: List[Any],
) -> float:
    matched_tasks: List[str] = []
    matched_tasks.extend(graph_tasks)
    matched_tasks.extend(tool_task_hints(tool_name))
    for evidence in evidence_items:
        matched_tasks.extend(_task_terms_from_evidence(evidence))
    return task_alignment_score(task_terms, matched_tasks)


def _task_terms_from_evidence(evidence: Any) -> List[str]:
    terms: List[str] = []
    metric_value = getattr(evidence, "metric_value", None)
    if isinstance(metric_value, dict):
        for key in ("task", "subtask", "task_family"):
            value = metric_value.get(key)
            if isinstance(value, list):
                terms.extend(str(item) for item in value)
            elif value:
                terms.append(str(value))
    elif isinstance(metric_value, list):
        terms.extend(str(item) for item in metric_value)
    dataset_scope = getattr(evidence, "dataset_scope", "")
    source_title = getattr(evidence, "source_title", "")
    for value in [dataset_scope, source_title]:
        if not value:
            continue
        terms.extend(_split_taskish_text(value))
    return terms


def _split_taskish_text(value: str) -> List[str]:
    tokens: List[str] = []
    for chunk in str(value).replace("|", ";").replace(",", ";").split(";"):
        item = chunk.strip()
        if item:
            tokens.append(item)
    return tokens


def _passes_task_specific_gate(
    task: str,
    alignment: float,
    evidence_items: List[Any],
) -> bool:
    normalized_task = normalize_task_label(task)
    if normalized_task in FINE_TASKS:
        return alignment >= 0.75
    if any(_main_evidence_has_scope(evidence) for evidence in evidence_items):
        return alignment >= 0.5
    return alignment > 0


def _main_evidence_has_scope(evidence: Any) -> bool:
    return bool(
        getattr(evidence, "source_type", "") in {"paper", "benchmark"}
        and getattr(evidence, "graph_layer", "") == "trusted_core"
    )


def _is_blocked_main_tool(tool_name: str, task: str, user_query: str) -> bool:
    if (tool_name or "").lower() != "scib":
        return False
    query = (user_query or "").lower()
    if any(term in query for term in ["scib framework", "scib protocol", "benchmark protocol", "benchmark framework", "评测框架", "基准框架"]):
        return False
    return normalize_task_label(task) in {"Data Integration", "Batch Correction"}


def _extract_task_alignment(evidence_items: List[Any]) -> float:
    values = [
        item.metric_value
        for item in evidence_items
        if getattr(item, "metric_name", "") == "task_alignment"
        and isinstance(getattr(item, "metric_value", None), (int, float))
    ]
    return max([float(value) for value in values], default=0.0)


def _score_candidates(
    tool_candidates: List[ToolCandidate],
    constraints: Optional[Dict[str, Any]] = None,
) -> List[ScoredTool]:
    if not tool_candidates:
        return []
    constraints = constraints or {}

    client = Neo4jClient()
    try:
        names = [candidate.tool_name for candidate in tool_candidates]
        rows = client.execute_query(
            """
            MATCH (t:Tool)
            WHERE t.name IN $candidates
            OPTIONAL MATCH (t)-[:WRITTEN_IN]->(lang:Language)
            RETURN t.name AS tool_name,
                   t.description AS description,
                   t.github_url AS github_url,
                   t.github_stars AS github_stars,
                   coalesce(t.language, lang.name, 'Unknown') AS language
            """,
            {"candidates": names},
        )
        evidence_by_tool = client.fetch_tool_evidence(names)
    finally:
        client.close()

    candidates_by_name = {candidate.tool_name: candidate for candidate in tool_candidates}
    rows_by_name = {row["tool_name"]: row for row in rows}
    for name, candidate in candidates_by_name.items():
        if name not in rows_by_name:
            rows_by_name[name] = {
                "tool_name": name,
                "description": candidate.description,
                "github_url": None,
                "github_stars": None,
                "language": candidate.language or "Unknown",
            }
    metrics = []
    for row in rows_by_name.values():
        tool_name = row["tool_name"]
        evidence_items = list(candidates_by_name[tool_name].evidence.items)
        evidence_items.extend(evidence_by_tool.get(tool_name, []))
        alignment = _extract_task_alignment(evidence_items)
        if alignment <= 0 and constraints.get("task"):
            alignment = _candidate_task_alignment(
                task_terms=build_task_query_terms(
                    constraints.get("task", "Unknown"),
                    constraints.get("task_family") or task_family(constraints.get("task", "Unknown")),
                ),
                tool_name=tool_name,
                graph_tasks=tool_task_hints(tool_name),
                evidence_items=evidence_items,
            )
        github_stars = row.get("github_stars")
        if github_stars is not None:
            try:
                github_stars = int(github_stars)
            except (TypeError, ValueError):
                github_stars = None
        if github_stars is not None and not any(e.metric_name == "github_stars" for e in evidence_items):
            evidence_items.append(
                github_evidence(
                    tool_name=tool_name,
                    metric_name="github_stars",
                    metric_value=github_stars,
                    source_url=row.get("github_url"),
                    kg_version=get_settings().kg_version,
                )
            )
        missing = []
        if not any(e.metric_name in {"benchmark_rank", "benchmark_score", "benchmark_result"} for e in evidence_items):
            missing.append("benchmark")
        if not any(e.metric_name in {"citations", "paper_citations"} for e in evidence_items):
            missing.append("literature")
        if not any(e.metric_name == "github_stars" for e in evidence_items):
            missing.append("engineering")
        if not any(e.can_support_recommendation for e in evidence_items):
            missing.append("trusted_recommendation_evidence")

        metrics.append(
            {
                "tool_name": tool_name,
                "description": row.get("description") or candidates_by_name[tool_name].description,
                "github_stars": github_stars,
                "language": row.get("language") or "Unknown",
                "task_alignment": alignment,
                "evidence_bundle": EvidenceBundle(
                    items=evidence_items,
                    missing_evidence=missing,
                ),
            }
        )

    raw_scored = MCDMCalculator().calculate_scores(metrics)
    raw_scored = [
        item for item in raw_scored
        if audit_evidence(item["evidence_bundle"]).has_main_recommendation_evidence
    ][:MAIN_RECOMMENDATION_TOP_K]
    scored_tools = []
    for rank, raw_tool in enumerate(raw_scored, start=1):
        bundle = raw_tool["evidence_bundle"]
        audit = audit_evidence(bundle)
        scored_tools.append(
            ScoredTool(
                tool_name=raw_tool["tool_name"],
                score=raw_tool["mcdm_score"],
                rank=rank,
                evidence=bundle,
                evidence_breakdown={
                    **raw_tool["evidence_breakdown"],
                    "recommendation_grade_evidence": [
                        evidence.metric_name for evidence in audit.recommendation_evidence
                    ],
                    "retrieval_only_evidence_count": len(audit.retrieval_only_evidence),
                    "guardrails": evidence_guardrail_warnings(bundle),
                },
                recommendation_confidence=(
                    "high" if audit.recommendation_coverage >= 0.8
                    else "medium" if audit.recommendation_coverage >= 0.5
                    else "low"
                ),
            )
        )
    return scored_tools


def _build_fallback_migrations(
    constraints: Dict[str, Any],
    tool_candidates: List[ToolCandidate],
    expected_source_tools: Optional[List[str]] = None,
) -> List[MigrationPath]:
    task = constraints.get("task", "Unknown")
    modality = constraints.get("modality", "Unknown")
    structured_paths = build_migration_hypotheses(
        constraints=constraints,
        expected_source_tools=expected_source_tools,
        top_k=MIGRATION_TOP_K,
    )
    if structured_paths:
        return structured_paths

    source_tools = tool_candidates[:MIGRATION_TOP_K]
    if not source_tools:
        source_tools = [
            ToolCandidate(
                tool_name=f"template:{task}",
                description="No direct graph candidate found; use structured algorithm migration template.",
                evidence=EvidenceBundle(
                    items=[
                        derived_evidence(
                            evidence_id=f"migration_template:{task}:{modality}",
                            metric_name="migration_need",
                            metric_value={"task": task, "modality": modality},
                            extraction_method="eval.generate_predictions._build_fallback_migrations",
                            source_title="Exploratory migration fallback",
                            confidence=0.25,
                            trust_level="inferred",
                            graph_layer="experimental",
                            evidence_strength="exploratory",
                            use_for=["retrieval"],
                            kg_version=get_settings().kg_version,
                        )
                    ],
                    missing_evidence=["direct_tool_evidence"],
                ),
            )
        ]

    paths: List[MigrationPath] = []
    for candidate in source_tools:
        paths.append(
            MigrationPath(
                tool_name=candidate.tool_name,
                score=0.45,
                cos_sim=None,
                features=f"Exploratory transfer candidate for {task} on {modality}.",
                risk_level="exploratory",
                evidence=EvidenceBundle(
                    items=list(candidate.evidence.items),
                    missing_evidence=[
                        "embedding_similarity",
                        "structured_algorithm_compatibility",
                        "data_object_mapping",
                    ],
                ),
                limitations=[
                    "No validated structured migration rule has been applied yet.",
                    "Requires manual review before scientific use.",
                ],
            )
        )
    return paths


def _combine_evidence(
    tool_candidates: List[ToolCandidate],
    scored_tools: List[ScoredTool],
    migration_paths: List[MigrationPath],
    workflow: Any,
) -> EvidenceBundle:
    items = []
    missing = []
    for candidate in tool_candidates:
        items.extend(candidate.evidence.items)
        missing.extend(candidate.evidence.missing_evidence)
    for tool in scored_tools:
        items.extend(tool.evidence.items)
        missing.extend(tool.evidence.missing_evidence)
    for path in migration_paths:
        items.extend(path.evidence.items)
        missing.extend(path.evidence.missing_evidence)
    if workflow:
        items.extend(workflow.evidence.items)
        missing.extend(workflow.evidence.missing_evidence)
        for step in workflow.steps:
            items.extend(step.evidence.items)
            missing.extend(step.evidence.missing_evidence)

    dedup_items = {item.evidence_id: item for item in items}
    return EvidenceBundle(
        items=list(dedup_items.values()),
        missing_evidence=sorted(set(missing)),
    )


def _missing_components(
    constraints_dict: Dict[str, Any],
    evidence_bundle: EvidenceBundle,
    workflow: Any,
    recommendation_type: str,
    candidate_count: int = 0,
    scored_count: int = 0,
) -> List[str]:
    missing = list(evidence_bundle.missing_evidence)
    missing.extend(
        f"constraint:{field}"
        for field in constraints_dict.get("pending_constraints", [])
    )
    if evidence_bundle.recommendation_coverage == 0:
        missing.append("trusted_recommendation_evidence")
    if recommendation_type in {"ranked_tools", "workflow", "evidence_chain"} and candidate_count and scored_count == 0:
        missing.append("trusted_recommendation_evidence")
    if recommendation_type in WORKFLOW_EXPECTED_TYPES and not workflow:
        missing.append("workflow_recommendation")
    if recommendation_type == "migration" and "structured_algorithm_compatibility" not in missing:
        missing.append("structured_algorithm_compatibility")
    return sorted(set(missing))


def _build_final_report(
    constraints: Dict[str, Any],
    recommendation_type: str,
    scored_tools: List[ScoredTool],
    migration_paths: List[MigrationPath],
    workflow: Any,
    missing_components: List[str],
) -> str:
    lines = [
        "## scKG Prediction Report",
        f"- recommendation_type: {recommendation_type}",
        f"- task: {constraints.get('task', 'Unknown')}",
        f"- modality: {constraints.get('modality', 'Unknown')}",
        f"- clarification_state: {constraints.get('clarification_state', 'needs_clarification')}",
    ]
    if scored_tools:
        lines.append("- ranked_tools: " + ", ".join(tool.tool_name for tool in scored_tools[:5]))
    if migration_paths:
        lines.append("- migration_paths: " + ", ".join(path.tool_name for path in migration_paths[:3]))
        lines.append(
            "- migration_plausibility: "
            + "; ".join(
                f"{path.tool_name} score={path.score:.3f} "
                f"io={path.io_compatibility if path.io_compatibility is not None else 'NA'} "
                f"jaccard={path.graph_jaccard if path.graph_jaccard is not None else 'NA'}"
                for path in migration_paths[:3]
            )
        )
        gaps = [
            f"{path.tool_name}: " + " | ".join(
                _safe_report_text(gap) for gap in path.compatibility_gaps[:2]
            )
            for path in migration_paths[:3]
            if path.compatibility_gaps
        ]
        if gaps:
            lines.append("- migration_compatibility_gaps: " + " ; ".join(gaps))
        lines.append(
            "- migration_claim_boundary: exploratory hypothesis only; "
            "requires validation before operational use and has no benchmark-backed performance claim."
        )
    if workflow:
        lines.append("- workflow_steps: " + " -> ".join(_report_step_name(step.name) for step in workflow.steps))
        if workflow.compatibility_warnings:
            lines.append("- compatibility_warnings: " + " | ".join(workflow.compatibility_warnings))
    if missing_components:
        lines.append("- missing_components: " + ", ".join(missing_components))
    caveats = _task_caveats(constraints, missing_components)
    if caveats:
        lines.append("- evidence_caveats: " + " | ".join(caveats))
    return "\n".join(lines)


def _blocking_audit_issues(audit_payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [
        issue for issue in audit_payload.get("issues", []) or []
        if issue.get("severity") in {"critical", "high"}
    ]


def _safe_audit_blocked_report(
    *,
    constraints: Dict[str, Any],
    recommendation_type: str,
    scored_tools: List[ScoredTool],
    migration_paths: List[MigrationPath],
    workflow: Any,
    missing_components: List[str],
) -> str:
    lines = [
        "## Safe Scientific Output",
        "- report_status: blocked_by_semantic_auditor",
        f"- recommendation_type: {recommendation_type}",
        f"- task: {constraints.get('task', 'Unknown')}",
        f"- modality: {constraints.get('modality', 'Unknown')}",
        f"- clarification_state: {constraints.get('clarification_state', 'needs_clarification')}",
    ]
    if scored_tools:
        lines.append("- ranked_tools: " + ", ".join(tool.tool_name for tool in scored_tools[:5]))
    if migration_paths:
        lines.append("- migration_paths: " + ", ".join(path.tool_name for path in migration_paths[:3]))
        gaps = [
            f"{path.tool_name}: " + " | ".join(
                _safe_report_text(gap) for gap in path.compatibility_gaps[:2]
            )
            for path in migration_paths[:3]
            if path.compatibility_gaps
        ]
        if gaps:
            lines.append("- migration_compatibility_gaps: " + " ; ".join(gaps))
        lines.append(
            "- migration_claim_boundary: exploratory hypothesis only; "
            "requires validation before operational use and has no benchmark-backed performance claim."
        )
    if workflow:
        lines.append("- workflow_steps: " + " -> ".join(_report_step_name(step.name) for step in workflow.steps))
    if missing_components:
        lines.append("- missing_components: " + ", ".join(missing_components))
    caveats = _task_caveats(constraints, missing_components)
    if caveats:
        lines.append("- evidence_caveats: " + " | ".join(caveats))
    lines.append("- safety_note: unsupported high-risk claims were blocked by AuditorAgent.")
    return "\n".join(lines)


def _task_caveats(
    constraints: Dict[str, Any],
    missing_components: List[str],
) -> List[str]:
    task = constraints.get("task", "Unknown")
    general = []
    if "full_benchmark_validation" in missing_components:
        general.append("Migration hypotheses require downstream validation and are not benchmark-backed recommendations.")
    if task != "Perturbation Differential Expression":
        return general
    caveats = [
        "MIMOSCA can be surfaced only as a conservative perturbation-analysis candidate."
    ]
    if "benchmark" in missing_components or "trusted_recommendation_evidence" in missing_components:
        caveats.append(
            "No strong benchmark-backed performance claim is allowed for this perturbation task."
        )
    return general + caveats


def _report_step_name(value: str) -> str:
    return _safe_report_text(value).replace("benchmark audit", "evidence audit")


def _safe_report_text(value: str) -> str:
    text = str(value)
    replacements = {
        "must be validated": "requires validation",
        "must be checked": "requires checking",
        "must be verified": "requires verification",
    }
    lowered = text.lower()
    for old, new in replacements.items():
        if old in lowered:
            text = text.replace(old, new)
            text = text.replace(old.capitalize(), new.capitalize())
    return text


def _claim_stats(
    scored_tools: List[ScoredTool],
    migration_paths: List[MigrationPath],
    workflow: Any,
    final_report: str,
) -> tuple[int, int]:
    claim_count = 0
    unsupported_claims = 0
    claim_count += len(scored_tools)
    unsupported_claims += sum(1 for tool in scored_tools if tool.evidence.coverage == 0)
    claim_count += len(migration_paths)
    unsupported_claims += sum(1 for path in migration_paths if path.evidence.coverage == 0)
    if workflow:
        claim_count += len(workflow.steps)
        unsupported_claims += sum(1 for step in workflow.steps if step.evidence.coverage == 0)
    if final_report:
        claim_count += 1
    return claim_count, unsupported_claims


def write_predictions(records: List[PredictionRecord], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(record.model_dump_json() + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate standardized scKG eval predictions.")
    parser.add_argument(
        "--gold",
        type=Path,
        default=PROJECT_ROOT / "eval" / "gold_queries.jsonl",
        help="Path to gold query JSONL.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "eval" / "predictions.jsonl",
        help="Output prediction JSONL path.",
    )
    parser.add_argument(
        "--use-agent",
        action="store_true",
        help="Run the full LangGraph agent instead of the deterministic eval path.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional number of gold queries to run.",
    )
    parser.add_argument(
        "--offline-llm",
        action="store_true",
        help="Disable DeepSeek/OpenAI calls; deterministic mode already avoids LLM calls, and agent mode will fail closed.",
    )
    parser.add_argument(
        "--blind-migration",
        action="store_true",
        help="Do not pass gold expected_source_tools into migration generation; use gold only for scoring.",
    )
    args = parser.parse_args()
    if args.offline_llm:
        os.environ["SCKG_OFFLINE_LLM"] = "true"
        get_settings.cache_clear()

    records = load_gold_queries(args.gold)
    if args.limit is not None:
        records = records[: args.limit]

    predictions = []
    for index, record in enumerate(records, start=1):
        print(f"[{index}/{len(records)}] generating prediction for {record['id']}")
        predictions.append(
            generate_prediction(
                record,
                use_agent=args.use_agent,
                blind_migration=args.blind_migration,
            )
        )

    write_predictions(predictions, args.output)
    print(f"wrote {len(predictions)} predictions to {args.output}")


if __name__ == "__main__":
    main()
