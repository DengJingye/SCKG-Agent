from __future__ import annotations

from core.evaluation_models import (
    EvaluationMetricStatus,
    EvaluationRunRecord,
    EvaluationSignal,
    EvaluatorResult,
)
from core.representation_models import RepresentationLedger, RepresentationRecord
from eval.architecture_ablation import (
    RawOnlyRepresentationProfiler,
    load_fixed_research_cases,
    paired_mode_comparison,
)


def test_fixed_research_cases_use_only_stable_evaluation_split():
    cases, first_digest = load_fixed_research_cases(
        __import__("pathlib").Path("eval/fixtures/retrieval_gold_v2.json")
    )
    repeated, second_digest = load_fixed_research_cases(
        __import__("pathlib").Path("eval/fixtures/retrieval_gold_v2.json")
    )

    assert cases
    assert [item.case_id for item in cases] == [item.case_id for item in repeated]
    assert first_digest == second_digest
    assert all(item.split == "evaluation" for item in cases)
    assert all(item.expected_trajectory is not None for item in cases)
    assert all("query" in item.input for item in cases)
    hard_negatives = [item for item in cases if item.metadata["must_block"]]
    assert hard_negatives
    assert all(
        item.expected_trajectory.required_steps == ["routing"]
        and "retrieval" in item.expected_trajectory.forbidden_steps
        and item.expected_trajectory.must_stop_after == "routing"
        for item in hard_negatives
    )
    workflow_cases = [
        item for item in cases if item.metadata["category"] == "workflow_relation"
    ]
    assert workflow_cases
    assert all(
        item.expected_trajectory.must_stop_after == "" for item in workflow_cases
    )


def test_paired_comparison_keeps_regressions_and_not_run_explicit():
    baseline = [
        _metric("citation.coverage", 0.5, direction="higher"),
        EvaluatorResult(
            evaluator_id="test",
            metric_id="scientific.qualification",
            status=EvaluationMetricStatus.NOT_RUN,
        ),
    ]
    current = [
        _metric("citation.coverage", 0.25, direction="higher"),
        EvaluatorResult(
            evaluator_id="test",
            metric_id="scientific.qualification",
            status=EvaluationMetricStatus.NOT_RUN,
        ),
    ]
    baseline_records = [_record("case-a", "completed"), _record("case-b", "failed")]
    current_records = [_record("case-a", "failed"), _record("case-b", "completed")]

    report = paired_mode_comparison(
        baseline_metrics=baseline,
        current_metrics=current,
        baseline_records=baseline_records,
        current_records=current_records,
    )

    deltas = {item["metric_id"]: item for item in report["metric_deltas"]}
    assert deltas["citation.coverage"]["delta"] == -0.25
    assert deltas["citation.coverage"]["regressed"] is True
    assert deltas["scientific.qualification"]["status"] == "not_comparable"
    assert report["regressed_case_ids"] == ["case-a"]
    assert report["improved_case_ids"] == ["case-b"]


def test_raw_only_profiler_projects_without_mutating_source_ledger():
    source = _ledger()

    class _Delegate:
        def profile(self, *args, **kwargs):
            return source

    projected = RawOnlyRepresentationProfiler(_Delegate()).profile("unused")

    assert projected.source_hash == source.source_hash
    assert projected.profile_id == source.profile_id
    assert projected.ledger_id.endswith(":raw-only-ablation")
    assert projected.available_ids() == {"raw_counts"}
    assert source.available_ids() == {
        "raw_counts",
        "registered_anndata",
        "umap",
    }
    assert source.records[0].parent_record_ids == ["rep:registered"]
    assert projected.records[0].parent_record_ids == []
    assert projected.metadata["evaluation_projection"] == "raw_counts_only"


def _metric(metric_id: str, value: float, *, direction: str) -> EvaluatorResult:
    return EvaluatorResult(
        evaluator_id="test",
        metric_id=metric_id,
        status=EvaluationMetricStatus.MEASURED,
        signal=EvaluationSignal.PASSED,
        value=value,
        numerator=value,
        denominator=1,
        direction=direction,
    )


def _record(case_id: str, status: str) -> EvaluationRunRecord:
    return EvaluationRunRecord(
        run_id=f"run:{case_id}",
        experiment_id="experiment",
        case_id=case_id,
        status=status,
    )


def _ledger() -> RepresentationLedger:
    return RepresentationLedger(
        ledger_id="ledger-source",
        profile_id="profile-source",
        source_artifact_id="artifact-source",
        source_hash="s" * 64,
        cell_index_hash="c" * 64,
        gene_index_hash="g" * 64,
        records=[
            RepresentationRecord(
                representation_record_id="rep:raw",
                representation_id="raw_counts",
                schema_version="1",
                value_state="counts",
                slot="layers/counts",
                parent_record_ids=["rep:registered"],
                validated=True,
            ),
            RepresentationRecord(
                representation_record_id="rep:registered",
                representation_id="registered_anndata",
                schema_version="1",
                value_state="table",
                slot="artifact",
                validated=True,
            ),
            RepresentationRecord(
                representation_record_id="rep:umap",
                representation_id="umap",
                schema_version="1",
                value_state="embedding",
                slot="obsm/X_umap",
                parent_record_ids=["rep:registered"],
                validated=True,
            ),
        ],
    )
