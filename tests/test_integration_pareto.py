from core.execution_models import CandidateEvaluation, MetricSummary
from engine.pareto_decision import ParetoDecisionEngine


def test_batch_pareto_uses_integration_scope_and_rejects_biology_collapse():
    balanced = _candidate("balanced", mixing=0.8, biology=0.8)
    collapsed = _candidate("collapsed", mixing=0.99, biology=0.3, eligible=False)
    result = ParetoDecisionEngine().decide([balanced, collapsed])

    assert result.decision_scope == "batch_integration_configuration"
    assert result.recommended_candidate_id == balanced.candidate_id
    assert collapsed.candidate_id not in result.eligible_candidate_ids


def _candidate(name, *, mixing, biology, eligible=True):
    return CandidateEvaluation(
        candidate_id=f"Harmony:2.0.0:{name}",
        tool_name="Harmony",
        tool_version="2.0.0",
        configuration_hash=(name[0] * 64),
        parameters={"name": name},
        parameter_provenance={},
        split_role="development",
        run_ids=[f"{name}-1", f"{name}-2"],
        successful_run_ids=[f"{name}-1", f"{name}-2"] if eligible else [],
        failed_run_ids=[] if eligible else [f"{name}-1", f"{name}-2"],
        metric_summaries={
            "batch_mixing_asw": MetricSummary(count=2, mean=mixing, median=mixing),
            "biology_conservation_asw": MetricSummary(count=2, mean=biology, median=biology),
        },
        seed_stability={"stability_score": 0.9},
        runtime_summary=MetricSummary(count=2, mean=2.0, median=2.0),
        peak_memory_summary=MetricSummary(count=2, mean=100.0, median=100.0),
        execution_success_rate=1.0 if eligible else 0.0,
        limitations=[] if eligible else ["biology_conservation_below_decision_floor"],
        eligible_for_decision=eligible,
    )
