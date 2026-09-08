from __future__ import annotations

import json
from pathlib import Path

import pytest

import agent.research_chat_service as research_module
from agent.audited_parent_agent import AuditedParentAgent
from agent.bounded_parent_agent import BoundedParentAgent
from agent.research_tool_registry import ResearchToolExecution
from core.knowledge_intelligence_models import HybridRetrievalResult
from core.research_agent_models import AgentMode, ResearchAgentRequest
from core.trace_context import (
    TraceCollector,
    TraceContext,
    TraceCorrelationKind,
    TraceKind,
    TracePersistenceError,
    TraceStateError,
    TraceValidationError,
    trace_correlation_id,
)
from tests.test_research_chat_service import _default_service, _service


def _row(path: Path) -> dict:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1
    return rows[0]


def _stages(row: dict) -> list[str]:
    return [span["stage"] for span in row["spans"]]


def test_research_request_owns_one_canonical_trace_and_propagates_id(tmp_path):
    service = _service(tmp_path)
    response = service.run_request(
        ResearchAgentRequest(
            request_id="trace-ask",
            query="What raw count input does Scrublet require?",
            mode=AgentMode.ASK,
        )
    )

    row = _row(tmp_path / "traces.jsonl")
    assert response.canonical_trace_id == response.state.canonical_trace_id == row["trace_id"]
    assert response.state.request_id == "trace-ask"
    assert row["request_id"] == "trace-ask"
    assert row["trace_kind"] == "RESEARCH"
    assert _stages(row) == ["REQUEST", "ROUTING", "RETRIEVAL"]
    assert len([span for span in row["spans"] if span["parent_span_id"] is None]) == 1
    assert "STATE_INSPECTION" not in _stages(row)
    persisted = (tmp_path / "traces.jsonl").read_text(encoding="utf-8")
    assert response.user_query not in persisted
    assert "Scrublet requires raw count matrices" not in persisted


def test_plan_trace_records_planning_and_service_owned_handoff(tmp_path):
    service = _service(tmp_path)
    response = service.run_request(
        ResearchAgentRequest(
            request_id="trace-plan",
            query="Build a doublet detection workflow.",
            mode=AgentMode.PLAN,
        )
    )

    row = _row(tmp_path / "traces.jsonl")
    handoff = response.workspace_handoff
    assert _stages(row) == ["REQUEST", "ROUTING", "RETRIEVAL", "PLANNING", "HANDOFF"]
    assert handoff.status == "available"
    assert handoff.origin_trace_id == response.canonical_trace_id
    assert handoff.parent_request_id == row["request_id"]
    assert handoff.original_plan_id == response.workflow_plan["plan_id"]
    assert handoff.handoff_id
    handoff_span = next(span for span in row["spans"] if span["stage"] == "HANDOFF")
    assert handoff_span["output_refs"][0]["record_id"] == handoff.handoff_id


def test_plan_with_optional_evidence_miss_records_partial_retrieval(tmp_path):
    service = _default_service(tmp_path)
    response = service.run_request(
        ResearchAgentRequest(
            request_id="trace-plan-optional-evidence",
            query=(
                "请为 10x PBMC 生成一个经过 smoke 测试、可复制运行的 "
                "doublet detection workflow。\n\n"
                "本轮只生成 dry-run workflow，不执行数据。"
            ),
            mode=AgentMode.PLAN,
        )
    )

    row = _row(tmp_path / "traces.jsonl")
    assert response.workflow_plan["plan_status"] == "dry_run"
    assert response.workflow_code_bundle["smoke_tested"] is True
    assert response.execution_handoff.status == "not_requested"
    retrieval_span = next(span for span in row["spans"] if span["stage"] == "RETRIEVAL")
    assert retrieval_span["status"] == "PARTIAL"
    assert retrieval_span["decision_evidence"][-1]["reason_code"] == (
        "optional_evidence_context_missing"
    )


def test_evidence_question_with_no_hits_remains_blocked_retrieval(tmp_path):
    service = _service(tmp_path)
    service._research_tools.execute = lambda *_args, **_kwargs: ResearchToolExecution(
        retrieval_results=[
            HybridRetrievalResult(
                query="What raw count input does Scrublet require?",
                mode="kg_bm25",
                hits=[],
                latency_ms=0.0,
                index_build_id="empty-test-index",
            )
        ]
    )
    service.run_request(
        ResearchAgentRequest(
            request_id="trace-evidence-miss",
            query="What raw count input does Scrublet require?",
            mode=AgentMode.ASK,
        )
    )

    row = _row(tmp_path / "traces.jsonl")
    retrieval_span = next(span for span in row["spans"] if span["stage"] == "RETRIEVAL")
    assert retrieval_span["status"] == "BLOCKED"
    assert retrieval_span["decision_evidence"][-1]["reason_code"] == (
        "retrieval_result_missing"
    )


def test_non_retrieval_and_clarification_routes_do_not_emit_fake_spans(tmp_path):
    system_path = tmp_path / "system-traces.jsonl"
    service = _service(tmp_path)
    service._trace_collector = TraceCollector(system_path)
    system = service.run_request(
        ResearchAgentRequest(request_id="system-route", query="你好，你是什么模型？")
    )
    system_row = _row(system_path)
    assert system.status == "ANSWERED"
    assert _stages(system_row) == ["REQUEST", "ROUTING"]

    clarification_path = tmp_path / "clarification-traces.jsonl"
    service._trace_collector = TraceCollector(clarification_path)
    clarification = service.run_request(
        ResearchAgentRequest(request_id="clarify-route", query="这个矩阵为什么不对？")
    )
    clarification_row = _row(clarification_path)
    assert clarification.status == "WAITING"
    assert clarification_row["status"] == "PARTIAL"
    assert _stages(clarification_row) == ["REQUEST", "ROUTING"]


def test_injected_context_identity_and_lifecycle_transfer(tmp_path):
    service = _service(tmp_path)
    trace = TraceContext.new_request(
        trace_kind=TraceKind.RESEARCH,
        request_id="injected-request",
        conversation_id="local-conversation",
    )
    seen: list[int] = []
    original = service._execute_pipeline

    def observe(*args, **kwargs):
        seen.append(id(kwargs["trace_context"]))
        return original(*args, **kwargs)

    service._execute_pipeline = observe
    response = service.run_request(
        ResearchAgentRequest(
            request_id="injected-request",
            query="What raw count input does Scrublet require?",
        ),
        trace_context=trace,
    )

    assert seen == [id(trace)]
    assert response.canonical_trace_id == trace.trace_id
    assert trace.collected is True
    with pytest.raises(TraceStateError):
        trace.finish()
    with pytest.raises(TraceStateError):
        service._trace_collector.collect(trace)


def test_invalid_injected_contexts_are_rejected_before_business(tmp_path):
    service = _service(tmp_path)
    request = ResearchAgentRequest(request_id="expected-request", query="hello")
    legacy = TraceContext()
    with pytest.raises(TraceStateError):
        service.run_request(request, trace_context=legacy)

    mismatched = TraceContext.new_request(
        trace_kind=TraceKind.RESEARCH,
        request_id="different-request",
    )
    with pytest.raises(TraceValidationError):
        service.run_request(request, trace_context=mismatched)

    finalized = TraceContext.new_request(
        trace_kind=TraceKind.RESEARCH,
        request_id="expected-request",
    )
    finalized.finish()
    with pytest.raises(TraceStateError):
        service.run_request(request, trace_context=finalized)


@pytest.mark.parametrize(
    "trace_kind",
    [TraceKind.STEPWISE, TraceKind.CONTROLLED_EXECUTION],
)
def test_non_research_injected_context_is_rejected_before_business(
    tmp_path,
    trace_kind,
):
    class ObservedGraph:
        calls = 0

        @classmethod
        def invoke(cls, _payload):
            cls.calls += 1
            raise AssertionError("business graph must not run")

    service = _service(tmp_path)
    service._application_graph = ObservedGraph()
    trace = TraceContext.new_request(
        trace_kind=trace_kind,
        request_id="wrong-kind-request",
        conversation_id="local-conversation",
    )

    with pytest.raises(TraceStateError, match="RESEARCH kind"):
        service.run_request(
            ResearchAgentRequest(
                request_id="wrong-kind-request",
                query="What raw count input does Scrublet require?",
            ),
            trace_context=trace,
        )

    assert ObservedGraph.calls == 0
    assert trace.finished_at is None
    assert trace.collected is False
    assert not (tmp_path / "traces.jsonl").exists()


def test_long_business_ids_use_deterministic_refs_without_changing_research(tmp_path):
    request_id = "r" * 257
    conversation_id = "c" * 257
    request = ResearchAgentRequest(
        request_id=request_id,
        conversation_id=conversation_id,
        query="What raw count input does Scrublet require?",
    )
    response = _service(tmp_path).run_request(request)
    row = _row(tmp_path / "traces.jsonl")

    assert response.state.request_id == request_id
    assert response.state.conversation_id == conversation_id
    assert row["request_id"] == trace_correlation_id(
        request_id,
        kind=TraceCorrelationKind.REQUEST,
    )
    assert row["conversation_id"] == trace_correlation_id(
        conversation_id,
        kind=TraceCorrelationKind.CONVERSATION,
    )
    persisted = (tmp_path / "traces.jsonl").read_text(encoding="utf-8")
    assert request_id not in persisted
    assert conversation_id not in persisted


def test_injected_context_matches_long_business_id_by_surrogate(tmp_path):
    request_id = "r" * 257
    conversation_id = "c" * 257
    trace = TraceContext.new_request(
        trace_kind=TraceKind.RESEARCH,
        request_id=trace_correlation_id(
            request_id,
            kind=TraceCorrelationKind.REQUEST,
        ),
        conversation_id=trace_correlation_id(
            conversation_id,
            kind=TraceCorrelationKind.CONVERSATION,
        ),
    )
    response = _service(tmp_path).run_request(
        ResearchAgentRequest(
            request_id=request_id,
            conversation_id=conversation_id,
            query="What raw count input does Scrublet require?",
        ),
        trace_context=trace,
    )
    assert response.canonical_trace_id == trace.trace_id
    assert trace.collected is True


def test_sensitive_business_ids_get_opaque_trace_without_hashing_or_injection(tmp_path):
    request_id = "sk-1234567890abcdef"
    conversation_id = "jupyter-token-1234567890"
    injected = TraceContext.new_request(
        trace_kind=TraceKind.RESEARCH,
        request_id="caller-injected-safe-id",
    )
    request = ResearchAgentRequest(
        request_id=request_id,
        conversation_id=conversation_id,
        query="What raw count input does Scrublet require?",
    )
    response = _service(tmp_path).run_request(request, trace_context=injected)
    row = _row(tmp_path / "traces.jsonl")

    assert response.state.request_id == request_id
    assert response.canonical_trace_id != injected.trace_id
    assert injected.finished_at is None
    assert injected.collected is False
    assert row["request_id"].startswith("request-ref:opaque:")
    assert row["conversation_id"] is None
    decisions = [
        decision
        for span in row["spans"]
        for decision in span["decision_evidence"]
    ]
    assert any(
        decision["reason_code"] == "sensitive_source_id_redacted"
        for decision in decisions
    )
    persisted = (tmp_path / "traces.jsonl").read_text(encoding="utf-8")
    assert request_id not in persisted
    assert conversation_id not in persisted


def test_sensitive_plan_keeps_business_planning_but_omits_legacy_trace_link(tmp_path):
    request_id = "sk-1234567890abcdef"
    conversation_id = "jupyter-token-1234567890"
    service = _default_service(tmp_path)
    parent = BoundedParentAgent()
    audited_parent = AuditedParentAgent(parent)
    original_plan = audited_parent.plan
    observed_request_ids: list[str] = []

    def observe_plan(request, *, case_id):
        observed_request_ids.append(request.request_id)
        return original_plan(request, case_id=case_id)

    audited_parent.plan = observe_plan
    service._parent_agent = parent
    service._audited_parent = audited_parent
    response = service.run_request(
        ResearchAgentRequest(
            request_id=request_id,
            conversation_id=conversation_id,
            query="Build a doublet detection workflow.",
            mode=AgentMode.PLAN,
        )
    )

    row = _row(tmp_path / "traces.jsonl")
    assert observed_request_ids == [request_id]
    assert response.status == "READY"
    assert response.workflow_plan is not None
    assert response.trace is not None
    assert response.trace["request_id"] == request_id
    legacy_trace_id = response.trace["trace_id"]
    assert legacy_trace_id in response.state.trace_ids
    assert row["request_id"].startswith("request-ref:opaque:")
    assert row["conversation_id"] is None
    assert "PLANNING" in _stages(row)
    assert not any(
        link["link_type"] == "UNIFIED_AGENT_TRACE" for link in row["links"]
    )
    decisions = [
        decision
        for span in row["spans"]
        for decision in span["decision_evidence"]
    ]
    assert any(
        decision["reason_code"] == "sensitive_source_id_redacted"
        for decision in decisions
    )
    persisted = (tmp_path / "traces.jsonl").read_text(encoding="utf-8")
    assert request_id not in persisted
    assert conversation_id not in persisted
    assert legacy_trace_id not in persisted


@pytest.mark.parametrize("mode", [AgentMode.PLAN, AgentMode.RUN])
def test_safe_plan_and_run_preserve_unified_agent_trace_alias(tmp_path, mode):
    request_id = f"safe-{mode.value.casefold()}-request"
    response = _default_service(tmp_path).run_request(
        ResearchAgentRequest(
            request_id=request_id,
            query="Build a doublet detection workflow.",
            mode=mode,
        )
    )

    row = _row(tmp_path / "traces.jsonl")
    assert response.trace is not None
    legacy_trace_id = response.trace["trace_id"]
    assert response.trace["request_id"] == request_id
    assert legacy_trace_id in response.state.trace_ids
    assert any(
        link["link_type"] == "UNIFIED_AGENT_TRACE"
        and link["target_id"] == legacy_trace_id
        for link in row["links"]
    )


def test_correlation_adapter_is_never_called_with_query_content(tmp_path, monkeypatch):
    calls: list[str] = []
    real_adapter = research_module.trace_correlation_id

    def observe(value, *, kind):
        calls.append(value)
        return real_adapter(value, kind=kind)

    monkeypatch.setattr(research_module, "trace_correlation_id", observe)
    query = "q" * 400
    request = ResearchAgentRequest(
        request_id="adapter-request",
        conversation_id="adapter-conversation",
        query=query,
    )
    _service(tmp_path).run_request(request)
    assert calls == [request.request_id, request.conversation_id]
    assert query not in (tmp_path / "traces.jsonl").read_text(encoding="utf-8")


def test_trace_persistence_failure_does_not_change_research_result(tmp_path, monkeypatch):
    collector = TraceCollector(tmp_path / "traces.jsonl")

    def fail_append(_encoded):
        raise TracePersistenceError("trace append failed")

    monkeypatch.setattr(collector, "_append_encoded", fail_append)
    service = _service(tmp_path)
    service._trace_collector = collector
    response = service.run_request(
        ResearchAgentRequest(
            request_id="persistence-failure",
            query="What raw count input does Scrublet require?",
        )
    )
    assert response.status == "ANSWERED"
    assert not (tmp_path / "traces.jsonl").exists()


def test_safe_trace_emission_failure_does_not_change_research_result(
    tmp_path,
    monkeypatch,
):
    def reject_ref(*_args, **_kwargs):
        raise TraceValidationError("telemetry ref rejected")

    monkeypatch.setattr(TraceContext, "_add_span_ref", reject_ref)
    response = _service(tmp_path).run_request(
        ResearchAgentRequest(
            request_id="emission-failure",
            query="What raw count input does Scrublet require?",
        )
    )
    assert response.status == "ANSWERED"
    row = _row(tmp_path / "traces.jsonl")
    assert row["status"] == "SUCCESS"


def test_business_exception_remains_primary(tmp_path):
    class BusinessFailure(RuntimeError):
        pass

    class FailingGraph:
        @staticmethod
        def invoke(_payload):
            raise BusinessFailure("primary business failure")

    service = _service(tmp_path)
    service._application_graph = FailingGraph()
    with pytest.raises(BusinessFailure, match="primary business failure"):
        service.run_request(
            ResearchAgentRequest(request_id="business-failure", query="hello")
        )
    row = _row(tmp_path / "traces.jsonl")
    assert row["status"] == "FAILED"


def test_routing_business_exception_marks_semantic_span_failed(tmp_path):
    class BusinessFailure(RuntimeError):
        pass

    class FailingReasoner:
        @staticmethod
        def parse(**_kwargs):
            raise BusinessFailure("semantic provider failed")

    service = _service(tmp_path)
    service._reasoner = FailingReasoner()
    with pytest.raises(BusinessFailure, match="semantic provider failed"):
        service.run_request(
            ResearchAgentRequest(
                request_id="routing-business-failure",
                query="What raw count input does Scrublet require?",
            ),
            user_runtime_config={"privacy_authorized": True},
        )
    row = _row(tmp_path / "traces.jsonl")
    assert row["status"] == "FAILED"
    assert _stages(row) == ["REQUEST", "ROUTING"]
    assert row["spans"][1]["status"] == "FAILED"


def test_app_no_longer_owns_research_trace_or_handoff_identity():
    source = (Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8")
    run_agent = source[source.index("def _run_agent("):source.index("\ndef _state_get_list")]
    handoff = source[
        source.index("def _workspace_handoff_payload("):
        source.index("\ndef _render_workspace_handoff")
    ]
    assert "TraceContext" not in run_agent
    assert "TraceCollector" not in run_agent
    assert "stage_timer" not in run_agent
    assert "reflect_agent_run" in run_agent
    assert 'f"workspace-{uuid.uuid4().hex}"' not in handoff
    assert 'governed_handoff.get("handoff_id")' in handoff
