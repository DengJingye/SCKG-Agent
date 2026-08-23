from __future__ import annotations

import json

from eval.agent_quality_evaluation import (
    AgentEvalCase,
    AgentQualityEvaluator,
    compare_with_baseline,
    load_cases,
    write_artifacts,
)


class _FakeService:
    def run(self, query, *, conversation_context=None):
        is_workflow = "workflow" in query
        return {
            "response_intent": "workflow" if is_workflow else "tool_recommendation",
            "extracted_constraints": {"canonical_task": "doublet_detection"},
            "candidate_tools": ["Scrublet"],
            "workflow_plan": {"plan_status": "dry_run"} if is_workflow else None,
            "deterministic_parent_result": {
                "status": "READY" if is_workflow else "ANSWERED",
                "execution_request_count": 0,
            },
            "context_pack": {
                "retrieval_context": {
                    "snippets": [{"source_id": "source:scrublet"}],
                    "governance_leakage_count": 0,
                }
            },
            "final_report": "执行步骤" if is_workflow else "优先用 Scrublet",
            "runtime_mode": "test",
        }


def _case(query="推荐 doublet 方法", *, workflow=False):
    return AgentEvalCase(
        case_id="case-1",
        capability_domain="recommendation",
        query=query,
        expected_intent="workflow" if workflow else "tool_recommendation",
        expected_task="doublet_detection",
        required_top_tools=["Scrublet"],
        expected_workflow=workflow,
        expected_blocked=False,
        required_phrases=["执行步骤" if workflow else "优先用 Scrublet"],
        forbidden_phrases=[],
    )


def test_agent_quality_evaluation_measures_repetition_stability():
    runs, summary = AgentQualityEvaluator(service_factory=_FakeService).evaluate(
        [_case()],
        repetitions=3,
    )

    assert len(runs) == 3
    assert summary.task_completion_rate == 1.0
    assert summary.tool_correctness == 1.0
    assert summary.governance_violation_rate == 0.0
    assert summary.hallucination_rate == 0.0
    assert summary.compliance_pass_rate == 1.0
    assert summary.stability_rate == 1.0
    assert summary.answer_exact_stability_rate == 1.0
    assert summary.release_gate_passed is True


def test_failure_attribution_identifies_answer_router():
    bad = _case("workflow please", workflow=False)
    runs, summary = AgentQualityEvaluator(service_factory=_FakeService).evaluate(
        [bad],
        repetitions=1,
    )

    owners = {failure["owner"] for failure in runs[0].failures}
    assert "answer_router" in owners
    assert "planner" in owners
    assert summary.release_gate_passed is False


def test_regression_comparison_and_artifacts(tmp_path):
    runs, summary = AgentQualityEvaluator(service_factory=_FakeService).evaluate(
        [_case()],
        repetitions=1,
    )
    baseline = tmp_path / "baseline.json"
    baseline.write_text(
        json.dumps({"task_completion_rate": 0.5, "release_gate_passed": False}),
        encoding="utf-8",
    )
    regression = compare_with_baseline(summary, baseline)
    write_artifacts(tmp_path / "out", runs, summary, regression)

    assert regression.status == "compared"
    assert regression.improvements["task_completion_rate"] == 0.5
    assert (tmp_path / "out" / "runs.jsonl").exists()
    assert (tmp_path / "out" / "summary.json").exists()
    assert (tmp_path / "out" / "failure_queue.jsonl").exists()


def test_versioned_case_bank_contains_user_regressions():
    cases = load_cases()
    ids = {case.case_id for case in cases}

    assert len(cases) == 100
    assert sum(case.capability_domain == "multi_turn_transition" for case in cases) == 20
    assert "chat-doublet-recommend-zh-01" in ids
    assert "chat-doublet-caveat-top3-01" in ids
    assert "chat-doublet-workflow-context-01" in ids
    assert "chat-hard-negative-variant-01" in ids
