from __future__ import annotations

from core.evaluation_models import EvaluationCase, ExpectedTrajectory, ReferenceClaim
from core.trace_context import TraceCollector, TraceContext, TraceKind, TraceStage
from eval.unified_case_runner import UnifiedConversationCaseRunner


class _Service:
    def run(self, query, *, conversation_context=None):
        return {
            "domain": "SINGLE_CELL",
            "response_intent": "evidence_qa",
            "extracted_constraints": {"canonical_task": "doublet_detection"},
            "deterministic_parent_result": {"execution_request_count": 0},
            "context_pack": {
                "semantic_route": {"domain": "SINGLE_CELL"},
                "grounded_answer_audit": {"invalid_citations": []},
            },
            "references": [
                {"source_span_id": "sourcev2:e28960d0fd977f0c60ce"}
            ],
            "final_report": "Scrublet uses a raw UMI count matrix [1].",
            "runtime_mode": "test",
        }


def test_unified_runner_scores_real_source_span_not_arbitrary_snippet():
    case = EvaluationCase(
        case_id="conversation.scrublet",
        dataset_version="v1",
        source="test",
        split="evaluation",
        input={"query": "Scrublet input?"},
        applicable_metrics=[
            "routing.domain",
            "claim.scientific_precision",
            "citation.precision",
        ],
        routing_gold={
            "domain": "SINGLE_CELL",
            "intent": "evidence_qa",
            "task": "doublet_detection",
        },
        answer_gold=[
            ReferenceClaim(
                claim_id="raw",
                claim_text="raw counts",
                source_span_ids=["sourcev2:e28960d0fd977f0c60ce"],
                scope="Scrublet",
            )
        ],
    )
    records, metrics = UnifiedConversationCaseRunner(service=_Service()).run(
        [case], experiment_id="exp"
    )
    by_id = {metric.metric_id: metric for metric in metrics}
    assert records[0].status == "completed"
    assert by_id["citation.precision"].value == 1.0
    assert by_id["citation.coverage"].value == 1.0
    assert by_id["trace.completeness"].value == 0.0
    assert records[0].trace == []


class _CanonicalTraceService:
    def __init__(self, collector):
        self.collector = collector

    def run(self, query, *, conversation_context=None):
        trace = TraceContext.new_request(
            trace_kind=TraceKind.RESEARCH,
            request_id="evaluation-research-request",
        )
        with self.collector.request_scope(trace):
            with trace.span(
                stage=TraceStage.ROUTING,
                component="research_router",
                operation="route",
            ):
                pass
            with trace.span(
                stage=TraceStage.RETRIEVAL,
                component="hybrid_retrieval",
                operation="retrieve",
            ):
                pass
        return {
            "canonical_trace_id": trace.trace_id,
            "domain": "SINGLE_CELL",
            "response_intent": "evidence_qa",
            "extracted_constraints": {"canonical_task": "doublet_detection"},
            "deterministic_parent_result": {"execution_request_count": 0},
            "context_pack": {
                "semantic_route": {"domain": "SINGLE_CELL"},
                "grounded_answer_audit": {"invalid_citations": []},
            },
            "references": [],
            "final_report": "bounded answer",
            "runtime_mode": "test",
        }


def test_unified_runner_links_canonical_trace_and_scores_trajectory(tmp_path):
    trace_path = tmp_path / "canonical-traces.jsonl"
    case = EvaluationCase(
        case_id="conversation.trace",
        dataset_version="v1",
        source="test",
        split="evaluation",
        input={"query": "trace this request"},
        applicable_metrics=[
            "trajectory.required_steps",
            "trajectory.forbidden_steps",
            "trajectory.ordering",
            "trace.completeness",
        ],
        expected_trajectory=ExpectedTrajectory(
            required_steps=["routing", "retrieval"],
            forbidden_steps=["planning", "execution"],
            ordered_steps=["routing", "retrieval"],
            must_stop_after="retrieval",
        ),
    )
    records, metrics = UnifiedConversationCaseRunner(
        service=_CanonicalTraceService(TraceCollector(trace_path)),
        trace_path=trace_path,
    ).run([case], experiment_id="exp")
    by_id = {metric.metric_id: metric for metric in metrics}

    record = records[0]
    assert record.canonical_trace_id.startswith("trace_")
    assert [span["stage"] for span in record.trace] == [
        "REQUEST",
        "ROUTING",
        "RETRIEVAL",
    ]
    assert record.evaluation_failures == []
    assert by_id["trace.completeness"].value == 1.0
    assert by_id["trajectory.required_steps"].value == 1.0
    assert by_id["trajectory.forbidden_steps"].value == 1.0
    assert by_id["trajectory.ordering"].value == 1.0
    assert by_id["trajectory.stop_correctness"].value == 1.0
