from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, TypeVar

from core.task_ontology import task_family


MIGRATION_TRIGGER_TERMS = [
    "找不到",
    "没有现成",
    "没有成熟",
    "借用",
    "借鉴",
    "借到",
    "迁移",
    "可迁移",
    "创新",
    "算法思想",
    "建模思想",
    "机制假设",
    "机制迁移",
    "研发路线",
    "研发假设",
    "迁移假设",
    "探索性路线",
    "做探索",
    "做机制假设",
    "method transfer",
    "transfer",
    "borrow idea",
    "adapt mechanism",
    "migration hypothesis",
    "no direct tool",
    "没有直接工具",
    "没有直接方法",
    "没有标准工具",
    "no mature tool",
    "no existing tool",
    "not a standard workflow",
]


def has_any(text: str, terms: Sequence[str]) -> bool:
    lowered = text.lower()
    return any(term.lower() in lowered for term in terms)


def has_negated_causal_scope(text: str) -> bool:
    return has_any(
        text,
        [
            "不做因果",
            "不打算解释因果",
            "不推导因果",
            "不做 grn",
            "不做grn",
            "不做 causal",
            "不做 causal grn",
            "不推导 causal",
            "不推导 causal grn",
            "不推导 grn",
            "not infer causal",
            "not use it to infer causal",
            "not doing causal",
            "feature extraction only",
        ],
    )


def direct_output_type_for_task(task: str) -> str:
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


def classify_migration_intent(
    user_query: str,
    constraints: Dict[str, Any],
) -> Dict[str, Any]:
    """Classify exploratory migration intent without using an LLM.

    The classifier is intentionally conservative: it can route to migration,
    normal recommendation/workflow, evidence lookup, rejection, or clarification.
    It should not decide that a migration is scientifically valid; it only
    decides which downstream deterministic pathway should inspect the query.
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
        "证据等级",
        "主论文",
        "主论文 doi",
        "主论文doi",
        "官方文档",
        "适用范围",
        "critique",
        "局限性",
        "publication lookup",
        "publication evidence",
        "查某个工具的主论文",
        "比较几篇 benchmark",
        "证据强弱",
    ]
    if has_any(query, evidence_chain_terms):
        return decision("evidence_chain", 0.94, "explicit_evidence_or_protocol_lookup")

    if has_any(query, ["github stars", "github star", "github"]) and has_any(
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
        "不要算法迁移",
        "不要生成算法迁移",
        "不是在做创新迁移",
        "不是做创新迁移",
        "不做创新迁移",
        "不是要迁移假设",
        "not asking for migration",
        "not a migration problem",
        "not looking for migration",
    ]
    if has_any(query, direct_non_migration_terms):
        if task == "Workflow Compatibility" or has_any(query, ["seuratobject", "h5ad", "对象字段", "object conversion"]):
            return decision("evidence_chain", 0.95, "explicit_workflow_compatibility_not_migration")
        if has_any(query, ["标准", "常规", "主工具", "工具推荐", "standard", "main tool"]):
            return decision("direct_recommendation", 0.93, "explicit_direct_recommendation_not_migration")
        return decision("workflow", 0.9, "explicit_not_migration")

    if has_any(query, ["seuratobject", "h5ad", "对象字段", "object conversion", "workflow compatibility"]):
        return decision("evidence_chain", 0.92, "workflow_object_compatibility")

    hard_reject = hard_migration_reject_reason(query, task)
    if hard_reject:
        return decision("reject", 0.93, hard_reject)

    if has_any(query, ["scrublet", "doubletfinder"]) and has_any(query, ["没有 synthetic", "没有 simulator", "没有自定义伪影模拟器", "no synthetic", "no simulator", "without synthetic", "without simulator"]):
        return decision("reject", 0.9, "synthetic_positive_required_for_anomaly_transfer")

    if has_any(query, ["scvi", "scvi-tools"]) and has_any(query, MIGRATION_TRIGGER_TERMS + ["migration"]):
        subclass_missing = has_any(
            query,
            ["只说了套件名", "没有说", "没说", "未说明", "没有说明", "不指定", "未指定", "没有指定"],
        )
        if subclass_missing or not has_any(query, ["multivi", "totalvi", "multi vi", "total vi", "具体子类", "损失函数", "loss"]):
            return decision("clarification", 0.9, "scvi_subclass_unspecified")

    clarification_terms = [
        "还没决定",
        "还没确定",
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
        "没有说明是否",
        "没说明",
        "没说",
        "没讲是做",
        "还没定义",
        "未定义",
        "not sure",
        "don't know",
    ]
    if has_any(query, clarification_terms):
        return decision("clarification", 0.9, "migration_target_or_design_unspecified")

    direct_standard_terms = [
        "常规",
        "标准",
        "主工具",
        "工具推荐",
        "现成工具推荐",
        "匹配 scrna reference",
        "matched scrna reference",
        "standard analysis",
        "main tool",
    ]
    negates_direct_request = has_any(query, [
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
        has_any(query, direct_standard_terms)
        and not has_any(query, MIGRATION_TRIGGER_TERMS)
        and not negates_direct_request
    ):
        return decision("direct_recommendation", 0.85, "standard_tool_or_workflow_request")

    migration_score = 0.0
    if has_any(query, MIGRATION_TRIGGER_TERMS):
        migration_score += 1.0
        reasons.append("explicit_migration_language")
    if has_any(query, ["不是找现成包", "不是找现成工具", "not looking for a package", "not looking for a tool"]):
        migration_score += 1.0
        reasons.append("not_direct_package_request")

    if has_any(query, ["连续浓度", "浓度梯度", "剂量梯度", "刺激强度", "连续读数", "响应曲线", "dose response", "dose-response"]):
        migration_score += 1.5
        task_hint = "Perturbation Differential Expression"
        modality_hint = "scRNA-seq" if modality == "Unknown" else modality_hint
        reasons.append("ordered_perturbation_response_curve")
    if has_any(
        query,
        [
            "mimosca",
            "additive perturbation",
            "perturbation coefficient",
            "additive perturbation coefficient",
            "扰动效应",
            "扰动系数",
            "离散扰动标签",
            "处理组",
            "对照组",
            "加性",
        ],
    ):
        migration_score += 1.4
        task_hint = "Perturbation Differential Expression"
        modality_hint = "scRNA-seq" if modality == "Unknown" else modality_hint
        reasons.append("additive_perturbation_effect_transfer")
    if has_any(query, ["空白区域", "背景信号", "背景谱", "玻片背景", "组织外 spot", "污染扣除", "background signal", "off-tissue"]):
        migration_score += 1.5
        task_hint = "Ambient RNA Removal"
        modality_hint = "Spatial Transcriptomics"
        reasons.append("spatial_background_contamination_modeling")
    if has_any(query, ["空间背景", "spatial contamination", "ambient profile subtraction", "spatial ambient", "marker preservation"]):
        migration_score += 1.5
        task_hint = "Ambient RNA Removal"
        modality_hint = "Spatial Transcriptomics"
        reasons.append("spatial_background_contamination_modeling")
    if has_any(query, ["共同低维轴", "共同因子", "共同漂移", "多个 view", "扰动造成的共同", "共同轴", "joint latent", "latent perturbation", "factor drift", "shared sparse latent", "shared sparse latent factors"]):
        migration_score += 1.4
        task_hint = "Multiome Integration"
        modality_hint = "scRNA-seq+scATAC-seq" if modality == "Unknown" else modality_hint
        reasons.append("multi_view_latent_perturbation_axis")
    if has_any(query, ["cca/rpca/wnn", "cca", "rpca", "wnn", "anchor matching", "anchor", "锚点匹配"]):
        migration_score += 1.4
        task_hint = "Data Integration"
        if has_any(query, ["跨模态", "multiome", "rna/atac", "scatac", "atac"]):
            modality_hint = "scRNA-seq+scATAC-seq"
        elif modality == "Unknown":
            modality_hint = "scRNA-seq"
        reasons.append("seurat_anchor_matching_transfer")
    if has_any(query, ["共享隐变量", "隐变量漂移", "shared latent", "latent drift"]):
        migration_score += 1.4
        task_hint = "Multiome Integration"
        if has_any(query, ["adt", "蛋白"]):
            modality_hint = "CITE-seq"
        elif modality == "Unknown":
            modality_hint = "scRNA-seq+scATAC-seq"
        reasons.append("multi_view_shared_latent_shift")
    if has_any(query, ["模拟出阳性", "模拟阳性", "人工阳性", "synthetic positive", "风险分数", "risk score", "邻域富集", "index hopping"]):
        migration_score += 1.4
        task_hint = "QC"
        modality_hint = "scRNA-seq" if modality == "Unknown" else modality_hint
        reasons.append("synthetic_positive_artifact_scoring")
    if has_any(query, ["成本矩阵", "代价矩阵", "联合代价", "融合代价", "joint cost", "cost matrix", "时间、空间和表达", "time, space and expression", "fused cost", "物理距离"]):
        migration_score += 1.5
        task_hint = "Optimal Transport Trajectory"
        if "空间" in raw_query or "spatial" in query:
            modality_hint = "Spatial Transcriptomics"
        reasons.append("fused_cost_transport_mapping")
    if has_any(query, ["特征提取器", "feature extractor", "feature encoder", "frozen encoder", "embedding", "嵌入", "表示空间", "linear probing", "linear probe"]) and (
        has_any(query, ["cellplm", "scgpt", "foundation model", "大模型"])
        or has_any(query, ["漂移", "偏移", "位移", "整体偏移", "drift", "处理前后", "疾病组", "对照组", "perturbation", "不打算解释因果", "不解释因果"])
    ):
        migration_score += 1.4
        task_hint = "Foundation Model Representation"
        modality_hint = "scRNA-seq" if modality == "Unknown" else modality_hint
        reasons.append("foundation_embedding_drift_feature_extraction")
    if has_any(query, ["spliced/unspliced", "spliced and unspliced", "spliced 和 unspliced", "spliced 和unspliced", "spliced layers", "unspliced layers"]) and has_any(
        query,
        ["scvelo", "rna velocity", "velocity", "kinetic", "ode", "directionality", "动态状态", "速度"],
    ):
        migration_score += 1.4
        task_hint = "RNA Velocity"
        modality_hint = "scRNA-seq" if modality == "Unknown" else modality_hint
        reasons.append("splicing_layer_velocity_transfer")
    if has_any(query, ["可靠轨迹", "lineage weights", "lineage probability", "不同分支", "响应形状", "外部 pseudotime"]):
        migration_score += 1.3
        task_hint = "Trajectory Differential Expression"
        modality_hint = "scRNA-seq" if modality == "Unknown" else modality_hint
        reasons.append("trajectory_supplied_response_shape")
    if has_any(query, ["状态转移 kernel", "transition kernel", "fate mapping", "fate probability", "absorbing-state", "absorbing state", "吸收概率", "终态假设", "终态命运", "命运假设"]):
        migration_score += 1.4
        task_hint = "Trajectory Inference"
        modality_hint = "scRNA-seq" if modality == "Unknown" else modality_hint
        reasons.append("transition_kernel_fate_mapping")
    niche_specific = has_any(
        query,
        ["niche-aware", "niche 表征", "niche表征", "微环境", "空间邻域", "spatial neighborhood", "microenvironment"],
    )
    spatial_mechanism_comparison = has_any(query, ["机制能不能给出研发路线", "机制比较"]) and has_any(
        query,
        ["空间", "spatial", "niche", "微环境"],
    )
    if niche_specific or spatial_mechanism_comparison:
        migration_score += 1.3
        task_hint = "Foundation Model Representation"
        if "空间" in raw_query or "spatial" in query:
            modality_hint = "Spatial Transcriptomics"
        reasons.append("mechanism_comparison_for_spatial_representation")
    if has_any(
        query,
        [
            "reference-based annotation",
            "参考注释思想",
            "参考标签",
            "reference label",
            "reference atlas",
            "reference correlation",
            "reference classifier",
            "reference similarity",
            "label relation",
            "label relationship",
            "相似性打分机制",
            "不完全匹配",
            "跨组织参考",
        ],
    ):
        migration_score += 1.3
        task_hint = "Cell Type Annotation"
        modality_hint = "scRNA-seq" if modality == "Unknown" else modality_hint
        reasons.append("reference_annotation_similarity_transfer")
    if has_any(
        query,
        [
            "embedding-level correction",
            "embedding correction",
            "soft clustering correction",
            "low-dimensional",
            "low dimensional",
            "fast alignment prototype",
            "批次校正",
            "跨样本对齐原型",
            "快速队列对齐",
            "队列对齐",
            "fast alignment",
            "batch-corrected embedding",
            "biology preservation",
        ],
    ):
        migration_score += 1.4
        task_hint = "Data Integration"
        modality_hint = "scRNA-seq" if modality == "Unknown" else modality_hint
        reasons.append("embedding_correction_transfer")
    if has_any(
        query,
        [
            "贝叶斯混合",
            "混合信号",
            "混合计数",
            "混合细胞组成",
            "多个细胞类型的混合",
            "区域聚合",
            "非标准空间",
            "reference-based count mixture",
            "spatial bin",
            "mixture model",
            "mixture signal",
            "mixed count",
            "mixed abundance",
            "bayesian count mixture",
            "cosmx",
        ],
    ):
        migration_score += 1.4
        task_hint = "Spatial Deconvolution"
        if "空间" in raw_query or "spatial" in query:
            modality_hint = "Spatial Transcriptomics"
        reasons.append("spatial_mixture_model_transfer")
    if has_any(query, ["wot", "最优传输", "optimal transport"]) and has_any(
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


def hard_migration_reject_reason(query: str, task: str) -> Optional[str]:
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
        (["harmony", "batch-corrected embedding", "整合后的 embedding", "整合后的 pca"], ["perturbation effect coefficient", "扰动系数", "每个基因的 perturbation"], "embedding_to_perturbation_coefficient_incompatible"),
        (["cell2location", "空间丰度后验", "空间细胞组成后验", "反卷积后验", "abundance posterior"], ["fate probability", "命运选择概率", "命运概率"], "deconvolution_posterior_to_fate_probability_incompatible"),
        (["scrublet", "doubletfinder", "doublet score", "doublet 分数"], ["fate probability", "命运选择概率", "命运概率"], "doublet_score_to_fate_probability_incompatible"),
        (["doublet 模拟器", "双细胞模拟器", "scrublet", "doubletfinder"], ["gene regulatory network", "grn", "调控网络", "因果"], "doublet_simulator_to_grn_incompatible"),
        (["wot", "waddington-ot", "waddington ot"], ["不同批细胞", "不做共同空间", "不做共同嵌入", "直接"], "wot_requires_shared_dense_state_space"),
        (["benchmark 框架", "benchmark framework", "scib"], ["批次校正算法", "batch correction algorithm", "当作"], "benchmark_framework_not_method"),
    ]
    for source_terms, target_terms, reason in incompatible_patterns:
        if has_any(query, source_terms) and has_any(query, target_terms):
            return reason
    if task == "Data Integration" and has_any(query, ["benchmark 框架本身", "scib"]) and has_any(query, ["当作", "运行"]):
        return "benchmark_framework_not_method"
    return None


def apply_migration_intent_to_constraints(
    constraints: Dict[str, Any],
    user_query: str,
) -> Dict[str, Any]:
    decision = classify_migration_intent(user_query, constraints)
    updated = dict(constraints)
    task_hint = decision.get("task_hint")
    modality_hint = decision.get("modality_hint")
    if task_hint and (
        updated.get("task") in {None, "", "Unknown", "Workflow Planning"}
        or decision["intent"] == "migration"
    ):
        updated["task"] = task_hint
        updated["task_family"] = task_family(task_hint)
    if modality_hint and updated.get("modality") in {None, "", "Unknown", "scRNA-seq"}:
        if modality_hint != "scRNA-seq" or updated.get("modality") in {None, "", "Unknown"}:
            updated["modality"] = modality_hint
    if decision["intent"] in {"migration", "clarification"}:
        updated["strictness"] = "exploratory"
    updated["migration_intent"] = decision["intent"]
    updated["migration_intent_confidence"] = decision["confidence"]
    updated["migration_intent_reasons"] = decision["reasons"]
    updated["migration_query_text"] = user_query or ""
    return updated


def migration_gate(
    user_query: str,
    constraints: Dict[str, Any],
    recommendation_type: str,
) -> Dict[str, Any]:
    query = (user_query or "").lower()
    task = constraints.get("task", "Unknown")
    pending = set(constraints.get("pending_constraints") or [])
    reasons: List[str] = []
    blocked_tools: List[str] = []
    missing_components: List[str] = []
    forced_type: Optional[str] = None
    allow_migration = recommendation_type == "migration"
    needs_clarification = False
    intent_decision = classify_migration_intent(user_query, constraints)
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
            forced=direct_output_type_for_task(task) if intent == "direct_recommendation" else "workflow",
        )
    elif intent == "migration":
        allow_migration = True

    if has_any(query, ["workflow compatibility", "object conversion", "seuratobject", "h5ad", "对象字段", "对象转换"]):
        block("workflow_compatibility_not_migration", forced="evidence_chain")
    if has_any(query, ["benchmark framework", "benchmark protocol", "评测协议", "评测框架"]):
        block("benchmark_protocol_not_migration", forced="evidence_chain")
    if "empirically proven best" in query or "best tool" in query:
        block("strong_claim_requires_reviewed_benchmark", forced="none")

    if allow_migration and task == "Unknown":
        clarify("target_task_unspecified")
    if allow_migration and task == "Multiome Integration" and has_any(query, ["不知道", "not sure", "don't know", "不确定", "还没确定"]):
        clarify("multiome_target_or_matchedness_unspecified", tools=["wot"])
    if "scvi" in query and task == "Multiome Integration" and intent != "evidence_chain":
        has_specific_subclass = has_any(
            query,
            ["multivi", "totalvi", "multi vi", "total vi", "具体子类", "损失函数", "loss"],
        )
        subclass_missing = has_any(
            query,
            ["只说了套件名", "没有说", "没说", "未说明", "没有说明", "不指定", "未指定", "没有指定"],
        )
        if subclass_missing or not has_specific_subclass:
            clarify("scvi_subclass_unspecified", tools=["scvi-tools"])
    if allow_migration and task == "Cell Type Annotation" and has_any(query, ["没有说明是否有可信 reference", "没有说明是否有 reference", "没有可信 reference", "没有说明是否有可信 reference atlas"]):
        clarify("reference_atlas_unspecified", tools=["SingleR", "CellTypist"])
    if allow_migration and task == "Cell Type Annotation" and has_any(
        query,
        ["没有说明", "没说明", "没说", "未说明", "不确定"],
    ) and has_any(
        query,
        ["reference atlas", "reference", "标签层级", "label hierarchy", "domain shift", "是否可信", "可信"],
    ):
        clarify("reference_atlas_or_label_hierarchy_unspecified", tools=["SingleR", "CellTypist"])
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
                "处理和对照",
                "处理和对照标签",
                "对照",
                "刺激强度",
                "连续读数",
                "perturbation label",
            ]
        )
        if "还没说" in query or "没说" in query or not has_design:
            clarify("perturbation_design_unspecified", tools=["tradeSeq"])
        has_ordered_covariate = has_any(
            query,
            [
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
                "连续",
                "连续读数",
            ],
        )
        discrete_perturbation = has_any(
            query,
            [
                "离散扰动",
                "离散",
                "ko",
                "knockout",
                "crispr",
                "处理组",
                "处理和对照",
                "处理和对照标签",
                "对照组",
                "对照标签",
                "treatment/control",
                "treatment vs control",
            ],
        )
        if discrete_perturbation and not has_ordered_covariate:
            blocked_tools.append("tradeSeq")
            reasons.append("tradeseq_requires_ordered_covariate")
            missing_components.append("migration_gate:tradeseq_requires_ordered_covariate")
    if allow_migration and task == "QC" and has_any(query, ["还没定义", "未定义", "没有定义", "没有办法模拟阳性", "没有自定义伪影模拟器"]):
        clarify("artifact_simulator_unspecified", tools=["Scrublet", "DoubletFinder"])
    if "scanpy" in query and intent != "evidence_chain" and has_any(
        query,
        ["工具箱", "utility", "utilities", "api", "通用流程", "底层包", "workflow utilities"],
    ):
        block("scanpy_toolkit_not_discrete_migration_algorithm", tools=["Scanpy"])

    if "scvelo" in query and task == "Ambient RNA Removal":
        block("velocity_to_ambient_incompatible", tools=["scVelo"])
    if "cell2location" in query and task == "RNA Velocity":
        block("deconvolution_to_velocity_incompatible", tools=["cell2location"])
    if "mofa2" in query and task == "Doublet Detection":
        block("factor_model_to_doublet_incompatible", tools=["MOFA2"])
    if task == "Doublet Detection" and has_any(query, ["反卷积", "deconvolution", "cell2location"]):
        block("deconvolution_to_doublet_incompatible", tools=["cell2location"])
    if "scrublet" in query and task == "Spatial Deconvolution":
        block("doublet_detection_to_spatial_deconvolution_incompatible", tools=["Scrublet"])
    if task == "Foundation Model Representation" and has_any(query, ["doublet 模拟器", "双细胞模拟器", "scrublet", "doubletfinder"]):
        block("doublet_simulator_to_grn_incompatible", tools=["Scrublet", "DoubletFinder"])
    if "soupx" in query and (task == "Cell Type Annotation" or has_any(query, ["注释", "cell type", "label", "标签"])):
        block("contamination_model_to_annotation_incompatible", tools=["SoupX"])
    if "harmony" in query and task == "Perturbation Differential Expression" and has_any(query, ["coefficient", "扰动系数", "每个基因"]):
        block("embedding_to_perturbation_coefficient_incompatible", tools=["Harmony"])
    if task == "Trajectory Inference" and has_any(query, ["cell2location", "空间丰度后验", "空间细胞组成后验", "反卷积后验", "abundance posterior"]) and has_any(query, ["fate probability", "命运选择概率", "命运概率"]):
        blocked_tools.append("cell2location")
        reasons.append("deconvolution_posterior_to_fate_probability_incompatible")
        missing_components.append("migration_gate:deconvolution_posterior_to_fate_probability_incompatible")
    if task == "Trajectory Inference" and has_any(query, ["scrublet", "doubletfinder", "doublet score", "doublet 分数"]) and has_any(query, ["fate probability", "命运选择概率", "命运概率"]):
        block("doublet_score_to_fate_probability_incompatible", tools=["Scrublet", "DoubletFinder"])
    if task == "Trajectory Inference" and has_any(
        query,
        ["cellrank", "fate probability", "命运概率", "命运选择概率"],
    ) and (
        has_any(query, ["没有 transition kernel", "no transition kernel", "without transition kernel", "缺少 transition kernel"])
        or (has_any(query, ["umap"]) and has_any(query, ["只拿", "只有", "仅", "only", "alone"]))
    ):
        block("cellrank_requires_legitimate_transition_kernel", tools=["CellRank"])
    if "scib" in query and task in {"Data Integration", "Batch Correction"}:
        forced = "evidence_chain" if has_any(query, ["benchmark", "protocol", "评测", "证据链"]) else "none"
        block("scib_is_benchmark_protocol_not_tool", forced=forced, tools=["scIB"])
    if "nicheformer" in query and task == "Spatial Deconvolution" and has_any(
        query,
        ["替代", "replace", "反卷积", "deconvolution", "细胞丰度", "abundance"],
    ):
        block("foundation_model_not_primary_deconvolution_tool", forced="workflow", tools=["nicheformer"])

    if task == "RNA Velocity" and intent != "evidence_chain" and has_any(query, ["scvelo", "rna velocity", "速度"]):
        has_splicing_layers = has_any(
            query,
            [
                "spliced/unspliced",
                "spliced and unspliced",
                "spliced",
                "unspliced",
                "剪接",
                "未剪接",
            ],
        )
        explicit_missing_layers = has_any(
            query,
            [
                "没有 spliced",
                "没有 unspliced",
                "无 spliced",
                "无 unspliced",
                "without spliced",
                "without unspliced",
                "no spliced",
                "no unspliced",
                "ordinary count",
                "普通 count",
                "普通表达矩阵",
                "expression-only",
                "只有表达",
            ],
        )
        if explicit_missing_layers:
            block("scvelo_requires_spliced_unspliced_layers", tools=["scVelo"])
        elif "scvelo" in query and not has_splicing_layers:
            clarify("splicing_layers_unspecified", tools=["scVelo"])

    if "harmony" in query and intent != "evidence_chain" and has_any(
        query,
        [
            "raw count",
            "raw counts",
            "原始 count",
            "原始 counts",
            "原始计数",
            "生成式计数",
            "generative count",
            "还原 count",
            "还原 counts",
        ],
    ):
        block("harmony_embedding_only_not_raw_count_generative", tools=["Harmony"])

    if "seurat" in query and intent != "evidence_chain" and has_any(
        query,
        [
            "通用优越",
            "通用最优",
            "万能",
            "overall best",
            "generic superiority",
            "universally superior",
            "always best",
            "always-best",
            "默认用它",
        ],
    ):
        if not has_any(query, ["不把", "不说成", "不要把", "不要说成", "不要将", "不是", "not "]):
            block("seurat_anchor_scope_required", tools=["Seurat"])

    if task == "Foundation Model Representation" and intent != "evidence_chain" and "cell2location" in query:
        comparator_terms = [
            "对照",
            "比较",
            "comparator",
            "baseline",
            "control",
            "机制比较",
        ]
        fm_source_terms = [
            "特征源",
            "encoder",
            "feature extractor",
            "embedding source",
            "大模型来源",
            "foundation source",
        ]
        if has_any(query, fm_source_terms) and not has_any(query, comparator_terms):
            block("cell2location_is_comparator_not_foundation_encoder", tools=["cell2location"])

    if "tradeseq" in query and intent != "evidence_chain":
        if has_any(query, ["离散", "unordered", "没有剂量", "没有时间", "没有伪时间"]):
            block("tradeseq_requires_ordered_covariate", tools=["tradeSeq"])
    if intent != "evidence_chain" and ("wot" in query or "waddington" in query):
        if has_any(query, ["直接", "原始特征空间", "相隔很远", "只有两个", "day0", "day14", "完全没采样", "不做共同嵌入", "中间完全没采样", "不同批细胞"]):
            block("wot_requires_shared_dense_state_space", tools=["wot"])
    if intent != "evidence_chain" and "cellrank" in query:
        has_kernel = has_any(
            query,
            [
                "transition kernel",
                "合法 kernel",
                "velocity kernel",
                "pseudotime kernel",
                "转移核",
                "速度核",
                "伪时间",
            ],
        )
        lacks_kernel = has_any(
            query,
            [
                "只有 umap",
                "仅有 umap",
                "没有 kernel",
                "无 kernel",
                "no kernel",
                "without kernel",
                "umap only",
            ],
        )
        if lacks_kernel or not has_kernel:
            block("cellrank_requires_legitimate_transition_kernel", tools=["CellRank"])
    if allow_migration and "soupx" in query and task == "Ambient RNA Removal":
        if has_any(query, ["没有 off-tissue", "没有空白区域", "no off-tissue", "no background spot"]):
            reasons.append("soupx_requires_background_profile")
            missing_components.append("migration_gate:soupx_requires_background_profile")
    if intent != "evidence_chain" and has_any(query, ["scgpt", "cellplm", "nicheformer", "foundation model", "大模型"]):
        causal_direct = has_any(
            query,
            [
                "直接推导因果",
                "直接恢复因果",
                "直接推 grn",
                "直接推导 grn",
                "因果调控网络",
                "causal grn",
                "causal gene regulatory",
                "causal regulatory",
                "gene regulatory network",
                "recover causal",
                "infer causal",
                "调控网络",
            ],
        )
        if causal_direct and not has_negated_causal_scope(query):
            block(
                "foundation_embedding_not_causal_grn",
                tools=["scGPT", "CellPLM", "nicheformer"],
            )
        elif has_any(query, ["因果", "causal", "grn", "调控网络"]):
            reasons.append("foundation_embedding_not_causal_grn")
            missing_components.append("migration_gate:foundation_embedding_not_causal_grn")

    if intent != "evidence_chain" and task in {"QC", "Doublet Detection"} and has_any(query, ["scrublet", "doubletfinder"]):
        missing_simulator = has_any(
            query,
            [
                "没有 synthetic",
                "没有 simulator",
                "没有自定义伪影模拟器",
                "no synthetic",
                "no simulator",
                "without synthetic",
                "without simulator",
            ],
        )
        if missing_simulator or has_any(query, ["通用 qc", "常规 qc", "generic qc", "常规过滤", "general filter"]) and not has_any(
            query,
            ["synthetic", "模拟", "人工阳性", "simulator", "阳性"],
        ):
            block("synthetic_positive_required_for_anomaly_transfer", tools=["Scrublet", "DoubletFinder"])

    if allow_migration and len(pending.intersection({"task", "data_object", "scale", "noise", "species"})) >= 4:
        if has_any(query, ["还没", "不知道", "不确定", "not sure"]):
            clarify("core_constraints_unspecified")

    return {
        "allow_migration": allow_migration,
        "recommendation_type": forced_type,
        "needs_clarification": needs_clarification,
        "blocked_tools": sorted(set(blocked_tools), key=lambda item: item.lower()),
        "missing_components": sorted(set(missing_components)),
        "reasons": sorted(set(reasons)),
    }


def mark_needs_clarification(
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
        questions.append(clarification_question_for_gate(reason))
    updated["clarification_questions"] = questions
    return updated


def clarification_question_for_gate(reason: str) -> str:
    questions = {
        "target_task_unspecified": "请先明确目标迁移任务，例如反卷积、轨迹、污染建模、扰动响应或表示学习。",
        "multiome_target_or_matchedness_unspecified": "请说明多组学数据是否 matched cells/samples，以及目标是轨迹、聚类还是扰动解释。",
        "perturbation_design_unspecified": "请说明扰动设计是剂量梯度、时间暴露、伪时间连续变量，还是离散 KO 标签。",
        "artifact_simulator_unspecified": "请先定义目标伪影的形成机制，或给出可生成 synthetic positive 的模拟器假设。",
        "reference_atlas_unspecified": "请说明是否有可信 reference atlas、标签粒度，以及目标组织与 reference 的 domain shift。",
        "splicing_layers_unspecified": "请说明输入矩阵是否包含 spliced/unspliced layers；没有这些层时不能生成 RNA velocity 迁移假设。",
        "scvi_subclass_unspecified": "请明确 scvi-tools 的具体子类与目标损失，例如 MultiVI、totalVI 或其它变分模型；套件名本身不能作为迁移机制。",
        "core_constraints_unspecified": "请补充关键实验设计和输出目标后再生成迁移假设。",
    }
    return questions.get(reason, f"请补充迁移前提：{reason}。")


T = TypeVar("T")


def tool_key(tool_name: str) -> str:
    return "".join(ch for ch in (tool_name or "").lower() if ch.isalnum())


def filter_blocked_by_tool_name(items: List[T], blocked_tools: List[str]) -> List[T]:
    blocked = {tool_key(name) for name in blocked_tools}
    if not blocked:
        return items
    return [
        item for item in items
        if tool_key(str(getattr(item, "tool_name", ""))) not in blocked
    ]


def filter_blocked_migration_paths(migration_paths: List[Any], blocked_tools: List[str]) -> List[Any]:
    return filter_blocked_by_tool_name(migration_paths, blocked_tools)
