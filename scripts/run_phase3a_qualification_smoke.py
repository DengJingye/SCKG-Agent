#!/usr/bin/env python
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


_CONTROL_DEPENDENCY_TEMP: tempfile.TemporaryDirectory[str] | None = None


def _ensure_control_plane_dependencies() -> str:
    global _CONTROL_DEPENDENCY_TEMP
    try:
        import pydantic  # noqa: F401

        return "active_environment"
    except ModuleNotFoundError:
        conda_exe = Path(os.environ.get("CONDA_EXE", "/opt/anaconda3/bin/conda"))
        conda_root = conda_exe.parent.parent
        candidates = sorted((conda_root / "lib").glob("python3.*/site-packages"))
        if not candidates:
            raise RuntimeError("Pydantic unavailable and control-plane site-packages not found")
        source_root = candidates[-1]
        _CONTROL_DEPENDENCY_TEMP = tempfile.TemporaryDirectory(
            prefix="sckg_phase3a_control_deps_"
        )
        isolated_root = Path(_CONTROL_DEPENDENCY_TEMP.name)
        for package_name in ("annotated_types", "dotenv", "pydantic", "pydantic_core"):
            source = source_root / package_name
            if not source.exists():
                raise RuntimeError(f"Missing control-plane dependency: {source}")
            (isolated_root / package_name).symlink_to(source, target_is_directory=True)
        sys.path.append(str(isolated_root))
        import pydantic  # noqa: F401

        return f"isolated_pydantic_from:{source_root}"


CONTROL_DEPENDENCY_SOURCE = _ensure_control_plane_dependencies()

from core.deterministic_router import DeterministicRouter
from core.execution_models import ExecutionRequest, QualificationArtifact
from core.tool_contract_registry import ToolContractRegistry
from engine.data_profiler import AnnDataProfiler
from execution.environment_registry import EnvironmentRegistry
from execution.local_controlled_executor import LocalControlledExecutor
from execution.probe_builder import ProbeBuilder
from execution.validators.doublet import DoubletValidator
from execution.wrapper_registry import WrapperDefinition, WrapperRegistry
from tests.fixtures.anndata_factory import FIXTURE_SEED, write_phase1_fixtures


PARAMETERS = {
    "min_counts": 1,
    "min_cells": 1,
    "min_gene_variability_pctl": 0.0,
    "n_prin_comps": 10,
    "use_approx_neighbors": False,
    "random_state": FIXTURE_SEED,
}


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="sckg_phase3a_") as temp_dir:
        root = Path(temp_dir)
        fixtures = write_phase1_fixtures(root / "fixtures")
        profile = AnnDataProfiler().profile(fixtures["raw_x"])
        probe = ProbeBuilder().build(
            source_path=fixtures["raw_x"],
            output_dir=root / "probes" / "phase3a",
            profile_id=profile.profile_id,
            fixture_id="phase1_raw_counts_x",
            allowed_output_root=root / "probes",
        )
        artifact = QualificationArtifact(
            artifact_id="phase3a-probe",
            fixture_id=probe.source_fixture_id,
            path=probe.probe_artifact_path,
            sha256=probe.probe_hash,
            synthetic=True,
            allowlisted=True,
            expected_cells=probe.n_probe_cells,
        )
        environments = EnvironmentRegistry()
        contracts = ToolContractRegistry(environment_registry=environments)
        contract = contracts.load("scrublet", "0.2.3")
        planning_gate = contracts.planning_gate(contract, data_profile=profile)
        execution_gate = contracts.execution_gate(contract)
        request = _request(contract, artifact)
        decision = DeterministicRouter().route_qualification(
            request=request,
            artifact=artifact,
            tool_contract=contract,
            environment=environments.get("scRNAseq"),
            planning_gate=planning_gate,
            max_timeout_seconds=120,
        )
        executor = LocalControlledExecutor(
            run_root=root / "runs",
            approved_input_root=root / "probes",
            environment_registry=environments,
        )
        run = executor.execute(
            request=request,
            artifact=artifact,
            contract=contract,
            router_decision=decision,
        )
        validation = DoubletValidator().validate(run, expected_cells=probe.n_probe_cells)
        metadata = _read_metadata(run.artifact_paths.get("result_metadata.json"))
        security = _security_smoke(
            root=root,
            request=request,
            artifact=artifact,
            contract=contract,
            decision=decision,
            environments=environments,
        )

        checks = {
            "scrublet_actually_executed": metadata.get("scrublet_actually_executed") is True,
            "fixture_is_synthetic": metadata.get("synthetic_fixture") is True,
            "user_data_used_is_false": metadata.get("user_data_used") is False,
            "artifacts_complete": set(run.artifact_paths)
            == {"doublet_results.tsv", "parameters.json", "result_metadata.json"},
            "validation_passed": validation.passed,
            "planning_gate_passed": planning_gate.allowed,
            "execution_gate_remains_closed": not execution_gate.allowed,
            "timeout_process_cleanup_tested": security["timeout_process_cleanup_tested"],
            "unauthorized_execution_zero": security["unauthorized_execution_count"] == 0,
            "path_escape_zero": security["path_escape_execution_count"] == 0,
            "unknown_wrapper_execution_zero": security["unknown_wrapper_execution_count"] == 0,
        }
        summary = {
            "ok": all(checks.values()),
            "phase": "Phase 3A Scrublet qualification smoke",
            "conda_environment": os.getenv("CONDA_DEFAULT_ENV", "unknown"),
            "python": sys.version.split()[0],
            "control_dependency_source": CONTROL_DEPENDENCY_SOURCE,
            "checks": checks,
            "probe": probe.model_dump(mode="json"),
            "run": {
                "run_id": run.run_id,
                "status": run.status,
                "exit_code": run.exit_code,
                "runtime_seconds": run.runtime_seconds,
                "peak_memory_mb": run.peak_memory_mb,
                "artifact_names": sorted(run.artifact_paths),
            },
            "validation": validation.model_dump(mode="json"),
            "security": security,
            "planning_gate": planning_gate.model_dump(mode="json"),
            "execution_gate": execution_gate.model_dump(mode="json"),
            "contract_status": {
                "wrapper_status": contract.wrapper_status,
                "environment_status": contract.environment_status,
                "execution_status": contract.execution_status,
                "enabled_for_execution": contract.enabled_for_execution,
            },
            "guardrail": (
                "Only a maintainer-approved synthetic engineering fixture was executed; "
                "no user data or scientific performance claim is involved."
            ),
        }
        print(json.dumps(summary, indent=2, sort_keys=True))
        return 0 if summary["ok"] else 1


def _request(contract, artifact: QualificationArtifact) -> ExecutionRequest:
    return ExecutionRequest(
        request_id="phase3a-qualification-request",
        run_id="phase3a-scrublet-qualification",
        trace_id="phase3a-qualification-trace",
        plan_id="phase3a-qualification-plan",
        step_id="run-scrublet-qualification",
        wrapper_id=contract.wrapper_id,
        environment_id=contract.environment_id,
        input_artifact_id=artifact.artifact_id,
        parameters=PARAMETERS,
        timeout_seconds=120,
        actor={"actor_id": "phase3a-smoke", "role": "maintainer"},
        qualification={
            "mode": True,
            "authorized": True,
            "fixture_allowlisted": True,
            "fixture_id": artifact.fixture_id,
        },
    )


def _security_smoke(*, root, request, artifact, contract, decision, environments) -> dict:
    unauthorized_request = request.model_copy(
        update={
            "run_id": "security-unauthorized",
            "actor": request.actor.model_copy(update={"role": "user"}),
        }
    )
    unauthorized_decision = DeterministicRouter().route_qualification(
        request=unauthorized_request,
        artifact=artifact,
        tool_contract=contract,
        environment=environments.get("scRNAseq"),
        planning_gate=contracts_gate(contract, artifact),
        max_timeout_seconds=120,
    )
    executor = LocalControlledExecutor(
        run_root=root / "security-runs",
        approved_input_root=root / "probes",
        environment_registry=environments,
    )
    unauthorized = executor.execute(
        request=unauthorized_request,
        artifact=artifact,
        contract=contract,
        router_decision=unauthorized_decision,
    )

    outside = root / "outside-probe.h5ad"
    outside.write_bytes(Path(artifact.path).read_bytes())
    path_escape = executor.execute(
        request=request.model_copy(update={"run_id": "security-path-escape"}),
        artifact=artifact.model_copy(update={"path": str(outside)}),
        contract=contract,
        router_decision=decision,
    )

    unknown_contract = contract.model_copy(update={"wrapper_id": "unknown_wrapper"})
    unknown_request = request.model_copy(
        update={"run_id": "security-unknown-wrapper", "wrapper_id": "unknown_wrapper"}
    )
    unknown_decision = DeterministicRouter().route_qualification(
        request=unknown_request,
        artifact=artifact,
        tool_contract=unknown_contract,
        environment=environments.get("scRNAseq"),
        planning_gate=contracts_gate(unknown_contract, artifact),
        max_timeout_seconds=120,
    )
    unknown = executor.execute(
        request=unknown_request,
        artifact=artifact,
        contract=unknown_contract,
        router_decision=unknown_decision,
    )

    timeout_registry = WrapperRegistry(
        [
            WrapperDefinition(
                wrapper_id=contract.wrapper_id,
                environment_id=contract.environment_id,
                tool_name=contract.tool_name,
                tool_version=contract.tool_version,
                module="scripts._phase3a_timeout_probe",
                python_executable=Path(sys.executable),
            )
        ]
    )
    timeout_executor = LocalControlledExecutor(
        run_root=root / "timeout-runs",
        approved_input_root=root / "probes",
        wrapper_registry=timeout_registry,
        environment_registry=environments,
    )
    timeout = timeout_executor.execute(
        request=request.model_copy(
            update={"run_id": "security-timeout", "timeout_seconds": 1}
        ),
        artifact=artifact,
        contract=contract,
        router_decision=decision,
    )
    return {
        "unauthorized_execution_count": int(unauthorized.status != "blocked"),
        "path_escape_execution_count": int(path_escape.status != "blocked"),
        "unknown_wrapper_execution_count": int(unknown.status != "blocked"),
        "timeout_process_cleanup_tested": (
            timeout.status == "timeout"
            and timeout.process_cleanup.timeout_triggered
            and (
                timeout.process_cleanup.terminate_sent
                or timeout.process_cleanup.kill_sent
            )
            and not timeout.process_cleanup.residual_processes
        ),
        "timeout_status": timeout.status,
        "timeout_cleanup": timeout.process_cleanup.model_dump(mode="json"),
    }


def contracts_gate(contract, artifact):
    del artifact
    return ToolContractRegistry(environment_registry=EnvironmentRegistry()).planning_gate(contract)


def _read_metadata(path_text: str | None) -> dict:
    if not path_text:
        return {}
    return json.loads(Path(path_text).read_text(encoding="utf-8"))


if __name__ == "__main__":
    raise SystemExit(main())
