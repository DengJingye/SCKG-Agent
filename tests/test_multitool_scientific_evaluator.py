from core.execution_models import CandidateEvaluation, MetricSummary
from execution.multitool_scientific_evaluator import (
    MultitoolScientificCandidateEvaluator,
)


def test_multitool_scientific_candidate_uses_evaluation_metrics_and_dev_stability():
    development = _candidate(
        split_role="development",
        run_ids=["dev-1", "dev-2"],
        successful=["dev-1", "dev-2"],
        auprc=0.7,
        f1=0.6,
        stability=0.93,
        eligible=True,
    )
    evaluation = _candidate(
        split_role="evaluation",
        run_ids=["eval-1"],
        successful=["eval-1"],
        auprc=0.8,
        f1=0.65,
        stability=0.0,
        eligible=False,
    )

    result = MultitoolScientificCandidateEvaluator().finalize(
        development_candidates=[development],
        evaluation_candidates=[evaluation],
    )[0]

    assert result.eligible_for_decision is True
    assert result.metric_authority == "scientific_pilot_metric"
    assert result.metric_summaries["scientific_pilot_auprc"].mean == 0.8
    assert result.metric_summaries["scientific_pilot_f1"].mean == 0.65
    assert result.seed_stability["stability_score"] == 0.93
    assert result.run_ids == ["eval-1"]


def test_multitool_scientific_candidate_rejects_failed_or_unqualified_evaluation():
    development = _candidate(
        split_role="development",
        run_ids=["dev-1", "dev-2"],
        successful=["dev-1", "dev-2"],
        auprc=0.7,
        f1=0.6,
        stability=0.9,
        eligible=True,
    )
    evaluation = _candidate(
        split_role="evaluation",
        run_ids=["eval-1"],
        successful=[],
        auprc=0.0,
        f1=0.0,
        stability=0.0,
        eligible=False,
    )

    result = MultitoolScientificCandidateEvaluator().finalize(
        development_candidates=[development],
        evaluation_candidates=[evaluation],
    )[0]
    assert result.eligible_for_decision is False


def _candidate(
    *,
    split_role,
    run_ids,
    successful,
    auprc,
    f1,
    stability,
    eligible,
):
    summary_auprc = MetricSummary(
        count=len(successful),
        mean=auprc,
        median=auprc,
        standard_deviation=0.0,
        minimum=auprc,
        maximum=auprc,
    )
    summary_f1 = summary_auprc.model_copy(
        update={"mean": f1, "median": f1, "minimum": f1, "maximum": f1}
    )
    resource = MetricSummary(
        count=len(run_ids),
        mean=1.0,
        median=1.0,
        standard_deviation=0.0,
        minimum=1.0,
        maximum=1.0,
    )
    return CandidateEvaluation(
        candidate_id="Scrublet:0.2.3:" + "a" * 16,
        tool_name="Scrublet",
        tool_version="0.2.3",
        configuration_hash="a" * 64,
        parameters={"expected_doublet_rate": 0.1},
        parameter_provenance={},
        split_role=split_role,
        run_ids=run_ids,
        successful_run_ids=successful,
        failed_run_ids=[item for item in run_ids if item not in successful],
        metric_summaries={
            "scientific_pilot_auprc": summary_auprc,
            "scientific_pilot_f1": summary_f1,
        },
        seed_stability={"stability_score": stability},
        runtime_summary=resource,
        peak_memory_summary=resource,
        execution_success_rate=len(successful) / len(run_ids),
        limitations=([] if eligible else ["fewer_than_two_successful_seeds"]),
        eligible_for_decision=eligible,
        metric_authority="scientific_pilot_metric",
    )
