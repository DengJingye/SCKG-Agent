from __future__ import annotations

import hashlib
import json
import platform
import shutil
import subprocess
from pathlib import Path
from typing import Iterable

from core.execution_models import (
    CandidateEvaluation,
    DataProfile,
    DecisionResult,
    EnvironmentRecord,
    ExecutionRun,
    ExperimentBatchResult,
    ProbeSpec,
    ReproducibilityPackageResult,
    RequirementSpec,
    ScientificDatasetManifest,
    ScientificEvaluationResult,
    ScientificLabelReport,
    ScientificSplitManifest,
    ToolContract,
    ValidationResult,
    WorkflowPlan,
)
from core.settings import PROJECT_ROOT
from execution.repair_policy import RepairAction, RepairProposal


REQUIRED_FILES = [
    "requirement.json",
    "data_profile.json",
    "development_probe_manifest.json",
    "evaluation_probe_manifest.json",
    "workflow_plan.json",
    "contract_snapshot.json",
    "environment_snapshot.json",
    "execution_runs.jsonl",
    "validation_results.jsonl",
    "candidate_evaluations.json",
    "decision_result.json",
    "artifact_manifest.json",
    "reproducibility_manifest.json",
    "rerun_instructions.md",
    "limitations.md",
]


class ReproducibilityPackager:
    def __init__(
        self,
        *,
        package_root: Path = PROJECT_ROOT / ".sckg_exec" / "packages",
        repository_root: Path = PROJECT_ROOT,
    ) -> None:
        self.package_root = Path(package_root).resolve()
        self.repository_root = Path(repository_root).resolve()

    def build(
        self,
        *,
        package_id: str,
        requirement: RequirementSpec,
        data_profile: DataProfile,
        development_probe: ProbeSpec,
        evaluation_probe: ProbeSpec,
        workflow_plan: WorkflowPlan,
        contract: ToolContract,
        environment: EnvironmentRecord,
        batches: Iterable[ExperimentBatchResult],
        candidate_evaluations: list[CandidateEvaluation],
        decision_result: DecisionResult,
        rerun_command: str,
        user_data_used: bool,
    ) -> ReproducibilityPackageResult:
        if user_data_used:
            raise ValueError("reproducibility package cannot include user data in Phase 3A-E")
        if development_probe.split_role != "development":
            raise ValueError("development probe manifest has wrong split role")
        if evaluation_probe.split_role != "evaluation":
            raise ValueError("evaluation probe manifest has wrong split role")
        if development_probe.probe_hash == evaluation_probe.probe_hash:
            raise ValueError("development and evaluation probes must differ")
        if not package_id or any(
            character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-"
            for character in package_id
        ):
            raise ValueError("unsafe package id")
        package_dir = (self.package_root / package_id).resolve()
        _require_within(package_dir, self.package_root)
        if package_dir.exists():
            raise FileExistsError(f"package already exists: {package_dir}")
        package_dir.mkdir(parents=True)

        batches = list(batches)
        runs = [run for batch in batches for run in batch.execution_runs]
        validations = [item for batch in batches for item in batch.validation_results]
        _write_model(package_dir / "requirement.json", requirement)
        _write_model(package_dir / "data_profile.json", data_profile)
        _write_model(package_dir / "development_probe_manifest.json", development_probe)
        _write_model(package_dir / "evaluation_probe_manifest.json", evaluation_probe)
        _write_model(package_dir / "workflow_plan.json", workflow_plan)
        _write_model(package_dir / "contract_snapshot.json", contract)
        _write_model(package_dir / "environment_snapshot.json", environment)
        _write_jsonl(package_dir / "execution_runs.jsonl", runs)
        _write_jsonl(package_dir / "validation_results.jsonl", validations)
        _write_json(
            package_dir / "candidate_evaluations.json",
            [item.model_dump(mode="json") for item in candidate_evaluations],
        )
        _write_model(package_dir / "decision_result.json", decision_result)

        artifact_manifest = _execution_artifact_manifest(runs)
        _write_json(package_dir / "artifact_manifest.json", artifact_manifest)
        (package_dir / "rerun_instructions.md").write_text(
            "# Rerun Instructions\n\n"
            "Run from the repository root with the registered `scRNAseq` environment:\n\n"
            f"```bash\n{rerun_command}\n```\n\n"
            "This command rebuilds synthetic probes and reruns qualification only. "
            "It does not use or copy user data.\n",
            encoding="utf-8",
        )
        (package_dir / "limitations.md").write_text(
            "# Limitations\n\n"
            "- Results are synthetic engineering metrics, not biological accuracy claims.\n"
            "- This package compares Scrublet configurations, not independent tools.\n"
            "- Reproducibility Level 2 records code, environment, parameters, hashes, and metrics.\n"
            "- Cross-platform byte-identical artifact hashes are not required.\n"
            "- No user data or original input matrix is copied into this package.\n",
            encoding="utf-8",
        )

        git_metadata = _git_metadata(self.repository_root)
        before_manifest = {
            path.name: _sha256(path)
            for path in sorted(package_dir.iterdir())
            if path.is_file() and path.name != "reproducibility_manifest.json"
        }
        reproducibility_manifest = {
            "package_id": package_id,
            "reproducibility_level": "Level 2",
            "tool": {"name": contract.tool_name, "version": contract.tool_version},
            "environment_id": environment.environment_id,
            "environment_packages": environment.package_versions,
            "platform": {
                "system": platform.system(),
                "release": platform.release(),
                "machine": platform.machine(),
                "python": platform.python_version(),
            },
            "git": git_metadata,
            "rerun_command": rerun_command,
            "parameter_provenance_preserved": True,
            "development_probe_hash": development_probe.probe_hash,
            "evaluation_probe_hash": evaluation_probe.probe_hash,
            "user_data_copied": False,
            "cross_platform_byte_identity_required": False,
            "file_hashes": before_manifest,
        }
        _write_json(
            package_dir / "reproducibility_manifest.json", reproducibility_manifest
        )
        all_hashes = {
            path.name: _sha256(path)
            for path in sorted(package_dir.iterdir())
            if path.is_file()
        }
        complete = all((package_dir / name).is_file() for name in REQUIRED_FILES)
        hashes_valid = all(
            (package_dir / name).is_file()
            and _sha256(package_dir / name) == expected
            for name, expected in before_manifest.items()
        )
        return ReproducibilityPackageResult(
            package_id=package_id,
            package_path=str(package_dir),
            required_files=REQUIRED_FILES,
            artifact_hashes=all_hashes,
            complete=complete,
            manifest_hashes_valid=hashes_valid,
        )

    def build_scientific_pilot(
        self,
        *,
        package_id: str,
        requirement: RequirementSpec,
        data_profile: DataProfile,
        workflow_plan: WorkflowPlan,
        contract: ToolContract,
        environment: EnvironmentRecord,
        dataset_manifest: ScientificDatasetManifest,
        label_report: ScientificLabelReport,
        exclusion_report_path: Path,
        split_manifest: ScientificSplitManifest,
        frozen_configurations: list,
        batches: Iterable[ExperimentBatchResult],
        scientific_evaluations: list[ScientificEvaluationResult],
        prediction_paths: list[Path],
        candidate_evaluations: list[CandidateEvaluation],
        decision_result: DecisionResult,
        rerun_command: str,
    ) -> ReproducibilityPackageResult:
        package_dir = (self.package_root / package_id).resolve()
        _require_within(package_dir, self.package_root)
        if package_dir.exists():
            raise FileExistsError(f"package already exists: {package_dir}")
        package_dir.mkdir(parents=True)
        predictions_dir = package_dir / "predictions"
        predictions_dir.mkdir()
        batches = list(batches)
        runs = [run for batch in batches for run in batch.execution_runs]
        validations = [item for batch in batches for item in batch.validation_results]

        _write_model(package_dir / "requirement.json", requirement)
        _write_model(package_dir / "data_profile.json", data_profile)
        _write_model(package_dir / "workflow_plan.json", workflow_plan)
        _write_model(package_dir / "contract_snapshot.json", contract)
        _write_model(package_dir / "environment_snapshot.json", environment)
        _write_model(package_dir / "dataset_manifest.json", dataset_manifest)
        _write_model(package_dir / "label_mapping.json", label_report)
        _write_model(package_dir / "split_manifest.json", split_manifest)
        _write_json(
            package_dir / "frozen_configs.json",
            [
                item.model_dump(mode="json")
                if hasattr(item, "model_dump")
                else item
                for item in frozen_configurations
            ],
        )
        _write_jsonl(package_dir / "execution_runs.jsonl", runs)
        _write_jsonl(package_dir / "validation_results.jsonl", validations)
        _write_json(
            package_dir / "scientific_metrics.json",
            [item.model_dump(mode="json") for item in scientific_evaluations],
        )
        _write_json(
            package_dir / "bootstrap_ci.json",
            {
                item.run_id: {
                    name: interval.model_dump(mode="json")
                    for name, interval in item.bootstrap_ci.items()
                }
                for item in scientific_evaluations
            },
        )
        _write_json(
            package_dir / "candidate_evaluations.json",
            [item.model_dump(mode="json") for item in candidate_evaluations],
        )
        _write_model(package_dir / "decision_result.json", decision_result)
        shutil.copy2(exclusion_report_path, package_dir / "exclusion_report.tsv")
        for path in prediction_paths:
            shutil.copy2(path, predictions_dir / path.name)
        _write_json(
            package_dir / "artifact_manifest.json",
            _execution_artifact_manifest(runs),
        )
        (package_dir / "limitations.md").write_text(
            "# Scientific Pilot Limitations\n\n"
            + "\n".join(f"- {item}" for item in label_report.limitations)
            + "\n",
            encoding="utf-8",
        )
        (package_dir / "rerun_instructions.md").write_text(
            "# Rerun Instructions\n\n"
            f"```bash\n{rerun_command}\n```\n\n"
            "The command uses only public GSE108313 processed data and does not enable user execution.\n",
            encoding="utf-8",
        )

        file_hashes = {
            str(path.relative_to(package_dir)): _sha256(path)
            for path in sorted(package_dir.rglob("*"))
            if path.is_file() and path.name != "reproducibility_manifest.json"
        }
        reproducibility_manifest = {
            "package_id": package_id,
            "reproducibility_level": "Level 2",
            "pilot_type": "scientific",
            "accession": dataset_manifest.accession,
            "doi": dataset_manifest.doi,
            "git": _git_metadata(self.repository_root),
            "tool": {"name": contract.tool_name, "version": contract.tool_version},
            "environment": environment.model_dump(mode="json"),
            "rerun_command": rerun_command,
            "file_hashes": file_hashes,
            "raw_processed_source_hashes": {
                item["name"]: item["sha256"]
                for item in [*dataset_manifest.raw_files, *dataset_manifest.processed_files]
            },
            "user_data_copied": False,
            "contract_enabled_for_execution": contract.enabled_for_execution,
            "environment_enabled_for_execution": environment.enabled_for_execution,
        }
        _write_json(
            package_dir / "reproducibility_manifest.json", reproducibility_manifest
        )
        all_hashes = {
            str(path.relative_to(package_dir)): _sha256(path)
            for path in sorted(package_dir.rglob("*"))
            if path.is_file()
        }
        hashes_valid = all(
            (package_dir / name).is_file()
            and _sha256(package_dir / name) == expected
            for name, expected in file_hashes.items()
        )
        required = [
            "dataset_manifest.json",
            "label_mapping.json",
            "exclusion_report.tsv",
            "split_manifest.json",
            "frozen_configs.json",
            "execution_runs.jsonl",
            "scientific_metrics.json",
            "bootstrap_ci.json",
            "candidate_evaluations.json",
            "decision_result.json",
            "artifact_manifest.json",
            "reproducibility_manifest.json",
            "limitations.md",
            "rerun_instructions.md",
        ]
        complete = all((package_dir / name).is_file() for name in required) and bool(
            list(predictions_dir.glob("*.tsv"))
        )
        return ReproducibilityPackageResult(
            package_id=package_id,
            package_path=str(package_dir),
            required_files=required,
            artifact_hashes=all_hashes,
            complete=complete,
            manifest_hashes_valid=hashes_valid,
        )

    def build_multitool(
        self,
        *,
        package_id: str,
        requirement: RequirementSpec,
        data_profile: DataProfile,
        shared_probe: ProbeSpec,
        contracts: list[ToolContract],
        environments: list[EnvironmentRecord],
        batches: Iterable[ExperimentBatchResult],
        candidate_evaluations: list[CandidateEvaluation],
        decision_result: DecisionResult,
        environment_check: dict,
        rerun_command: str,
        cross_tool_comparison_complete: bool,
    ) -> ReproducibilityPackageResult:
        """Build a Level 2 package for bounded multi-tool qualification."""

        if not package_id or any(
            character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-"
            for character in package_id
        ):
            raise ValueError("unsafe package id")
        package_dir = (self.package_root / package_id).resolve()
        _require_within(package_dir, self.package_root)
        if package_dir.exists():
            raise FileExistsError(f"package already exists: {package_dir}")
        package_dir.mkdir(parents=True)
        batches = list(batches)
        runs = [run for batch in batches for run in batch.execution_runs]
        validations = [item for batch in batches for item in batch.validation_results]
        if any(run.user_data_used for run in runs):
            raise ValueError("multi-tool package cannot include user data")

        _write_model(package_dir / "requirement.json", requirement)
        _write_model(package_dir / "data_profile.json", data_profile)
        _write_model(package_dir / "shared_probe_manifest.json", shared_probe)
        _write_json(
            package_dir / "contract_snapshots.json",
            {item.tool_name: item.model_dump(mode="json") for item in contracts},
        )
        _write_json(
            package_dir / "environment_snapshots.json",
            {item.environment_id: item.model_dump(mode="json") for item in environments},
        )
        _write_json(package_dir / "environment_check.json", environment_check)
        _write_jsonl(package_dir / "execution_runs.jsonl", runs)
        _write_jsonl(package_dir / "validation_results.jsonl", validations)
        _write_json(
            package_dir / "candidate_evaluations.json",
            [item.model_dump(mode="json") for item in candidate_evaluations],
        )
        _write_model(package_dir / "decision_result.json", decision_result)
        _write_json(
            package_dir / "artifact_manifest.json", _execution_artifact_manifest(runs)
        )
        (package_dir / "rerun_instructions.md").write_text(
            "# Rerun Instructions\n\n"
            f"```bash\n{rerun_command}\n```\n\n"
            "The smoke uses one shared maintainer synthetic fixture. User execution remains disabled.\n",
            encoding="utf-8",
        )
        limitations = [
            "Synthetic engineering metrics do not establish biological performance.",
            "Raw doublet scores from different tools are not compared directly.",
            "Both tools require independently qualified contracts, wrappers, and environments.",
            "No user data is copied into this package.",
        ]
        if not cross_tool_comparison_complete:
            limitations.append(
                "Cross-tool comparison is incomplete because scDblFinder did not execute in a qualified R environment."
            )
        (package_dir / "limitations.md").write_text(
            "# Limitations\n\n"
            + "\n".join(f"- {item}" for item in limitations)
            + "\n",
            encoding="utf-8",
        )

        file_hashes = {
            path.name: _sha256(path)
            for path in sorted(package_dir.iterdir())
            if path.is_file() and path.name != "reproducibility_manifest.json"
        }
        _write_json(
            package_dir / "reproducibility_manifest.json",
            {
                "package_id": package_id,
                "reproducibility_level": "Level 2",
                "workflow_type": "multitool_doublet_qualification",
                "tools": [
                    {
                        "name": item.tool_name,
                        "version": item.tool_version,
                        "enabled_for_execution": item.enabled_for_execution,
                    }
                    for item in contracts
                ],
                "environments": [
                    {
                        "environment_id": item.environment_id,
                        "qualification_status": item.qualification_status,
                        "enabled_for_execution": item.enabled_for_execution,
                    }
                    for item in environments
                ],
                "shared_probe_hash": shared_probe.probe_hash,
                "cross_tool_comparison_complete": cross_tool_comparison_complete,
                "raw_scores_compared_directly": False,
                "git": _git_metadata(self.repository_root),
                "rerun_command": rerun_command,
                "user_data_copied": False,
                "file_hashes": file_hashes,
            },
        )
        required = [
            "requirement.json",
            "data_profile.json",
            "shared_probe_manifest.json",
            "contract_snapshots.json",
            "environment_snapshots.json",
            "environment_check.json",
            "execution_runs.jsonl",
            "validation_results.jsonl",
            "candidate_evaluations.json",
            "decision_result.json",
            "artifact_manifest.json",
            "reproducibility_manifest.json",
            "rerun_instructions.md",
            "limitations.md",
        ]
        all_hashes = {
            path.name: _sha256(path)
            for path in sorted(package_dir.iterdir())
            if path.is_file()
        }
        hashes_valid = all(
            (package_dir / name).is_file()
            and _sha256(package_dir / name) == expected
            for name, expected in file_hashes.items()
        )
        return ReproducibilityPackageResult(
            package_id=package_id,
            package_path=str(package_dir),
            required_files=required,
            artifact_hashes=all_hashes,
            complete=all((package_dir / name).is_file() for name in required),
            manifest_hashes_valid=hashes_valid,
        )

    def build_orchestrated(
        self,
        *,
        package_id: str,
        requirement: RequirementSpec,
        data_profile: DataProfile,
        workflow_plan: WorkflowPlan,
        contract: ToolContract,
        environment: EnvironmentRecord,
        batches: Iterable[ExperimentBatchResult],
        candidate_evaluations: list[CandidateEvaluation],
        decision_result: DecisionResult,
        repair_proposals: list[RepairProposal],
        repair_actions: list[RepairAction],
        trace_events: list,
        rerun_command: str,
    ) -> ReproducibilityPackageResult:
        """Package a bounded qualification run including complete repair lineage."""

        if not package_id or any(
            character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-"
            for character in package_id
        ):
            raise ValueError("unsafe package id")
        package_dir = (self.package_root / package_id).resolve()
        _require_within(package_dir, self.package_root)
        if package_dir.exists():
            raise FileExistsError(f"package already exists: {package_dir}")
        package_dir.mkdir(parents=True)

        batches = list(batches)
        runs = [run for batch in batches for run in batch.execution_runs]
        validations = [item for batch in batches for item in batch.validation_results]
        if any(run.user_data_used for run in runs):
            raise ValueError("orchestrated qualification package cannot include user data")

        _write_model(package_dir / "requirement.json", requirement)
        _write_model(package_dir / "data_profile.json", data_profile)
        _write_model(package_dir / "workflow_plan.json", workflow_plan)
        _write_model(package_dir / "contract_snapshot.json", contract)
        _write_model(package_dir / "environment_snapshot.json", environment)
        _write_jsonl(package_dir / "execution_runs.jsonl", runs)
        _write_jsonl(package_dir / "validation_results.jsonl", validations)
        _write_json(
            package_dir / "candidate_evaluations.json",
            [item.model_dump(mode="json") for item in candidate_evaluations],
        )
        _write_model(package_dir / "decision_result.json", decision_result)
        _write_json(
            package_dir / "repair_history.json",
            {
                "proposals": [item.model_dump(mode="json") for item in repair_proposals],
                "actions": [item.model_dump(mode="json") for item in repair_actions],
                "lineage": {
                    action.new_run_id: action.parent_run_id for action in repair_actions
                },
            },
        )
        _write_jsonl(package_dir / "orchestrator_trace.jsonl", trace_events)
        _write_json(
            package_dir / "artifact_manifest.json", _execution_artifact_manifest(runs)
        )
        (package_dir / "rerun_instructions.md").write_text(
            "# Rerun Instructions\n\n"
            f"```bash\n{rerun_command}\n```\n\n"
            "This remains a maintainer-only qualification run. User execution is disabled.\n",
            encoding="utf-8",
        )
        (package_dir / "limitations.md").write_text(
            "# Limitations\n\n"
            "- Repairs are deterministic and policy allowlisted.\n"
            "- Repair success is engineering evidence, not biological accuracy evidence.\n"
            "- Failed run logs and artifact hashes are retained.\n"
            "- No user data is copied and execution enable flags remain false.\n",
            encoding="utf-8",
        )

        file_hashes = {
            path.name: _sha256(path)
            for path in sorted(package_dir.iterdir())
            if path.is_file() and path.name != "reproducibility_manifest.json"
        }
        _write_json(
            package_dir / "reproducibility_manifest.json",
            {
                "package_id": package_id,
                "reproducibility_level": "Level 2",
                "workflow_type": "bounded_repair_orchestration",
                "tool": {"name": contract.tool_name, "version": contract.tool_version},
                "environment_id": environment.environment_id,
                "git": _git_metadata(self.repository_root),
                "rerun_command": rerun_command,
                "repair_lineage_preserved": True,
                "contract_enabled_for_execution": contract.enabled_for_execution,
                "environment_enabled_for_execution": environment.enabled_for_execution,
                "user_data_copied": False,
                "file_hashes": file_hashes,
            },
        )
        all_hashes = {
            path.name: _sha256(path)
            for path in sorted(package_dir.iterdir())
            if path.is_file()
        }
        required = [
            "requirement.json",
            "data_profile.json",
            "workflow_plan.json",
            "contract_snapshot.json",
            "environment_snapshot.json",
            "execution_runs.jsonl",
            "validation_results.jsonl",
            "candidate_evaluations.json",
            "decision_result.json",
            "repair_history.json",
            "orchestrator_trace.jsonl",
            "artifact_manifest.json",
            "reproducibility_manifest.json",
            "rerun_instructions.md",
            "limitations.md",
        ]
        hashes_valid = all(
            (package_dir / name).is_file()
            and _sha256(package_dir / name) == expected
            for name, expected in file_hashes.items()
        )
        return ReproducibilityPackageResult(
            package_id=package_id,
            package_path=str(package_dir),
            required_files=required,
            artifact_hashes=all_hashes,
            complete=all((package_dir / name).is_file() for name in required),
            manifest_hashes_valid=hashes_valid,
        )

    def refresh_orchestrated_trace(
        self,
        *,
        package_result: ReproducibilityPackageResult,
        trace_events: list,
    ) -> ReproducibilityPackageResult:
        """Finalize the packaged trace after the terminal state is committed."""

        package_dir = Path(package_result.package_path).resolve()
        _require_within(package_dir, self.package_root)
        trace_path = package_dir / "orchestrator_trace.jsonl"
        manifest_path = package_dir / "reproducibility_manifest.json"
        _write_jsonl(trace_path, trace_events)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["file_hashes"][trace_path.name] = _sha256(trace_path)
        _write_json(manifest_path, manifest)
        all_hashes = {
            path.name: _sha256(path)
            for path in sorted(package_dir.iterdir())
            if path.is_file()
        }
        hashes_valid = all(
            (package_dir / name).is_file()
            and _sha256(package_dir / name) == expected
            for name, expected in manifest["file_hashes"].items()
        )
        return package_result.model_copy(
            update={
                "artifact_hashes": all_hashes,
                "manifest_hashes_valid": hashes_valid,
            }
        )


def _execution_artifact_manifest(runs: list[ExecutionRun]) -> dict:
    return {
        "user_original_data_copied": False,
        "runs": [
            {
                "run_id": run.run_id,
                "input_hash": run.input_hash,
                "artifact_hashes": run.artifact_hashes,
                "artifact_names": sorted(run.artifact_paths),
                "parameters": run.parameters,
                "parameter_provenance": run.parameter_provenance,
                "runtime_seconds": run.runtime_seconds,
                "peak_memory_mb": run.peak_memory_mb,
                "status": run.status,
            }
            for run in runs
        ],
    }


def _git_metadata(repository_root: Path) -> dict:
    commit, commit_complete = _git(repository_root, ["rev-parse", "HEAD"])
    diff_index_code, tracked_complete = _git_returncode(
        repository_root, ["diff-index", "--quiet", "HEAD", "--"]
    )
    return {
        "commit": commit.strip() or "unknown",
        "dirty_worktree": diff_index_code == 1,
        "dirty_scope": "tracked_and_index",
        "untracked_files_included_in_dirty_check": False,
        "metadata_collection_complete": commit_complete and tracked_complete,
    }


def _git(repository_root: Path, arguments: list[str]) -> tuple[str, bool]:
    try:
        result = subprocess.run(
            ["git", *arguments],
            cwd=repository_root,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            shell=False,
            timeout=20,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return "", False
    return (result.stdout, True) if result.returncode == 0 else ("", False)


def _git_returncode(repository_root: Path, arguments: list[str]) -> tuple[int, bool]:
    try:
        result = subprocess.run(
            ["git", *arguments],
            cwd=repository_root,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            shell=False,
            timeout=20,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return -1, False
    return result.returncode, result.returncode in {0, 1}


def _write_model(path: Path, value) -> None:
    path.write_text(value.model_dump_json(indent=2) + "\n", encoding="utf-8")


def _write_json(path: Path, value) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _write_jsonl(path: Path, values: Iterable) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for value in values:
            handle.write(value.model_dump_json() + "\n")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _require_within(path: Path, root: Path) -> None:
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError("package path escapes package root") from exc
