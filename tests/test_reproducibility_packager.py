import json
from pathlib import Path

import pytest

from core.execution_models import (
    DecisionResult,
    ExperimentBatchResult,
    RequirementSpec,
    WorkflowPlan,
    ValidationResult,
)
from core.capability_pack_registry import CapabilityPackRegistry
from core.representation_models import RepresentationLedger, RepresentationRecord
from execution.environment_registry import EnvironmentRegistry
from core.tool_contract_registry import ToolContractRegistry
from execution.reproducibility_packager import REQUIRED_FILES, ReproducibilityPackager
from tests.qualification_helpers import build_qualification_case


def test_level2_reproducibility_package_is_complete_and_hash_valid(tmp_path):
    case = build_qualification_case(tmp_path / "case")
    development = case["probe"].model_copy(
        update={
            "split_role": "development",
            "probe_hash": "d" * 64,
            "ground_truth_hash": "1" * 64,
            "random_seed": 101,
        }
    )
    evaluation = case["probe"].model_copy(
        update={
            "split_role": "evaluation",
            "probe_hash": "e" * 64,
            "ground_truth_hash": "2" * 64,
            "random_seed": 202,
        }
    )
    empty_batch = ExperimentBatchResult(
        experiment_id="batch",
        split_role="development",
        probe_hash=development.probe_hash,
        configurations=[],
        execution_runs=[],
        validation_results=[],
        run_records=[],
        requested_run_count=0,
        completed_run_count=0,
    )
    requirement = RequirementSpec(
        request_id="phase3ae-test",
        query="synthetic engineering evaluation",
        input_path=case["artifact"].path,
        input_object_type="AnnData",
        data_access_authorized=True,
    )
    plan = WorkflowPlan(
        plan_id="plan-test",
        requirement_id=requirement.request_id,
        profile_id=case["profile"].profile_id,
    )
    decision = DecisionResult(
        decision_id="decision-test",
        eligible_candidate_ids=[],
        pareto_candidate_ids=[],
        recommended_candidate_id=None,
        alternative_candidate_ids=[],
        elimination_reasons={},
        preference_profile="performance",
        decision_flip_conditions=[],
        limitations=["test package"],
    )
    result = ReproducibilityPackager(
        package_root=tmp_path / "packages"
    ).build(
        package_id="package-test",
        requirement=requirement,
        data_profile=case["profile"],
        development_probe=development,
        evaluation_probe=evaluation,
        workflow_plan=plan,
        contract=case["contract"],
        environment=case["environment_registry"].get("scRNAseq"),
        batches=[empty_batch],
        candidate_evaluations=[],
        decision_result=decision,
        rerun_command="conda run -n scRNAseq python scripts/run_phase3ae_engineering_smoke.py",
        user_data_used=False,
    )

    package = Path(result.package_path)
    assert result.reproducibility_level == "Level 2"
    assert result.complete is True
    assert result.manifest_hashes_valid is True
    assert set(path.name for path in package.iterdir()) == set(REQUIRED_FILES)
    assert not list(package.glob("*.h5ad"))
    manifest = json.loads((package / "reproducibility_manifest.json").read_text())
    assert manifest["git"]["commit"]
    assert isinstance(manifest["git"]["dirty_worktree"], bool)
    assert manifest["git"]["dirty_scope"] == "tracked_and_index"
    assert manifest["git"]["untracked_files_included_in_dirty_check"] is False
    assert manifest["user_data_copied"] is False
    assert manifest["cross_platform_byte_identity_required"] is False


def test_packager_rejects_user_data_and_non_independent_probes(tmp_path):
    case = build_qualification_case(tmp_path / "case")
    packager = ReproducibilityPackager(package_root=tmp_path / "packages")
    requirement = RequirementSpec(request_id="r", query="q")
    plan = WorkflowPlan(plan_id="p", requirement_id="r", profile_id="profile")
    decision = DecisionResult(
        decision_id="d", eligible_candidate_ids=[], pareto_candidate_ids=[],
        recommended_candidate_id=None, alternative_candidate_ids=[], elimination_reasons={},
        preference_profile="performance", decision_flip_conditions=[], limitations=[],
    )
    development = case["probe"].model_copy(update={"split_role": "development"})
    evaluation = case["probe"].model_copy(update={"split_role": "evaluation"})
    with pytest.raises(ValueError, match="user data"):
        packager.build(
            package_id="blocked-user-data", requirement=requirement,
            data_profile=case["profile"], development_probe=development,
            evaluation_probe=evaluation, workflow_plan=plan, contract=case["contract"],
            environment=case["environment_registry"].get("scRNAseq"), batches=[],
            candidate_evaluations=[], decision_result=decision, rerun_command="false",
            user_data_used=True,
        )
    with pytest.raises(ValueError, match="must differ"):
        packager.build(
            package_id="blocked-same-probe", requirement=requirement,
            data_profile=case["profile"], development_probe=development,
            evaluation_probe=evaluation, workflow_plan=plan, contract=case["contract"],
            environment=case["environment_registry"].get("scRNAseq"), batches=[],
            candidate_evaluations=[], decision_result=decision, rerun_command="false",
            user_data_used=False,
        )


def test_capability_level2_package_preserves_pack_ledger_trace_and_plot_hashes(tmp_path):
    registry = CapabilityPackRegistry()
    manifest = registry.load("scanpy_core", "1.0.0")
    ledger = RepresentationLedger(
        ledger_id="capability-package-ledger",
        profile_id="capability-package-profile",
        source_artifact_id="registered-fixture",
        source_hash="a" * 64,
        cell_index_hash="b" * 64,
        gene_index_hash="c" * 64,
        records=[
            RepresentationRecord(
                representation_record_id="package-raw",
                representation_id="raw_counts",
                schema_version="1.0",
                value_state="nonnegative_integer",
                slot="layers/counts",
                provenance=["count_source_validated"],
                cell_index_hash="b" * 64,
                gene_index_hash="c" * 64,
                validated=True,
            )
        ],
    )
    plan = WorkflowPlan(
        plan_id="capability-package-plan",
        requirement_id="capability-package-requirement",
        profile_id=ledger.profile_id,
        plan_status="dry_run",
        execution_eligible=False,
    )
    validation = ValidationResult(
        validation_id="capability-package-validation",
        run_id="capability-package-run",
        passed=True,
        eligible_for_candidate_aggregation=True,
        validation_version="capability-validation-pipeline-v1",
    )
    plot = tmp_path / "umap_clusters.png"
    plot.write_bytes(b"governed-plot")
    environments = EnvironmentRegistry()
    contracts = ToolContractRegistry(environment_registry=environments)

    result = ReproducibilityPackager(
        package_root=tmp_path / "capability-packages"
    ).build_capability_package(
        package_id="scanpy-core-level2",
        pack_manifest=manifest,
        representation_ledger=ledger,
        workflow_plan=plan,
        contract_snapshots=[contracts.load("scanpy", "1.11.2")],
        environment_snapshots=[environments.get("scRNAseq")],
        trace_records=[
            {
                "trace_id": "capability-package-trace",
                "stage": "package",
                "status": "completed",
            }
        ],
        validation_results=[validation],
        plot_paths=[plot],
        limitations=["Synthetic engineering package; not a biological conclusion."],
        rerun_command="python scripts/run_scanpy_core_capability_smoke.py",
        user_data_used=False,
    )

    package = Path(result.package_path)
    manifest_payload = json.loads(
        (package / "reproducibility_manifest.json").read_text(encoding="utf-8")
    )
    assert result.complete is True
    assert result.manifest_hashes_valid is True
    assert result.user_data_copied is False
    assert manifest_payload["reproducibility_level"] == "Level 2"
    assert manifest_payload["execution_policy"] == "disabled"
    assert manifest_payload["execution_request_count"] == 0
    assert (package / "plots" / plot.name).is_file()
    assert not list(package.rglob("*.h5ad"))
