from core.execution_models import CandidateEvaluation, MetricSummary
from engine.pareto_decision import ParetoDecisionEngine


def test_pareto_decision_changes_with_preference_and_is_configuration_scoped():
    fast = _candidate("fast", f1=0.70, stability=0.90, runtime=1.0, memory=80.0)
    accurate = _candidate("accurate", f1=0.90, stability=0.85, runtime=4.0, memory=140.0)
    engine = ParetoDecisionEngine()

    performance = engine.decide([fast, accurate], preference="performance")
    resource = engine.decide([fast, accurate], preference="resource")

    assert performance.decision_scope == "scrublet_configuration"
    assert performance.recommended_candidate_id == accurate.candidate_id
    assert resource.recommended_candidate_id == fast.candidate_id
    assert set(performance.pareto_candidate_ids) == {fast.candidate_id, accurate.candidate_id}
    assert not hasattr(performance, "confidence")
    assert any("seed median" in item for item in performance.limitations)


def test_pareto_excludes_dominated_and_ineligible_candidates():
    best = _candidate("best", f1=0.9, stability=0.9, runtime=1.0, memory=80.0)
    dominated = _candidate("dominated", f1=0.7, stability=0.8, runtime=2.0, memory=100.0)
    ineligible = _candidate("ineligible", f1=1.0, stability=1.0, runtime=0.5, memory=60.0, eligible=False)
    result = ParetoDecisionEngine().decide([best, dominated, ineligible])

    assert result.pareto_candidate_ids == [best.candidate_id]
    assert "dominated_on_configuration_level_engineering_objectives" in result.elimination_reasons[dominated.candidate_id]
    assert result.elimination_reasons[ineligible.candidate_id]


def test_pareto_returns_null_when_no_candidate_is_eligible():
    result = ParetoDecisionEngine().decide([_candidate("none", eligible=False)])
    assert result.recommended_candidate_id is None
    assert result.pareto_candidate_ids == []


def test_performance_profile_keeps_primary_metric_primary():
    higher_primary = _candidate(
        "higher-primary", f1=0.81, stability=0.80, runtime=3.0, memory=120.0
    )
    slightly_stabler = _candidate(
        "slightly-stabler", f1=0.80, stability=1.0, runtime=1.0, memory=80.0
    )
    result = ParetoDecisionEngine().decide(
        [higher_primary, slightly_stabler], preference="performance"
    )
    assert result.recommended_candidate_id == higher_primary.candidate_id


def test_multitool_decision_marks_blocked_tool_as_incomplete_comparison():
    scrublet = _candidate("scrublet", tool_name="Scrublet", eligible=True)
    scdblfinder = _candidate(
        "scdblfinder", tool_name="scDblFinder", eligible=False
    )
    scdblfinder = scdblfinder.model_copy(
        update={"limitations": ["blocked_execution:qualification_route_blocked"]}
    )
    result = ParetoDecisionEngine().decide([scrublet, scdblfinder])

    assert result.decision_scope == "multitool_doublet_detection"
    assert result.recommended_candidate_id == scrublet.candidate_id
    assert any("incomplete" in item for item in result.limitations)
    assert result.elimination_reasons[scdblfinder.candidate_id]


def _candidate(
    name,
    *,
    f1=0.8,
    stability=0.8,
    runtime=2.0,
    memory=100.0,
    eligible=True,
    tool_name="Scrublet",
):
    return CandidateEvaluation(
        candidate_id=f"{tool_name}:0.2.3:{name}", tool_name=tool_name, tool_version="0.2.3",
        configuration_hash=(name[0] * 64), parameters={"name": name}, parameter_provenance={},
        split_role="development", run_ids=[f"{name}-1", f"{name}-2"],
        successful_run_ids=[f"{name}-1", f"{name}-2"] if eligible else [],
        failed_run_ids=[] if eligible else [f"{name}-1", f"{name}-2"],
        metric_summaries={"synthetic_engineering_f1": MetricSummary(count=2, mean=f1, median=f1, standard_deviation=0.0, minimum=f1, maximum=f1)},
        seed_stability={"stability_score": stability},
        runtime_summary=MetricSummary(count=2, mean=runtime, median=runtime, standard_deviation=0.0, minimum=runtime, maximum=runtime),
        peak_memory_summary=MetricSummary(count=2, mean=memory, median=memory, standard_deviation=0.0, minimum=memory, maximum=memory),
        execution_success_rate=1.0 if eligible else 0.0,
        limitations=[] if eligible else ["not_eligible"], eligible_for_decision=eligible,
    )
