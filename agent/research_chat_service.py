from __future__ import annotations

import csv
import hashlib
import json
import re
import threading
import time
import uuid
from dataclasses import dataclass
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, Optional
from urllib.parse import urlparse

from agent.audited_parent_agent import AuditedParentAgent
from agent.bounded_parent_agent import (
    BoundedParentAgent,
    ParentAgentRequest,
    ParentAgentResult,
)
from agent.research_agent_graph import ResearchAgentGraph
from agent.research_chat_reasoner import (
    ExternalReasoningResult,
    ExternalResearchReasoner,
    SemanticParseResult,
)
from agent.conversation_state import (
    next_conversation_task_state,
    resolve_conversation_task_state,
)
from agent.grounded_answer_audit import audit_grounded_answer_v3
from agent.research_tool_registry import ResearchToolRegistry
from core.canonical_task_ontology import (
    CANONICAL_TASKS,
    TOOL_TASK_IDS,
    canonical_task,
    canonical_task_for_text,
)
from core.knowledge_intelligence_models import (
    AdaptiveRetrievalDecision,
    ChatStageTiming,
    HybridRetrievalRequest,
)
from core.settings import PROJECT_ROOT, get_settings
from core.research_agent_models import (
    ActionSafetyDecision,
    AgentMode,
    AnswerabilityDecision,
    ConversationTaskState,
    DomainDecision,
    DomainKind,
    ExecutionHandoff,
    ResearchAgentRequest,
    ResearchAgentResponse,
    ResearchAgentState,
    ResearchToolCall,
    ResearchToolPlan,
    SemanticRouteDecision,
)
from core.runtime_build_identity import get_runtime_build_identity
from core.trace_context import (
    TraceCollector,
    TraceContext,
    TraceCorrelationKind,
    TraceKind,
    TraceLinkType,
    TracePrivacyError,
    TraceStage,
    TraceStateError,
    TraceStatus,
    TraceValidationError,
    trace_correlation_id,
)
from core.open_world_evaluation_models import (
    ClaimAction,
    ClaimEntailmentStatus,
    ClaimRecord,
    GroundedAnswerAuditV2,
    GroundedAnswerAuditV3,
)
from engine.evidence_graph_query import EvidenceGraphQuery
from engine.hybrid_retrieval import HybridRetrievalService
from engine.migration_hypothesis_engine import build_migration_hypotheses
from engine.workflow_code_service import WorkflowCodeService


_SERVICE_SOURCE_AT_IMPORT = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


class ResearchChatIntent(str, Enum):
    TOOL_RECOMMENDATION = "tool_recommendation"
    WORKFLOW = "workflow"
    CAVEAT_COMPARISON = "caveat_comparison"
    MIGRATION_EXPLORATION = "migration_exploration"
    EVIDENCE_QA = "evidence_qa"


@dataclass(frozen=True)
class _ClaimTarget:
    """One conservatively parsed entity/predicate request."""

    entity: str
    predicate: str
    legacy_claim_type: str
    ambiguous: bool = False


@dataclass(frozen=True)
class _BoundEvidenceRef:
    """Immutable source-bound evidence needed by one atomic claim."""

    evidence_span_id: str
    source_id: str
    source_span: str
    title: str
    bounded_excerpt: str
    metadata_claim_type: str


@dataclass(frozen=True)
class _ClaimEvidenceBinding:
    """One atomic scientific claim and its explicit evidence provenance."""

    entity: str
    predicate: str
    legacy_claim_type: str
    claim_text: str
    evidence_refs: tuple[_BoundEvidenceRef, ...]
    source_refs: tuple[str, ...]
    support_status: str
    support_type: str
    support_quality: int
    abstain_reason: Optional[str] = None


class _ResearchTraceScopes:
    """Request-local cleanup for safe semantic scopes; owns no trace data."""

    def __init__(self) -> None:
        self._scopes: list[Any] = []

    def enter(self, scope: Any) -> Any:
        scope.__enter__()
        self._scopes.append(scope)
        return scope

    def fail_open(self, exc: Exception) -> None:
        for scope in reversed(self._scopes):
            record = scope.record
            if record is not None and not record.terminal:
                scope.__exit__(type(exc), exc, exc.__traceback__)


def _finish_research_trace_span(
    span: Any,
    status: TraceStatus,
    *,
    decision_type: str,
    outcome: str,
    reason_code: str,
    rule_version: str,
    record_ref: Optional[dict[str, Any]] = None,
    error_code: Optional[str] = None,
) -> None:
    if status is TraceStatus.SUCCESS:
        span.add_decision(
            decision_type=decision_type,
            outcome=outcome,
            reason_code=reason_code,
            rule_version=rule_version,
            record_ref=record_ref,
        )
        span.succeed()
    elif status is TraceStatus.PARTIAL:
        span.partial(
            decision_type=decision_type,
            outcome=outcome,
            reason_code=reason_code,
            rule_version=rule_version,
            record_ref=record_ref,
        )
    elif status is TraceStatus.BLOCKED:
        span.blocked(
            decision_type=decision_type,
            outcome=outcome,
            reason_code=reason_code,
            rule_version=rule_version,
            record_ref=record_ref,
        )
    elif status is TraceStatus.SKIPPED:
        span.skipped(
            decision_type=decision_type,
            outcome=outcome,
            reason_code=reason_code,
            rule_version=rule_version,
            record_ref=record_ref,
        )
    else:
        span.add_decision(
            decision_type=decision_type,
            outcome=outcome,
            reason_code=reason_code,
            rule_version=rule_version,
            record_ref=record_ref,
        )
        span.fail(error_code or "research_stage_failed")


def _close_research_trace_span(
    span: Any,
    status: TraceStatus,
    *,
    outcome: str,
    reason_code: str,
    decision_type: str = "research_route",
    rule_version: str = "research_routing_v0",
    record_ref: Optional[dict[str, Any]] = None,
) -> None:
    _finish_research_trace_span(
        span,
        status,
        decision_type=decision_type,
        outcome=outcome,
        reason_code=reason_code,
        rule_version=rule_version,
        record_ref=record_ref,
    )
    span.__exit__(None, None, None)


def _set_research_request_outcome(
    trace: TraceContext,
    response: ResearchAgentResponse,
) -> None:
    instrumentation = trace.instrumentation()
    if response.status == "FAILED":
        instrumentation.set_request_outcome(
            TraceStatus.FAILED,
            error_code="research_request_failed",
        )
        return
    if response.status == "BLOCKED":
        instrumentation.set_request_outcome(
            TraceStatus.BLOCKED,
            decision_type="research_request_outcome",
            outcome="blocked",
            reason_code="research_request_blocked",
            rule_version="research_outcome_v0",
        )
        return
    if response.status == "WAITING" or response.runtime_mode == "general_local_fallback":
        instrumentation.set_request_outcome(
            TraceStatus.PARTIAL,
            decision_type="research_request_outcome",
            outcome="partial",
            reason_code=(
                "research_request_waiting"
                if response.status == "WAITING"
                else "general_answer_degraded"
            ),
            rule_version="research_outcome_v0",
        )
        return
    instrumentation.set_request_outcome(TraceStatus.SUCCESS)


def _dense_default_enabled(
    policy_path: Path = PROJECT_ROOT / "data/indexes/retrieval_route_policy.json",
) -> bool:
    try:
        payload = json.loads(policy_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return bool(
        payload.get("dense_default_enabled")
        and payload.get("default_profile") == "kg_hybrid_tool_contract"
    )


_ALGORITHM_GUIDE: dict[str, dict[str, Any]] = {
    "scrublet": {
        "mechanism": "模拟人工 doublet，并在降维后的近邻空间中计算 doublet score。",
        "best_for": "Python/Scanpy 流程中的 10x droplet scRNA-seq；建议按独立上样批次运行。",
        "input": "非负 raw UMI count matrix",
        "output": "每个细胞的 doublet score 与预测标签",
        "caveats": [
            "同型 doublet 或连续细胞状态较难识别。",
            "多样本应按 capture/sample 分别运行，并结合模拟 doublet score 分布检查阈值。",
            "expected doublet rate 仍需结合 10x 上样量与实验设计核对。",
        ],
        "readiness": "decision_ready",
    },
    "scdblfinder": {
        "mechanism": "结合人工 doublet 与分类模型，在 Bioconductor 数据结构中预测 doublet。",
        "best_for": "R/Bioconductor 或 SingleCellExperiment 工作流。",
        "input": "raw count matrix、稳定的 cell ID；多样本时需要正确 sample 分组",
        "output": "doublet score 与 singlet/doublet 分类",
        "caveats": [
            "预期 doublet rate 对 score 影响较小，但会显著改变分类阈值。",
            "多 capture 数据应提供 sample 分组，以估计 sample-specific doublet rate。",
            "项目内科学验证只覆盖 GSE108313 PBMC pilot，不能外推为普遍最优。",
        ],
        "readiness": "decision_ready",
    },
    "doubletfinder": {
        "mechanism": "在 Seurat PCA 邻域中加入人工 doublet，并以 pANN 进行排序。",
        "best_for": "已经以 Seurat 为主的分析流程。",
        "input": "按样本处理的 Seurat 对象及已完成的预处理/PCA",
        "output": "pANN 与 doublet 分类元数据",
        "caveats": [
            "预期 doublet 数 nExp 需要依据上样密度估计，并对 homotypic doublet 比例作调整。",
            "pK 需要针对数据集选择；真实数据没有 ground truth 时只能用代理指标估计。",
            "当前 scKG 中尚无资格化 ToolContract 和独立 scientific pilot，只能作为规划候选。",
        ],
        "readiness": "planning_only",
    },
    "harmony": {
        "mechanism": "在 PCA embedding 上迭代聚类并校正 batch-specific centroid。",
        "best_for": "需要快速获得 batch-corrected embedding 的 scRNA-seq 整合。",
        "input": "PCA embedding、batch labels 与稳定 cell IDs",
        "output": "保持细胞顺序的 integrated embedding",
        "caveats": [
            "输出是校正后的 embedding，不是 corrected count matrix。",
            "过强校正可能抹去与 batch 混杂的真实生物差异。",
            "项目内 pilot 只覆盖冻结的 scIB pancreas 设置。",
        ],
        "readiness": "decision_ready",
    },
    "scanorama": {
        "mechanism": "通过数据集间匹配与流形拼接构建整合表示。",
        "best_for": "多个 scRNA-seq batch/dataset 的 CPU 整合。",
        "input": "按 batch 分组的表达矩阵、共同基因与稳定 cell IDs",
        "output": (
            "`scanorama.integrate_scanpy()` 将 integrated embedding 写入 "
            "`adata.obsm['X_scanorama']`；受控 wrapper 输出时恢复原始细胞顺序"
        ),
        "caveats": [
            "基因交集和 batch 划分错误会直接破坏匹配。",
            "稀有或 batch-specific 细胞群可能被错误对齐。",
            "项目内 pilot 只覆盖冻结的 scIB pancreas 设置。",
        ],
        "readiness": "decision_ready",
    },
}

_TOOL_DISPLAY_NAMES: dict[str, str] = {
    "scrublet": "Scrublet",
    "scdblfinder": "scDblFinder",
    "doubletfinder": "DoubletFinder",
    "harmony": "Harmony",
    "scanorama": "Scanorama",
    "seurat": "Seurat",
    "scanpy": "Scanpy",
    "scvitools": "scvi-tools",
    "celltypist": "CellTypist",
    "singler": "SingleR",
    "cell2location": "cell2location",
    "scvelo": "scVelo",
    "cellrank": "CellRank",
    "mofa2": "MOFA2",
    "moscot": "moscot",
    "tradeseq": "tradeSeq",
}


class ResearchChatService:
    """Deterministic local Parent Agent for evidence Q&A and governed planning."""

    def __init__(
        self,
        *,
        retrieval: Optional[HybridRetrievalService] = None,
        parent_agent: Optional[BoundedParentAgent] = None,
        graph_query: Optional[EvidenceGraphQuery] = None,
        workflow_code: Optional[WorkflowCodeService] = None,
        research_tools: Optional[ResearchToolRegistry] = None,
        reasoner: Optional[ExternalResearchReasoner] = None,
        dense_default_enabled: Optional[bool] = None,
        evaluation_retrieval_profile: Optional[str] = None,
        trace_collector: Optional[TraceCollector] = None,
    ) -> None:
        self.retrieval = retrieval or HybridRetrievalService()
        self._parent_agent = parent_agent
        self._audited_parent: Optional[AuditedParentAgent] = (
            AuditedParentAgent(parent_agent)
            if isinstance(parent_agent, BoundedParentAgent)
            else None
        )
        self._graph_query = graph_query
        self._workflow_code = workflow_code or WorkflowCodeService()
        self._research_tools = research_tools or ResearchToolRegistry(
            retrieval=self.retrieval,
            workflow_code=self._workflow_code,
        )
        self._reasoner = reasoner
        self._parent_lock = threading.Lock()
        self._application_graph: Optional[ResearchAgentGraph] = None
        self._dense_default_enabled = (
            _dense_default_enabled()
            if dense_default_enabled is None
            else bool(dense_default_enabled)
        )
        allowed_profiles = {
            None,
            "bm25",
            "kg_hybrid",
            "kg_hybrid_contract",
        }
        if evaluation_retrieval_profile not in allowed_profiles:
            raise ValueError(
                "evaluation_retrieval_profile must be bm25, kg_hybrid, "
                "kg_hybrid_contract, or None"
            )
        self._evaluation_retrieval_profile = evaluation_retrieval_profile
        self._trace_collector = trace_collector or TraceCollector()
        if self._dense_default_enabled:
            self.retrieval.start_dense_warmup()

    def prepare_for_evaluation(self, *, timeout: float = 60.0) -> Dict[str, Any]:
        """Warm optional local components outside measured request latency."""

        if not self._dense_default_enabled:
            return {"dense_status": "disabled"}
        return self.retrieval.wait_for_dense_ready(timeout).model_dump(mode="json")

    def run(
        self,
        query: str,
        *,
        mode: Optional[AgentMode] = None,
        request_id: Optional[str] = None,
        conversation_id: str = "local-conversation",
        user_id: str = "local-research-user",
        artifact_id: Optional[str] = None,
        data_grant_id: Optional[str] = None,
        execution_approval_id: Optional[str] = None,
        requested_tool: Optional[str] = None,
        parameters: Optional[Dict[str, Any]] = None,
        project_memory: Optional[Dict[str, Any]] = None,
        uploaded_context: Optional[Dict[str, Any]] = None,
        conversation_context: Optional[list[dict[str, Any]]] = None,
        user_runtime_config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        request = ResearchAgentRequest(
            request_id=request_id or "research-chat-" + uuid.uuid4().hex[:16],
            conversation_id=conversation_id,
            user_id=user_id,
            query=query,
            mode=mode,
            artifact_id=artifact_id,
            data_grant_id=data_grant_id,
            execution_approval_id=execution_approval_id,
            requested_tool=requested_tool,
            parameters=parameters or {},
        )
        response = self.run_request(
            request,
            project_memory=project_memory,
            uploaded_context=uploaded_context,
            conversation_context=conversation_context,
            user_runtime_config=user_runtime_config,
        )
        return self._legacy_response(response)

    def run_request(
        self,
        request: ResearchAgentRequest,
        *,
        project_memory: Optional[Dict[str, Any]] = None,
        uploaded_context: Optional[Dict[str, Any]] = None,
        conversation_context: Optional[list[dict[str, Any]]] = None,
        user_runtime_config: Optional[Dict[str, Any]] = None,
        trace_context: Optional[TraceContext] = None,
    ) -> ResearchAgentResponse:
        correlation_degraded = False
        try:
            trace_request_id = trace_correlation_id(
                request.request_id,
                kind=TraceCorrelationKind.REQUEST,
            )
        except TracePrivacyError:
            trace_request_id = f"request-ref:opaque:{uuid.uuid4().hex}"
            correlation_degraded = True
        try:
            trace_conversation_id = trace_correlation_id(
                request.conversation_id,
                kind=TraceCorrelationKind.CONVERSATION,
            )
        except TracePrivacyError:
            trace_conversation_id = None
            correlation_degraded = True

        if trace_context is not None and not correlation_degraded:
            if not trace_context.is_v0:
                raise TraceStateError("injected research trace must be canonical v0")
            if trace_context.trace_kind is not TraceKind.RESEARCH:
                raise TraceStateError("injected research trace must have RESEARCH kind")
            if trace_context.request_id != trace_request_id:
                raise TraceValidationError("injected trace request correlation mismatch")
            if (
                trace_context.conversation_id is not None
                and trace_context.conversation_id != trace_conversation_id
            ):
                raise TraceValidationError(
                    "injected trace conversation correlation mismatch"
                )
            trace = trace_context
        else:
            trace = TraceContext.new_request(
                trace_kind=TraceKind.RESEARCH,
                request_id=trace_request_id,
                conversation_id=trace_conversation_id,
            )
        if self._application_graph is None:
            with self._parent_lock:
                if self._application_graph is None:
                    self._application_graph = ResearchAgentGraph(self)
        with self._trace_collector.request_scope(trace):
            result = self._application_graph.invoke(
                {
                    "request": request,
                    "trace_context": trace,
                    "trace_correlation_degraded": correlation_degraded,
                    "project_memory": dict(project_memory or {}),
                    "uploaded_context": dict(uploaded_context or {}),
                    "conversation_context": list(conversation_context or []),
                    "user_runtime_config": dict(user_runtime_config or {}),
                }
            )
            response = result["response"]
            _set_research_request_outcome(trace, response)
        return response

    def _execute_pipeline(
        self,
        request: ResearchAgentRequest,
        *,
        trace_context: TraceContext,
        trace_correlation_degraded: bool = False,
        project_memory: Optional[Dict[str, Any]] = None,
        uploaded_context: Optional[Dict[str, Any]] = None,
        conversation_context: Optional[list[dict[str, Any]]] = None,
        user_runtime_config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        trace_scopes = _ResearchTraceScopes()
        try:
            return self._execute_pipeline_body(
                request,
                trace_context=trace_context,
                trace_correlation_degraded=trace_correlation_degraded,
                project_memory=project_memory,
                uploaded_context=uploaded_context,
                conversation_context=conversation_context,
                user_runtime_config=user_runtime_config,
                trace_scopes=trace_scopes,
            )
        except Exception as exc:
            trace_scopes.fail_open(exc)
            raise

    def _execute_pipeline_body(
        self,
        request: ResearchAgentRequest,
        *,
        trace_context: TraceContext,
        trace_correlation_degraded: bool = False,
        project_memory: Optional[Dict[str, Any]] = None,
        uploaded_context: Optional[Dict[str, Any]] = None,
        conversation_context: Optional[list[dict[str, Any]]] = None,
        user_runtime_config: Optional[Dict[str, Any]] = None,
        trace_scopes: _ResearchTraceScopes,
    ) -> Dict[str, Any]:
        run_started = time.perf_counter()
        query = request.query
        intent_started = time.perf_counter()
        context = conversation_context or []
        runtime_config = dict(user_runtime_config or {})
        instrumentation = trace_context.instrumentation()
        routing_span = instrumentation.span(
            stage=TraceStage.ROUTING,
            component="research_chat_service",
            operation="resolve_research_route",
            input_refs=[
                {
                    "record_type": "research_request",
                    "record_id": trace_context.request_id,
                    "relation": "routes",
                }
            ],
            exception_error_code="research_routing_failed",
        )
        trace_scopes.enter(routing_span)
        if trace_correlation_degraded:
            routing_span.add_decision(
                decision_type="correlation_adaptation",
                outcome="opaque_fallback",
                reason_code="sensitive_source_id_redacted",
                rule_version="trace_correlation_v0",
            )
        runtime_build = get_runtime_build_identity().model_dump(mode="json")
        conversation_state = resolve_conversation_task_state(
            context,
            runtime_build_id=str(runtime_build.get("source_fingerprint") or ""),
        )
        if _service_source_is_stale():
            _close_research_trace_span(
                routing_span,
                TraceStatus.BLOCKED,
                outcome="stale_build",
                reason_code="runtime_source_changed_restart_required",
            )
            return _stale_build_result(
                request=request,
                run_started=run_started,
                conversation_state=conversation_state,
            )
        if _is_system_info_query(query):
            _close_research_trace_span(
                routing_span,
                TraceStatus.SUCCESS,
                outcome="system_info",
                reason_code="system_runtime_question",
            )
            return _system_info_result(
                request=request,
                runtime_config=runtime_config,
                run_started=run_started,
            )
        if _is_product_capability_query(query):
            _close_research_trace_span(
                routing_span,
                TraceStatus.SUCCESS,
                outcome="product_capabilities",
                reason_code="product_capability_question",
            )
            return _product_capability_result(
                request=request,
                runtime_config=runtime_config,
                run_started=run_started,
            )
        reasoner = self._reasoner or ExternalResearchReasoner()
        explicit_task = _task_for_query(query)
        inheritable_task = (
            _task_from_context(context) if _can_inherit_task(query) else None
        )
        governed_task_anchor = explicit_task or inheritable_task
        intent = _classify_intent(query)
        governed_intent_anchor = _has_explicit_intent_signal(query, intent)
        preliminary_mode = _resolve_mode(
            query,
            intent=intent,
            requested_mode=request.mode,
        )
        action_safety = _action_safety_decision(query, mode=preliminary_mode)
        domain_decision = _query_domain(
            query,
            explicit_task=explicit_task,
            conversation_context=context,
        )
        if (
            _contains_incompatible_task_marker(query)
            and preliminary_mode is AgentMode.ASK
            and action_safety.verdict != "BLOCK"
            and not _requests_incompatible_action(query)
        ):
            _close_research_trace_span(
                routing_span,
                TraceStatus.SUCCESS,
                outcome="general_chat",
                reason_code="incompatible_topic_ask_only",
            )
            return _general_chat_result(
                request=request,
                runtime_config=runtime_config,
                conversation_context=context,
                reasoner=reasoner,
                run_started=run_started,
            )
        if action_safety.verdict == "BLOCK" or (
            _contains_incompatible_task_marker(query)
            and (
                preliminary_mode is not AgentMode.ASK
                or explicit_task is not None
                or _contains_catalog_tool(query)
                or _requests_incompatible_action(query)
            )
        ):
            route_reason = (
                action_safety.reason_codes[0]
                if action_safety.reason_codes
                else "tool_task_or_modality_incompatible"
            )
            _close_research_trace_span(
                routing_span,
                TraceStatus.BLOCKED,
                outcome="unsupported_action",
                reason_code=route_reason,
            )
            return _unsupported_action_result(
                request=request,
                mode=preliminary_mode,
                run_started=run_started,
                reason=route_reason,
                action_safety=action_safety,
                conversation_state=conversation_state,
            )
        if (
            domain_decision.domain == DomainKind.GENERAL.value
            and (
                not runtime_config.get("privacy_authorized")
                or domain_decision.confidence >= 0.9
            )
        ):
            if preliminary_mode is AgentMode.ASK:
                _close_research_trace_span(
                    routing_span,
                    TraceStatus.SUCCESS,
                    outcome="general_chat",
                    reason_code="complete_general_question",
                )
                return _general_chat_result(
                    request=request,
                    runtime_config=runtime_config,
                    conversation_context=context,
                    reasoner=reasoner,
                    run_started=run_started,
                )
            _close_research_trace_span(
                routing_span,
                TraceStatus.BLOCKED,
                outcome="unsupported_action",
                reason_code="task_outside_qualified_single_cell_action_space",
            )
            return _unsupported_action_result(
                request=request,
                mode=preliminary_mode,
                run_started=run_started,
                reason="task_outside_qualified_single_cell_action_space",
                action_safety=ActionSafetyDecision(
                    verdict="BLOCK",
                    reason_codes=["task_outside_qualified_single_cell_action_space"],
                ),
                conversation_state=conversation_state,
            )
        semantic_parse = SemanticParseResult(status="not_requested")
        if runtime_config.get("privacy_authorized") and hasattr(reasoner, "parse"):
            semantic_parse = reasoner.parse(
                query=_latest_followup_text(query),
                conversation_context=context,
                canonical_tasks=[item.task_id for item in CANONICAL_TASKS],
                runtime_config=runtime_config,
            )
        semantic_task = (
            canonical_task(semantic_parse.canonical_task)
            if semantic_parse.status == "ready" and semantic_parse.canonical_task
            else None
        )
        semantic_context_task = (
            semantic_task
            if semantic_task is not None
            and semantic_task.task_id == conversation_state.confirmed_task
            else None
        )
        governed_task_anchor = (
            governed_task_anchor or semantic_context_task
        )
        if semantic_parse.status == "ready":
            parsed_domain = (
                DomainKind.SINGLE_CELL
                if governed_task_anchor is not None
                else DomainKind(semantic_parse.domain)
            )
            domain_decision = DomainDecision(
                domain=parsed_domain,
                confidence=(
                    max(domain_decision.confidence, semantic_parse.confidence)
                    if governed_task_anchor is not None
                    else semantic_parse.confidence
                ),
                source=(
                    "conversation_context"
                    if (
                        (inheritable_task is not None or semantic_context_task is not None)
                        and explicit_task is None
                    )
                    else "local_rule"
                    if explicit_task is not None
                    else "semantic_parser"
                ),
                reason=(
                    "governed_single_cell_task_anchor_vetoed_llm_downgrade"
                    if governed_task_anchor is not None
                    else "domain_resolved_by_structured_llm"
                ),
                needs_clarification=(
                    False
                    if governed_task_anchor is not None
                    else semantic_parse.needs_clarification
                ),
            )
        if domain_decision.domain == DomainKind.GENERAL.value:
            if preliminary_mode is AgentMode.ASK:
                _close_research_trace_span(
                    routing_span,
                    TraceStatus.SUCCESS,
                    outcome="general_chat",
                    reason_code="semantic_general_route",
                )
                return _general_chat_result(
                    request=request,
                    runtime_config=runtime_config,
                    conversation_context=context,
                    reasoner=reasoner,
                    run_started=run_started,
                    semantic_parse=semantic_parse,
                )
            _close_research_trace_span(
                routing_span,
                TraceStatus.BLOCKED,
                outcome="unsupported_action",
                reason_code="task_outside_qualified_single_cell_action_space",
            )
            return _unsupported_action_result(
                request=request,
                mode=preliminary_mode,
                run_started=run_started,
                reason="task_outside_qualified_single_cell_action_space",
                action_safety=ActionSafetyDecision(
                    verdict="BLOCK",
                    reason_codes=["task_outside_qualified_single_cell_action_space"],
                ),
                conversation_state=conversation_state,
            )
        if (
            domain_decision.domain == DomainKind.UNCERTAIN.value
            or domain_decision.needs_clarification
            or (
                semantic_parse.status == "ready"
                and semantic_parse.confidence < 0.6
                and governed_task_anchor is None
            )
        ):
            _close_research_trace_span(
                routing_span,
                TraceStatus.PARTIAL,
                outcome="clarification_required",
                reason_code=domain_decision.reason,
            )
            return _clarification_result(
                request=request,
                mode=preliminary_mode,
                domain_decision=domain_decision,
                semantic_parse=semantic_parse,
                conversation_context=context,
                run_started=run_started,
            )
        if _contains_incompatible_task_marker(query):
            semantic_task = None
        task = explicit_task or inheritable_task or semantic_task
        task_source = (
            "explicit_query"
            if explicit_task
            else "elliptical_followup"
            if inheritable_task
            else "semantic_parser"
            if semantic_task
            else ""
        )
        task_id = task.task_id if task else ""
        if semantic_parse.status == "ready":
            semantic_intent = _semantic_intent(semantic_parse.intent)
            if semantic_intent is not None and not governed_intent_anchor:
                intent = semantic_intent
        mode = _resolve_mode(
            query,
            intent=intent,
            requested_mode=request.mode,
            semantic=None if governed_intent_anchor else semantic_parse,
        )
        intent_timing = _chat_timing(
            "intent",
            intent_started,
            detail=(
                f"mode={mode.value};intent={intent.value};task={task_id or 'unresolved'};"
                f"task_source={task_source or 'none'};semantic={semantic_parse.status}"
            ),
        )
        _close_research_trace_span(
            routing_span,
            TraceStatus.SUCCESS,
            outcome=f"{str(domain_decision.domain).lower()}_{mode.value.lower()}",
            reason_code=domain_decision.reason,
            record_ref=(
                {
                    "record_type": "canonical_task",
                    "record_id": task_id,
                    "relation": "selected",
                }
                if task_id
                else None
            ),
        )
        contextual_query = _retrieval_query(
            _contextual_query(
                query,
                context,
                task_id,
                referenced_tools=(
                    conversation_state.referenced_tools
                    if _is_evidence_followup(query)
                    else []
                ),
            ),
            task_id=task_id,
            intent=intent,
        )
        explicit_query_tools = _known_tools_in_query(query)
        required_claim_types = _claim_types_for_tool_query(query, intent)
        retrieval_span = instrumentation.span(
            stage=TraceStage.RETRIEVAL,
            component="research_chat_service",
            operation="retrieve_governed_evidence",
            exception_error_code="research_retrieval_failed",
        )
        trace_scopes.enter(retrieval_span)
        tool_plan = _research_tool_plan(
            semantic_parse=semantic_parse,
            query=contextual_query,
            task_id=task_id,
            intent=intent,
            mode=mode,
            referenced_tools=(
                conversation_state.referenced_tools
                if _is_evidence_followup(query) or _is_multi_tool_followup(query)
                else []
            ),
        )
        for call in tool_plan.calls:
            retrieval_span.add_input_ref(
                record_type="research_tool_call",
                record_id=call.call_id,
                relation="executes",
            )
        retrieval_decision = _adaptive_retrieval_decision(
            query=query,
            task_id=task_id,
            intent=intent,
            dense_available=self._dense_default_enabled,
        )
        retrieval_options = _retrieval_options(
            retrieval_decision,
            evaluation_profile=self._evaluation_retrieval_profile,
        )
        retrieval_decision = retrieval_options["decision"]
        tool_execution = self._research_tools.execute(
            tool_plan,
            fallback_query=contextual_query,
            fallback_task=task_id,
            enable_dense=retrieval_options["enable_dense"],
            use_kg=retrieval_options["use_kg"],
            use_governance_rerank=retrieval_options["use_governance_rerank"],
            use_contract_gate=retrieval_options["use_contract_gate"],
        )
        retrieval = tool_execution.retrieval
        if retrieval is None:
            retrieval = self.retrieval.search(
                HybridRetrievalRequest(
                    query=contextual_query,
                    tool_names=explicit_query_tools,
                    canonical_tasks=[task_id] if task_id else [],
                    claim_types=required_claim_types,
                    top_k=12,
                    include_catalog=False,
                    enable_dense=retrieval_options["enable_dense"],
                    nonblocking_dense=True,
                    use_kg=retrieval_options["use_kg"],
                    use_governance_rerank=retrieval_options[
                        "use_governance_rerank"
                    ],
                    use_contract_gate=retrieval_options["use_contract_gate"],
                )
            )
        source_bound_hits = sum(hit.source_bound for hit in retrieval.hits)
        worker_status = self.retrieval.embedding_worker_status
        if (
            not retrieval_decision.enable_dense
            and source_bound_hits == 0
            and self._dense_default_enabled
            and worker_status.state == "ready"
            and self._evaluation_retrieval_profile is None
        ):
            retrieval = self.retrieval.search(
                HybridRetrievalRequest(
                    query=contextual_query,
                    tool_names=explicit_query_tools,
                    canonical_tasks=[task_id] if task_id else [],
                    claim_types=required_claim_types,
                    top_k=12,
                    enable_dense=True,
                    nonblocking_dense=True,
                    use_kg=True,
                    use_governance_rerank=True,
                )
            )
            retrieval_decision = AdaptiveRetrievalDecision(
                route="kg_hybrid",
                enable_dense=True,
                reason="sparse_source_coverage_missing_escalated_to_ready_local_dense",
                escalated=True,
                source_bound_hits_before_escalation=source_bound_hits,
            )
        candidates = self._candidate_rows(retrieval, task_id)
        if intent in {
            ResearchChatIntent.TOOL_RECOMMENDATION,
            ResearchChatIntent.CAVEAT_COMPARISON,
        }:
            retrieval = _complete_top_tool_evidence(
                retrieval,
                retrieval_service=self.retrieval,
                query=contextual_query,
                task_id=task_id,
                claim_types=required_claim_types,
                tool_names=[row["tool_name"] for row in candidates[:3]],
                intent=intent,
                retrieval_options=retrieval_options,
            )
        requested_answer_tools = _requested_tools_for_answer(
            query=query,
            semantic_parse=semantic_parse,
            tool_plan=tool_plan,
            conversation_state=conversation_state,
            candidates=candidates,
        )
        if requested_answer_tools:
            order = {
                name.casefold(): index
                for index, name in enumerate(requested_answer_tools)
            }
            candidates.sort(
                key=lambda row: (
                    order.get(str(row.get("tool_name") or "").casefold(), len(order)),
                    -float(row.get("score") or 0.0),
                )
            )
        explicit_tool = _explicit_tool(query, candidates)
        if explicit_tool:
            candidates.sort(
                key=lambda row: row["tool_name"].casefold() != explicit_tool.casefold()
            )
            if (
                intent is ResearchChatIntent.CAVEAT_COMPARISON
                and "top" not in query.casefold()
                and len(requested_answer_tools) <= 1
            ):
                candidates = candidates[:1]
        for hit in retrieval.hits[:12]:
            retrieval_span.add_output_ref(
                record_type="evidence_chunk",
                record_id=hit.chunk_id,
                relation="retrieved",
            )
        if retrieval.index_build_id:
            retrieval_span.add_output_ref(
                record_type="retrieval_index",
                record_id=retrieval.index_build_id,
                relation="queried",
            )
        retrieval_span.set_counter("tool_call_count", len(tool_plan.calls))
        retrieval_span.set_counter(
            "observation_count",
            len(tool_execution.observations),
        )
        retrieval_span.set_counter("result_count", len(retrieval.hits))
        retrieval_span.set_counter(
            "source_bound_count",
            sum(hit.source_bound for hit in retrieval.hits),
        )
        incomplete_observation = any(
            observation.status in {"blocked", "failed"}
            for observation in tool_execution.observations
        )
        retrieval_status = (
            TraceStatus.BLOCKED
            if not retrieval.hits
            else TraceStatus.PARTIAL
            if incomplete_observation
            else TraceStatus.SUCCESS
        )
        _close_research_trace_span(
            retrieval_span,
            retrieval_status,
            decision_type="adaptive_retrieval",
            outcome=retrieval_decision.route,
            reason_code=(
                "retrieval_result_missing"
                if not retrieval.hits
                else "tool_observation_incomplete"
                if incomplete_observation
                else retrieval_decision.reason
            ),
            rule_version="adaptive_retrieval_v0",
        )
        snippets = [_legacy_snippet(hit) for hit in retrieval.hits]
        parent_started = time.perf_counter()
        if mode in {AgentMode.PLAN, AgentMode.RUN}:
            planning_span = instrumentation.span(
                stage=TraceStage.PLANNING,
                component="research_chat_service",
                operation="plan_if_requested",
                exception_error_code="research_planning_failed",
            )
            with planning_span:
                parent_result = self._plan_if_requested(
                    contextual_query,
                    task_id,
                    intent=intent,
                    mode=mode,
                    request=request,
                )
                profile = parent_result.get("data_profile") or {}
                if isinstance(profile, dict) and profile.get("profile_id"):
                    planning_span.add_output_ref(
                        record_type="data_profile",
                        record_id=profile["profile_id"],
                        relation="planning_context",
                    )
                for bundle in list(parent_result.get("action_bundles") or [])[:8]:
                    if not isinstance(bundle, dict):
                        continue
                    if bundle.get("bundle_id"):
                        planning_span.add_input_ref(
                            record_type="action_bundle",
                            record_id=bundle["bundle_id"],
                            relation="planning_context",
                        )
                    if bundle.get("contract_id"):
                        planning_span.add_input_ref(
                            record_type="tool_contract",
                            record_id=bundle["contract_id"],
                            relation="planning_context",
                        )
                workflow_plan = parent_result.get("workflow_plan") or {}
                if isinstance(workflow_plan, dict) and workflow_plan.get("plan_id"):
                    planning_span.add_output_ref(
                        record_type="workflow_plan",
                        record_id=workflow_plan["plan_id"],
                        relation="planned",
                    )
                unified_trace = parent_result.get("_unified_trace") or {}
                if (
                    not trace_correlation_degraded
                    and isinstance(unified_trace, dict)
                    and unified_trace.get("trace_id")
                ):
                    instrumentation.add_link(
                        link_type=TraceLinkType.UNIFIED_AGENT_TRACE,
                        target_type="unified_agent_trace",
                        target_id=unified_trace["trace_id"],
                    )
                planning_span.set_counter(
                    "execution_request_count",
                    int(parent_result.get("execution_request_count") or 0),
                )
                parent_status = str(parent_result.get("status") or "BLOCKED")
                planning_status = (
                    TraceStatus.SUCCESS
                    if parent_status == "READY"
                    else TraceStatus.PARTIAL
                    if parent_status == "WAITING"
                    else TraceStatus.FAILED
                    if parent_status == "FAILED"
                    else TraceStatus.BLOCKED
                )
                _finish_research_trace_span(
                    planning_span,
                    planning_status,
                    decision_type="planning_result",
                    outcome=parent_status.lower(),
                    reason_code=str(parent_result.get("route") or "planning_blocked").lower(),
                    rule_version="research_planning_v0",
                    error_code=(
                        "planner_reported_failure"
                        if planning_status is TraceStatus.FAILED
                        else None
                    ),
                )
        else:
            parent_result = self._plan_if_requested(
                contextual_query,
                task_id,
                intent=intent,
                mode=mode,
                request=request,
            )
        parent_timing = _chat_timing(
            "parent_planning",
            parent_started,
            status=(
                "completed"
                if mode in {AgentMode.PLAN, AgentMode.RUN}
                else "skipped"
            ),
            detail=f"route={parent_result.get('route', '')}",
        )
        blockers = list(parent_result.get("blockers") or [])
        if not task_id:
            blockers.append("canonical_task_unresolved")
        if not any(hit.source_bound for hit in retrieval.hits):
            blockers.append("source_bound_context_missing")
        if retrieval_decision.enable_dense and retrieval.dense_status != "ready":
            blockers.append("dense_worker_not_ready_using_kg_bm25")
        blockers = list(dict.fromkeys(blockers))
        compose_started = time.perf_counter()
        algorithm_cards = [_algorithm_card(row, snippets) for row in candidates[:5]]
        migration_paths = _migration_paths(intent, query, task_id, candidates)
        requested_tool_keys = {name.casefold() for name in requested_answer_tools}
        reference_candidates = (
            [
                row
                for row in candidates
                if row["tool_name"].casefold() in requested_tool_keys
            ]
            if len(requested_tool_keys) >= 2
            else [
                row
                for row in candidates
                if row["tool_name"].casefold() == explicit_tool.casefold()
            ]
            if explicit_tool
            else candidates
        )
        response_intent = (
            ResearchChatIntent.WORKFLOW
            if mode in {AgentMode.PLAN, AgentMode.RUN}
            else intent
        )
        reference_tools = requested_answer_tools or explicit_query_tools
        if response_intent is ResearchChatIntent.EVIDENCE_QA:
            evidence_claim_targets = (
                _requested_claim_targets(query, reference_tools)
                if reference_tools
                else _entityless_claim_targets(query, snippets)
            )
            evidence_entities = list(
                dict.fromkeys(target.entity for target in evidence_claim_targets)
            )
        else:
            evidence_claim_targets = []
            evidence_entities = reference_tools
        evidence_bindings = (
            _select_claim_evidence_bindings(
                snippets,
                targets=evidence_claim_targets,
                query=query,
            )
            if response_intent is ResearchChatIntent.EVIDENCE_QA
            else []
        )
        references = _references(
            snippets,
            reference_candidates,
            query=query,
            intent=response_intent,
            requested_tools=evidence_entities,
            claim_bindings=evidence_bindings,
        )
        workflow_code_bundle = (
            tool_execution.workflow_bundles[0]
            if tool_execution.workflow_bundles
            else None
        )
        if workflow_code_bundle is None and mode is AgentMode.PLAN:
            fixed_bundle = self._workflow_code.get_bundle(
                task_id=task_id,
                preferred_tool=explicit_tool,
            )
            workflow_code_bundle = (
                fixed_bundle.model_dump(mode="json")
                if fixed_bundle is not None
                else None
            )
        report = _report(
            intent=response_intent,
            query=query,
            task_id=task_id,
            task_label=task.label if task else "Unresolved task",
            algorithm_cards=algorithm_cards,
            migration_paths=migration_paths,
            references=references,
            blockers=blockers,
            parent_result=parent_result,
            retrieval_snippets=snippets,
            workflow_code_bundle=workflow_code_bundle,
            requested_tools=requested_answer_tools,
            claim_bindings=evidence_bindings,
        )
        external_reasoning = ExternalReasoningResult(status="not_requested")
        grounded_answer_audit = _audit_grounded_answer_v3(
            report,
            references=references,
            execution_request_count=int(
                parent_result.get("execution_request_count") or 0
            ),
        ).model_dump(mode="json")
        rejected_external_answer_audit: Optional[dict[str, Any]] = None
        external_answer_used = False
        if (
            runtime_config.get("privacy_authorized")
            and mode is AgentMode.ASK
            and intent is not ResearchChatIntent.MIGRATION_EXPLORATION
            and bool(task_id)
            and hasattr(reasoner, "synthesize")
        ):
            external_reasoning = reasoner.synthesize(
                query=_latest_followup_text(query),
                intent=intent.value,
                task_label=task.label if task else "Unresolved task",
                algorithm_cards=algorithm_cards,
                retrieval_snippets=_synthesis_snippets(snippets, references),
                references=references,
                blockers=blockers,
                tool_observations=[
                    item.model_dump(mode="json")
                    for item in tool_execution.observations
                ],
                contract_context=tool_execution.contract_context,
                requested_tools=requested_answer_tools or explicit_query_tools,
                required_claim_types=required_claim_types,
                allow_unverified_model_knowledge=True,
                runtime_config=runtime_config,
            )
            if external_reasoning.status == "ready":
                external_answer_audit = _audit_grounded_answer_v3(
                    external_reasoning.content,
                    references=references,
                    execution_request_count=int(parent_result.get("execution_request_count") or 0),
                ).model_dump(mode="json")
                answer_shape_valid = (
                    intent is not ResearchChatIntent.CAVEAT_COMPARISON
                    or _top_k_answer_is_valid(query, external_reasoning.content)
                )
                requested_tool_coverage_valid = _requested_tool_coverage_is_valid(
                    query,
                    external_reasoning.content,
                    requested_answer_tools,
                )
                answer_shape_valid = (
                    answer_shape_valid and requested_tool_coverage_valid
                )
                if not answer_shape_valid:
                    external_answer_audit["passed"] = False
                    reason = (
                        "requested_tool_coverage_mismatch"
                        if not requested_tool_coverage_valid
                        else "requested_top_k_format_mismatch"
                    )
                    external_answer_audit.setdefault("reasons", []).append(reason)
                    external_answer_audit["governance_violation_count"] = int(
                        external_answer_audit.get("governance_violation_count") or 0
                    ) + 1
                if external_answer_audit["passed"]:
                    report = external_reasoning.content
                    grounded_answer_audit = external_answer_audit
                    external_answer_used = True
                else:
                    rejected_external_answer_audit = external_answer_audit
        compose_timing = _chat_timing(
            "answer_compose",
            compose_started,
            detail=f"runtime={external_reasoning.status}",
        )
        stage_timings = [
            intent_timing,
            *retrieval.stage_timings,
            parent_timing,
            compose_timing,
        ]
        context_pack = {
            "retrieval_context": {
                "mode": retrieval.mode,
                "pipeline": retrieval.pipeline,
                "snippets": snippets,
                "latency_ms": retrieval.latency_ms,
                "dense_status": retrieval.dense_status,
                "governance_leakage_count": retrieval.governance_leakage_count,
                "adaptive_decision": retrieval_decision.model_dump(mode="json"),
                "embedding_worker": self.retrieval.embedding_worker_status.model_dump(
                    mode="json"
                ),
                "stage_timings": [
                    item.model_dump(mode="json") for item in retrieval.stage_timings
                ],
            },
            "missing_evidence": [
                blocker
                for blocker in blockers
                if blocker in {"canonical_task_unresolved", "source_bound_context_missing"}
            ],
            "memory_context": {
                "explicit_preferences": project_memory or {},
                "can_affect_scientific_authority": False,
            },
            "conversation_turns_used": len(context),
            "uploaded_context_present": bool(uploaded_context),
            "external_reasoning": external_reasoning.model_dump(
                mode="json",
                exclude={"content"},
            ),
            "semantic_parse": semantic_parse.model_dump(mode="json"),
            "research_tool_plan": tool_plan.model_dump(mode="json"),
            "research_tool_observations": [
                item.model_dump(mode="json")
                for item in tool_execution.observations
            ],
            "tool_contract_context": tool_execution.contract_context,
            "capability_context": tool_execution.capability_context,
            "semantic_route": {
                "domain": domain_decision.domain,
                "confidence": domain_decision.confidence,
                "source": domain_decision.source,
                "reason": domain_decision.reason,
                "needs_clarification": domain_decision.needs_clarification,
            },
            "grounded_answer_audit": grounded_answer_audit,
            "rejected_external_answer_audit": rejected_external_answer_audit,
            "action_safety": action_safety.model_dump(mode="json"),
            "external_provider_call_count": int(
                semantic_parse.provider_call_attempted
            )
            + int(external_reasoning.provider_call_attempted),
            "chat_stage_timings": [
                item.model_dump(mode="json") for item in stage_timings
            ],
            "total_latency_ms": round(
                (time.perf_counter() - run_started) * 1000.0,
                3,
            ),
        }
        answerability = _answerability_decision(
            mode=mode,
            domain=DomainKind.SINGLE_CELL,
            action_safety=action_safety,
            source_bound_context_available=bool(references),
            external_reasoning=external_reasoning,
        )
        context_pack["answerability"] = answerability.model_dump(mode="json")
        audit_claims = list(grounded_answer_audit.get("claims") or [])
        task_switched = bool(
            task_id
            and conversation_state.confirmed_task
            and task_id != conversation_state.confirmed_task
        )
        updated_conversation_state = next_conversation_task_state(
            conversation_state,
            domain=DomainKind.SINGLE_CELL,
            task=task_id,
            referenced_tools=[item["tool_name"] for item in candidates[:5]],
            claim_ids=[
                str(item.get("claim_id"))
                for item in audit_claims
                if isinstance(item, dict) and item.get("claim_id")
            ],
            plan_id=(
                str((parent_result.get("workflow_plan") or {}).get("plan_id"))
                if isinstance(parent_result.get("workflow_plan"), dict)
                and (parent_result.get("workflow_plan") or {}).get("plan_id")
                else None
            ),
            action_bundle_ids=[
                str(item.get("bundle_id"))
                for item in parent_result.get("action_bundles", [])
                if isinstance(item, dict) and item.get("bundle_id")
            ],
            task_switched=task_switched,
        )
        context_pack["conversation_state"] = updated_conversation_state.model_dump(
            mode="json"
        )
        return {
            "user_query": query,
            "agent_mode": mode.value,
            "request_id": request.request_id,
            "conversation_id": request.conversation_id,
            "user_id": request.user_id,
            "response_intent": intent.value,
            "extracted_constraints": {
                "task": task.label if task else "Unknown",
                "canonical_task": task_id or "Unknown",
                "modality": "scRNA-seq",
            },
            "candidate_tools": [item["tool_name"] for item in candidates],
            "tool_candidates": candidates,
            "algorithm_cards": algorithm_cards,
            "retrieval_results": snippets,
            "references": references,
            "scored_tools": candidates,
            "migration_paths": migration_paths,
            "workflow_recommendations": [],
            "workflow_plan": parent_result.get("workflow_plan"),
            "workflow_code_bundle": workflow_code_bundle,
            "deterministic_parent_result": parent_result,
            "decision_report": None,
            "final_report": report,
            "hallucination_audit": {
                "passed": retrieval.governance_leakage_count == 0,
                "issues": [],
                "authority": "deterministic_evidence_boundary",
            },
            "context_pack": context_pack,
            "current_step": "complete",
            "error_message": None,
            "runtime_mode": (
                "external_reasoning_with_deterministic_governance"
                if external_answer_used
                else "external_semantic_with_deterministic_governance"
                if semantic_parse.status == "ready"
                else "degraded_local_fallback"
            ),
        }

    def _graph_gateway(self, payload: dict[str, Any]) -> dict[str, Any]:
        request: ResearchAgentRequest = payload["request"]
        intent = _classify_intent(request.query)
        mode = _resolve_mode(request.query, intent=intent, requested_mode=request.mode)
        return {
            "turn": {
                "mode": mode.value,
                "intent": intent.value,
                "request_id": request.request_id,
            }
        }

    def _graph_requirement_parse(self, payload: dict[str, Any]) -> dict[str, Any]:
        request: ResearchAgentRequest = payload["request"]
        context = payload.get("conversation_context") or []
        task = _task_for_query(request.query)
        if task is None and _can_inherit_task(request.query):
            task = _task_from_context(context)
        turn = dict(payload.get("turn") or {})
        turn.update(
            {
                "task_id": task.task_id if task else "",
                "task_label": task.label if task else "Unresolved task",
                "modality": "scRNA-seq",
            }
        )
        return {"turn": turn}

    def _graph_action_retrieval(self, payload: dict[str, Any]) -> dict[str, Any]:
        legacy_result = self._execute_pipeline(
            payload["request"],
            trace_context=payload["trace_context"],
            trace_correlation_degraded=bool(
                payload.get("trace_correlation_degraded")
            ),
            project_memory=payload.get("project_memory"),
            uploaded_context=payload.get("uploaded_context"),
            conversation_context=payload.get("conversation_context"),
            user_runtime_config=payload.get("user_runtime_config"),
        )
        return {"legacy_result": legacy_result}

    def _graph_plan_compile(self, payload: dict[str, Any]) -> dict[str, Any]:
        result = payload["legacy_result"]
        parent = dict(result.get("deterministic_parent_result") or {})
        return {"parent": parent}

    def _graph_deterministic_route(self, payload: dict[str, Any]) -> dict[str, Any]:
        parent = dict(payload.get("parent") or {})
        return {
            "parent": {
                **parent,
                "route": parent.get("route") or "BLOCKED",
                "execution_request_count": int(
                    parent.get("execution_request_count") or 0
                ),
            }
        }

    def _graph_answer_or_handoff(
        self,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        graph_runtime = (
            self._application_graph.runtime
            if self._application_graph is not None
            else "deterministic_graph"
        )
        response = self._response_from_legacy(
            payload["request"],
            payload["legacy_result"],
            trace_context=payload["trace_context"],
            trace_correlation_degraded=bool(
                payload.get("trace_correlation_degraded")
            ),
            visited_nodes=[*payload.get("visited_nodes", []), "answer_or_handoff"],
            graph_runtime=graph_runtime,
        )
        return {"response": response}

    @staticmethod
    def _response_from_legacy(
        request: ResearchAgentRequest,
        result: dict[str, Any],
        *,
        trace_context: TraceContext,
        trace_correlation_degraded: bool,
        visited_nodes: list[str],
        graph_runtime: str,
    ) -> ResearchAgentResponse:
        parent = dict(result.get("deterministic_parent_result") or {})
        plan = result.get("workflow_plan") or None
        profile = parent.get("data_profile") or None
        mode = AgentMode(result.get("agent_mode") or AgentMode.ASK.value)
        parent_status = str(parent.get("status") or "ANSWERED")
        blockers = list(dict.fromkeys(parent.get("blockers") or []))
        next_actions = list(parent.get("next_actions") or [])
        if (
            mode is AgentMode.RUN
            and not request.artifact_id
            and parent_status not in {"BLOCKED", "FAILED"}
        ):
            blockers.append("registered_artifact_required_for_run")
            next_actions.insert(0, "Register or select a local AnnData artifact before RUN.")
        router_route = str(parent.get("route") or "") or None
        if parent_status in {"BLOCKED", "FAILED"} and str(parent.get("route")) == "UNSUPPORTED_ACTION":
            status = parent_status
            handoff_status = "blocked"
        elif parent_status == "WAITING":
            status = "WAITING"
            handoff_status = "waiting"
        elif mode is AgentMode.ASK:
            status = "ANSWERED"
            handoff_status = "not_requested"
        elif parent_status in {"BLOCKED", "FAILED"}:
            status = parent_status
            handoff_status = "blocked"
        elif mode is AgentMode.RUN and not request.artifact_id:
            status = "WAITING"
            handoff_status = "waiting"
        else:
            status = "READY"
            handoff_status = "ready" if mode is AgentMode.RUN else "not_requested"
        action_bundles = list(parent.get("action_bundles") or [])
        action_bundle_ids = [
            str(row.get("bundle_id"))
            for row in action_bundles
            if isinstance(row, dict) and row.get("bundle_id")
        ]
        context_pack = dict(result.get("context_pack") or {})
        retrieval_context = dict(context_pack.get("retrieval_context") or {})
        evidence_chunk_ids = [
            str(row.get("chunk_id"))
            for row in retrieval_context.get("snippets", [])
            if row.get("chunk_id")
        ]
        trace = parent.pop("_unified_trace", None)
        trace_ids = [trace["trace_id"]] if isinstance(trace, dict) else []
        application_graph_id = (
            "application-graph:"
            + hashlib.sha256(
                f"{trace_context.request_id}:{','.join(visited_nodes)}".encode("utf-8")
            ).hexdigest()[:16]
        )
        trace_ids.append(application_graph_id)
        trace_context.instrumentation().add_link(
            link_type=TraceLinkType.APPLICATION_GRAPH_ALIAS,
            target_type="application_graph",
            target_id=application_graph_id,
        )
        context_pack["application_graph"] = {
            "runtime": graph_runtime,
            "visited_nodes": visited_nodes,
            "same_business_nodes_with_or_without_langgraph": True,
        }
        conversation_state = ConversationTaskState.model_validate(
            context_pack.get("conversation_state")
            or {
                "confirmed_domain": (
                    (context_pack.get("semantic_route") or {}).get("domain")
                    or DomainKind.UNCERTAIN.value
                ),
                "confirmed_task": str(
                    (result.get("extracted_constraints") or {}).get("canonical_task")
                    or ""
                ).replace("Unknown", ""),
                "referenced_tools": list(result.get("candidate_tools") or [])[:8],
                "runtime_build_id": str(
                    get_runtime_build_identity().source_fingerprint
                ),
            }
        )
        cards = list(result.get("algorithm_cards") or [])
        applicability = [
            str(card.get("best_for")) for card in cards[:3] if card.get("best_for")
        ]
        limitations = list(
            dict.fromkeys(
                [
                    str(caveat)
                    for card in cards[:3]
                    for caveat in card.get("caveats", [])[:1]
                ]
                + blockers
            )
        )
        direct_answer = str(result.get("final_report") or "")
        if (
            mode is AgentMode.RUN
            and not request.artifact_id
            and parent_status not in {"BLOCKED", "FAILED"}
        ):
            direct_answer = (
                "**尚未执行。** 当前没有绑定已登记的 AnnData artifact，"
                "因此系统只完成了数据无关的计划检查，未创建 ExecutionRequest。\n\n"
                "- 当前状态：`WAITING`\n"
                "- ExecutionRequest：`0`\n"
                "- 下一步：在受限本地执行区登记或选择数据，完成数据访问授权，"
                "然后重新确认由该数据画像生成的 plan-specific approval。\n\n"
                + direct_answer
            )
        state = ResearchAgentState(
            request_id=request.request_id,
            conversation_id=request.conversation_id,
            user_id=request.user_id,
            mode=mode,
            domain=DomainKind(
                str(
                    (context_pack.get("semantic_route") or {}).get("domain")
                    or (
                        DomainKind.GENERAL.value
                        if str(result.get("response_intent") or "")
                        in {"general_chat", "system_info", "product_capabilities"}
                        else DomainKind.SINGLE_CELL.value
                    )
                )
            ),
            intent=str(result.get("response_intent") or "evidence_qa"),
            task=str(
                (result.get("extracted_constraints") or {}).get("canonical_task")
                or ""
            ).replace("Unknown", ""),
            artifact_id=request.artifact_id,
            profile_id=profile.get("profile_id") if isinstance(profile, dict) else None,
            retrieval_route=str(
                (retrieval_context.get("adaptive_decision") or {}).get("route")
                or retrieval_context.get("mode")
                or ""
            ),
            evidence_chunk_ids=evidence_chunk_ids,
            action_bundle_ids=action_bundle_ids,
            plan_id=plan.get("plan_id") if isinstance(plan, dict) else None,
            router_route=router_route,
            approval_status=(
                "required"
                if mode is AgentMode.RUN and status in {"WAITING", "READY"}
                else "not_requested"
            ),
            blockers=blockers,
            next_actions=next_actions,
            trace_ids=trace_ids,
            canonical_trace_id=trace_context.trace_id,
            conversation_state=conversation_state,
        )
        build_identity = get_runtime_build_identity().model_dump(mode="json")
        context_pack["runtime_build"] = build_identity
        claim_audit = dict(context_pack.get("grounded_answer_audit") or {})
        semantic_payload = dict(context_pack.get("semantic_route") or {})
        semantic_route = SemanticRouteDecision(
            domain=state.domain,
            intent=state.intent,
            task=state.task,
            confidence=float(semantic_payload.get("confidence") or 0.0),
            needs_clarification=bool(semantic_payload.get("needs_clarification")),
            source=str(semantic_payload.get("source") or "local_rule"),
        )
        action_safety = ActionSafetyDecision.model_validate(
            context_pack.get("action_safety") or {}
        )
        answerability = AnswerabilityDecision.model_validate(
            context_pack.get("answerability")
            or {
                "verdict": "CLARIFY" if status == "WAITING" else "BLOCK" if status == "BLOCKED" else "ANSWER_VERIFIED",
                "reason_codes": blockers,
                "verified_context_available": bool(result.get("references")),
            }
        )
        verified_claims = list(claim_audit.get("verified_claims") or [])
        unverified_claims = list(
            claim_audit.get("unverified_model_knowledge_claims") or []
        )
        workflow_bundle = result.get("workflow_code_bundle") or {}
        capability_handoff = _capability_workspace_handoff(
            context_pack=context_pack,
            mode=mode,
            task=state.task,
            plan_id=plan.get("plan_id") if isinstance(plan, dict) else None,
            query=request.query,
        )
        workspace_handoff = capability_handoff or ({
            "status": "available",
            "task_family": state.task,
            "tool_name": workflow_bundle.get("tool_name"),
            "plan_id": plan.get("plan_id") if isinstance(plan, dict) else None,
            "notebook_strategy": "fixed_shadow",
            "stepwise_preview_available": True,
        } if (
            state.task == "doublet_detection"
            and workflow_bundle.get("tool_name") == "Scrublet"
            and bool(workflow_bundle.get("smoke_tested"))
        ) else {
            "status": "not_applicable",
            "task_family": state.task,
            "tool_name": workflow_bundle.get("tool_name"),
            "blockers": ["task_specific_workspace_not_available"]
            if workflow_bundle
            else [],
        })
        if workspace_handoff.get("status") == "available":
            handoff_id = f"research-handoff:{uuid.uuid4().hex}"
            original_plan_id = (
                plan.get("plan_id") if isinstance(plan, dict) else None
            )
            workspace_handoff.update(
                {
                    "handoff_id": handoff_id,
                    "origin_trace_id": trace_context.trace_id,
                    "parent_request_id": trace_context.request_id,
                    "original_plan_id": original_plan_id,
                }
            )
            instrumentation = trace_context.instrumentation()
            with instrumentation.span(
                stage=TraceStage.HANDOFF,
                component="research_chat_service",
                operation="create_workspace_handoff",
                input_refs=(
                    [
                        {
                            "record_type": "workflow_plan",
                            "record_id": original_plan_id,
                            "relation": "origin",
                        }
                    ]
                    if original_plan_id
                    else []
                ),
                exception_error_code="research_handoff_failed",
            ) as handoff_span:
                handoff_span.add_output_ref(
                    record_type="research_workspace_handoff",
                    record_id=handoff_id,
                    relation="created",
                )
                handoff_span.set_counter(
                    "target_count",
                    len(workspace_handoff.get("target_representations") or []),
                )
                _finish_research_trace_span(
                    handoff_span,
                    TraceStatus.SUCCESS,
                    decision_type="workspace_handoff",
                    outcome="data_preview",
                    reason_code="workspace_handoff_available",
                    rule_version="research_handoff_v0",
                )
            if original_plan_id:
                instrumentation.add_link(
                    link_type=TraceLinkType.ORIGIN_PLAN,
                    target_type="workflow_plan",
                    target_id=original_plan_id,
                )
        return ResearchAgentResponse(
            state=state,
            canonical_trace_id=trace_context.trace_id,
            user_query=request.query,
            status=status,
            direct_answer=direct_answer,
            applicability=applicability,
            limitations=limitations,
            references=list(result.get("references") or []),
            candidate_tools=list(result.get("candidate_tools") or []),
            tool_candidates=list(result.get("tool_candidates") or []),
            algorithm_cards=cards,
            migration_hypotheses=list(result.get("migration_paths") or []),
            workflow_plan=plan,
            workflow_code_bundle=result.get("workflow_code_bundle") or None,
            evidence_context_pack=context_pack,
            parent_result=parent,
            execution_handoff=ExecutionHandoff(
                status=handoff_status,
                artifact_id=request.artifact_id,
                profile_id=profile.get("profile_id") if isinstance(profile, dict) else None,
                plan_id=plan.get("plan_id") if isinstance(plan, dict) else None,
                router_route=router_route,
                approval_required=mode is AgentMode.RUN and status in {"WAITING", "READY"},
                execution_request_count=int(parent.get("execution_request_count") or 0),
                blockers=blockers,
                next_actions=next_actions,
            ),
            workspace_handoff=workspace_handoff,
            trace=trace,
            runtime_mode=str(result.get("runtime_mode") or "degraded_local_fallback"),
            claim_audit=claim_audit,
            runtime_build=build_identity,
            semantic_route=semantic_route,
            action_safety=action_safety,
            answerability=answerability,
            verified_claims=verified_claims,
            unverified_model_knowledge_claims=unverified_claims,
        )

    @staticmethod
    def _legacy_response(response: ResearchAgentResponse) -> dict[str, Any]:
        state = response.state
        context_pack = dict(response.evidence_context_pack)
        parent = dict(response.parent_result)
        if response.trace is not None:
            parent["_unified_trace"] = response.trace
        return {
            "user_query": response.user_query,
            "agent_mode": state.mode,
            "domain": state.domain,
            "request_id": state.request_id,
            "conversation_id": state.conversation_id,
            "canonical_trace_id": response.canonical_trace_id,
            "user_id": state.user_id,
            "response_intent": state.intent,
            "extracted_constraints": {
                "task": state.task or "Unknown",
                "canonical_task": state.task or "Unknown",
                "modality": state.modality,
            },
            "candidate_tools": response.candidate_tools,
            "tool_candidates": response.tool_candidates,
            "algorithm_cards": response.algorithm_cards,
            "retrieval_results": (
                context_pack.get("retrieval_context", {}).get("snippets", [])
            ),
            "references": response.references,
            "scored_tools": response.tool_candidates,
            "migration_paths": response.migration_hypotheses,
            "workflow_recommendations": [],
            "workflow_plan": response.workflow_plan,
            "workflow_code_bundle": response.workflow_code_bundle,
            "deterministic_parent_result": parent,
            "decision_report": None,
            "final_report": response.direct_answer,
            "hallucination_audit": {
                "passed": (
                    context_pack.get("retrieval_context", {}).get(
                        "governance_leakage_count", 0
                    )
                    == 0
                ),
                "issues": [],
                "authority": "deterministic_evidence_boundary",
            },
            "context_pack": context_pack,
            "execution_handoff": response.execution_handoff.model_dump(mode="json"),
            "workspace_handoff": response.workspace_handoff.model_dump(mode="json"),
            "current_step": "complete",
            "error_message": None,
            "runtime_mode": response.runtime_mode,
            "claim_audit": response.claim_audit,
            "runtime_build": response.runtime_build,
            "conversation_state": state.conversation_state.model_dump(mode="json"),
            "semantic_route": (
                response.semantic_route.model_dump(mode="json")
                if response.semantic_route is not None
                else None
            ),
            "action_safety": response.action_safety.model_dump(mode="json"),
            "answerability": response.answerability.model_dump(mode="json"),
            "verified_claims": response.verified_claims,
            "unverified_model_knowledge_claims": response.unverified_model_knowledge_claims,
        }

    def _candidate_rows(self, result: Any, task_id: str) -> list[dict[str, Any]]:
        rows = _retrieval_candidate_rows(result)
        if not task_id:
            return rows
        try:
            graph = (
                self._graph_query
                or getattr(self.retrieval, "_graph_query", None)
                or EvidenceGraphQuery()
            )
            self._graph_query = graph
            matches = graph.rank_tools(
                task=task_id,
                modality="scRNA-seq",
                limit=12,
                include_hypotheses=True,
            )
        except Exception:
            matches = []
        by_name = {row["tool_name"].casefold(): row for row in rows}
        governed: list[dict[str, Any]] = []
        for match in matches:
            row = by_name.pop(match.tool_name.casefold(), {})
            governed.append(
                {
                    **row,
                    "tool_name": match.tool_name,
                    "score": max(float(row.get("score") or 0.0), match.graph_score),
                    "graph_score": match.graph_score,
                    "source_chunk_count": max(
                        int(row.get("source_chunk_count") or 0),
                        match.source_chunk_count,
                    ),
                    "canonical_tasks": sorted(
                        set(row.get("canonical_tasks") or []) | {task_id}
                    ),
                    "candidate_basis": match.candidate_basis,
                    "contract_available": match.contract_available,
                    "scientific_pilot_available": match.scientific_pilot_available,
                    "warnings": list(match.warnings),
                    "evidence": {
                        "retrieval_only": match.candidate_basis != "execution_verified",
                        "can_affect_scientific_authority": False,
                    },
                }
            )
        governed.extend(by_name.values())
        return governed[:8]

    def _plan_if_requested(
        self,
        query: str,
        task_id: str,
        *,
        intent: ResearchChatIntent,
        mode: AgentMode,
        request: ResearchAgentRequest,
    ) -> Dict[str, Any]:
        if not task_id:
            return {
                "status": "BLOCKED",
                "route": "EVIDENCE_RECOVERY",
                "blockers": ["canonical_task_unresolved"],
                "next_actions": ["Clarify the scientific task before planning or recommendation."],
                "execution_request_count": 0,
                "workflow_plan": None,
            }
        if mode is AgentMode.ASK:
            return {
                "status": "ANSWERED",
                "route": intent.value.upper(),
                "blockers": [],
                "next_actions": [],
                "execution_request_count": 0,
                "workflow_plan": None,
            }
        try:
            if self._parent_agent is None:
                with self._parent_lock:
                    if self._parent_agent is None:
                        self._parent_agent = BoundedParentAgent()
                        self._audited_parent = AuditedParentAgent(self._parent_agent)
            agent = self._parent_agent
            parent_request = ParentAgentRequest(
                request_id=request.request_id,
                user_id=request.user_id,
                query=query,
                artifact_id=request.artifact_id,
                data_grant_id=request.data_grant_id,
                execution_approval_id=request.execution_approval_id,
                requested_tool=request.requested_tool,
                parameters=request.parameters,
            )
            if self._audited_parent is not None:
                result, trace = self._audited_parent.plan(
                    parent_request,
                    case_id=f"research-{mode.value.casefold()}",
                )
                payload = result.model_dump(mode="json")
                payload["_unified_trace"] = trace.model_dump(mode="json")
                return payload
            result = agent.run(parent_request)
            return result.model_dump(mode="json")
        except Exception as exc:
            return {
                "status": "BLOCKED",
                "route": "CONTRACT_REVIEW",
                "blockers": [f"deterministic_planner_unavailable:{type(exc).__name__}"],
                "next_actions": ["Use retrieval context while the planning projection is repaired."],
                "execution_request_count": 0,
            }


def _research_tool_plan(
    *,
    semantic_parse: SemanticParseResult,
    query: str,
    task_id: str,
    intent: ResearchChatIntent,
    mode: AgentMode,
    referenced_tools: list[str],
) -> ResearchToolPlan:
    explicit_tools = _known_tools_in_query(query)
    requested_tools = list(
        dict.fromkeys(
            [*explicit_tools, *semantic_parse.requested_tools, *referenced_tools]
        )
    )[:5]
    calls: list[ResearchToolCall] = []
    if semantic_parse.status == "ready":
        for call in semantic_parse.tool_calls:
            if call.tool_name == "compile_workflow" and (
                mode is AgentMode.ASK
                or task_id not in {"doublet_detection", "batch_integration"}
            ):
                continue
            calls.append(
                call.model_copy(
                    update={
                        "query": call.query or query,
                        "canonical_task": call.canonical_task or task_id,
                        "tool_names": call.tool_names or requested_tools,
                    }
                )
            )

    has_search = any(
        call.tool_name in {"search_catalog", "search_evidence"} for call in calls
    )
    if not has_search:
        search_name = (
            "search_catalog"
            if intent
            in {
                ResearchChatIntent.TOOL_RECOMMENDATION,
                ResearchChatIntent.MIGRATION_EXPLORATION,
            }
            else "search_evidence"
        )
        calls.insert(
            0,
            ResearchToolCall(
                call_id="local-tool-search",
                tool_name=search_name,
                query=query,
                canonical_task=task_id,
                tool_names=requested_tools,
                claim_types=_claim_types_for_tool_query(query, intent),
                top_k=12,
                reason="required_grounding_for_single_cell_answer",
            ),
        )

    if mode in {AgentMode.PLAN, AgentMode.RUN} and not any(
        call.tool_name == "discover_capabilities" for call in calls
    ):
        calls.append(
            ResearchToolCall(
                call_id="local-capability-discovery",
                tool_name="discover_capabilities",
                query=query,
                canonical_task=task_id,
                tool_names=requested_tools,
                reason="plan_checks_registered_capability_packs_before_handoff",
            )
        )
    if mode in {AgentMode.PLAN, AgentMode.RUN} and not any(
        call.tool_name == "get_tool_contract" for call in calls
    ):
        calls.append(
            ResearchToolCall(
                call_id="local-tool-contract",
                tool_name="get_tool_contract",
                query=query,
                canonical_task=task_id,
                tool_names=requested_tools,
                reason="workflow_requires_governed_contract_context",
            )
        )
    if mode is AgentMode.PLAN and task_id in {
        "doublet_detection",
        "batch_integration",
    } and not any(call.tool_name == "compile_workflow" for call in calls):
        calls.append(
            ResearchToolCall(
                call_id="local-tool-workflow",
                tool_name="compile_workflow",
                query=query,
                canonical_task=task_id,
                tool_names=requested_tools,
                reason="explicit_plan_uses_smoke_tested_workflow_bundle",
            )
        )

    deduplicated: list[ResearchToolCall] = []
    seen: set[tuple[str, str, tuple[str, ...]]] = set()
    for call in calls:
        key = (
            call.tool_name,
            call.canonical_task,
            tuple(value.casefold() for value in call.tool_names),
        )
        if key in seen:
            continue
        seen.add(key)
        deduplicated.append(call)
    return ResearchToolPlan(
        source=(
            "semantic_parser"
            if semantic_parse.status == "ready" and semantic_parse.tool_calls
            else "deterministic_fallback"
        ),
        calls=deduplicated[:4],
        answer_strategy=(
            "workflow"
            if mode in {AgentMode.PLAN, AgentMode.RUN}
            else "dual_layer"
            if not task_id
            else "grounded"
        ),
        rationale=(
            "LLM proposed bounded read-only tools; local policy normalized the plan."
            if semantic_parse.status == "ready" and semantic_parse.tool_calls
            else "Deterministic fallback selected the minimum grounding tools."
        ),
    )


def _claim_types_for_tool_query(
    query: str,
    intent: ResearchChatIntent,
) -> list[str]:
    text = query.casefold()
    claim_types: list[str] = []

    def add(value: str) -> None:
        if value not in claim_types:
            claim_types.append(value)

    if intent is ResearchChatIntent.CAVEAT_COMPARISON or any(
        marker in text
        for marker in ("caveat", "limitation", "限制", "局限", "失败模式")
    ):
        add("failure_mode")
    if any(
        marker in text
        for marker in ("parameter", "threshold", "参数", "阈值", "默认值")
    ):
        add("parameter")
    if any(
        marker in text
        for marker in (
            "input",
            "raw count",
            "raw umi",
            "输入",
            "矩阵",
            "需要什么数据",
            "归一化矩阵",
        )
    ):
        add("input_requirement")
    if any(
        marker in text
        for marker in (
            "output",
            "artifact",
            "return",
            "输出",
            "返回",
            "结果字段",
            "放在哪里",
            "存在哪里",
            "obsm",
        )
    ):
        add("output")
    if any(
        marker in text
        for marker in ("benchmark", "metric", "rank", "指标", "排名", "评测")
    ):
        add("benchmark")
        add("metric")
    return claim_types or ["mechanism", "general"]


def _adaptive_retrieval_decision(
    *,
    query: str,
    task_id: str,
    intent: ResearchChatIntent,
    dense_available: bool,
) -> AdaptiveRetrievalDecision:
    if not dense_available:
        return AdaptiveRetrievalDecision(
            route="kg_bm25",
            enable_dense=False,
            reason="local_dense_route_disabled_or_model_pack_unavailable",
        )
    if intent in {ResearchChatIntent.WORKFLOW, ResearchChatIntent.CAVEAT_COMPARISON}:
        return AdaptiveRetrievalDecision(
            route="kg_bm25",
            enable_dense=False,
            reason=f"latency_bounded_known_intent:{intent.value}",
        )
    if intent in {
        ResearchChatIntent.TOOL_RECOMMENDATION,
        ResearchChatIntent.MIGRATION_EXPLORATION,
    }:
        return AdaptiveRetrievalDecision(
            route="kg_hybrid",
            enable_dense=True,
            reason=f"semantic_recall_sensitive_intent:{intent.value}",
        )
    text = _latest_followup_text(query).casefold()
    if any(
        marker in text
        for marker in (
            "parameter",
            "threshold",
            "default",
            "output",
            "artifact",
            "参数",
            "阈值",
            "输出",
            "结果字段",
        )
    ):
        return AdaptiveRetrievalDecision(
            route="kg_hybrid",
            enable_dense=True,
            reason="parameter_or_output_evidence_discovery",
        )
    explicit_tool = any(tool in text for tool in _ALGORITHM_GUIDE)
    if explicit_tool and any(
        marker in text
        for marker in (
            "input",
            "require",
            "failure",
            "limitation",
            "输入",
            "要求",
            "失败",
            "限制",
        )
    ):
        return AdaptiveRetrievalDecision(
            route="kg_bm25",
            enable_dense=False,
            reason="known_tool_structured_evidence_lookup",
        )
    if not task_id or any(
        marker in text
        for marker in (
            "which tools",
            "compare methods",
            "tool discovery",
            "algorithm discovery",
            "有哪些工具",
            "比较方法",
            "发现工具",
        )
    ):
        return AdaptiveRetrievalDecision(
            route="kg_hybrid",
            enable_dense=True,
            reason="ambiguous_or_tool_discovery_query",
        )
    return AdaptiveRetrievalDecision(
        route="kg_bm25",
        enable_dense=False,
        reason="known_task_evidence_qa_prefers_low_latency_bm25",
    )


def _retrieval_options(
    decision: AdaptiveRetrievalDecision,
    *,
    evaluation_profile: Optional[str],
) -> dict[str, Any]:
    """Resolve retrieval controls; overrides are restricted to offline evaluation."""

    if evaluation_profile == "bm25":
        return {
            "decision": AdaptiveRetrievalDecision(
                route="bm25",
                enable_dense=False,
                reason="evaluation_profile:bm25",
            ),
            "enable_dense": False,
            "use_kg": False,
            "use_governance_rerank": False,
            "use_contract_gate": False,
        }
    if evaluation_profile == "kg_hybrid":
        return {
            "decision": AdaptiveRetrievalDecision(
                route="kg_hybrid",
                enable_dense=True,
                reason="evaluation_profile:kg_hybrid",
            ),
            "enable_dense": True,
            "use_kg": True,
            "use_governance_rerank": False,
            "use_contract_gate": False,
        }
    if evaluation_profile == "kg_hybrid_contract":
        return {
            "decision": AdaptiveRetrievalDecision(
                route="kg_hybrid_contract",
                enable_dense=True,
                reason="evaluation_profile:kg_hybrid_contract",
            ),
            "enable_dense": True,
            "use_kg": True,
            "use_governance_rerank": True,
            "use_contract_gate": True,
        }
    return {
        "decision": decision,
        "enable_dense": decision.enable_dense,
        "use_kg": True,
        "use_governance_rerank": True,
        "use_contract_gate": True,
    }


def _chat_timing(
    stage: str,
    started: float,
    *,
    status: str = "completed",
    detail: str = "",
) -> ChatStageTiming:
    return ChatStageTiming(
        stage=stage,
        elapsed_ms=round((time.perf_counter() - started) * 1000.0, 3),
        status=status,
        detail=detail,
    )


def _classify_intent(query: str) -> ResearchChatIntent:
    text = _intent_classification_text(query)
    if any(
        marker in text
        for marker in (
            "这条推荐",
            "刚才的推荐",
            "这个结论",
            "上述结论",
            "the recommendation",
            "that recommendation",
        )
    ) and any(
        marker in text
        for marker in (
            "benchmark",
            "doi",
            "证据",
            "依据",
            "来源",
            "reference",
            "source",
        )
    ):
        return ResearchChatIntent.EVIDENCE_QA
    if any(
        marker in text
        for marker in (
            "workflow",
            "工作流",
            "可执行",
            "代码",
            "脚本",
            "pipeline",
            "整理成",
        )
    ):
        return ResearchChatIntent.WORKFLOW
    if any(
        marker in text
        for marker in (
            "迁移",
            "新算法",
            "算法创新",
            "transfer",
            "migration",
            "novel algorithm",
        )
    ):
        return ResearchChatIntent.MIGRATION_EXPLORATION
    if any(
        marker in text
        for marker in (
            "caveat",
            "限制分别",
            "各自限制",
            "top-",
            "top ",
            "前三",
            "前两个",
            "主要限制",
            "限制有哪些",
            "局限",
            "注意事项",
            "简要说说",
        )
    ):
        return ResearchChatIntent.CAVEAT_COMPARISON
    if any(
        marker in text
        for marker in (
            "应该用什么",
            "应该如何",
            "用什么方法",
            "如何检测",
            "怎么检测",
            "推荐",
            "怎么选择",
            "怎么选",
            "which method",
            "recommend",
        )
    ):
        return ResearchChatIntent.TOOL_RECOMMENDATION
    return ResearchChatIntent.EVIDENCE_QA


def _has_explicit_intent_signal(
    query: str,
    intent: ResearchChatIntent,
) -> bool:
    """Prevent the semantic parser from changing an explicit answer shape."""

    text = _intent_classification_text(query)
    markers = {
        ResearchChatIntent.WORKFLOW: (
            "workflow",
            "工作流",
            "可执行",
            "代码",
            "脚本",
            "pipeline",
            "整理成",
        ),
        ResearchChatIntent.CAVEAT_COMPARISON: (
            "caveat",
            "top-",
            "top ",
            "前三",
            "限制",
            "局限",
            "注意事项",
        ),
        ResearchChatIntent.TOOL_RECOMMENDATION: (
            "应该用什么",
            "应该如何",
            "用什么方法",
            "如何检测",
            "怎么检测",
            "推荐",
            "怎么选择",
            "怎么选",
            "which method",
            "recommend",
        ),
        ResearchChatIntent.EVIDENCE_QA: (
            "证据",
            "依据",
            "来源",
            "benchmark",
            "doi",
            "基本原理",
            "核心原理",
            "为什么",
            "输入要求",
            "输出是什么",
        ),
    }
    return any(marker in text for marker in markers.get(intent, ()))


def _intent_classification_text(query: str) -> str:
    """Remove explicitly rejected answer shapes before keyword routing."""

    text = _latest_followup_text(query).casefold()
    workflow_terms = (
        "workflow",
        "工作流",
        "可执行代码",
        "代码",
        "脚本",
        "pipeline",
    )
    negation_prefixes = (
        "不要再输出",
        "不要输出",
        "不再输出",
        "别再输出",
        "无需输出",
        "请勿输出",
        "不要再生成",
        "不要生成",
        "do not output",
        "don't output",
        "do not generate",
        "don't generate",
        "no more",
    )
    for prefix in negation_prefixes:
        for term in workflow_terms:
            text = re.sub(
                rf"{re.escape(prefix)}\s*.{{0,12}}?{re.escape(term)}",
                " ",
                text,
                flags=re.IGNORECASE,
            )
    return text


def _is_system_info_query(query: str) -> bool:
    """Identify product/runtime questions that must not enter scientific RAG."""

    text = _latest_followup_text(query).casefold().strip()
    compact = re.sub(r"[\s？?！!。,.，：:]", "", text)
    markers = (
        "你是什么模型",
        "你是哪个模型",
        "当前是什么模型",
        "用的什么模型",
        "使用什么模型",
        "当前llm",
        "有没有调用大模型",
        "是否调用deepseek",
        "deepseek连上了吗",
        "deepseek连接了吗",
        "whatmodelareyou",
        "whichmodelareyou",
        "whatllmareyouusing",
        "isdeepseekconnected",
    )
    return any(marker in compact for marker in markers)


def _is_product_capability_query(query: str) -> bool:
    """Keep product capability claims bound to the implemented local manifest."""

    text = _latest_followup_text(query).casefold().strip()
    compact = re.sub(r"[\s？?！!。,.，：:]", "", text)
    markers = (
        "你能做什么",
        "你可以做什么",
        "你能帮助我做什么",
        "你可以帮助我做什么",
        "介绍一下你的能力",
        "介绍你的能力",
        "介绍一下你真正能够完成的功能",
        "你真正能够完成的功能",
        "你真正能完成什么",
        "你有哪些功能",
        "你的功能是什么",
        "你的能力范围",
        "支持哪些任务",
        "支持什么任务",
        "whatcanyoudo",
        "whatcanyouhelpwith",
        "whatdoyousupport",
    )
    return any(marker in compact for marker in markers)


def _service_source_is_stale() -> bool:
    try:
        current = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    except OSError:
        return True
    return current != _SERVICE_SOURCE_AT_IMPORT


def _stale_build_result(
    *,
    request: ResearchAgentRequest,
    run_started: float,
    conversation_state: ConversationTaskState,
) -> dict[str, Any]:
    reason = "runtime_source_changed_restart_required"
    context_pack = _non_scientific_context_pack(
        route="stale_build_blocked",
        reason=reason,
        external=ExternalReasoningResult(status="not_requested"),
        call_count=0,
        run_started=run_started,
        domain=DomainKind.UNCERTAIN,
    )
    context_pack["action_safety"] = ActionSafetyDecision(
        verdict="BLOCK",
        reason_codes=[reason],
    ).model_dump(mode="json")
    context_pack["answerability"] = AnswerabilityDecision(
        verdict="BLOCK",
        reason_codes=[reason],
    ).model_dump(mode="json")
    context_pack["conversation_state"] = conversation_state.model_dump(mode="json")
    return _non_scientific_result(
        request=request,
        mode=AgentMode.ASK,
        response_intent="runtime_build_mismatch",
        status="BLOCKED",
        route="STALE_BUILD",
        report=(
            "**当前页面后端仍在运行旧版 Research Chat 代码。**\n\n"
            "为避免旧路由继续生成错误回答，本轮已停止。请重启本地 Streamlit 服务后重试；"
            "本轮没有调用 LLM、检索器或创建 ExecutionRequest。"
        ),
        blockers=[reason],
        runtime_mode="stale_build_blocked",
        context_pack=context_pack,
    )


def _system_info_result(
    *,
    request: ResearchAgentRequest,
    runtime_config: dict[str, Any],
    run_started: float,
) -> dict[str, Any]:
    """Return safe runtime identity without retrieval or an external model call."""

    settings = get_settings()
    api_base = str(runtime_config.get("api_base") or settings.chat_api_base or "")
    model_name = str(
        runtime_config.get("model_name")
        or settings.model_name
        or settings.extract_model
        or "not configured"
    )
    api_key_present = bool(
        runtime_config.get("api_key")
        or settings.deepseek_api_key
        or settings.openai_api_key
    )
    session_unlocked = bool(runtime_config.get("api_key"))
    outbound_authorized = bool(runtime_config.get("privacy_authorized"))
    configured = api_key_present and model_name != "not configured"
    if configured and outbound_authorized:
        config_status = "已配置、已解锁，并已授权本会话按需外发"
    elif configured and session_unlocked:
        config_status = "已配置并解锁，但本轮未授权外部调用"
    elif configured:
        config_status = "检测到本地配置，但当前 UI 会话尚未解锁或授权"
    else:
        config_status = "未配置，或加密配置尚未在当前会话解锁"
    parsed = urlparse(api_base)
    provider_host = parsed.netloc or parsed.path or "not configured"
    report = (
        "**我是 scKG-Agent Research Chat，不是 DeepSeek 本体。**\n\n"
        "DeepSeek 是可选的语义理解与 grounded prose 层；KG、检索、合同、审批和执行治理"
        "仍由 scKG-Agent 的本地确定性后端负责。\n\n"
        f"- 外部语义层状态：{config_status}\n"
        f"- Provider：`{provider_host}`\n"
        f"- 配置模型：`{model_name}`\n"
        "- 本轮是否调用 LLM：**否**。系统身份问题由本地层回答，避免让外部模型错误自报身份。\n"
        "- 如何判断科学问答是否真实调用：看到 `LLM USED` 或 `LLM SEMANTIC PARSE`；"
        "看到 `DEGRADED LOCAL FALLBACK` 就表示该轮没有得到可用的外部模型回答。"
    )
    timing = ChatStageTiming(
        stage="intent",
        elapsed_ms=round((time.perf_counter() - run_started) * 1000.0, 3),
        status="completed",
        detail="mode=ASK;intent=system_info;retrieval=skipped",
    )
    parent_result = {
        "status": "ANSWERED",
        "route": "SYSTEM_INFO",
        "blockers": [],
        "next_actions": [],
        "execution_request_count": 0,
        "workflow_plan": None,
    }
    context_pack = {
        "retrieval_context": {
            "mode": "not_requested",
            "pipeline": [],
            "snippets": [],
            "latency_ms": 0.0,
            "dense_status": "not_requested",
            "governance_leakage_count": 0,
            "adaptive_decision": {
                "route": "system_info_local",
                "enable_dense": False,
                "reason": "system_runtime_question_skips_scientific_retrieval",
            },
            "stage_timings": [],
        },
        "missing_evidence": [],
        "memory_context": {
            "explicit_preferences": {},
            "can_affect_scientific_authority": False,
        },
        "conversation_turns_used": 0,
        "uploaded_context_present": False,
        "external_reasoning": ExternalReasoningResult(
            status="not_requested"
        ).model_dump(mode="json", exclude={"content"}),
        "semantic_parse": SemanticParseResult(status="not_requested").model_dump(
            mode="json"
        ),
        "grounded_answer_audit": {
            "passed": True,
            "invalid_citations": [],
            "execution_claim_violation": False,
            "reason": "local_system_identity_answer",
        },
        "external_provider_call_count": 0,
        "system_info": {
            "provider_host": provider_host,
            "model_name": model_name,
            "configured": configured,
            "session_unlocked": session_unlocked,
            "outbound_authorized": outbound_authorized,
            "llm_called_this_turn": False,
        },
        "chat_stage_timings": [timing.model_dump(mode="json")],
        "total_latency_ms": round(
            (time.perf_counter() - run_started) * 1000.0,
            3,
        ),
    }
    return {
        "user_query": request.query,
        "agent_mode": AgentMode.ASK.value,
        "request_id": request.request_id,
        "conversation_id": request.conversation_id,
        "user_id": request.user_id,
        "response_intent": "system_info",
        "extracted_constraints": {
            "task": "System information",
            "canonical_task": "Unknown",
            "modality": "scRNA-seq",
        },
        "candidate_tools": [],
        "tool_candidates": [],
        "algorithm_cards": [],
        "retrieval_results": [],
        "references": [],
        "scored_tools": [],
        "migration_paths": [],
        "workflow_recommendations": [],
        "workflow_plan": None,
        "workflow_code_bundle": None,
        "deterministic_parent_result": parent_result,
        "decision_report": None,
        "final_report": report,
        "hallucination_audit": {
            "passed": True,
            "issues": [],
            "authority": "local_system_identity",
        },
        "context_pack": context_pack,
        "current_step": "complete",
        "error_message": None,
        "runtime_mode": "system_info_local",
    }


def _product_capability_result(
    *,
    request: ResearchAgentRequest,
    runtime_config: dict[str, Any],
    run_started: float,
) -> dict[str, Any]:
    """Describe only capabilities backed by the current product boundary."""

    llm_ready = bool(
        runtime_config.get("api_key") and runtime_config.get("privacy_authorized")
    )
    semantic_status = (
        "本会话已启用，可参与语义理解和受证据约束的答案组织"
        if llm_ready
        else "当前未启用；通用问答会明确降级，不会由随机工具代答"
    )
    report = (
        "**我是 scKG-Agent Research Chat：一个本地优先、证据治理、合同约束的"
        "单细胞分析规划与受控执行 Agent。**\n\n"
        "我当前真正完成的能力是：\n\n"
        "1. **科研问答（ASK）**：检索单细胞工具、输入要求、参数、输出、失败模式和原文位置；"
        "启用 DeepSeek 时，由它基于 KG/RAG 返回的受控上下文组织答案。\n"
        "2. **工作流规划（PLAN）**：为已资格化任务导出经过 synthetic smoke 的固定代码配方、"
        "输入要求、产物和结果图说明；不会把任意 LLM 代码冒充已验证流程。\n"
        "3. **受控执行（RUN）**：仅在本地策略、数据授权、ToolContract、环境和"
        " plan-specific approval 全部通过后，调用固定 wrapper，随后执行验证、有限修复、"
        "Pareto 决策和复现包生成。\n\n"
        "**当前正式范围**\n"
        "- Doublet Detection：Scrublet、scDblFinder\n"
        "- Batch Integration：Harmony、Scanorama\n\n"
        "**当前边界**\n"
        "- 其他 scRNA 工具可以作为目录或证据检索候选，但不能自动宣称可执行。\n"
        "- 不支持 SPARQL、任意代码执行、自动安装未知依赖或越权访问本地数据。\n"
        "- 全局 ExecutionPolicy 默认仍为 `disabled`；规划不等于执行。\n\n"
        f"**DeepSeek 状态**：{semantic_status}。"
    )
    external = ExternalReasoningResult(status="not_requested")
    context_pack = _non_scientific_context_pack(
        route="product_capabilities_local",
        reason="product_capability_claims_use_local_manifest",
        external=external,
        call_count=0,
        run_started=run_started,
    )
    return _non_scientific_result(
        request=request,
        mode=AgentMode.ASK,
        response_intent="product_capabilities",
        status="ANSWERED",
        route="PRODUCT_CAPABILITIES",
        report=report,
        blockers=[],
        runtime_mode="product_capabilities_local",
        context_pack=context_pack,
    )


def _query_domain(
    query: str,
    *,
    explicit_task: Any,
    conversation_context: list[dict[str, Any]],
) -> DomainDecision:
    """Route only single-cell questions into the governed scientific stack."""

    text = _latest_followup_text(query).casefold()
    inherited_task = (
        _task_from_context(conversation_context) if _can_inherit_task(query) else None
    )
    single_cell_markers = (
        "single-cell",
        "single cell",
        "scrna",
        "sc-rna",
        "单细胞",
        "10x",
        "anndata",
        "h5ad",
        "scanpy",
        "seurat",
        "scrublet",
        "scdblfinder",
        "doubletfinder",
        "harmony",
        "scanorama",
        "cell2location",
        "doublet",
        "批次整合",
        "batch integration",
        "cell type annotation",
        "细胞类型注释",
        "cell-cell communication",
        "细胞通讯",
        "spatial transcriptomics",
        "空间转录组",
        "umap",
        "leiden",
        "cluster",
        "marker gene",
        "marker genes",
        "highly variable gene",
        "hvg",
        "raw counts",
        "umi",
        "细胞簇",
        "细胞群",
        "基因表达矩阵",
        "原始计数",
    )
    mentions_single_cell = bool(
        explicit_task
        or inherited_task
        or any(marker in text for marker in single_cell_markers)
        or _contains_catalog_tool(text)
    )
    if mentions_single_cell:
        return DomainDecision(
            domain=DomainKind.SINGLE_CELL,
            confidence=1.0 if explicit_task else 0.9,
            source=(
                "conversation_context"
                if inherited_task and not explicit_task
                else "local_rule"
            ),
            reason=(
                "canonical_or_context_task_detected"
                if explicit_task or inherited_task
                else "single_cell_entity_or_tool_detected"
            ),
        )
    ambiguous_biomedical_markers = (
        "表达矩阵",
        "这个矩阵",
        "几个样本",
        "多个样本",
        "细胞",
        "基因",
        "marker",
        "样本合并",
        "质控",
        "污染",
        "过渡状态",
        "expression matrix",
        "cell population",
        "cell cluster",
        "gene expression",
        "quality control",
    )
    if any(marker in text for marker in ambiguous_biomedical_markers):
        return DomainDecision(
            domain=DomainKind.UNCERTAIN,
            confidence=0.45,
            source="local_rule",
            reason="biomedical_language_without_explicit_single_cell_anchor",
            needs_clarification=True,
        )
    explicit_general_markers = (
        "什么是递归",
        "解释什么是递归",
        "检索增强生成",
        "retrieval augmented generation",
        "写一封邮件",
        "write an email",
        "翻译成",
        "translate",
        "天气",
        "weather",
        "写一首诗",
        "write a poem",
    )
    if any(marker in text for marker in explicit_general_markers):
        return DomainDecision(
            domain=DomainKind.GENERAL,
            confidence=0.95,
            source="local_rule",
            reason="explicit_general_topic_detected",
        )
    vague_without_object = (
        "这个结果",
        "这个问题",
        "为什么不对",
        "为什么失败",
        "怎么报错",
        "又失败了",
        "不能运行",
        "not working",
        "why did it fail",
        "unexpected behaviour",
        "unexpected behavior",
    )
    if len(text) < 48 and any(marker in text for marker in vague_without_object):
        return DomainDecision(
            domain=DomainKind.UNCERTAIN,
            confidence=0.25,
            source="local_rule",
            reason="underspecified_question_without_domain_or_object",
            needs_clarification=True,
        )
    return DomainDecision(
        domain=DomainKind.GENERAL,
        confidence=0.75,
        source="local_rule",
        reason="complete_question_without_single_cell_anchor",
        needs_clarification=False,
    )


def _clarification_result(
    *,
    request: ResearchAgentRequest,
    mode: AgentMode,
    domain_decision: DomainDecision,
    semantic_parse: SemanticParseResult,
    conversation_context: list[dict[str, Any]],
    run_started: float,
) -> dict[str, Any]:
    report = (
        "**我还不能可靠判断你指的是哪一种单细胞分析场景。**\n\n"
        "请补充最少一项信息：\n"
        "- 数据类型或对象，例如 10x scRNA-seq、AnnData/.h5ad；\n"
        "- 当前步骤，例如 QC、doublet、批次整合、注释或差异分析；\n"
        "- 你遇到的具体现象，例如矩阵状态、UMAP 分离或 marker 混合。\n\n"
        "在任务确认前，我不会检索随机工具、生成可执行计划或创建 ExecutionRequest。"
    )
    context_pack = _non_scientific_context_pack(
        route="clarification_required",
        reason=domain_decision.reason,
        external=ExternalReasoningResult(status="not_requested"),
        call_count=int(semantic_parse.provider_call_attempted),
        run_started=run_started,
        domain=DomainKind.UNCERTAIN,
        conversation_turns_used=len(conversation_context),
    )
    context_pack["semantic_parse"] = semantic_parse.model_dump(mode="json")
    context_pack["semantic_route"] = {
        "domain": DomainKind.UNCERTAIN.value,
        "confidence": domain_decision.confidence,
        "source": domain_decision.source,
        "reason": domain_decision.reason,
        "needs_clarification": True,
    }
    return _non_scientific_result(
        request=request,
        mode=mode,
        response_intent="clarification",
        status="WAITING",
        route="WAITING_USER_INPUT",
        report=report,
        blockers=["domain_or_task_clarification_required"],
        runtime_mode="clarification_required",
        context_pack=context_pack,
    )


@lru_cache(maxsize=1)
def _catalog_tool_names() -> tuple[str, ...]:
    path = PROJECT_ROOT / "data/scrna_tools.tsv"
    try:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            rows = csv.DictReader(handle, delimiter="\t")
            names = {
                str(row.get("Tool") or "").strip().casefold()
                for row in rows
                if len(str(row.get("Tool") or "").strip()) >= 3
            }
    except OSError:
        names = set()
    names.update(_ALGORITHM_GUIDE)
    return tuple(sorted(names, key=lambda value: (-len(value), value)))


def _contains_catalog_tool(text: str) -> bool:
    normalized = text.casefold()
    for name in _catalog_tool_names():
        start = normalized.find(name)
        while start >= 0:
            end = start + len(name)
            left_ok = start == 0 or not normalized[start - 1].isalnum()
            right_ok = end == len(normalized) or not normalized[end].isalnum()
            if left_ok and right_ok:
                return True
            start = normalized.find(name, start + 1)
    return False


def _general_chat_result(
    *,
    request: ResearchAgentRequest,
    runtime_config: dict[str, Any],
    conversation_context: list[dict[str, Any]],
    reasoner: Any,
    run_started: float,
    semantic_parse: Optional[SemanticParseResult] = None,
) -> dict[str, Any]:
    """Use the external model for ordinary chat without touching scRNA retrieval."""

    if hasattr(reasoner, "answer_general"):
        external = reasoner.answer_general(
            query=_latest_followup_text(request.query),
            conversation_context=conversation_context,
            runtime_config=runtime_config,
        )
    else:
        external = ExternalReasoningResult(
            status="failed",
            error_type="GeneralReasonerUnavailable",
        )
    if external.status == "ready":
        report = external.content
        runtime_mode = "external_general_reasoning"
    elif external.status == "not_authorized":
        report = (
            "这是一个通用问答，不应进入单细胞 KG/RAG。当前会话尚未启用外部 LLM，"
            "因此我没有用工具目录拼接答案。请在 Settings 解锁配置，并显式启用本会话的 "
            "DeepSeek 语义推理后重试。"
        )
        runtime_mode = "general_local_fallback"
    else:
        report = (
            "这是一个通用问答，不应进入单细胞 KG/RAG；但本轮外部 LLM 调用失败，"
            f"失败类型为 `{external.error_type or external.status}`。系统没有用随机工具候选代答。"
        )
        runtime_mode = "general_local_fallback"
    call_count = int(external.provider_call_attempted) + int(
        bool(semantic_parse and semantic_parse.provider_call_attempted)
    )
    context_pack = _non_scientific_context_pack(
        route="general_llm",
        reason="query_outside_single_cell_domain",
        external=external,
        call_count=call_count,
        run_started=run_started,
        domain=DomainKind.GENERAL,
        conversation_turns_used=len(conversation_context),
    )
    if semantic_parse is not None:
        context_pack["semantic_parse"] = semantic_parse.model_dump(mode="json")
        context_pack["semantic_route"] = {
            "domain": DomainKind.GENERAL.value,
            "confidence": semantic_parse.confidence,
            "source": "semantic_parser",
            "reason": "uncertain_local_route_resolved_as_general",
            "needs_clarification": semantic_parse.needs_clarification,
        }
    return _non_scientific_result(
        request=request,
        mode=AgentMode.ASK,
        response_intent="general_chat",
        status="ANSWERED",
        route="GENERAL_LLM",
        report=report,
        blockers=[],
        runtime_mode=runtime_mode,
        context_pack=context_pack,
    )


def _unsupported_action_result(
    *,
    request: ResearchAgentRequest,
    mode: AgentMode,
    run_started: float,
    reason: str,
    action_safety: Optional[ActionSafetyDecision] = None,
    conversation_state: Optional[ConversationTaskState] = None,
) -> dict[str, Any]:
    report = (
        "**当前请求不在 scKG-Agent 已资格化的执行范围内，因此没有创建执行请求。**\n\n"
        "目前只有已登记、已资格化的单细胞 ActionBundle 可以进入受控执行。"
        "系统不会把越界任务回退成 Scrublet、cell2location 或其他随机单细胞工具。\n\n"
        f"- 阻断原因：`{reason}`\n"
        "- ExecutionRequest：`0`\n"
        "- 你仍可以在 ASK 模式下让通用 LLM 解释相关概念，但它不会冒充已验证的 scKG workflow。"
    )
    external = ExternalReasoningResult(status="not_requested")
    context_pack = _non_scientific_context_pack(
        route="unsupported_action",
        reason=reason,
        external=external,
        call_count=0,
        run_started=run_started,
        domain=DomainKind.GENERAL,
    )
    safety = action_safety or ActionSafetyDecision(
        verdict="BLOCK",
        reason_codes=[reason],
    )
    context_pack["action_safety"] = safety.model_dump(mode="json")
    context_pack["answerability"] = AnswerabilityDecision(
        verdict="BLOCK",
        reason_codes=[reason],
    ).model_dump(mode="json")
    if conversation_state is not None:
        context_pack["conversation_state"] = conversation_state.model_dump(mode="json")
    return _non_scientific_result(
        request=request,
        mode=mode,
        response_intent="unsupported_action",
        status="BLOCKED",
        route="UNSUPPORTED_ACTION",
        report=report,
        blockers=[reason],
        runtime_mode="unsupported_action_blocked",
        context_pack=context_pack,
    )


def _non_scientific_context_pack(
    *,
    route: str,
    reason: str,
    external: ExternalReasoningResult,
    call_count: int,
    run_started: float,
    domain: DomainKind = DomainKind.GENERAL,
    conversation_turns_used: int = 0,
) -> dict[str, Any]:
    timing = ChatStageTiming(
        stage="intent",
        elapsed_ms=round((time.perf_counter() - run_started) * 1000.0, 3),
        status="completed",
        detail=f"domain_route={route};scientific_retrieval=skipped",
    )
    return {
        "retrieval_context": {
            "mode": "not_requested",
            "pipeline": [],
            "snippets": [],
            "latency_ms": 0.0,
            "dense_status": "not_requested",
            "governance_leakage_count": 0,
            "adaptive_decision": {
                "route": route,
                "enable_dense": False,
                "reason": reason,
            },
            "stage_timings": [],
        },
        "missing_evidence": [],
        "memory_context": {
            "explicit_preferences": {},
            "can_affect_scientific_authority": False,
        },
        "conversation_turns_used": conversation_turns_used,
        "uploaded_context_present": False,
        "external_reasoning": external.model_dump(mode="json", exclude={"content"}),
        "semantic_parse": SemanticParseResult(status="not_requested").model_dump(
            mode="json"
        ),
        "semantic_route": {
            "domain": domain.value,
            "confidence": 1.0 if domain is not DomainKind.UNCERTAIN else 0.0,
            "source": "local_rule",
            "reason": reason,
            "needs_clarification": domain is DomainKind.UNCERTAIN,
        },
        "grounded_answer_audit": {
            "passed": True,
            "invalid_citations": [],
            "execution_claim_violation": False,
            "reason": "not_a_scientific_evidence_answer",
        },
        "external_provider_call_count": call_count,
        "chat_stage_timings": [timing.model_dump(mode="json")],
        "total_latency_ms": round(
            (time.perf_counter() - run_started) * 1000.0,
            3,
        ),
    }


def _non_scientific_result(
    *,
    request: ResearchAgentRequest,
    mode: AgentMode,
    response_intent: str,
    status: str,
    route: str,
    report: str,
    blockers: list[str],
    runtime_mode: str,
    context_pack: dict[str, Any],
) -> dict[str, Any]:
    parent = {
        "status": status,
        "route": route,
        "blockers": blockers,
        "next_actions": [],
        "execution_request_count": 0,
        "workflow_plan": None,
    }
    return {
        "user_query": request.query,
        "agent_mode": mode.value,
        "request_id": request.request_id,
        "conversation_id": request.conversation_id,
        "user_id": request.user_id,
        "response_intent": response_intent,
        "extracted_constraints": {
            "task": "Unknown",
            "canonical_task": "Unknown",
            "modality": "general" if response_intent == "general_chat" else "unknown",
        },
        "candidate_tools": [],
        "tool_candidates": [],
        "algorithm_cards": [],
        "retrieval_results": [],
        "references": [],
        "scored_tools": [],
        "migration_paths": [],
        "workflow_recommendations": [],
        "workflow_plan": None,
        "workflow_code_bundle": None,
        "deterministic_parent_result": parent,
        "decision_report": None,
        "final_report": report,
        "hallucination_audit": {
            "passed": True,
            "issues": [],
            "authority": "non_scientific_route_boundary",
        },
        "context_pack": context_pack,
        "current_step": "complete",
        "error_message": None,
        "runtime_mode": runtime_mode,
    }


def _semantic_intent(value: str) -> Optional[ResearchChatIntent]:
    if value == "execution":
        return ResearchChatIntent.WORKFLOW
    try:
        return ResearchChatIntent(value)
    except ValueError:
        return None


def _mode_for_intent(intent: ResearchChatIntent) -> AgentMode:
    if intent is ResearchChatIntent.WORKFLOW:
        return AgentMode.PLAN
    return AgentMode.ASK


def _resolve_mode(
    query: str,
    *,
    intent: ResearchChatIntent,
    requested_mode: Optional[AgentMode] = None,
    semantic: Optional[SemanticParseResult] = None,
) -> AgentMode:
    if requested_mode is not None:
        return AgentMode(requested_mode)
    if _is_run_request(query) or (semantic is not None and semantic.status == "ready" and semantic.intent == "execution"):
        return AgentMode.RUN
    return _mode_for_intent(intent)


def _is_run_request(query: str) -> bool:
    text = _latest_followup_text(query).casefold()
    return any(
        marker in text
        for marker in (
            "现在运行",
            "现在执行",
            "现在请运行",
            "现在请执行",
            "立即运行",
            "立即执行",
            "开始运行",
            "开始执行",
            "run now",
            "execute now",
            "run this",
            "execute this",
        )
    )


def _action_safety_decision(
    query: str,
    *,
    mode: AgentMode,
) -> ActionSafetyDecision:
    text = _latest_followup_text(query).casefold()
    blocked: list[str] = []
    if any(marker in text for marker in ("../", "..\\", ".env", "path traversal")):
        blocked.append("path_or_secret_access_forbidden")
    if any(marker in text for marker in ("rm -rf", "run_shell", "shell command")):
        blocked.append("arbitrary_shell_forbidden")
    if (
        any(marker in text for marker in ("跳过审批", "ignore approval", "绕过审批"))
        or ("跳过" in text and any(marker in text for marker in ("审批", "toolcontract", "contract")))
    ):
        blocked.append("approval_bypass_forbidden")
    if (
        any(marker in text for marker in ("上一次", "旧", "previous", "prior"))
        and "approval" in text
        and any(marker in text for marker in ("这次", "修改", "变化", "changed", "new plan"))
    ):
        blocked.append("approval_replay_forbidden")
    if "自动安装" in text or "auto-install" in text or "auto install" in text:
        blocked.append("unreviewed_auto_install_forbidden")
    if any(marker in text for marker in ("只凭论文标题", "title-only", "title only")):
        blocked.append("title_only_evidence_forbidden")
    if "catalog-only" in text and any(
        marker in text for marker in ("正式推荐", "execution-qualified", "执行资格", "晋升")
    ):
        blocked.append("catalog_only_promotion_forbidden")
    if any(marker in text for marker in ("偏好当成论文证据", "memory as evidence")):
        blocked.append("memory_cannot_be_scientific_evidence")
    if _contains_incompatible_task_marker(query) and (
        mode is not AgentMode.ASK or _requests_incompatible_action(query)
    ):
        blocked.append("tool_task_or_modality_incompatible")
    return ActionSafetyDecision(
        verdict="BLOCK" if blocked else "ALLOW",
        reason_codes=list(dict.fromkeys(blocked)),
        execution_request_allowed=False,
    )


def _answerability_decision(
    *,
    mode: AgentMode,
    domain: DomainKind,
    action_safety: ActionSafetyDecision,
    source_bound_context_available: bool,
    external_reasoning: ExternalReasoningResult,
) -> AnswerabilityDecision:
    if action_safety.verdict == "BLOCK":
        return AnswerabilityDecision(
            verdict="BLOCK",
            reason_codes=action_safety.reason_codes,
        )
    if domain is DomainKind.UNCERTAIN:
        return AnswerabilityDecision(
            verdict="CLARIFY",
            reason_codes=["domain_or_task_clarification_required"],
        )
    if mode is not AgentMode.ASK:
        return AnswerabilityDecision(
            verdict="ANSWER_VERIFIED",
            reason_codes=["qualified_workflow_contract_required"],
            verified_context_available=source_bound_context_available,
        )
    if source_bound_context_available:
        return AnswerabilityDecision(
            verdict="ANSWER_DUAL_LAYER",
            reason_codes=["source_bound_context_with_optional_model_knowledge"],
            verified_context_available=True,
            unverified_model_knowledge_allowed=external_reasoning.status == "ready",
        )
    if external_reasoning.status == "ready":
        return AnswerabilityDecision(
            verdict="ANSWER_DUAL_LAYER",
            reason_codes=["source_coverage_missing_model_knowledge_unverified"],
            unverified_model_knowledge_allowed=True,
        )
    return AnswerabilityDecision(
        verdict="CLARIFY",
        reason_codes=["source_coverage_and_external_reasoning_missing"],
    )


def _is_evidence_followup(query: str) -> bool:
    text = _latest_followup_text(query).casefold()
    return any(
        marker in text
        for marker in (
            "这条推荐",
            "上一条推荐",
            "刚才的推荐",
            "这个结论",
            "背后的证据",
            "benchmark",
            "doi",
            "source span",
            "原文",
            "引用",
        )
    )


def _can_inherit_task(query: str) -> bool:
    text = _latest_followup_text(query).casefold().strip()
    if not text:
        return False
    return any(
        marker in text
        for marker in (
            "这个分析",
            "这个方法",
            "这个流程",
            "这条推荐",
            "上一条推荐",
            "上一条结论",
            "刚才的推荐",
            "这个结论",
            "上述结论",
            "背后的 benchmark",
            "背后的 doi",
            "背后的证据",
            "上述分析",
            "上一轮",
            "上一步",
            "继续",
            "它的",
            "它们的",
            "分别是什么",
            "只告诉我",
            "只返回",
            "top-3 工具",
            "top 3 tools",
            "前三个工具",
            "工具的限制",
            "把这个",
            "基于这个",
            "可以直接运行",
            "能直接运行",
            "整合后",
            "this analysis",
            "this method",
            "continue",
            "previous step",
        )
    )


def _is_multi_tool_followup(query: str) -> bool:
    text = _latest_followup_text(query).casefold()
    return any(
        marker in text
        for marker in (
            "分别",
            "各自",
            "两者",
            "它们",
            "比较",
            "如何选择",
            "还是",
            " versus ",
            " vs ",
            "compare",
            "both",
            "each tool",
        )
    )


def _latest_followup_text(query: str) -> str:
    marker = "请继续回答这个追问："
    if marker in query:
        return query.rsplit(marker, 1)[1].strip()
    return query.strip()


def _task_for_query(query: str) -> Any:
    query_without_negated_tasks = _remove_negated_task_mentions(query)
    if _contains_incompatible_task_marker(query_without_negated_tasks):
        return None
    named_tools = _known_tools_in_query(query_without_negated_tasks)
    named_task_ids = {
        task_ids[0]
        for tool_name in named_tools
        if len(
            task_ids := TOOL_TASK_IDS.get(_compact_tool_name(tool_name), ())
        )
        == 1
    }
    if len(named_task_ids) == 1:
        return canonical_task(named_task_ids.pop())
    semantic = canonical_task_for_text(query_without_negated_tasks)
    if semantic is not None:
        return semantic
    for tool_name in named_tools:
        task_ids = TOOL_TASK_IDS.get(_compact_tool_name(tool_name), ())
        if task_ids:
            return canonical_task(task_ids[0])
    return None


def _compact_tool_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())


def _known_tools_in_query(query: str) -> list[str]:
    """Return maintained tool entities in user order, independent of retrieval hits."""

    compact = _compact_tool_name(_latest_followup_text(query))
    matches: list[tuple[int, int, str]] = []
    for tool_key, display_name in _TOOL_DISPLAY_NAMES.items():
        position = compact.find(tool_key)
        if position >= 0:
            matches.append((position, -len(tool_key), display_name))
    ordered = [item[2] for item in sorted(matches)]
    if len(ordered) > 1 and not _is_multi_tool_followup(query):
        # In "Scanorama in Scanpy", the first tool is the method being asked
        # about and the second is host-framework context.
        return ordered[:1]
    return ordered


def _contains_incompatible_task_marker(query: str) -> bool:
    text = str(query or "").casefold()
    incompatible_markers = (
        "variant",
        "mutation",
        "genome assembly",
        "assemble a genome",
        "long-read genome",
        "long read genome",
        "base calling",
        "protein structure",
        "somatic",
        "bam file",
        "bam ",
        "histology image",
        "histology",
        "mass spectrometry",
        "metabolite",
        "体细胞突变",
        "突变检测",
        "基因组组装",
        "长读长",
        "碱基识别",
        "蛋白结构",
        "蛋白质结构",
        "蛋白质三维结构",
        "组织切片图像",
        "质谱",
        "代谢物",
    )
    return any(marker in text for marker in incompatible_markers)


def _requests_incompatible_action(query: str) -> bool:
    text = _latest_followup_text(query).casefold()
    action_markers = (
        "use ",
        "run ",
        "execute ",
        "predict ",
        "call ",
        "align ",
        "assemble ",
        "quantify ",
        "claim that",
        "execution-qualified",
        "现在执行",
        "立即执行",
        "立即运行",
        "请运行",
        "请预测",
        "请检测",
        "做体细胞",
        "突变检测",
        "自动安装",
        "声称",
    )
    return any(marker in text for marker in action_markers)


def _remove_negated_task_mentions(query: str) -> str:
    cleaned = str(query or "")
    negation_prefixes = (
        "不要继续",
        "不再",
        "停止",
        "别再",
        "do not continue",
        "stop",
    )
    aliases = sorted(
        {
            alias
            for item in CANONICAL_TASKS
            for alias in (item.task_id.replace("_", " "), item.label, *item.aliases)
        },
        key=len,
        reverse=True,
    )
    alias_pattern = "|".join(re.escape(alias) for alias in aliases)
    for prefix in negation_prefixes:
        cleaned = re.sub(
            rf"{re.escape(prefix)}\s*(?:做|进行|the)?\s*(?:{alias_pattern})(?:了|任务|分析|流程)?",
            " ",
            cleaned,
            flags=re.IGNORECASE,
        )
    return cleaned


def _task_from_context(context: Iterable[dict[str, Any]]) -> Any:
    for message in reversed(list(context)):
        task_id = str(message.get("canonical_task") or "")
        if not task_id:
            conversation_state = message.get("conversation_state")
            if isinstance(conversation_state, dict):
                task_id = str(conversation_state.get("confirmed_task") or "")
        if not task_id:
            metadata = message.get("metadata")
            if isinstance(metadata, dict):
                state = metadata.get("conversation_state") or {}
                if isinstance(state, dict):
                    task_id = str(state.get("confirmed_task") or "")
        if task_id:
            task = canonical_task(task_id)
            if task is not None:
                return task
        task = _task_for_query(str(message.get("content") or ""))
        if task is not None:
            return task
    return None


def _contextual_query(
    query: str,
    context: list[dict[str, Any]],
    task_id: str,
    *,
    referenced_tools: Optional[list[str]] = None,
) -> str:
    tool_hint = ", ".join((referenced_tools or [])[:5])
    if _task_for_query(query) is not None or (not context and not tool_hint):
        return query if not tool_hint else f"{query}\nReferenced tools: {tool_hint}"
    prior_user = next(
        (
            str(message.get("content") or "")
            for message in reversed(context)
            if message.get("role") == "user" and message.get("content")
        ),
        "",
    )
    task_hint = task_id.replace("_", " ") if task_id else ""
    parts = [query, f"Context task: {task_hint}."]
    if tool_hint:
        parts.append(f"Referenced tools: {tool_hint}.")
    if prior_user:
        parts.append(f"Previous user request: {prior_user}")
    return "\n".join(parts).strip()


def _retrieval_query(
    query: str,
    *,
    task_id: str,
    intent: ResearchChatIntent,
) -> str:
    """Attach deterministic English retrieval hints without changing user intent."""

    hints = []
    if task_id:
        hints.append(f"canonical task: {task_id.replace('_', ' ')}")
    named_tools = _known_tools_in_query(query)
    if named_tools:
        hints.append("explicit tool: " + ", ".join(named_tools))
    claim_types = _claim_types_for_tool_query(query, intent)
    claim_hints = {
        "input_requirement": "accepted input raw UMI count matrix expression state requirements",
        "output": "returned output stored artifact embedding obsm coordinates labels",
        "parameter": "parameter default threshold legal range",
        "failure_mode": "failure limitation caveat warning",
        "benchmark": "benchmark dataset rank scope",
        "metric": "metric evaluation definition",
        "mechanism": "method mechanism principle",
        "general": "method documentation",
    }
    for claim_type in claim_types:
        if claim_type in claim_hints:
            hints.append(f"claim: {claim_hints[claim_type]}")
    if intent is ResearchChatIntent.CAVEAT_COMPARISON:
        hints.append("claim: failure limitation caveat")
    elif intent is ResearchChatIntent.WORKFLOW:
        hints.append("claim: workflow input output parameter")
    elif intent is ResearchChatIntent.MIGRATION_EXPLORATION:
        hints.append("claim: mechanism input output workflow")
    elif intent is ResearchChatIntent.TOOL_RECOMMENDATION:
        hints.append("claim: method input limitation")
        if task_id == "doublet_detection":
            hints.append(
                "best practices: multiple samples separately expected doublet rate "
                "threshold score histogram embedded doublets"
            )
        elif task_id == "batch_integration":
            hints.append(
                "best practices: batch labels batch mixing biology conservation "
                "overcorrection embedding"
            )
    return f"{query}\nRetrieval hints: {'; '.join(hints)}" if hints else query


def _retrieval_candidate_rows(result: Any) -> list[dict[str, Any]]:
    by_tool: Dict[str, Dict[str, Any]] = {}
    for hit in result.hits:
        if not hit.tool_name:
            continue
        row = by_tool.setdefault(
            hit.tool_name,
            {
                "tool_name": hit.tool_name,
                "score": 0.0,
                "source_chunk_count": 0,
                "canonical_tasks": set(),
                "candidate_basis": "source_bound_retrieval",
                "contract_available": False,
                "scientific_pilot_available": False,
                "warnings": [],
                "evidence": {
                    "retrieval_only": True,
                    "can_affect_scientific_authority": False,
                },
            },
        )
        row["score"] = max(float(row["score"]), hit.score)
        row["source_chunk_count"] += int(hit.source_bound)
        if hit.canonical_task:
            row["canonical_tasks"].add(hit.canonical_task)
    values = []
    for row in by_tool.values():
        row["canonical_tasks"] = sorted(row["canonical_tasks"])
        values.append(row)
    return sorted(values, key=lambda row: (-row["score"], row["tool_name"]))[:8]


def _complete_top_tool_evidence(
    retrieval: Any,
    *,
    retrieval_service: HybridRetrievalService,
    query: str,
    task_id: str,
    claim_types: list[str],
    tool_names: list[str],
    intent: ResearchChatIntent,
    retrieval_options: dict[str, Any],
) -> Any:
    """Add bounded per-tool evidence when a top-k answer needs tool diversity."""

    present = {
        str(hit.tool_name or "").casefold()
        for hit in retrieval.hits
        if hit.source_bound
    }
    supplemental = []
    warnings = list(retrieval.warnings)
    timings = list(retrieval.stage_timings)
    extra_latency = 0.0
    leakage = int(retrieval.governance_leakage_count)
    request_specs: list[tuple[str, list[str], str]] = []
    if intent is ResearchChatIntent.TOOL_RECOMMENDATION and tool_names:
        primary = tool_names[0]
        for claim_type in (
            "mechanism",
            "input_requirement",
            "output",
            "failure_mode",
        ):
            request_specs.append(
                (
                    primary,
                    [claim_type],
                    f"{primary} {_claim_retrieval_terms(claim_type)}",
                )
            )
        for tool_name in tool_names[1:3]:
            request_specs.append(
                (
                    tool_name,
                    claim_types,
                    f"{tool_name} {_claim_retrieval_terms(claim_types[0] if claim_types else 'general')}",
                )
            )
    elif intent is ResearchChatIntent.CAVEAT_COMPARISON:
        request_specs.extend(
            (
                tool_name,
                ["failure_mode"],
                f"{tool_name} limitation caveat threshold homotypic warning",
            )
            for tool_name in tool_names[:3]
        )
    else:
        request_specs.extend(
            (tool_name, claim_types, query)
            for tool_name in tool_names[:3]
            if tool_name.casefold() not in present
        )

    for tool_name, scoped_claim_types, scoped_query in request_specs:
        result = retrieval_service.search(
            HybridRetrievalRequest(
                query=scoped_query,
                tool_names=[tool_name],
                canonical_tasks=[task_id] if task_id else [],
                claim_types=scoped_claim_types,
                top_k=4,
                include_catalog=False,
                enable_dense=bool(retrieval_options["enable_dense"]),
                nonblocking_dense=True,
                use_kg=bool(retrieval_options["use_kg"]),
                use_governance_rerank=bool(
                    retrieval_options["use_governance_rerank"]
                ),
                use_contract_gate=bool(retrieval_options["use_contract_gate"]),
            )
        )
        supplemental.extend(result.hits)
        warnings.extend(result.warnings)
        timings.extend(result.stage_timings)
        extra_latency += result.latency_ms
        leakage += result.governance_leakage_count
    if not supplemental:
        return retrieval
    by_chunk = {hit.chunk_id: hit for hit in [*retrieval.hits, *supplemental]}
    return retrieval.model_copy(
        update={
            "hits": list(by_chunk.values()),
            "latency_ms": retrieval.latency_ms + extra_latency,
            "pipeline": [*retrieval.pipeline, "per_tool_evidence_completion"],
            "warnings": list(dict.fromkeys(warnings)),
            "governance_leakage_count": leakage,
            "stage_timings": timings,
        }
    )


def _claim_retrieval_terms(claim_type: str) -> str:
    return {
        "mechanism": "algorithm general approach simulate method classifier",
        "input_requirement": "required input raw UMI count matrix accepts starting with",
        "output": "returned output doublet score predicted labels artifact",
        "failure_mode": (
            "limitations embedded homotypic expected doublet rate threshold "
            "multiple samples separately score histogram"
        ),
        "parameter": "parameter default threshold legal range",
        "metric": "benchmark metric dataset scope",
        "general": "official method documentation",
    }.get(claim_type, "official method documentation")


def _algorithm_card(
    row: dict[str, Any],
    snippets: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
    tool = str(row.get("tool_name") or "Unknown")
    guide = _ALGORITHM_GUIDE.get(tool.casefold(), {})
    tool_snippets = [
        item
        for item in snippets or []
        if str(item.get("tool_name") or "").casefold() == tool.casefold()
    ]
    by_claim: dict[str, list[str]] = {}
    for item in tool_snippets:
        claim_type = str(item.get("claim_type") or "general")
        text = _bounded_claim_text(str(item.get("claim_span") or ""))
        if text and text not in by_claim.setdefault(claim_type, []):
            by_claim[claim_type].append(text)

    mechanism = guide.get("mechanism") or _first_claim(by_claim, "general", "workflow") or (
        "机制说明仍需从 source-bound corpus 补齐。"
    )
    input_claim = guide.get("input") or _first_claim(by_claim, "input_requirement") or "未确认"
    output_claim = guide.get("output") or _first_claim(by_claim, "output") or "未确认"
    caveats = list(guide.get("caveats") or by_claim.get("failure_mode") or [])[:3]
    if not caveats:
        caveats = list(guide.get("caveats") or row.get("warnings") or [])
    return {
        "tool_name": tool,
        "mechanism": mechanism,
        "best_for": guide.get("best_for", "作为检索候选，需要结合数据与合同继续核对。"),
        "input": input_claim,
        "output": output_claim,
        "caveats": caveats,
        "readiness": guide.get("readiness", row.get("candidate_basis", "catalog_only")),
        "contract_available": bool(row.get("contract_available")),
        "scientific_pilot_available": bool(row.get("scientific_pilot_available")),
        "source_chunk_count": int(row.get("source_chunk_count") or 0),
        "content_source": "source_bound_chunks" if tool_snippets else "bounded_fallback",
    }


def _first_claim(by_claim: dict[str, list[str]], *claim_types: str) -> str:
    for claim_type in claim_types:
        values = by_claim.get(claim_type) or []
        if values:
            return values[0]
    return ""


def _bounded_claim_text(value: str, limit: int = 260) -> str:
    text = " ".join(value.split())
    if not text:
        return ""
    if len(text) <= limit:
        return text
    boundary = max(text.rfind(". ", 0, limit), text.rfind("。", 0, limit))
    if boundary < 80:
        boundary = limit
    return text[:boundary].rstrip(" .。；;") + "..."


def _explicit_tool(query: str, candidates: list[dict[str, Any]]) -> str:
    compact_query = "".join(character for character in query.casefold() if character.isalnum())
    for row in candidates:
        tool = str(row.get("tool_name") or "")
        compact_tool = "".join(character for character in tool.casefold() if character.isalnum())
        if compact_tool and compact_tool in compact_query:
            return tool
    return ""


def _requested_tools_for_answer(
    *,
    query: str,
    semantic_parse: SemanticParseResult,
    tool_plan: ResearchToolPlan,
    conversation_state: ConversationTaskState,
    candidates: list[dict[str, Any]],
) -> list[str]:
    """Resolve the tools that the answer must cover, preserving user order."""

    values: list[str] = [*semantic_parse.requested_tools]
    for call in tool_plan.calls:
        values.extend(call.tool_names)

    compact_query = "".join(
        character for character in _latest_followup_text(query).casefold()
        if character.isalnum()
    )
    for row in candidates:
        name = str(row.get("tool_name") or "")
        compact_name = "".join(
            character for character in name.casefold() if character.isalnum()
        )
        if compact_name and compact_name in compact_query:
            values.append(name)

    if _is_multi_tool_followup(query):
        values.extend(conversation_state.referenced_tools)

    candidate_names = {
        str(row.get("tool_name") or "").casefold(): str(row.get("tool_name") or "")
        for row in candidates
    }
    resolved: list[str] = []
    seen: set[str] = set()
    for value in values:
        canonical_name = candidate_names.get(str(value).casefold())
        if not canonical_name or canonical_name.casefold() in seen:
            continue
        seen.add(canonical_name.casefold())
        resolved.append(canonical_name)
    return resolved[:5]


def _requested_tool_coverage_is_valid(
    query: str,
    content: str,
    requested_tools: list[str],
) -> bool:
    if not _is_multi_tool_followup(query) or len(requested_tools) < 2:
        return True
    normalized = content.casefold()
    return all(name.casefold() in normalized for name in requested_tools)


def _migration_paths(
    intent: ResearchChatIntent,
    query: str,
    task_id: str,
    candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if intent is not ResearchChatIntent.MIGRATION_EXPLORATION:
        return []
    try:
        paths = build_migration_hypotheses(
            {
                "task": task_id or query,
                "modality": "scRNA-seq",
                "query": query,
            },
            expected_source_tools=[row["tool_name"] for row in candidates[:5]],
            top_k=3,
        )
    except Exception:
        return []
    values = []
    for path in paths:
        row = path.model_dump(mode="json") if hasattr(path, "model_dump") else dict(path)
        row.update(
            {
                "claim_status": "exploratory_hypothesis",
                "can_authorize_execution": False,
                "validation_required": True,
            }
        )
        values.append(row)
    return values


def _legacy_snippet(hit: Any) -> Dict[str, Any]:
    return {
        "record_id": hit.source_id,
        "chunk_id": hit.chunk_id,
        "source_id": hit.source_id,
        "source_span": hit.source_span,
        "tool_name": hit.tool_name,
        "title": hit.title,
        "task": hit.canonical_task,
        "claim_type": hit.claim_type,
        "claim_span": hit.text,
        "relevance_score": hit.score,
        "source_bound": bool(hit.source_bound),
        "recommendation_eligible": hit.recommendation_eligible,
        "claim_boundary": "Retrieval context only; cannot authorize execution or promote evidence.",
    }


def _references(
    snippets: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    *,
    query: str = "",
    intent: ResearchChatIntent = ResearchChatIntent.EVIDENCE_QA,
    requested_tools: Optional[list[str]] = None,
    claim_bindings: Optional[list[_ClaimEvidenceBinding]] = None,
) -> list[dict[str, Any]]:
    requested_tools = list(requested_tools or [])
    default_tool_limit = 3 if intent in {
        ResearchChatIntent.TOOL_RECOMMENDATION,
        ResearchChatIntent.CAVEAT_COMPARISON,
    } else 5
    preferred_names = requested_tools or [
        row["tool_name"] for row in candidates[:default_tool_limit]
    ]
    preferred_order = [str(name).casefold() for name in preferred_names]
    preferred_tools = set(preferred_order)
    refs: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    source_bound_snippets = [
        row
        for row in snippets
        if bool(row.get("source_bound")) and bool(row.get("source_span"))
    ]
    ordered_snippets = sorted(
        source_bound_snippets,
        key=lambda row: (
            preferred_order.index(str(row.get("tool_name") or "").casefold())
            if str(row.get("tool_name") or "").casefold() in preferred_tools
            else len(preferred_order),
            -_reference_relevance(row, query=query, intent=intent),
        ),
    )
    if intent is ResearchChatIntent.EVIDENCE_QA:
        bindings = claim_bindings
        if bindings is None:
            bindings = _select_claim_evidence_bindings(
                ordered_snippets,
                targets=_requested_claim_targets(query, preferred_names),
                query=query,
            )
        return _references_from_claim_bindings(bindings)
    elif intent is ResearchChatIntent.CAVEAT_COMPARISON:
        selected = []
        for tool in preferred_order[:5]:
            rows = [
                row
                for row in ordered_snippets
                if str(row.get("tool_name") or "").casefold() == tool
            ]
            if rows:
                ranked = sorted(
                    rows,
                    key=lambda row: _reference_claim_score(
                        row,
                        claim_type="failure_mode",
                        query=query,
                        intent=intent,
                    ),
                    reverse=True,
                )
                # One caveat often has two independent parts (for example,
                # threshold sensitivity and sample grouping). Preserve at most
                # two distinct source spans per tool so every clause can be
                # inspected without turning the answer into a reference dump.
                selected.extend(ranked[:2])
        ordered_snippets = selected
    elif intent is ResearchChatIntent.TOOL_RECOMMENDATION and preferred_order:
        primary_tool = preferred_order[0]
        primary_rows = [
            row
            for row in ordered_snippets
            if str(row.get("tool_name") or "").casefold() == primary_tool
        ]
        selected = []
        selected_by_key: dict[tuple[str, str], dict[str, Any]] = {}
        for claim_type in (
            "mechanism",
            "input_requirement",
            "output",
            "failure_mode",
        ):
            if not primary_rows:
                break
            match = max(
                primary_rows,
                key=lambda row: _reference_claim_score(
                    row,
                    claim_type=claim_type,
                    query=query,
                    intent=intent,
                ),
            )
            match_key = (
                str(match.get("source_id") or ""),
                str(match.get("source_span") or ""),
            )
            if match_key in selected_by_key:
                selected_by_key[match_key].setdefault(
                    "_selected_for_claim_types", []
                ).append(claim_type)
            else:
                selected_match = dict(match)
                selected_match["_selected_for_claim_types"] = [claim_type]
                selected.append(selected_match)
                selected_by_key[match_key] = selected_match
        failure_rows = sorted(
            primary_rows,
            key=lambda row: _reference_claim_score(
                row,
                claim_type="failure_mode",
                query=query,
                intent=intent,
            ),
            reverse=True,
        )
        for match in failure_rows:
            match_key = (
                str(match.get("source_id") or ""),
                str(match.get("source_span") or ""),
            )
            if match_key in selected_by_key:
                continue
            selected_match = dict(match)
            selected_match["_selected_for_claim_types"] = ["failure_mode"]
            selected.append(selected_match)
            selected_by_key[match_key] = selected_match
            break
        for tool in preferred_order[1:3]:
            tool_rows = [
                row
                for row in ordered_snippets
                if str(row.get("tool_name") or "").casefold() == tool
            ]
            if tool_rows:
                selected.append(
                    max(
                        tool_rows,
                        key=lambda row: _reference_claim_score(
                            row,
                            claim_type="mechanism",
                            query=query,
                            intent=intent,
                        ),
                    )
                )
        ordered_snippets = selected
    else:
        first_per_tool: list[dict[str, Any]] = []
        remaining: list[dict[str, Any]] = []
        covered_tools: set[str] = set()
        for snippet in ordered_snippets:
            tool = str(snippet.get("tool_name") or "").casefold()
            if tool in preferred_tools and tool not in covered_tools:
                first_per_tool.append(snippet)
                covered_tools.add(tool)
            else:
                remaining.append(snippet)
        ordered_snippets = [*first_per_tool, *remaining]

    if intent is ResearchChatIntent.TOOL_RECOMMENDATION:
        limit = 8
    else:
        limit = 6
    for snippet in ordered_snippets:
        if str(snippet.get("tool_name") or "").casefold() not in preferred_tools:
            continue
        key = (str(snippet.get("source_id") or ""), str(snippet.get("source_span") or ""))
        if key in seen or not snippet.get("source_span"):
            continue
        seen.add(key)
        refs.append(
            {
                "index": len(refs) + 1,
                "tool_name": snippet.get("tool_name") or "Source",
                "title": snippet.get("title") or snippet.get("source_id") or "Source",
                "source_id": snippet.get("source_id") or "",
                "source_span": snippet.get("source_span") or "",
                "source_span_id": (
                    snippet.get("chunk_id")
                    or f"{snippet.get('source_id') or 'source'}:{len(refs) + 1}"
                ),
                "claim_text": snippet.get("claim_span") or "",
                "claim_type": snippet.get("claim_type") or "general",
                "support_claim_types": _supported_claim_types_for_snippet(snippet),
                "selected_for_claim_types": [],
                "source_bound": bool(snippet.get("source_bound")),
                "authority": (
                    "source_bound"
                    if bool(snippet.get("source_bound"))
                    else "catalog_only"
                ),
            }
        )
        if len(refs) >= limit:
            break
    return refs


def _claim_types_for_evidence_query(
    query: str,
    tool_names: Iterable[str],
) -> list[str]:
    claim_query = _mask_claim_entities(_latest_followup_text(query), tool_names)
    return list(
        dict.fromkeys(
            _legacy_claim_type_for_predicate(value)
            for value in _semantic_predicates_for_text(claim_query)
        )
    )


def _requested_claim_targets(
    query: str,
    entities: Iterable[str],
) -> list[_ClaimTarget]:
    ordered_entities = list(
        dict.fromkeys(str(value).strip() for value in entities if str(value).strip())
    )
    if not ordered_entities:
        return []
    text = _latest_followup_text(query)
    clauses = _claim_scope_clauses(text, ordered_entities)
    targets: list[_ClaimTarget] = []
    locally_scoped_entities: set[str] = set()
    for clause in clauses:
        clause_entities = [
            entity
            for entity in ordered_entities
            if re.search(re.escape(entity), clause, flags=re.IGNORECASE)
        ]
        if not clause_entities:
            continue
        predicates = _semantic_predicates_for_text(
            _mask_claim_entities(clause, ordered_entities)
        )
        if len(clause_entities) > 1 and not _has_shared_predicate_scope(clause):
            targets.extend(
                _ClaimTarget(
                    entity=entity,
                    predicate=(predicates[0] if len(predicates) == 1 else "unspecified"),
                    legacy_claim_type=(
                        _legacy_claim_type_for_predicate(predicates[0])
                        if len(predicates) == 1
                        else "general"
                    ),
                    ambiguous=True,
                )
                for entity in clause_entities
            )
        else:
            targets.extend(
                _ClaimTarget(
                    entity=entity,
                    predicate=predicate,
                    legacy_claim_type=_legacy_claim_type_for_predicate(predicate),
                )
                for entity in clause_entities
                for predicate in predicates
            )
        locally_scoped_entities.update(entity.casefold() for entity in clause_entities)

    if not targets:
        predicates = _semantic_predicates_for_text(
            _mask_claim_entities(text, ordered_entities)
        )
        if len(ordered_entities) == 1 or _has_shared_predicate_scope(text):
            targets.extend(
                _ClaimTarget(
                    entity=entity,
                    predicate=predicate,
                    legacy_claim_type=_legacy_claim_type_for_predicate(predicate),
                )
                for entity in ordered_entities
                for predicate in predicates
            )
        else:
            targets.extend(
                _ClaimTarget(
                    entity=entity,
                    predicate=(predicates[0] if len(predicates) == 1 else "unspecified"),
                    legacy_claim_type=(
                        _legacy_claim_type_for_predicate(predicates[0])
                        if len(predicates) == 1
                        else "general"
                    ),
                    ambiguous=True,
                )
                for entity in ordered_entities
            )
    elif locally_scoped_entities:
        targets.extend(
            _ClaimTarget(
                entity=entity,
                predicate="unspecified",
                legacy_claim_type="general",
                ambiguous=True,
            )
            for entity in ordered_entities
            if entity.casefold() not in locally_scoped_entities
        )

    deduplicated: list[_ClaimTarget] = []
    seen: set[tuple[str, str, bool]] = set()
    for target in targets:
        key = (target.entity.casefold(), target.predicate, target.ambiguous)
        if key in seen:
            continue
        seen.add(key)
        deduplicated.append(target)
    return deduplicated


def _entityless_claim_targets(
    query: str,
    snippets: Iterable[dict[str, Any]],
    *,
    limit: int = 5,
) -> list[_ClaimTarget]:
    """Derive bounded targets only from source text supporting the query predicate."""

    predicates = _semantic_predicates_for_text(_latest_followup_text(query))
    targets: list[_ClaimTarget] = []
    seen: set[tuple[str, str]] = set()
    for snippet in snippets:
        entity = str(snippet.get("tool_name") or "").strip()
        if (
            not entity
            or not bool(snippet.get("source_bound"))
            or not str(snippet.get("source_span") or "").strip()
        ):
            continue
        for predicate in predicates:
            if not _claim_supporting_excerpt(snippet, predicate)[1]:
                continue
            key = (entity.casefold(), predicate)
            if key in seen:
                continue
            seen.add(key)
            targets.append(
                _ClaimTarget(
                    entity=entity,
                    predicate=predicate,
                    legacy_claim_type=_legacy_claim_type_for_predicate(predicate),
                )
            )
            if len(targets) >= max(1, int(limit)):
                return targets
    return targets


def _mask_claim_entities(text: str, entities: Iterable[str]) -> str:
    masked = str(text)
    for entity in entities:
        if entity:
            masked = re.sub(
                re.escape(str(entity)),
                " ",
                masked,
                flags=re.IGNORECASE,
            )
    return masked


def _claim_scope_clauses(text: str, entities: Iterable[str]) -> list[str]:
    ordered_entities = list(entities)
    clauses: list[str] = []
    for coarse_clause in re.split(r"[;；。!?！？]+", str(text)):
        coarse_clause = coarse_clause.strip()
        if not coarse_clause:
            continue
        parts = [
            value.strip()
            for value in re.split(r"\s+(?:and|versus|vs)\s+|[，,]|以及|和|与", coarse_clause, flags=re.IGNORECASE)
            if value.strip()
        ]
        independently_scoped = len(parts) > 1 and all(
            any(
                re.search(re.escape(entity), part, flags=re.IGNORECASE)
                for entity in ordered_entities
            )
            and bool(
                _explicit_semantic_predicates_for_text(
                    _mask_claim_entities(part, ordered_entities)
                )
            )
            for part in parts
        )
        clauses.extend(parts if independently_scoped else [coarse_clause])
    return clauses


def _has_shared_predicate_scope(text: str) -> bool:
    lowered = str(text).casefold()
    return any(
        marker in lowered
        for marker in (
            " and ",
            " both ",
            " each ",
            " respectively",
            "分别",
            "各自",
            "两者",
            "以及",
            "和",
            "与",
            "都",
        )
    )


def _semantic_predicates_for_text(text: str) -> list[str]:
    return _explicit_semantic_predicates_for_text(text) or ["method_type"]


def _explicit_semantic_predicates_for_text(text: str) -> list[str]:
    lowered = str(text).casefold()
    predicate_markers = (
        (
            "limitation",
            ("caveat", "limitation", "failure mode", "限制", "局限", "失败模式", "注意事项"),
        ),
        ("parameter", ("parameter", "threshold", "default", "参数", "阈值", "默认值")),
        (
            "input_requirement",
            (
                "input",
                "raw count",
                "raw umi",
                "输入",
                "矩阵",
                "需要什么数据",
                "归一化矩阵",
            ),
        ),
        (
            "output",
            (
                "output",
                "artifact",
                "return",
                "输出",
                "返回",
                "结果字段",
                "放在哪里",
                "存在哪里",
                "obsm",
            ),
        ),
        ("metric", ("metric", "precision", "recall", "f1", "指标", "评估指标")),
        ("benchmark_result", ("benchmark", "ranked", "ranking", "排名", "基准评测")),
        (
            "mechanism",
            ("mechanism", "principle", "how does", "how it works", "原理", "机制", "为什么"),
        ),
        (
            "method_type",
            (
                "method type",
                "type of method",
                "supported task",
                "designed for",
                "方法类型",
                "是什么方法",
                "支持的任务",
                "适用任务",
                "用于什么",
            ),
        ),
    )
    located: list[tuple[int, int, str]] = []
    for order, (predicate, markers) in enumerate(predicate_markers):
        positions = [lowered.find(marker) for marker in markers if marker in lowered]
        if positions:
            located.append((min(positions), order, predicate))
    return [value for _, _, value in sorted(located)]


def _legacy_claim_type_for_predicate(predicate: str) -> str:
    return {
        "limitation": "failure_mode",
        "benchmark_result": "benchmark",
        "method_type": "general",
        "mechanism": "general",
        "unspecified": "general",
    }.get(predicate, predicate)


def _select_claim_evidence_bindings(
    snippets: list[dict[str, Any]],
    *,
    targets: Iterable[_ClaimTarget],
    query: str,
) -> list[_ClaimEvidenceBinding]:
    bindings: list[_ClaimEvidenceBinding] = []
    for target in targets:
        if target.ambiguous:
            bindings.append(_abstained_claim_binding(target, "ambiguous_target"))
            continue
        rows = [
            row
            for row in snippets
            if bool(row.get("source_bound"))
            and bool(row.get("source_span"))
            and str(row.get("tool_name") or "").casefold()
            == target.entity.casefold()
        ]
        if not rows:
            bindings.append(_abstained_claim_binding(target, "no_candidate"))
            continue
        supported: list[tuple[dict[str, Any], str, str, int]] = []
        for row in rows:
            bounded_excerpt, claim_text, support_quality = _claim_supporting_excerpt(
                row,
                target.predicate,
            )
            if claim_text:
                supported.append((row, bounded_excerpt, claim_text, support_quality))
        if not supported:
            bindings.append(_abstained_claim_binding(target, "no_direct_support"))
            continue
        if _claim_support_candidates_conflict(supported, target.predicate):
            bindings.append(_abstained_claim_binding(target, "conflicting_support"))
            continue
        row, bounded_excerpt, claim_text, support_quality = max(
            supported,
            key=lambda item: _evidence_binding_rank(
                item[0],
                target=target,
                support_quality=item[3],
                claim_text=item[2],
                query=query,
            ),
        )
        source_id = str(row.get("source_id") or "")
        metadata_claim_type = str(row.get("claim_type") or "general")
        evidence_ref = _BoundEvidenceRef(
            evidence_span_id=str(
                row.get("chunk_id")
                or f"{source_id or 'source'}:{row.get('source_span')}"
            ),
            source_id=source_id,
            source_span=str(row.get("source_span") or ""),
            title=str(row.get("title") or source_id or "Source"),
            bounded_excerpt=bounded_excerpt,
            metadata_claim_type=metadata_claim_type,
        )
        metadata_confirmed = _claim_metadata_compatible(
            metadata_claim_type,
            target,
        )
        bindings.append(
            _ClaimEvidenceBinding(
                entity=target.entity,
                predicate=target.predicate,
                legacy_claim_type=target.legacy_claim_type,
                claim_text=claim_text,
                evidence_refs=(evidence_ref,),
                source_refs=(source_id,),
                support_status="supported",
                support_type=(
                    "direct_excerpt_metadata_confirmed"
                    if metadata_confirmed
                    else "direct_excerpt"
                ),
                support_quality=support_quality,
            )
        )
    return bindings


def _abstained_claim_binding(
    target: _ClaimTarget,
    reason: str,
) -> _ClaimEvidenceBinding:
    return _ClaimEvidenceBinding(
        entity=target.entity,
        predicate=target.predicate,
        legacy_claim_type=target.legacy_claim_type,
        claim_text=(
            f"缺少 source-bound 证据，无法核验 {target.entity} 的"
            f"{_claim_predicate_label(target.predicate)}。"
        ),
        evidence_refs=(),
        source_refs=(),
        support_status="abstained",
        support_type="none",
        support_quality=0,
        abstain_reason=reason,
    )


def _references_from_claim_bindings(
    bindings: Iterable[_ClaimEvidenceBinding],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    by_evidence_id: dict[str, dict[str, Any]] = {}
    for binding in bindings:
        if binding.support_status != "supported":
            continue
        for evidence in binding.evidence_refs:
            row = by_evidence_id.get(evidence.evidence_span_id)
            if row is None:
                row = {
                    "index": len(rows) + 1,
                    "tool_name": binding.entity,
                    "title": evidence.title,
                    "source_id": evidence.source_id,
                    "source_span": evidence.source_span,
                    "source_span_id": evidence.evidence_span_id,
                    "claim_text": evidence.bounded_excerpt,
                    "claim_type": evidence.metadata_claim_type,
                    "support_claim_types": [],
                    "selected_for_claim_types": [],
                    "source_bound": True,
                    "authority": "source_bound",
                }
                rows.append(row)
                by_evidence_id[evidence.evidence_span_id] = row
            if binding.legacy_claim_type not in row["support_claim_types"]:
                row["support_claim_types"].append(binding.legacy_claim_type)
            if binding.legacy_claim_type not in row["selected_for_claim_types"]:
                row["selected_for_claim_types"].append(binding.legacy_claim_type)
    return rows


def _evidence_binding_rank(
    snippet: dict[str, Any],
    *,
    target: _ClaimTarget,
    support_quality: int,
    claim_text: str,
    query: str,
) -> tuple[int, int, int, int, int, float]:
    metadata_compatible = int(
        _claim_metadata_compatible(
            str(snippet.get("claim_type") or ""),
            target,
        )
    )
    noise = _reference_noise_penalty(
        " ".join(
            (
                str(snippet.get("title") or ""),
                claim_text,
                str(snippet.get("source_span") or ""),
            )
        ).casefold(),
        query=query,
        intent=ResearchChatIntent.EVIDENCE_QA,
    )
    query_support = _reference_query_support_score(claim_text.casefold(), query=query)
    return (
        1,
        metadata_compatible,
        support_quality,
        -noise,
        query_support,
        min(float(snippet.get("relevance_score") or 0.0), 3.0),
    )


def _claim_metadata_compatible(
    metadata_type: str,
    target: _ClaimTarget,
) -> bool:
    if metadata_type == target.legacy_claim_type:
        return True
    return target.predicate in {"method_type", "mechanism"} and metadata_type in {
        "general",
        "mechanism",
        "workflow",
    }


def _claim_supporting_excerpt(
    snippet: dict[str, Any],
    predicate: str,
) -> tuple[str, str, int]:
    evidence_excerpt = _bounded_claim_text(
        str(snippet.get("claim_span") or ""),
        limit=900,
    )
    if not evidence_excerpt:
        return "", "", 0
    text = evidence_excerpt.casefold()
    patterns = {
        "input_requirement": (
            r"\binputs?\b.{0,100}\b(?:comprise|include|consist|accept|require)",
            r"\b(?:accepts?|requires?)\b.{0,120}\b(?:input|data|matrix|counts?|expression|anndata|file)",
            r"\b(?:takes?|uses?|consumes?|expects?)\b.{0,120}\b(?:input|data|matrices|matrix|counts?|expression|anndata|files?)\b",
            r"\b(?:input|data|matrix|counts?|expression|anndata|file)\b.{0,120}\b(?:is|are)\s+required\b",
            r"\bgiven\b.{0,160}\b(?:data|matrices|matrix|counts?|expression|anndata|files?)\b",
            r"\bstarting with\b.{0,100}\b(?:counts?|matrix|expression|anndata|data)\b",
            r"\bfile formats?\b.{0,160}\b(?:rows?|columns?|cells?|genes?|matrix)\b",
            r"\b(?:cells?|genes?)\b.{0,40}\b(?:rows?|columns?)\b",
            r"\b(?:log1p|logarithmi[sz]ed|normali[sz]ed|raw counts?|raw umi)\b.{0,120}\b(?:matrix|expression|anndata|input)\b",
        ),
        "output": (
            r"\b(?:will\s+)?output\b.{0,120}\b(?:matrix|coordinates?|embedding|labels?|scores?|artifact|entry)\b",
            r"\boutputs?\b.{0,80}\b(?:are|include|comprise|consist(?:s)?\s+of)\b.{0,180}\b(?:states?|probabilities|maps?|trends?|genes?|matrix|coordinates?|embedding|labels?|scores?|artifacts?|results?)\b",
            r"\b(?:returns?|returned|produces?)\b.{0,120}\b(?:matrix|coordinates?|embedding|labels?|scores?|artifact|result)\b",
            r"\b(?:provides?|generates?|creates?|yields?)\b.{0,120}\b(?:representation|coordinates?|matrix|embedding|labels?|scores?|artifact|data)\b",
            r"\b(?:stored in|adds? an entry)\b.{0,120}\b(?:obsm|matrix|coordinates?|embedding|labels?|scores?)\b",
            r"\b(?:aims?|objective|goal)\b.{0,100}\b(?:detect|define|assign|infer|identify|estimate|compute)\w*\b.{0,180}\b(?:states?|probabilities|maps?|trajectories|coordinates?|embedding|labels?|artifacts?|results?)\b",
            r"\b(?:detects?|defines?|assigns?|infers?|identifies?|estimates?|computes?)\b.{0,140}\b(?:states?|probabilities|maps?|trajectories|coordinates?|embedding|labels?|artifacts?|results?)\b",
        ),
        "parameter": (
            r"\bparameters?\b.{0,120}\b(?:optimized|clamped|set to|value|default|threshold|\d)",
            r"\b(?:resolution|max_epochs|epochs?|warmup|early_stopping|early stopping|batch size|minibatch|threshold)\b.{0,100}\b(?:set to|increased|decreased|enabled|disabled|default|\d)",
            r"\b(?:by default|default value)\b.{0,100}\b(?:true|false|enabled|disabled|\d)",
        ),
        "limitation": (
            r"\b(?:limitation|caveat|warning|failure mode)\b",
            r"\b(?:may perform poorly|not universally|should not|only within|overcorrect|over-correct)\b",
        ),
        "benchmark_result": (
            r"\b(?:benchmark|evaluated|performance|ranked)\b.{0,120}\b(?:dataset|method|tool|metric|result)\b",
        ),
        "metric": (
            r"\b(?:precision|recall|f1|auprc|auroc|silhouette|ilisi|clisi|kbet)\b",
        ),
        "mechanism": (
            r"\b(?:method|algorithm|framework|model)\b.{0,120}\b(?:for|performs?|integrat|correct|classif|infer|simulate)\b",
        ),
        "method_type": (
            r"\b(?:method|algorithm|framework|model)\b.{0,120}\b(?:for|performs?|integrat|correct|classif|infer|simulate)\b",
            r"\b(?:tool|method|algorithm|framework|model)\b.{0,120}\b(?:for|to|that|which)\b.{0,140}\b(?:annotat|classif|correlat|integrat|correct|infer|detect|predict|map|deconvol)\w*\b",
            r"\b(?:developed|introduced|presented)\b.{0,100}\b(?:tool|method|algorithm|framework|model)\b.{0,180}\b(?:annotat|classif|correlat|integrat|correct|infer|detect|predict|map|deconvol)\w*\b",
            r"\b(?:designed|developed)\b.{0,120}\b(?:for|to)\b",
            r"\b(?:enables?|supports?)\b.{0,140}\b(?:annotat|classif|integrat|correct|infer|detect|predict|map|deconvol)\w*\b",
            r"\b(?:requires?|accepts?|returns?|produces?)\b.{0,160}\b(?:matrix|counts?|scores?|labels?|embedding|coordinates?|data)\b",
        ),
    }
    matched = [
        match
        for pattern in patterns.get(predicate, ())
        if (match := re.search(pattern, text, flags=re.IGNORECASE)) is not None
    ]
    if not matched:
        return "", "", 0
    first = min(matched, key=lambda match: match.start())
    bounded_excerpt = _bounded_support_window(evidence_excerpt, first.start())
    claim_text = _bounded_support_proposition(
        evidence_excerpt,
        support_start=first.start(),
    )
    return bounded_excerpt, claim_text, len(matched)


def _bounded_support_window(value: str, support_start: int) -> str:
    sentence_start = _bounded_support_start(value, support_start)
    return _bounded_claim_text(value[sentence_start:].lstrip(), limit=260)


def _bounded_support_proposition(
    value: str,
    *,
    support_start: int,
) -> str:
    sentence_start = _bounded_support_start(value, support_start)
    endings = [
        position + len(marker)
        for marker in (". ", "? ", "! ", "。", "\n")
        if (position := value.find(marker, support_start)) >= 0
    ]
    sentence_end = min(endings) if endings else len(value)
    proposition = value[sentence_start:sentence_end].strip(" -*#>\t")
    return _bounded_claim_text(proposition, limit=220)


def _bounded_support_start(value: str, support_start: int) -> int:
    sentence_start = max(
        value.rfind(marker, 0, support_start)
        for marker in (". ", "? ", "! ", "。", "\n")
    )
    sentence_start = 0 if sentence_start < 0 else sentence_start + 1
    if support_start - sentence_start <= 160:
        return sentence_start
    bounded_start = max(sentence_start, support_start - 120)
    next_space = value.find(" ", bounded_start)
    return next_space + 1 if 0 <= next_space < support_start else bounded_start


def _claim_support_candidates_conflict(
    candidates: list[tuple[dict[str, Any], str, str, int]],
    predicate: str,
) -> bool:
    if predicate != "input_requirement" or len(candidates) < 2:
        return False
    values = [item[2].casefold() for item in candidates]
    raw_only = any(
        any(marker in value for marker in ("requires raw", "raw counts only", "must be raw"))
        for value in values
    )
    processed_allowed = any(
        any(
            marker in value
            for marker in (
                "accepts normalized",
                "accepts log-normalized",
                "accepts scaled",
            )
        )
        for value in values
    )
    return raw_only and processed_allowed


def _claim_predicate_label(predicate: str) -> str:
    return {
        "input_requirement": "输入要求",
        "output": "输出",
        "limitation": "主要限制",
        "parameter": "参数依据",
        "metric": "评估指标依据",
        "benchmark_result": "评测结果",
        "mechanism": "核心原理",
        "method_type": "方法类型",
        "unspecified": "请求范围",
    }.get(predicate, "科学结论")


def _reference_claim_score(
    snippet: dict[str, Any],
    *,
    claim_type: str,
    query: str,
    intent: ResearchChatIntent,
) -> float:
    text = " ".join(
        str(snippet.get(field) or "")
        for field in ("title", "claim_span", "source_span")
    ).casefold()
    score = min(float(snippet.get("relevance_score") or 0.0), 3.0)
    title = str(snippet.get("title") or "").casefold()
    tool_name = str(snippet.get("tool_name") or "").casefold()
    if tool_name and tool_name in title:
        score += 0.5
    if str(snippet.get("claim_type") or "") == claim_type:
        score += 3.0
    if _text_supports_claim_type(text, claim_type):
        score += 8.0
    if claim_type == "failure_mode":
        for cue in (
            "multiple samples",
            "sample-specific doublet rates",
            "doublet score threshold",
            "homotypic",
            "optimal pk",
            "pk values",
            "poorly separated",
            "continuum of cell states",
        ):
            if cue in text:
                score += 2.0
    if claim_type == "mechanism" and any(
        cue in text for cue in ("general approach", "the scrublet algorithm")
    ):
        score += 3.0
    return score


def _reference_query_support_score(text: str, *, query: str) -> int:
    query_text = _latest_followup_text(query).casefold()
    query_tokens = {
        token
        for token in _claim_tokens(query_text)
        if token
        not in {
            "about",
            "artifacts",
            "documented",
            "does",
            "find",
            "information",
            "outputs",
            "produce",
            "source-bound",
            "supported",
            "task",
            "what",
            "which",
        }
    }
    text_tokens = _claim_tokens(text)
    score = min(len(query_tokens & text_tokens), 6)
    if any(marker in query_text for marker in ("放在哪里", "存在哪里", "obsm")):
        if any(marker in text for marker in ("obsm", "add an entry")):
            score += 6
    return score


def _reference_noise_penalty(
    text: str,
    *,
    query: str,
    intent: ResearchChatIntent,
) -> int:
    markers = (
        "supplementary figure",
        "extended data fig",
        "figure ",
        "[![",
        "shields.io",
        "<img",
    )
    penalty = min(sum(marker in text for marker in markers), 2)
    query_text = _latest_followup_text(query).casefold()
    if (
        intent is ResearchChatIntent.EVIDENCE_QA
        and "benchmark" not in query_text
        and "benchmark" in text
    ):
        penalty += 3
    return penalty


def _supported_claim_types_for_snippet(snippet: dict[str, Any]) -> list[str]:
    text = " ".join(
        str(snippet.get(field) or "")
        for field in ("title", "claim_span", "source_span")
    ).casefold()
    values = {
        claim_type
        for claim_type in (
            "mechanism",
            "input_requirement",
            "output",
            "parameter",
            "failure_mode",
            "benchmark",
            "metric",
        )
        if _text_supports_claim_type(text, claim_type)
    }
    metadata_type = str(snippet.get("claim_type") or "")
    if metadata_type:
        values.add(metadata_type)
    return sorted(values)


def _reference_relevance(
    snippet: dict[str, Any],
    *,
    query: str,
    intent: ResearchChatIntent,
) -> float:
    text = " ".join(
        str(snippet.get(field) or "")
        for field in ("title", "claim_span", "source_span", "claim_type")
    ).casefold()
    score = float(snippet.get("relevance_score") or 0.0)
    claim_types = _claim_types_for_tool_query(query, intent)
    if str(snippet.get("claim_type") or "") in claim_types:
        # claim_type is extraction metadata, not evidence authority. Keep it as
        # a weak hint so mislabeled but directly relevant spans can still win.
        score += 0.75
    for claim_type in claim_types:
        if _text_supports_claim_type(text, claim_type):
            score += 2.0
    query_text = _latest_followup_text(query).casefold()
    title = str(snippet.get("title") or "").casefold()
    tool_name = str(snippet.get("tool_name") or "").casefold()
    if tool_name and tool_name in title:
        score += 1.5
    if (
        intent is ResearchChatIntent.EVIDENCE_QA
        and "benchmark" not in query_text
        and "benchmark" in title
    ):
        score -= 3.5
    technical_markers = (
        "raw",
        "count",
        "umi",
        "normalized",
        "归一化",
        "obsm",
        "x_scanorama",
        "pca",
        "batch",
        "threshold",
        "score",
    )
    for marker in technical_markers:
        if marker in query_text and marker in text:
            score += 1.25
    if any(marker in query_text for marker in ("放在哪里", "存在哪里", "obsm")):
        if "obsm" in text or "x_scanorama" in text or "adds an entry" in text:
            score += 5.0
    if "raw" in query_text and ("raw" in text or "count matrix" in text):
        score += 2.5
    if "input_requirement" in claim_types and any(
        cue in text for cue in ("starting with", "accepts", "requires", "input to")
    ):
        score += 2.5
    return score


def _text_supports_claim_type(text: str, claim_type: str) -> bool:
    cues = {
        "input_requirement": (
            "input",
            "accepts",
            "starting with",
            "count matrix",
            "raw umi",
            "requires",
        ),
        "output": (
            "output",
            "returns",
            "returned",
            "adds an entry",
            "obsm",
            "x_scanorama",
            "coordinates",
            "embedding",
            "doublet score",
            "predicted label",
        ),
        "parameter": ("parameter", "default", "threshold", "range"),
        "failure_mode": (
            "limitation",
            "limitations",
            "caveat",
            "warning",
            "detectable doublet fraction",
            "homotypic",
            "expected doublet rate",
            "multiple samples",
            "sample-specific doublet rates",
            "pk selection",
            "optimal pk",
        ),
        "benchmark": ("benchmark", "dataset", "rank"),
        "metric": ("metric", "auprc", "auroc", "f1", "silhouette"),
        "mechanism": (
            "method",
            "algorithm",
            "general approach",
            "simulate doublets",
            "nearest-neighbor",
            "classifier",
            "correction",
        ),
        "general": (),
    }
    values = cues.get(claim_type, ())
    return bool(values) and any(value in text for value in values)


def _synthesis_snippets(
    snippets: list[dict[str, Any]],
    references: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Keep DeepSeek context aligned with the references users can inspect."""

    span_ids = {str(ref.get("source_span_id") or "") for ref in references}
    source_ids = {str(ref.get("source_id") or "") for ref in references}
    selected = [
        row
        for row in snippets
        if str(row.get("chunk_id") or "") in span_ids
        or str(row.get("source_id") or "") in source_ids
    ]
    if not selected:
        selected = snippets[:4]
    return selected[:8]


def _report(
    *,
    intent: ResearchChatIntent,
    query: str,
    task_id: str,
    task_label: str,
    algorithm_cards: list[dict[str, Any]],
    migration_paths: list[dict[str, Any]],
    references: list[dict[str, Any]],
    blockers: list[str],
    parent_result: Dict[str, Any],
    retrieval_snippets: list[dict[str, Any]],
    workflow_code_bundle: Optional[dict[str, Any]],
    requested_tools: list[str],
    claim_bindings: Optional[list[_ClaimEvidenceBinding]] = None,
) -> str:
    if intent is ResearchChatIntent.CAVEAT_COMPARISON:
        count = _requested_top_k(query, default=3)
        return _caveat_report(task_label, algorithm_cards[:count], references)
    if intent is ResearchChatIntent.WORKFLOW:
        return _workflow_report(
            task_id,
            task_label,
            parent_result,
            references,
            workflow_code_bundle,
        )
    if intent is ResearchChatIntent.MIGRATION_EXPLORATION:
        return _migration_report(task_label, migration_paths, references)
    if intent is ResearchChatIntent.TOOL_RECOMMENDATION:
        return _recommendation_report(
            query,
            task_id,
            task_label,
            algorithm_cards,
            references,
        )
    return _evidence_qa_report(
        query,
        task_label,
        algorithm_cards,
        references,
        blockers,
        retrieval_snippets,
        requested_tools,
        claim_bindings,
    )


def _recommendation_report(
    query: str,
    task_id: str,
    task_label: str,
    cards: list[dict[str, Any]],
    references: list[dict[str, Any]],
) -> str:
    if not cards:
        return f"我识别到任务是 **{task_label}**，但目前没有足够的 source-bound 候选可以安全推荐。"
    primary = cards[0]
    primary_citation = _citation_for_tool(primary["tool_name"], references)
    mechanism_citation = (
        _citation_for_tool(primary["tool_name"], references, claim_type="mechanism")
        or primary_citation
    )
    input_citation = (
        _citation_for_tool(
            primary["tool_name"], references, claim_type="input_requirement"
        )
        or primary_citation
    )
    output_citation = (
        _citation_for_tool(primary["tool_name"], references, claim_type="output")
        or primary_citation
    )
    caveat_citation = _citations_for_tool(
        primary["tool_name"],
        references,
        claim_type="failure_mode",
        limit=2,
    ) or primary_citation
    if task_id == "doublet_detection":
        subject = "这批 10x PBMC 数据" if "pbmc" in query.casefold() else "这批 scRNA-seq 数据"
        opening = (
            f"对于{subject}，我会优先用 **{primary['tool_name']}**，"
            f"因为它匹配 raw-count 输入且已有受控执行合同；"
            f"多样本应按独立 capture/sample 运行。{caveat_citation}"
        )
        input_detail = (
            "先用 DataProfile 确认 `.h5ad` 中真正的 raw count source；"
            "scaled matrix 不能直接进入 doublet caller"
        )
        output_detail = "把预测作为 QC 标记，并结合 marker、cluster 和样本信息复核"
    elif task_id == "batch_integration":
        opening = (
            f"针对多批次 scRNA-seq 整合，我会优先比较并使用 **{primary['tool_name']}**；"
            f"前提是 batch 标签可靠，并同时检查批次混合与生物学结构保留。{primary_citation}"
        )
        input_detail = (
            "确认预处理/PCA 状态、稳定 cell ID 和真实技术 batch 列；"
            "不要把 cell type 当成 batch 标签"
        )
        output_detail = (
            "将 integrated embedding 用于邻域、UMAP 和聚类，并同时检查 batch mixing "
            "与 cell-type conservation"
        )
    else:
        opening = (
            f"针对 **{task_label}**，当前 source-bound 候选中我会优先考虑 "
            f"**{primary['tool_name']}**。{primary_citation}"
        )
        input_detail = "先核对当前数据对象与该工具输入合同是否匹配"
        output_detail = "先验证产物 schema 和适用范围，再解释科学结果"
    lines = [
        opening,
        "",
        "### 为什么这样选",
        f"- **机制：** {primary['mechanism']}{mechanism_citation}",
        f"- **输入匹配：** {primary['input']}。{input_detail}。{input_citation}",
        f"- **输出：** {primary['output']}。{output_detail}。{output_citation}",
    ]
    alternatives = [card for card in cards[1:3] if card["tool_name"] != primary["tool_name"]]
    if alternatives:
        lines.extend(["", "### 可替代选择"])
        for card in alternatives:
            boundary = "已资格化" if card["readiness"] == "decision_ready" else "仅规划候选"
            citation = _citation_for_tool(card["tool_name"], references)
            if not citation:
                continue
            lines.append(f"- **{card['tool_name']}**（{boundary}）：{card['best_for']}{citation}")
    lines.extend(["", "### 关键限制"])
    lines.extend(f"- {item}{caveat_citation}" for item in primary["caveats"][:3])
    if task_id == "doublet_detection":
        lines.extend(
            [
                "",
                "### 实际下一步",
                "1. 对 `.h5ad` 做 DataProfile，确认 `layers['counts']`、`X` 或 `raw.X` 中哪一个是 raw counts。",
                f"2. 按 capture/sample 拆分后运行，并检查 simulated doublet score 分布与阈值。{caveat_citation}",
                "3. 将预测标签与 QC、cluster marker 和样本信息联合复核，再决定是否过滤。",
            ]
        )
    elif task_id == "batch_integration":
        lines.extend(
            [
                "",
                "### 实际下一步",
                f"1. 确认 `adata.obs` 中的技术 batch 列、细胞类型标签和当前 PCA/表达矩阵状态。{primary_citation}",
                f"2. 在相同细胞与预处理上比较 Harmony/Scanorama，不直接比较两个工具的原始内部 score。{primary_citation}",
                f"3. 联合检查 batch mixing、cell-type conservation、运行时间和内存，再选择配置。{primary_citation}",
            ]
        )
    return _append_references(lines, references)


def _caveat_report(
    task_label: str,
    cards: list[dict[str, Any]],
    references: list[dict[str, Any]],
) -> str:
    lines = [f"**{task_label} Top-{len(cards)} caveat：**"]
    for card in cards:
        caveat = "；".join(
            item.rstrip("。；") for item in card["caveats"][:2]
        ) or "尚缺 source-bound caveat"
        citation = _citations_for_tool(
            card["tool_name"], references, claim_type="failure_mode", limit=2
        )
        lines.append(f"- **{card['tool_name']}**：{caveat}。{citation}")
    return _append_references(lines, references[:6], heading="参考")


def _requested_top_k(query: str, *, default: int) -> int:
    text = _latest_followup_text(query).casefold()
    match = re.search(r"(?:top\s*[- ]?|前)\s*([1-9])", text)
    if match:
        return min(5, int(match.group(1)))
    chinese = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5}
    match = re.search(r"前([一二三四五])", text)
    if match:
        return chinese[match.group(1)]
    return default


def _top_k_answer_is_valid(query: str, content: str) -> bool:
    expected = _requested_top_k(query, default=3)
    rows = [
        line
        for line in content.splitlines()
        if re.match(r"^\s*(?:[-*]|\d+[.)])\s+", line)
    ]
    return len(rows) == expected


def _workflow_report(
    task_id: str,
    task_label: str,
    parent_result: dict[str, Any],
    references: list[dict[str, Any]],
    workflow_code_bundle: Optional[dict[str, Any]],
) -> str:
    plan = parent_result.get("workflow_plan") or {}
    if not plan and not workflow_code_bundle:
        reasons = ", ".join(parent_result.get("blockers") or ["qualified plan unavailable"])
        return f"**{task_label} 暂不能生成受控 workflow。**\n\n阻断原因：`{reasons}`。"
    if workflow_code_bundle:
        smoke_label = (
            "已在 synthetic demo 上通过 smoke"
            if workflow_code_bundle.get("smoke_tested")
            else "配方已版本化，但当前摘要未匹配 smoke 记录"
        )
        lines = [
            f"下面给你的是 **{task_label}** 的可直接运行 Python 配方，不再只是内部节点清单。",
            "",
            f"- 当前是 **dry-run workflow 导出**；ExecutionRequest：`{parent_result.get('execution_request_count', 0)}`，本次回答不会运行你的数据。",
            f"- 工具：**{workflow_code_bundle['tool_name']}**；运行环境：`{workflow_code_bundle['environment_name']}`。",
            f"- 验证状态：**{smoke_label}**；demo 只证明代码和产物链可运行，不代表真实生物学准确率。",
            "- 输入要求：",
            "",
        ]
        lines.extend(
            f"  - {requirement}"
            for requirement in workflow_code_bundle["input_requirements"]
        )
        lines.extend(
            [
            "### 先跑内置模拟数据",
            "```bash",
            workflow_code_bundle["demo_command"],
            "```",
            "",
            "### 换成你的数据",
            "```bash",
            workflow_code_bundle["data_command"],
            "```",
            ]
        )
        if task_id == "doublet_detection":
            lines.append(
                "如果数据只有一个 capture，可以删去 `--sample-key sample`；多样本时将 `sample` 换成实际的 `adata.obs` 列名。"
            )
        elif task_id == "batch_integration":
            lines.append(
                "将 `batch` 换成实际技术批次列；如果输入已经 log-normalized，请把 `--matrix-state` 改为 `log_normalized`。"
            )
        lines.extend(
            [
            "",
            "### 会得到什么",
            ]
        )
        lines.extend(
            f"- `{artifact}`" for artifact in workflow_code_bundle["output_artifacts"]
        )
        lines.extend(
            [
                "",
                "### 已通过 smoke 的完整脚本",
                "完整 Python 配方显示在回答下方的 **Verified runnable recipe** 面板中；展开后可一键复制。",
                "",
                "### 使用前必须理解的限制",
            ]
        )
        lines.extend(f"- {item}" for item in workflow_code_bundle["limitations"])
        lines.append(
            "- 这是一份已审核的固定配方导出，不是 LLM 任意生成代码；在 scKG 内真实运行仍需数据授权、plan-specific approval 和 execution gate。"
        )
        return _append_references(lines, references)

    lines = [
        f"下面是 **{task_label}** 的可审计 dry-run workflow。当前还没有与它匹配的 smoke-tested 导出配方。",
        "",
        "### 执行步骤",
    ]
    for index, step in enumerate(plan.get("steps") or [], start=1):
        operation = step.get("operation") or step.get("name") or step.get("node_id")
        outputs = ", ".join(step.get("output_artifacts") or [])
        lines.append(f"{index}. **{step.get('name') or step.get('node_id')}**：`{operation}` -> `{outputs}`")
    selected_tool = (plan.get("candidate_tools") or ["未选择"])[0]
    run_step = next(
        (
            step
            for step in plan.get("steps") or []
            if str(step.get("operation") or "") == "plan_tool_candidate_only"
        ),
        {},
    )
    parameters = run_step.get("parameters") or {}
    parameter_preview = ", ".join(
        f"{name}={parameters[name]}"
        for name in (
            "expected_doublet_rate",
            "n_prin_comps",
            "sim_doublet_ratio",
            "theta",
            "approx",
        )
        if name in parameters
    )
    lines.extend(
        [
            "",
            "### 当前参数与边界",
            f"- 首选工具：**{selected_tool}**；计划状态：`{plan.get('plan_status', 'dry_run')}`。",
            f"- 数据感知：`{plan.get('data_awareness', 'generic')}`；ExecutionRequest：`{parent_result.get('execution_request_count', 0)}`。",
            "- 必须先确认 raw count source；scaled 或 unresolved matrix 会在 planning gate 被阻断。",
            "- 进入 Restricted Execution 后，审批指纹会绑定数据、计划、合同、环境和参数，参数变化会使旧审批失效。",
        ]
    )
    if parameter_preview:
        lines.append(
            f"- 合同默认参数快照：`{parameter_preview}`；它们是起点，不是对所有数据的最优值。"
        )
    if task_id == "doublet_detection":
        lines.extend(
            [
                "",
                "### 结果验收",
                "- 验证 score/label 数量、有限值、hash、runtime 与 memory；失败时只允许白名单有界 repair。",
                "- 输出预测表、参数快照、ValidationResult、DecisionResult 和 Level 2 复现包。",
            ]
        )
    return _append_references(lines, references)


def _migration_report(
    task_label: str,
    paths: list[dict[str, Any]],
    references: list[dict[str, Any]],
) -> str:
    lines = [
        f"下面是面向 **{task_label}** 的算法迁移假设，不是已经发现或验证的新算法。",
        "",
        "### 可探索机制",
    ]
    if not paths:
        lines.append("- 当前结构化表示不足以提出可复核的迁移假设。")
    for path in paths:
        source = path.get("source_tool") or path.get("tool_name") or "Unknown tool"
        mechanism = path.get("transferable_mechanism") or path.get("mechanism") or "机制待补齐"
        gaps = path.get("compatibility_gaps") or path.get("missing_evidence") or []
        if isinstance(gaps, list):
            gaps_text = "、".join(str(item) for item in gaps[:3])
        else:
            gaps_text = str(gaps)
        lines.append(f"- **{source}**：迁移机制为 {mechanism}；缺口：{gaps_text or '需要独立实验验证'}。")
    lines.extend(
        [
            "",
            "### 必须经过的验证",
            "1. 先检查输入/输出和数据假设是否同构。",
            "2. 用 synthetic probe 验证工程可行性，再用独立真实数据验证科学有效性。",
            "3. 未通过验证的迁移结果只能显示为 hypothesis，不能进入推荐排名或自动执行。",
        ]
    )
    return _append_references(lines, references)


def _evidence_qa_report(
    query: str,
    task_label: str,
    cards: list[dict[str, Any]],
    references: list[dict[str, Any]],
    blockers: list[str],
    retrieval_snippets: list[dict[str, Any]],
    requested_tools: list[str],
    claim_bindings: Optional[list[_ClaimEvidenceBinding]] = None,
) -> str:
    bindings = list(claim_bindings) if claim_bindings is not None else []
    if claim_bindings is None:
        fallback_entities = requested_tools or [
            str(card.get("tool_name") or "")
            for card in cards[:1]
            if card.get("tool_name")
        ]
        bindings = _select_claim_evidence_bindings(
            retrieval_snippets,
            targets=_requested_claim_targets(query, fallback_entities),
            query=query,
        )
    if not bindings:
        return (
            f"我识别到任务为 **{task_label}**，但没有找到足以支持回答的 source-bound 内容。"
            "我不会用目录元数据补造结论。"
        )
    reference_by_evidence_id = {
        str(ref.get("source_span_id") or ""): ref
        for ref in references
        if ref.get("source_span_id")
    }
    rendered: list[tuple[_ClaimEvidenceBinding, str]] = []
    for binding in bindings:
        citations = "".join(
            f"[{reference_by_evidence_id[evidence.evidence_span_id]['index']}]"
            for evidence in binding.evidence_refs
            if evidence.evidence_span_id in reference_by_evidence_id
        )
        rendered.append((binding, citations))

    if len(rendered) == 1:
        binding, citations = rendered[0]
        if binding.support_status == "supported" and citations:
            lines = [
                f"**直接结论：{binding.entity} 的"
                f"{_claim_predicate_label(binding.predicate)}是：** "
                f"{binding.claim_text}{citations}"
            ]
        else:
            lines = [binding.claim_text]
    else:
        lines = [f"**{task_label}：直接回答**"]
        for binding, citations in rendered:
            label = _claim_predicate_label(binding.predicate)
            if binding.support_status == "supported" and citations:
                lines.append(
                    f"- **{binding.entity} · {label}**："
                    f"{binding.claim_text}{citations}"
                )
            else:
                lines.append(f"- **{binding.entity} · {label}**：{binding.claim_text}")

    if references:
        lines.extend(
            [
                "",
                f"检索到 {len(references)} 条与本问题直接匹配的 source-bound 片段；来源位置见下方参考资料。",
            ]
        )
    material_blockers = [item for item in blockers if item != "dense_model_pack_not_installed_using_kg_bm25"]
    if material_blockers:
        lines.append(f"- **证据边界：** `{', '.join(material_blockers[:3])}`。")
    return _append_references(lines, references)


def _claim_type_for_query(query: str) -> str:
    values = _claim_types_for_tool_query(
        _latest_followup_text(query),
        ResearchChatIntent.EVIDENCE_QA,
    )
    return next(
        (value for value in values if value not in {"mechanism", "benchmark"}),
        "general",
    )


def _append_references(
    lines: list[str],
    references: list[dict[str, Any]],
    *,
    heading: str = "参考资料",
) -> str:
    if not references:
        return "\n".join(lines)
    lines.extend(["", f"### {heading}"])
    for ref in references:
        lines.append(
            f"[{ref['index']}] {ref['tool_name']} · {ref['title']} · {ref['source_span']}"
        )
    return "\n".join(lines)


def _citation_for_tool(
    tool_name: str,
    references: list[dict[str, Any]],
    *,
    claim_type: str = "",
) -> str:
    matching = [
        ref
        for ref in references
        if str(ref.get("tool_name") or "").casefold() == str(tool_name).casefold()
    ]
    if claim_type and claim_type != "general":
        selected = [
            ref
            for ref in matching
            if claim_type in set(ref.get("selected_for_claim_types") or [])
        ]
        if selected:
            matching = selected
        typed = [
            ref
            for ref in matching
            if str(ref.get("claim_type") or "") == claim_type
            or claim_type in set(ref.get("support_claim_types") or [])
        ]
        if typed and not selected:
            matching = typed
    if not matching:
        return ""
    return f"[{matching[0]['index']}]"


def _citations_for_tool(
    tool_name: str,
    references: list[dict[str, Any]],
    *,
    claim_type: str = "",
    limit: int = 2,
) -> str:
    matching = [
        ref
        for ref in references
        if str(ref.get("tool_name") or "").casefold() == str(tool_name).casefold()
    ]
    if claim_type:
        typed = [
            ref
            for ref in matching
            if claim_type in set(ref.get("selected_for_claim_types") or [])
            or claim_type in set(ref.get("support_claim_types") or [])
            or str(ref.get("claim_type") or "") == claim_type
        ]
        if typed:
            matching = typed
    return "".join(f"[{ref['index']}]" for ref in matching[: max(1, limit)])


def _audit_grounded_answer(
    content: str,
    *,
    references: list[dict[str, Any]],
    execution_request_count: int,
) -> dict[str, Any]:
    return _audit_grounded_answer_v2(
        content,
        references=references,
        execution_request_count=execution_request_count,
    ).model_dump(mode="json")


def _audit_grounded_answer_v3(
    content: str,
    *,
    references: list[dict[str, Any]],
    execution_request_count: int,
) -> GroundedAnswerAuditV3:
    return audit_grounded_answer_v3(
        content,
        references=references,
        execution_request_count=execution_request_count,
    )


def _audit_grounded_answer_v2(
    content: str,
    *,
    references: list[dict[str, Any]],
    execution_request_count: int,
) -> GroundedAnswerAuditV2:
    allowed = {int(ref["index"]) for ref in references if ref.get("index") is not None}
    cited = {int(value) for value in re.findall(r"\[(\d+)\]", content)}
    invalid = sorted(cited - allowed)
    execution_claim = execution_request_count == 0 and any(
        marker in content.casefold()
        for marker in (
            "我已经运行",
            "已经执行成功",
            "本次执行成功",
            "已完成运行",
            "actually executed",
            "execution succeeded",
        )
    )
    by_index = {
        int(ref["index"]): ref
        for ref in references
        if ref.get("index") is not None
    }
    claims = _extract_claim_records(content, by_index=by_index)
    scientific_claims = [
        claim
        for claim in claims
        if claim.entailment_status != ClaimEntailmentStatus.NOT_APPLICABLE.value
    ]
    unsupported = [
        claim
        for claim in scientific_claims
        if claim.entailment_status
        in {
            ClaimEntailmentStatus.UNSUPPORTED.value,
            ClaimEntailmentStatus.CONFLICTING.value,
        }
    ]
    kept = [
        claim
        for claim in scientific_claims
        if claim.entailment_status
        in {
            ClaimEntailmentStatus.SUPPORTED.value,
            ClaimEntailmentStatus.PARTIALLY_SUPPORTED.value,
        }
    ]
    supported = [
        claim
        for claim in scientific_claims
        if claim.entailment_status == ClaimEntailmentStatus.SUPPORTED.value
    ]
    valid_cited = cited & allowed
    citation_precision = len(valid_cited) / len(cited) if cited else 0.0
    citation_coverage = (
        len(kept) / len(scientific_claims) if scientific_claims else 1.0
    )
    supported_claim_rate = (
        len(supported) / len(scientific_claims) if scientific_claims else 1.0
    )
    governance_violations = len(invalid) + int(execution_claim)
    passed = (
        bool(allowed)
        and not invalid
        and not execution_claim
        and not unsupported
        and citation_coverage >= 0.95
    )
    reasons: list[str] = []
    if invalid:
        reasons.append("invalid_reference_index")
    if not allowed:
        reasons.append("source_bound_context_missing")
    if execution_claim:
        reasons.append("unsupported_execution_claim")
    if unsupported:
        reasons.append("unsupported_scientific_claim")
    if citation_coverage < 0.95:
        reasons.append("claim_citation_coverage_below_gate")
    return GroundedAnswerAuditV2(
        passed=passed,
        claims=claims,
        cited_references=sorted(cited),
        invalid_citations=invalid,
        citation_precision=round(citation_precision, 6),
        citation_coverage=round(citation_coverage, 6),
        supported_claim_rate=round(supported_claim_rate, 6),
        unsupported_claim_count=len(unsupported),
        execution_claim_violation=execution_claim,
        governance_violation_count=governance_violations,
        reasons=reasons,
    )


def _extract_claim_records(
    content: str,
    *,
    by_index: dict[int, dict[str, Any]],
) -> list[ClaimRecord]:
    claims: list[ClaimRecord] = []
    segments = _claim_segments(content)
    for index, segment in enumerate(segments, start=1):
        cited_indexes = [int(value) for value in re.findall(r"\[(\d+)\]", segment)]
        clean_text = re.sub(r"\[(\d+)\]", "", segment).strip(" -*\t")
        if not clean_text:
            continue
        scientific = _looks_like_scientific_claim(clean_text)
        if not scientific:
            claims.append(
                ClaimRecord(
                    claim_id=f"claim-{index:03d}",
                    claim_text=clean_text,
                    claim_type="non_scientific",
                    entailment_status=ClaimEntailmentStatus.NOT_APPLICABLE,
                    action=ClaimAction.NOT_APPLICABLE,
                )
            )
            continue
        refs = [by_index[value] for value in cited_indexes if value in by_index]
        source_bound_refs = [
            ref
            for ref in refs
            if ref.get("authority") == "source_bound" and ref.get("source_bound", True)
        ]
        source_span_ids = [
            str(ref.get("source_span_id") or ref.get("source_id") or "")
            for ref in source_bound_refs
            if ref.get("source_span_id") or ref.get("source_id")
        ]
        if not cited_indexes or not source_bound_refs:
            status = ClaimEntailmentStatus.UNSUPPORTED
            action = ClaimAction.REMOVE
            reasons = ["scientific_claim_requires_source_bound_citation"]
            authority = "none"
        else:
            tool_names = {
                str(ref.get("tool_name") or "").casefold()
                for ref in source_bound_refs
                if ref.get("tool_name")
            }
            mentioned_tools = {
                name
                for name in _ALGORITHM_GUIDE
                if re.search(rf"\b{re.escape(name)}\b", clean_text.casefold())
            }
            tool_mismatch = bool(mentioned_tools and not (mentioned_tools & tool_names))
            overlap = max(
                (
                    _claim_overlap(
                        clean_text,
                        str(ref.get("claim_text") or ref.get("title") or ""),
                    )
                    for ref in source_bound_refs
                ),
                default=0.0,
            )
            conflict = any(
                _claim_conflicts(clean_text, str(ref.get("claim_text") or ""))
                for ref in source_bound_refs
            )
            if conflict:
                status = ClaimEntailmentStatus.CONFLICTING
                action = ClaimAction.SHOW_CONFLICT
                reasons = ["claim_conflicts_with_cited_source"]
            elif tool_mismatch:
                status = ClaimEntailmentStatus.UNSUPPORTED
                action = ClaimAction.REMOVE
                reasons = ["citation_tool_mismatch"]
            elif overlap >= 0.08 or bool(mentioned_tools & tool_names):
                status = ClaimEntailmentStatus.SUPPORTED
                action = ClaimAction.KEEP
                reasons = []
            else:
                status = ClaimEntailmentStatus.PARTIALLY_SUPPORTED
                action = ClaimAction.QUALIFY
                reasons = ["citation_present_but_lexical_entailment_is_weak"]
            authority = "source_bound"
        claims.append(
            ClaimRecord(
                claim_id=f"claim-{index:03d}",
                claim_text=clean_text,
                claim_type=_claim_type_for_query(clean_text),
                source_span_ids=source_span_ids,
                authority=authority,
                entailment_status=status,
                action=action,
                reasons=reasons,
            )
        )
    return claims


def _claim_segments(content: str) -> list[str]:
    segments: list[str] = []
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if len(line) <= 36 and line.rstrip("：:").casefold() in {
            "参考资料",
            "references",
            "适用",
            "输入",
            "输出",
            "限制",
        }:
            continue
        pieces = re.split(r"(?<=[。！？!?])\s+", line)
        segments.extend(piece.strip() for piece in pieces if piece.strip())
    return segments


def _capability_workspace_handoff(
    *,
    context_pack: dict[str, Any],
    mode: AgentMode,
    task: str,
    plan_id: str | None,
    query: str = "",
) -> dict[str, Any] | None:
    """Build a generic planning handoff from governed capability discovery."""

    if mode not in {AgentMode.PLAN, AgentMode.RUN}:
        return None
    candidates = []
    for item in context_pack.get("capability_context") or []:
        if not isinstance(item, dict):
            continue
        readiness = {str(value).casefold() for value in item.get("readiness") or []}
        if not any(value.endswith("planning_ready") for value in readiness):
            continue
        targets = [
            str(value)
            for value in item.get("suggested_workspace_targets") or []
            if str(value)
        ]
        if not targets:
            continue
        candidates.append((item, targets))
    if not candidates:
        return None
    task_key = task.casefold().replace("-", "_").strip()
    task_terms = {
        term
        for term in task_key.split("_")
        if term and term not in {"and", "workflow", "analysis"}
    }

    def matches_task(candidate: tuple[dict[str, Any], list[str]]) -> bool:
        capability = candidate[0]
        family = str(capability.get("task_family") or "").casefold()
        capability_id = str(capability.get("capability_id") or "").casefold()
        capability_title = str(capability.get("capability_title") or "").casefold()
        if task_key and family == task_key:
            return True
        searchable = {
            term
            for term in re.split(
                r"[^a-z0-9]+", f"{family} {capability_id} {capability_title}"
            )
            if term and term not in {"and", "workflow", "analysis", "scanpy", "core"}
        }
        return bool(task_terms and task_terms.intersection(searchable))

    matched = next((candidate for candidate in candidates if matches_task(candidate)), None)
    if matched is None:
        return None
    capability, targets = matched
    preferred_method_ids: list[str] = []
    query_key = query.casefold()
    pack_id = str(capability.get("pack_id") or "")
    if pack_id == "scanpy_core" and re.search(r"(?<![a-z])scale(?![a-z])", query_key):
        explicitly_requires_scale = any(
            phrase in query_key
            for phrase in (
                "不要跳过 scale",
                "必须保留 scale",
                "do not skip scale",
                "don't skip scale",
            )
        )
        disables_scale = not explicitly_requires_scale and any(
            phrase in query_key
            for phrase in (
                "skip scale",
                "without scale",
                "disable scale",
                "不使用 scale",
                "跳过 scale",
            )
        )
        preferred_method_ids = (
            ["scanpy_core.pca_log_hvg"]
            if disables_scale
            else ["scanpy_core.scale_hvg", "scanpy_core.pca_scaled"]
        )
    return {
        "status": "available",
        "task_family": str(capability.get("task_family") or task),
        "plan_id": plan_id,
        "notebook_strategy": "capability_renderer",
        "stepwise_preview_available": True,
        "pack_id": pack_id,
        "pack_version": str(capability.get("pack_version") or ""),
        "target_representations": targets,
        "preferred_method_ids": preferred_method_ids,
        "blockers": list(capability.get("blockers") or []),
    }


def _looks_like_scientific_claim(text: str) -> bool:
    lowered = text.casefold()
    non_scientific_prefixes = (
        "我还不能",
        "请补充",
        "下一步",
        "当前状态",
        "executionrequest",
        "execution request",
        "缺少 source-bound",
        "source-bound evidence is missing",
    )
    if lowered.startswith(non_scientific_prefixes):
        return False
    scientific_markers = (
        "scrublet",
        "scdblfinder",
        "doubletfinder",
        "harmony",
        "scanorama",
        "doublet",
        "raw count",
        "umi",
        "batch",
        "embedding",
        "matrix",
        "anndata",
        "h5ad",
        "细胞",
        "矩阵",
        "原始计数",
        "批次",
        "表达",
        "算法",
        "输入",
        "输出",
        "适用",
        "限制",
        "阈值",
    )
    return any(marker in lowered for marker in scientific_markers)


def _claim_overlap(left: str, right: str) -> float:
    left_tokens = _claim_tokens(left)
    right_tokens = _claim_tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens)


def _claim_conflicts(claim: str, source: str) -> bool:
    claim_text = claim.casefold()
    source_text = source.casefold()
    source_requires_raw = any(
        marker in source_text
        for marker in ("requires raw", "raw count", "原始计数", "raw umi")
    )
    claim_allows_processed = any(
        marker in claim_text
        for marker in (
            "scaled matrix",
            "scaled matrices",
            "log-normalized",
            "log normalized",
            "标准化矩阵",
            "缩放矩阵",
        )
    )
    return source_requires_raw and claim_allows_processed


def _claim_tokens(value: str) -> set[str]:
    normalized = re.sub(r"\s+", " ", value.casefold())
    words = set(re.findall(r"[a-z0-9_.-]{3,}", normalized))
    chinese = "".join(re.findall(r"[\u4e00-\u9fff]", normalized))
    bigrams = {chinese[index : index + 2] for index in range(max(0, len(chinese) - 1))}
    return words | bigrams
