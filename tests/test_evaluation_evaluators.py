from __future__ import annotations

from core.evaluation_models import (
    EvaluationMetricStatus,
    EvaluationRunRecord,
    EvaluationSignal,
    EvaluatorResult,
    ExpectedToolCall,
    ExpectedTrajectory,
    ReferenceClaim,
)
from eval.evaluation_evaluators import (
    attribute_failure,
    decide_release_gate,
    evaluate_atomic_claims,
    evaluate_trajectory,
    response_stability,
)


def test_trajectory_checks_tool_arguments_order_and_forbidden_actions():
    expected = ExpectedTrajectory(
        required_steps=["plan", "execution", "validation"],
        forbidden_steps=["install_package"],
        ordered_steps=["plan", "execution", "validation"],
        required_tool_calls=[
            ExpectedToolCall(tool_name="scrublet", required_arguments={"seed": 7})
        ],
        must_stop_after="validation",
    )
    trace = [
        {"stage": "plan", "type": "stage"},
        {"stage": "execution", "type": "tool_call", "tool": "scrublet", "arguments": {"seed": 7}},
        {"stage": "validation", "type": "stage"},
    ]
    result = evaluate_trajectory(expected, trace)
    assert result["required_step_subset"] is True
    assert result["tool_argument_correctness"] is True
    assert result["ordering_correct"] is True
    assert result["stop_correctness"] is True


def test_atomic_claims_do_not_accept_unmapped_claims_or_arbitrary_citations():
    gold = [
        ReferenceClaim(
            claim_id="claim.raw",
            claim_text="raw counts required",
            source_span_ids=["span:1"],
            scope="tool v1",
        )
    ]
    measured = evaluate_atomic_claims(
        gold,
        [
            {"claim_id": "claim.raw", "status": "supported", "source_span_ids": ["span:2"]},
            {"claim_id": "claim.made_up", "status": "supported", "source_span_ids": ["span:1"]},
        ],
    )
    assert measured["scientific_claim_precision"] == 0.5
    assert measured["citation_precision"] == 0.0
    assert measured["citation_coverage"] == 0.0
    assert measured["unsupported_scientific_claim_count"] == 1


def test_answer_text_changes_affect_stability():
    assert response_stability(["same answer", "same   answer"]) == 1.0
    assert response_stability(["first answer", "second answer"]) == 0.5


def test_failure_attribution_uses_earliest_trace_stage_not_check_order():
    record = EvaluationRunRecord(
        run_id="run",
        experiment_id="exp",
        case_id="case",
        status="failed",
        trace=[
            {"stage": "validation", "status": "failed", "error_type": "bad_artifact"},
            {"stage": "retrieval", "status": "failed", "error_type": "wrong_context"},
        ],
    )
    failure = attribute_failure(record)
    assert failure is not None
    assert failure.root_stage == "retrieval"
    assert failure.root_error_type == "wrong_context"
    assert failure.downstream_symptoms == ["bad_artifact"]


def test_failure_attribution_accepts_unified_failure_type():
    record = EvaluationRunRecord(
        run_id="run-unified",
        experiment_id="exp",
        case_id="case-unified",
        status="failed",
        trace=[
            {
                "stage": "intent_parse",
                "status": "failed",
                "failure_type": "task_mismatch",
                "owner": "research_chat_router",
            }
        ],
    )
    failure = attribute_failure(record)
    assert failure is not None
    assert failure.root_stage == "intent_parse"
    assert failure.root_error_type == "task_mismatch"
    assert failure.owner_module == "research_chat_router"


def test_low_response_shape_and_stability_block_release():
    metrics = []
    for metric_id, value in {
        "answer.response_shape": 0.65,
        "stability.critical_pass_power_3": 0.625,
    }.items():
        metrics.append(
            EvaluatorResult(
                evaluator_id="test",
                metric_id=metric_id,
                status=EvaluationMetricStatus.MEASURED,
                signal=EvaluationSignal.BLOCKED,
                value=value,
                numerator=value,
                denominator=1,
                direction="higher",
            )
        )
    gate = decide_release_gate(
        "exp",
        metrics,
        required_gates={
            "answer.response_shape": ("higher", 0.95),
            "stability.critical_pass_power_3": ("higher", 0.90),
        },
    )
    assert gate.status == EvaluationSignal.BLOCKED
    assert set(gate.blockers) == {
        "answer.response_shape",
        "stability.critical_pass_power_3",
    }
