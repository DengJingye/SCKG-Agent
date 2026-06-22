# agent/workflow.py
import json
from typing import Any, List

from langgraph.graph import StateGraph, END
from .states import ScKGAgentState, ScKGAgentStateModel
from core.llm_client import get_llm
from core.models import (
    DecisionReport,
    EvidenceBundle,
    MigrationPath,
    Recommendation,
    RetrievalResult,
    ScoredTool,
    ToolCandidate,
    derived_evidence,
    github_evidence,
    missing_evidence,
)
from core.evidence_policy import (
    MAIN_RECOMMENDATION_TOP_K,
    MIGRATION_TOP_K,
    audit_evidence,
    evidence_guardrail_warnings,
    has_main_recommendation_evidence,
)
from core.prompts import INTENT_EXTRACTION_PROMPT
from core.constraints import normalize_constraints
from core.task_ontology import (
    FINE_TASKS,
    build_task_query_terms,
    iter_tool_task_hints,
    normalize_task_label,
    task_alignment_score,
    task_family,
    tool_task_hints,
)
from connectors.graph_client import Neo4jClient
from engine.isomorphism_analyzer import IsomorphismAnalyzer
from core.prompts import REPORT_GENERATION_PROMPT # 确保已引入
from engine.context_pack_builder import build_evidence_context_pack
from engine.context_pack_reporter import render_context_pack_report
from engine.mcdm_calculator import MCDMCalculator
from engine.migration_hypothesis_engine import build_migration_hypotheses
from engine.semantic_hallucination_auditor import audit_report
from engine.workflow_recommender import build_minimal_workflow_recommendation
from core.settings import get_settings

# ==========================================
# 1. 定义节点函数 (Nodes)
# ==========================================


def _contextualized_query_for_llm(state: ScKGAgentState) -> str:
    """Attach user memory/upload context for LLM parsing without changing evidence."""

    query = state.get("user_query", "")
    project_memory = state.get("project_memory") or {}
    uploaded_context = state.get("uploaded_context") or {}
    conversation_context = state.get("conversation_context") or []
    context = {
        "current_user_query": query,
        "project_memory": project_memory,
        "uploaded_context": uploaded_context,
        "recent_conversation": conversation_context[-6:],
        "governance_note": (
            "Memory and uploads are user context only. They are not trusted "
            "scientific evidence and must not create benchmark or literature claims."
        ),
    }
    return json.dumps(context, ensure_ascii=False)

def parse_intent_node(state: ScKGAgentState) -> ScKGAgentState:
    """节点 1：解析用户意图，提取数据模态、规模等硬约束条件"""
    print("-> 执行节点: 🧠 意图解析 (调用 Qwen 提取结构化信息)")
    
    user_query = state["user_query"]
    contextual_query = _contextualized_query_for_llm(state)
    if get_settings().offline_llm:
        extracted_data = normalize_constraints({}, user_query=user_query)
        print("   🔒 LLM 离线模式已启用，使用 deterministic constraint fallback。")
        return {
            "current_step": "parse_intent",
            "extracted_constraints": extracted_data,
        }
    
    messages = [
        {"role": "system", "content": INTENT_EXTRACTION_PROMPT},
        {"role": "user", "content": contextual_query}
    ]
    
    try:
        llm = get_llm(state.get("user_runtime_config"))
        response = llm.invoke(messages)
        content = response.content.strip()
        
        # 清洗可能存在的 Markdown JSON 标记
        if content.startswith("```json"):
            content = content[7:-3].strip()
        elif content.startswith("```"):
            content = content[3:-3].strip()
            
        raw_extracted_data = json.loads(content)
        extracted_data = normalize_constraints(raw_extracted_data, user_query=user_query)
        print(f"   🎯 成功提取到约束条件: {extracted_data}")
        
    except Exception as e:
        print(f"   ❌ 意图解析失败，使用默认退避方案。报错: {e}")
        extracted_data = normalize_constraints({}, user_query=user_query)
        
    return {
        "current_step": "parse_intent",
        "extracted_constraints": extracted_data
    }

def hard_constraint_node(state: ScKGAgentState) -> ScKGAgentState:
    """节点 2：硬约束筛选 (Feasibility Reasoning)"""
    print("-> 执行节点: 🕸️ 知识图谱硬约束筛选 (正在检索 Neo4j...)")
    
    # 1. 拿到上一步 LLM 提取出的条件
    constraints = state.get("extracted_constraints", {})
    user_query = state.get("user_query", "")
    task = constraints.get("task", "Unknown")
    family = constraints.get("task_family") or task_family(task)
    modality = constraints.get("modality", "Unknown")
    platform = constraints.get("platform", "Unknown")
    task_terms = build_task_query_terms(task, family)
    
    raw_candidates = []
    candidates = []
    tool_candidates = []
    retrieval_results = []
    
    # 2. 如果条件合法，就去查 Neo4j
    if task != "Unknown" and modality != "Unknown":
        try:
            client = Neo4jClient()
            modality_queries = [modality]
            # 兼容旧图谱：早期数据可能把 Nanopore/PacBio 这类平台写进 Modality。
            if platform != "Unknown" and platform not in modality_queries:
                modality_queries.append(platform)

            rows_by_tool = {}
            for modality_query in modality_queries:
                for task_query in task_terms:
                    for record in client.find_candidates_by_hard_constraints(
                        task=task_query,
                        modality=modality_query,
                    ):
                        tool_name = record["tool_name"]
                        rows_by_tool.setdefault(
                            tool_name,
                            {
                                **record,
                                "matched_tasks": [],
                                "matched_modalities": [],
                                "retrieval_sources": [],
                            },
                        )
                        rows_by_tool[tool_name]["matched_tasks"].append(task_query)
                        rows_by_tool[tool_name]["matched_modalities"].append(modality_query)
                        rows_by_tool[tool_name]["retrieval_sources"].append("graph")
                if rows_by_tool:
                    print(f"   🔎 硬约束命中: task_terms={task_terms}, modality={modality_query}")
                    break
            for tool_name in _tool_hint_matches_for_query(task_terms):
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
            results = list(rows_by_tool.values())
            raw_candidates = [record["tool_name"] for record in results]
            evidence_by_tool = client.fetch_tool_evidence(raw_candidates)
            client.close()
            
            # 把查到的结果组装成列表
            for record in results:
                tool_name = record["tool_name"]
                if _is_blocked_main_tool(tool_name, task, user_query):
                    continue
                evidence_items = list(evidence_by_tool.get(tool_name, []))
                alignment = _candidate_task_alignment(
                    task_terms=task_terms,
                    tool_name=tool_name,
                    graph_tasks=(
                        record.get("matched_tasks", [])
                        if "task_hint" in record.get("retrieval_sources", [])
                        else []
                    ),
                    evidence_items=evidence_items,
                )
                if not _passes_task_specific_gate(task, alignment, evidence_items):
                    continue
                evidence = derived_evidence(
                    evidence_id=f"hard_constraint:{tool_name}:{task}:{modality}",
                    metric_name="hard_constraint_match",
                    metric_value={
                        "task": task,
                        "task_family": family,
                        "task_query_terms": task_terms,
                        "modality": modality,
                        "retrieval_sources": sorted(set(record.get("retrieval_sources", []))),
                    },
                    extraction_method="connectors.graph_client.find_candidates_by_hard_constraints",
                    source_title="Neo4j Tool-Task-Modality hard constraint match",
                    confidence=0.7,
                    kg_version=get_settings().kg_version,
                )
                alignment_evidence = derived_evidence(
                    evidence_id=f"hard_constraint:{tool_name}:{task}:{modality}:task_alignment",
                    metric_name="task_alignment",
                    metric_value=alignment,
                    extraction_method="agent.workflow.hard_constraint_node",
                    source_title="Task-specific ontology/evidence alignment",
                    confidence=0.6,
                    trust_level="inferred",
                    graph_layer="experimental",
                    evidence_strength="exploratory",
                    use_for=["retrieval", "ranking"],
                    kg_version=get_settings().kg_version,
                )
                evidence_bundle = EvidenceBundle(
                    items=[evidence, alignment_evidence, *evidence_items],
                )
                if not has_main_recommendation_evidence(evidence_bundle):
                    continue
                candidates.append(tool_name)
                tool_candidates.append(
                    ToolCandidate(
                        tool_name=tool_name,
                        description=record.get("desc") or "Unknown",
                        evidence=evidence_bundle,
                        feasibility_reasons=[
                            f"PERFORMS_TASK={task}",
                            f"TASK_FAMILY={family}",
                            f"TASK_ALIGNMENT={alignment:.2f}",
                            f"SUPPORTS_MODALITY={modality}",
                        ],
                    ).model_dump(mode="json")
                )
            if tool_candidates:
                retrieval_results.append(
                    RetrievalResult(
                        query=f"task={task}; modality={modality}; platform={platform}",
                        result_type="hard_constraint",
                        tool_candidates=[ToolCandidate.model_validate(item) for item in tool_candidates],
                        evidence_coverage=1.0,
                    ).model_dump(mode="json")
                )
            
            if raw_candidates:
                print(f"   🔒 主推荐证据门控: raw={len(raw_candidates)}, trusted_core={len(candidates)}")
            if candidates:
                print(f"   ✅ 图谱匹配成功！进入主推荐候选: {candidates[:MAIN_RECOMMENDATION_TOP_K]}")
            else:
                print("   ⚠️ 图谱中未找到可进入主推荐的 trusted_core 工具。")
        except Exception as e:
            print(f"   ❌ Neo4j 查询异常: {e}")
    else:
        print("   ⚠️ 提取的意图信息不完整，无法进行图谱匹配。")
        
    # 3. 将查到的候选工具更新到状态总线中
    return {
        "current_step": "hard_constraint",
        "candidate_tools": [
            item["tool_name"]
            for item in sorted(
                tool_candidates,
                key=lambda entry: _extract_task_alignment(
                    ToolCandidate.model_validate(entry).evidence.items
                ),
                reverse=True,
            )
        ][:MAIN_RECOMMENDATION_TOP_K],
        "tool_candidates": sorted(
            tool_candidates,
            key=lambda item: _extract_task_alignment(
                ToolCandidate.model_validate(item).evidence.items
            ),
            reverse=True,
        )[:MAIN_RECOMMENDATION_TOP_K],
        "retrieval_results": retrieval_results,
    }

def mcdm_scoring_node(state: ScKGAgentState) -> ScKGAgentState:
    """节点 3 (分支 A)：软约束打分 (基于图谱真实工程指标)"""
    print("\n-> 执行节点: ⚖️ MCDM 证据打分排序 (读取 Neo4j 真实数据...)")
    
    candidates = state.get("candidate_tools", [])
    existing_tool_candidates = {
        item.get("tool_name"): item
        for item in state.get("tool_candidates", [])
        if isinstance(item, dict)
    }
    scored_tools = []
    
    if candidates:
        try:
            client = Neo4jClient()
            # 编写 Cypher 语句：一次性查出所有候选工具的真实属性
            cypher = """
            MATCH (t:Tool)
            WHERE t.name IN $candidates
            OPTIONAL MATCH (t)-[:WRITTEN_IN]->(lang:Language)
            RETURN t.name AS tool_name,
                   t.description AS description,
                   t.github_url AS github_url,
                   t.github_stars AS github_stars,
                   coalesce(t.language, lang.name, 'Unknown') AS language
            """
            results = client.execute_query(cypher, {"candidates": candidates})
            evidence_by_tool = client.fetch_tool_evidence(candidates)
            client.close()
            
            metrics_to_score = []
            results_by_name = {row["tool_name"]: row for row in results}
            for name, candidate in existing_tool_candidates.items():
                if name not in results_by_name:
                    results_by_name[name] = {
                        "tool_name": name,
                        "description": candidate.get("description", "Unknown"),
                        "github_url": None,
                        "github_stars": None,
                        "language": candidate.get("language", "Unknown"),
                    }
            for r in results_by_name.values():
                existing_candidate = existing_tool_candidates.get(r["tool_name"], {})
                existing_bundle = EvidenceBundle()
                if existing_candidate:
                    existing_bundle = ToolCandidate.model_validate(existing_candidate).evidence
                evidence_items = list(existing_bundle.items)
                evidence_items.extend(evidence_by_tool.get(r["tool_name"], []))
                alignment = _extract_task_alignment(evidence_items)
                if alignment <= 0:
                    constraints = state.get("extracted_constraints", {})
                    task = constraints.get("task", "Unknown")
                    alignment = _candidate_task_alignment(
                        task_terms=build_task_query_terms(
                            task,
                            constraints.get("task_family") or task_family(task),
                        ),
                        tool_name=r["tool_name"],
                        graph_tasks=tool_task_hints(r["tool_name"]),
                        evidence_items=evidence_items,
                    )
                github_stars = int(r["github_stars"] or 0)
                if github_stars > 0 and not any(e.metric_name == "github_stars" for e in evidence_items):
                    evidence_items.append(
                        github_evidence(
                            tool_name=r["tool_name"],
                            metric_name="github_stars",
                            metric_value=github_stars,
                            source_url=r.get("github_url"),
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
                has_engineering_evidence = "engineering" not in missing

                evidence_bundle = EvidenceBundle(
                    items=evidence_items,
                    missing_evidence=missing,
                )
                metrics_to_score.append({
                    "tool_name": r["tool_name"],
                    "description": r.get("description") or "Unknown",
                    "github_stars": github_stars if has_engineering_evidence else None,
                    "language": r.get("language") or "Unknown",
                    "task_alignment": alignment,
                    "evidence_bundle": evidence_bundle,
                })
            
            # 调用我们写好的数学打分引擎
            calculator = MCDMCalculator()
            raw_scored_tools = calculator.calculate_scores(metrics_to_score)
            raw_scored_tools = [
                item for item in raw_scored_tools
                if audit_evidence(item["evidence_bundle"]).has_main_recommendation_evidence
            ][:MAIN_RECOMMENDATION_TOP_K]
            scored_models = []
            for rank, raw_tool in enumerate(raw_scored_tools, start=1):
                evidence_bundle = raw_tool["evidence_bundle"]
                audit = audit_evidence(evidence_bundle)
                scored = ScoredTool(
                    tool_name=raw_tool["tool_name"],
                    score=raw_tool["mcdm_score"],
                    rank=rank,
                    evidence=evidence_bundle,
                    evidence_breakdown={
                        **raw_tool["evidence_breakdown"],
                        "recommendation_grade_evidence": [
                            evidence.metric_name for evidence in audit.recommendation_evidence
                        ],
                        "retrieval_only_evidence_count": len(audit.retrieval_only_evidence),
                        "guardrails": evidence_guardrail_warnings(evidence_bundle),
                    },
                    recommendation_confidence=(
                        "high" if audit.recommendation_coverage >= 0.8
                        else "medium" if audit.recommendation_coverage >= 0.5
                        else "low"
                    ),
                )
                scored_models.append(scored)
                if raw_tool["tool_name"] not in existing_tool_candidates:
                    existing_tool_candidates[raw_tool["tool_name"]] = ToolCandidate(
                        tool_name=raw_tool["tool_name"],
                        description=raw_tool.get("description", "Unknown"),
                        github_stars=raw_tool.get("github_stars", 0),
                        language=raw_tool.get("language", "Unknown"),
                        evidence=evidence_bundle,
                    ).model_dump(mode="json")
            scored_tools = [item.model_dump(mode="json") for item in scored_models]
            
            print("   📊 基于 trusted_core 证据门控的 MCDM Top-K:")
            for idx, tool in enumerate(scored_tools):
                print(f"      [{idx+1}] {tool['tool_name']} - 综合得分: {tool['score']:.4f}")
                
        except Exception as e:
            print(f"   ❌ MCDM 真实数据查询失败: {e}")
    
    retrieval_results = state.get("retrieval_results", [])
    if scored_tools:
        retrieval_results.append(
            RetrievalResult(
                query="mcdm_scoring",
                result_type="mcdm",
                scored_tools=[ScoredTool.model_validate(item) for item in scored_tools],
                evidence_coverage=sum(
                    ScoredTool.model_validate(item).evidence.coverage for item in scored_tools
                ) / len(scored_tools),
            ).model_dump(mode="json")
        )

    return {
        "current_step": "mcdm_scoring",
        "candidate_tools": [tool["tool_name"] for tool in scored_tools],
        "tool_candidates": [
            existing_tool_candidates[tool["tool_name"]]
            for tool in scored_tools
            if tool["tool_name"] in existing_tool_candidates
        ],
        "scored_tools": scored_tools,
        "retrieval_results": retrieval_results,
    }
    
def migration_reasoning_node(state: ScKGAgentState) -> ScKGAgentState:
    """节点 3 (分支 B)：全量算法同构性迁移推理 (Workflow Migration)"""
    print("\n-> 执行节点: 🧬 算法同构性迁移推理 (无现成工具，启动图谱全量算法扫描...)")
    
    # 拿到用户真正想做的任务和模态
    constraints = state.get("extracted_constraints", {})
    
    # 构建搜索意图文本（给 BGE-M3 模型做向量化用的）
    requirement_text = "；".join([
        f"任务：{constraints.get('task', 'Unknown')}",
        f"任务家族：{constraints.get('task_family', 'Unknown')}",
        f"数据模态：{constraints.get('modality', 'Unknown')}",
        f"平台：{constraints.get('platform', 'Unknown')}",
        f"数据对象：{constraints.get('data_object', 'Unknown')}",
        f"数据规模：{constraints.get('scale', 'Unknown')}",
        f"噪声水平：{constraints.get('noise', 'Unknown')}",
        f"硬件约束：{constraints.get('hardware', ['Unknown'])}",
        f"物种：{constraints.get('species', 'Unknown')}",
        f"分析目标：{constraints.get('output_goal', 'Unknown')}",
        f"推荐严格程度：{constraints.get('strictness', 'Unknown')}",
    ])
    
    migration_paths = []
    migration_warnings = []

    settings = get_settings()
    profile_paths = build_migration_hypotheses(
        constraints=constraints,
        expected_source_tools=None,
        top_k=MIGRATION_TOP_K,
    )
    if profile_paths:
        print("   ✅ 使用审核后的算法画像生成探索性 MigrationHypothesis。")
        return {
            "current_step": "migration_reasoning",
            "migration_paths": [path.model_dump(mode="json") for path in profile_paths],
            "retrieval_results": state.get("retrieval_results", []) + [
                RetrievalResult(
                    query=requirement_text,
                    result_type="migration",
                    evidence_coverage=sum(path.evidence.coverage for path in profile_paths) / len(profile_paths),
                    warnings=[
                        "MigrationHypothesis is exploratory and must not enter main recommendation top-k.",
                        "Profile-based migration still requires downstream validation.",
                    ],
                ).model_dump(mode="json")
            ],
        }

    if settings.offline_llm or not settings.embedding_api_key:
        reason = (
            "offline_llm_enabled"
            if settings.offline_llm
            else "missing_embedding_api_key"
        )
        migration_warnings.append(
            f"Migration embedding search skipped: {reason}. "
            "No embedding-only migration path is emitted."
        )
        print(f"   🔒 跳过迁移向量检索: {reason}")
        return {
            "current_step": "migration_reasoning",
            "migration_paths": [],
            "retrieval_results": state.get("retrieval_results", []) + [
                RetrievalResult(
                    query=requirement_text,
                    result_type="migration",
                    evidence_coverage=0.0,
                    warnings=migration_warnings,
                ).model_dump(mode="json")
            ],
        }
    
    try:
        analyzer = IsomorphismAnalyzer()
        
        print(f"   🔍 正在扫描全图谱，寻找与 [{requirement_text}] 具备算法同构性的可迁移工具...")
        
        # 🚀 核心替换：直接调用我们刚写好的引擎全量检索方法！
        top_tools = analyzer.search_isomorphic_tools(requirement_text, top_k=MIGRATION_TOP_K)
        analyzer.close()
        
        if top_tools:
            for tool in top_tools:
                print(f"      - 评估 {tool['tool_name']}: 算法相似度 {tool['similarity']:.4f}")
                # 按照你原有的格式拼装数据，传给下一个节点
                migration_paths.append({
                    "tool_name": tool["tool_name"],
                    "score": max(0.0, min(1.0, tool["similarity"])), 
                    "cos_sim": tool["similarity"],
                    "features": tool["features"], # 把算法特征也传下去，大模型写报告时需要！
                    "risk_level": "exploratory",
                    "evidence": EvidenceBundle(
                        items=[
                            derived_evidence(
                                evidence_id=f"migration:{tool['tool_name']}:cosine_similarity",
                                metric_name="cosine_similarity",
                                metric_value=tool["similarity"],
                                extraction_method="engine.isomorphism_analyzer.search_isomorphic_tools",
                                source_title="Algorithm feature embedding similarity",
                                confidence=0.55,
                                kg_version=get_settings().kg_version,
                            )
                        ],
                        missing_evidence=["structured_algorithm_compatibility", "data_object_mapping"],
                    ).model_dump(mode="json"),
                    "limitations": [
                        "Embedding similarity is not sufficient scientific validation.",
                        "Structured algorithm compatibility is not implemented yet.",
                    ],
                })
                
            best_tool = top_tools[0]
            print(f"   💡 迁移引擎候选：[{best_tool['tool_name']}] (embedding 相似度: {best_tool['similarity']:.4f})")
        else:
            print("   ⚠️ 图谱全量扫描未找到匹配的算法特征。")
            
    except Exception as e:
        print(f"   ❌ 迁移推理引擎发生异常: {e}")
        migration_warnings.append(f"Migration reasoning failed: {e}")
        migration_paths = []
        
    # 保持你原有的 State 返回格式绝对不变，防止断流
    return {
        "current_step": "migration_reasoning",
        "migration_paths": migration_paths,
        "retrieval_results": state.get("retrieval_results", []) + (
            [
                RetrievalResult(
                    query=requirement_text,
                    result_type="migration",
                    evidence_coverage=0.5 if migration_paths else 0.0,
                    warnings=migration_warnings or ["Migration branch is exploratory until structured compatibility checks exist."],
                ).model_dump(mode="json")
            ] if migration_paths or migration_warnings else []
        ),
    }

def generate_report_node(state: ScKGAgentState) -> ScKGAgentState:
    """节点 4：生成最终报告 (闭环最后一步)"""
    print("-> 执行节点: 📝 生成包含证据链的最终分析报告")
    
    # 1. 整理上下文数据 (Context Ingestion)
    snapshot = ScKGAgentStateModel.model_validate(state)
    user_query = snapshot.user_query
    constraints = snapshot.extracted_constraints.to_state_dict()
    candidates = snapshot.candidate_tools[:MAIN_RECOMMENDATION_TOP_K]
    visible_scored_tools = [
        tool.model_dump(mode="json")
        for tool in snapshot.scored_tools[:MAIN_RECOMMENDATION_TOP_K]
    ]
    recommended_tool_names = [tool["tool_name"] for tool in visible_scored_tools] or candidates
    workflow_recommendation = build_minimal_workflow_recommendation(
        constraints,
        candidate_tools=recommended_tool_names[:3],
    )
    recommendations = []
    risks = []
    uncertainty = []
    uncertainty.extend(_task_caveats(constraints, []))
    recommendations.append(
        Recommendation(
            kind="workflow",
            title=workflow_recommendation.name,
            rationale="Baseline workflow assembled from structured task constraints.",
            evidence=workflow_recommendation.evidence,
            workflow=workflow_recommendation,
            risk_level="medium",
        )
    )
    uncertainty.extend(workflow_recommendation.compatibility_warnings)
    visible_migrations = snapshot.migration_paths[:MIGRATION_TOP_K]
    report_migrations = _accepted_migration_paths(visible_migrations)
    for tool in snapshot.scored_tools[:MAIN_RECOMMENDATION_TOP_K]:
        bundle = tool.evidence
        if not bundle.items and not bundle.missing_evidence:
            risks.append(f"Tool {tool.tool_name} excluded from recommendation: no evidence object.")
            continue
        recommendations.append(
            Recommendation(
                kind="direct_tool",
                title=f"Recommend {tool.tool_name}",
                rationale="Ranked by evidence-aware MCDM scoring.",
                evidence=bundle,
                tool=tool,
                risk_level="low" if tool.recommendation_confidence == "high" else "medium",
            )
        )
        if bundle.missing_evidence:
            uncertainty.append(f"{tool.tool_name} missing evidence: {', '.join(bundle.missing_evidence)}")
    for path in report_migrations:
        recommendations.append(
            Recommendation(
                kind="migration",
                title=f"Exploratory migration via {path.tool_name}",
                rationale="Suggested by algorithm feature similarity; requires validation.",
                evidence=path.evidence,
                migration=path,
                risk_level=path.risk_level,
            )
        )
        uncertainty.extend(path.limitations)
    decision_report = DecisionReport(
        user_query=user_query,
        constraints=constraints,
        recommendations=recommendations,
        risks=risks,
        uncertainty=uncertainty,
    )
    
    combined_evidence = _combine_report_evidence(
        scored_tools=snapshot.scored_tools[:MAIN_RECOMMENDATION_TOP_K],
        migration_paths=report_migrations,
        workflow_recommendation=workflow_recommendation,
    )
    missing_components = sorted(
        set(
            combined_evidence.missing_evidence
            + [
                f"constraint:{field}"
                for field in constraints.get("pending_constraints", []) or []
            ]
        )
    )
    context_pack = build_evidence_context_pack(
        user_query=user_query,
        constraints=constraints,
        recommendation_type=(
            "migration"
            if snapshot.migration_paths and not snapshot.scored_tools
            else "workflow"
        ),
        scored_tools=snapshot.scored_tools[:MAIN_RECOMMENDATION_TOP_K],
        tool_candidates=snapshot.tool_candidates[:MAIN_RECOMMENDATION_TOP_K],
        workflow=workflow_recommendation,
        migration_paths=visible_migrations,
        evidence_bundle=combined_evidence,
        missing_components=missing_components,
    )

    # 2. 构建输入给大模型的数据快照。v0.12 起 LLM 只能看到受控 context pack。
    context_data = {
        "user_query": user_query,
        "evidence_context_pack": context_pack.model_dump(mode="json"),
        "conversation_context": snapshot.conversation_context[-6:],
        "project_memory": snapshot.project_memory,
        "uploaded_context": snapshot.uploaded_context,
        "context_governance": (
            "Conversation memory and uploaded files are user-provided context only; "
            "they cannot upgrade evidence, ranking, benchmark claims, or trusted_core status."
        ),
    }
    
    # 3. 构造消息
    messages = [
        {"role": "system", "content": REPORT_GENERATION_PROMPT},
        {"role": "user", "content": f"请基于以下系统处理数据生成报告：\n{json.dumps(context_data, ensure_ascii=False)}"}
    ]
    
    if get_settings().offline_llm:
        report_content = render_context_pack_report(context_pack)
        print("   🔒 LLM 离线模式已启用，生成 deterministic structured report。")
    else:
        try:
            llm = get_llm(state.get("user_runtime_config"))
            # 调用 Qwen2.5 生成报告
            response = llm.invoke(messages)
            report_content = response.content
            print("   ✅ 报告生成成功！")
        except Exception as e:
            report_content = f"报告生成失败，原始错误：{e}"
            print(f"   ❌ 报告生成失败: {e}")

    hallucination_audit = audit_report(
        final_report=report_content,
        evidence_bundle=combined_evidence,
        scored_tools=snapshot.scored_tools[:MAIN_RECOMMENDATION_TOP_K],
        candidate_tools=snapshot.tool_candidates[:MAIN_RECOMMENDATION_TOP_K],
        migration_paths=report_migrations,
        workflow_recommendation=workflow_recommendation,
        context_pack=context_pack.model_dump(mode="json"),
    )
    blocking_issues = [
        issue for issue in hallucination_audit.issues
        if issue.severity in {"critical", "high"}
    ]
    if blocking_issues:
        print(f"   🛑 Semantic auditor blocked unsafe report: {len(blocking_issues)} high/critical issue(s)")
        report_content = _build_safe_blocked_report(
            constraints=constraints,
            scored_tools=snapshot.scored_tools[:MAIN_RECOMMENDATION_TOP_K],
            workflow_recommendation=workflow_recommendation,
            hallucination_audit=hallucination_audit,
        )
        hallucination_audit = audit_report(
            final_report=report_content,
            evidence_bundle=combined_evidence,
            scored_tools=snapshot.scored_tools[:MAIN_RECOMMENDATION_TOP_K],
            candidate_tools=snapshot.tool_candidates[:MAIN_RECOMMENDATION_TOP_K],
            migration_paths=report_migrations,
            workflow_recommendation=workflow_recommendation,
            context_pack=context_pack.model_dump(mode="json"),
        )

    context_pack = build_evidence_context_pack(
        user_query=user_query,
        constraints=constraints,
        recommendation_type=(
            "migration"
            if snapshot.migration_paths and not snapshot.scored_tools
            else "workflow"
        ),
        scored_tools=snapshot.scored_tools[:MAIN_RECOMMENDATION_TOP_K],
        tool_candidates=snapshot.tool_candidates[:MAIN_RECOMMENDATION_TOP_K],
        workflow=workflow_recommendation,
        migration_paths=visible_migrations,
        evidence_bundle=combined_evidence,
        missing_components=missing_components,
        hallucination_audit=hallucination_audit.model_dump(mode="json"),
    )
        
    return {
        "current_step": "generate_report",
        "workflow_recommendations": [workflow_recommendation.model_dump(mode="json")],
        "decision_report": decision_report.model_dump(mode="json"),
        "context_pack": context_pack.model_dump(mode="json"),
        "final_report": report_content,
        "hallucination_audit": hallucination_audit.model_dump(mode="json"),
    }


def _build_structured_offline_report(
    constraints,
    scored_tools,
    migration_paths,
    workflow_recommendation,
    uncertainty,
) -> str:
    lines = [
        "## scKG Structured Scientific Output",
        "- report_status: offline_llm_structured_report",
        f"- task: {constraints.get('task', 'Unknown')}",
        f"- modality: {constraints.get('modality', 'Unknown')}",
        f"- clarification_state: {constraints.get('clarification_state', 'needs_clarification')}",
    ]
    if scored_tools:
        lines.append("- ranked_tools: " + ", ".join(tool.tool_name for tool in scored_tools))
    if migration_paths:
        lines.append("- migration_paths: " + ", ".join(path.tool_name for path in migration_paths))
        lines.append(
            "- migration_claim_boundary: exploratory hypothesis only; "
            "requires validation before operational use and has no benchmark-backed performance claim."
        )
        gaps = [
            f"{path.tool_name}: " + " | ".join(path.compatibility_gaps[:2])
            for path in migration_paths
            if path.compatibility_gaps
        ]
        if gaps:
            lines.append("- migration_compatibility_gaps: " + " ; ".join(gaps[:3]))
    if workflow_recommendation:
        lines.append("- workflow_steps: " + " -> ".join(step.name for step in workflow_recommendation.steps))
    caveats = _task_caveats(constraints, [])
    if caveats:
        lines.append("- evidence_caveats: " + " | ".join(caveats))
    if uncertainty:
        lines.append("- uncertainty: " + " | ".join(dict.fromkeys(uncertainty[:6])))
    lines.append("- safety_note: generated without LLM calls from structured evidence only.")
    return "\n".join(lines)


def _combine_report_evidence(
    scored_tools,
    migration_paths,
    workflow_recommendation,
) -> EvidenceBundle:
    items = []
    missing = []
    for tool in scored_tools:
        items.extend(tool.evidence.items)
        missing.extend(tool.evidence.missing_evidence)
    for path in migration_paths:
        items.extend(path.evidence.items)
        missing.extend(path.evidence.missing_evidence)
    if workflow_recommendation:
        items.extend(workflow_recommendation.evidence.items)
        missing.extend(workflow_recommendation.evidence.missing_evidence)
        for step in workflow_recommendation.steps:
            items.extend(step.evidence.items)
            missing.extend(step.evidence.missing_evidence)
    return EvidenceBundle(
        items=list({item.evidence_id: item for item in items}.values()),
        missing_evidence=sorted(set(missing)),
    )


def _build_safe_blocked_report(
    constraints,
    scored_tools,
    workflow_recommendation,
    hallucination_audit,
) -> str:
    lines = [
        "## scKG Safe Scientific Output",
        "- report_status: blocked_by_semantic_auditor",
        f"- task: {constraints.get('task', 'Unknown')}",
        f"- modality: {constraints.get('modality', 'Unknown')}",
        f"- clarification_state: {constraints.get('clarification_state', 'needs_clarification')}",
    ]
    if scored_tools:
        lines.append("- ranked_tools: " + ", ".join(tool.tool_name for tool in scored_tools))
    if workflow_recommendation:
        lines.append("- workflow_steps: " + " -> ".join(step.name for step in workflow_recommendation.steps))
    caveats = _task_caveats(constraints, [])
    if caveats:
        lines.append("- evidence_caveats: " + " | ".join(caveats))
    lines.append("- safety_note: original report contained unsupported high-risk claims and was replaced.")
    lines.append("- blocked_by: semantic_auditor")
    return "\n".join(lines)


def _task_caveats(
    constraints: dict,
    missing_components: List[str],
) -> List[str]:
    if constraints.get("task") != "Perturbation Differential Expression":
        return []
    caveats = [
        "MIMOSCA can be surfaced only as a conservative perturbation-analysis candidate."
    ]
    if not missing_components or "benchmark" in missing_components or "trusted_recommendation_evidence" in missing_components:
        caveats.append(
            "No strong benchmark-backed performance claim is allowed for this perturbation task."
        )
    return caveats


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
    for value in [getattr(evidence, "dataset_scope", ""), getattr(evidence, "source_title", "")]:
        if not value:
            continue
        for chunk in str(value).replace("|", ";").replace(",", ";").split(";"):
            item = chunk.strip()
            if item:
                terms.append(item)
    return terms


def _passes_task_specific_gate(task: str, alignment: float, evidence_items: List[Any]) -> bool:
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


def _accepted_migration_paths(migration_paths: List[MigrationPath]) -> List[MigrationPath]:
    return [
        path for path in migration_paths
        if (path.reviewer_decision or "").strip().lower() == "accept_exploratory"
    ]

# ==========================================
# 2. 定义条件路由函数 (Conditional Edges)
# ==========================================

def route_based_on_candidates(state: ScKGAgentState) -> str:
    """核心路由判断：检查 I_cand 是否为空"""
    candidates = state.get("candidate_tools", [])
    if candidates and len(candidates) > 0:
        return "has_candidates"
    else:
        return "no_candidates"

# ==========================================
# 3. 组装工作流 (Graph Build)
# ==========================================

def build_sckg_graph():
    """构建 scKG-Atlas Agent 状态图"""
    workflow = StateGraph(ScKGAgentState)

    # 添加所有节点
    workflow.add_node("intent_parser", parse_intent_node)
    workflow.add_node("hard_constraint", hard_constraint_node)
    workflow.add_node("mcdm_scorer", mcdm_scoring_node)
    workflow.add_node("migration_engine", migration_reasoning_node)
    workflow.add_node("report_generator", generate_report_node)

    # 定义流转边
    workflow.set_entry_point("intent_parser")
    workflow.add_edge("intent_parser", "hard_constraint")

    workflow.add_conditional_edges(
        "hard_constraint",
        route_based_on_candidates,
        {
            "has_candidates": "mcdm_scorer",
            "no_candidates": "migration_engine"
        }
    )

    workflow.add_edge("mcdm_scorer", "report_generator")
    workflow.add_edge("migration_engine", "report_generator")
    workflow.add_edge("report_generator", END)

    app = workflow.compile()
    return app
