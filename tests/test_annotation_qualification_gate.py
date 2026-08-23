from __future__ import annotations

from core.execution_models import CandidateEvaluation, MetricSummary
from core.tool_contract_registry import ToolContractRegistry
from engine.annotation_data_profiler import AnnotationDataProfiler
from engine.pareto_decision import ParetoDecisionEngine
from execution.annotation_probe_builder import AnnotationProbeBuilder
from execution.environment_registry import EnvironmentRegistry
from tests.annotation_helpers import build_reference


def test_annotation_contracts_are_planning_ready_but_execution_blocked(tmp_path):
    reference = build_reference(tmp_path / "reference")
    probe = AnnotationProbeBuilder().build(
        output_dir=tmp_path / "probe",
        split_role="development",
        random_seed=901,
        reference=reference,
    )
    environments = EnvironmentRegistry()
    registry = ToolContractRegistry(environment_registry=environments)
    contract = registry.load("CellTypist", "1.7.1")
    profile = AnnotationDataProfiler().profile(
        probe.probe_artifact_path,
        tool_name="CellTypist",
        reference=reference,
        explicit_species="human",
    )

    planning = registry.planning_gate(contract, data_profile=profile)
    execution = registry.execution_gate(contract)
    assert planning.allowed is True
    assert execution.allowed is False
    assert "contract_execution_disabled" in execution.reasons
    assert "wrapper_smoke_not_passed:implemented" in execution.reasons
    assert contract.enabled_for_execution is False
    assert environments.get("annotation-python").enabled_for_execution is False


def test_annotation_pareto_compares_normalized_metrics_not_raw_scores():
    celltypist = _candidate(
        candidate_id="CellTypist:1.7.1:a",
        tool_name="CellTypist",
        macro_f1=0.91,
        balanced_accuracy=0.90,
        reject_rate=0.04,
        runtime=2.0,
    )
    singler = _candidate(
        candidate_id="SingleR:2.14.0:b",
        tool_name="SingleR",
        macro_f1=0.86,
        balanced_accuracy=0.88,
        reject_rate=0.08,
        runtime=4.0,
    )

    decision = ParetoDecisionEngine().decide(
        [celltypist, singler],
        preference="performance",
    )

    assert decision.decision_scope == "multitool_cell_type_annotation"
    assert decision.recommended_candidate_id == celltypist.candidate_id
    assert "raw score" not in " ".join(decision.limitations).casefold()
    assert any("macro-F1" in item for item in decision.limitations)


def _candidate(
    *,
    candidate_id,
    tool_name,
    macro_f1,
    balanced_accuracy,
    reject_rate,
    runtime,
):
    return CandidateEvaluation(
        candidate_id=candidate_id,
        tool_name=tool_name,
        tool_version="1.7.1" if tool_name == "CellTypist" else "2.14.0",
        configuration_hash=("a" if tool_name == "CellTypist" else "b") * 64,
        parameters={"reference": "fixed"},
        parameter_provenance={},
        split_role="evaluation",
        run_ids=[f"{tool_name}-1", f"{tool_name}-2"],
        successful_run_ids=[f"{tool_name}-1", f"{tool_name}-2"],
        failed_run_ids=[],
        metric_summaries={
            "macro_f1": _summary(macro_f1),
            "balanced_accuracy": _summary(balanced_accuracy),
            "reject_rate": _summary(reject_rate),
        },
        seed_stability={"stability_score": 1.0},
        runtime_summary=_summary(runtime),
        peak_memory_summary=_summary(100.0),
        execution_success_rate=1.0,
        limitations=[],
        eligible_for_decision=True,
    )


def _summary(value):
    return MetricSummary(
        count=2,
        mean=value,
        median=value,
        standard_deviation=0.0,
        minimum=value,
        maximum=value,
    )
