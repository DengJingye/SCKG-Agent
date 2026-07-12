from __future__ import annotations

from pathlib import Path

from core.deterministic_router import DeterministicRouter
from core.execution_models import ExecutionRequest, QualificationArtifact
from core.tool_contract_registry import ToolContractRegistry
from engine.data_profiler import AnnDataProfiler
from execution.environment_registry import EnvironmentRegistry
from execution.probe_builder import ProbeBuilder
from tests.fixtures.anndata_factory import write_phase1_fixtures


QUALIFICATION_PARAMETERS = {
    "min_counts": 1,
    "min_cells": 1,
    "min_gene_variability_pctl": 0.0,
    "n_prin_comps": 10,
    "use_approx_neighbors": False,
    "random_state": 20260711,
}


def build_qualification_case(tmp_path: Path, *, run_id: str = "qualification-run") -> dict:
    fixture_paths = write_phase1_fixtures(tmp_path / "fixtures")
    profile = AnnDataProfiler().profile(fixture_paths["raw_x"])
    probe = ProbeBuilder().build(
        source_path=fixture_paths["raw_x"],
        output_dir=tmp_path / "probes" / "probe-1",
        profile_id=profile.profile_id,
        fixture_id="phase1_raw_counts_x",
        allowed_output_root=tmp_path / "probes",
    )
    artifact = QualificationArtifact(
        artifact_id="qualification-probe",
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
    request = ExecutionRequest(
        request_id=f"request-{run_id}",
        run_id=run_id,
        trace_id=f"trace-{run_id}",
        plan_id="phase3a-qualification-plan",
        step_id="run-scrublet-qualification",
        wrapper_id=contract.wrapper_id,
        environment_id=contract.environment_id,
        input_artifact_id=artifact.artifact_id,
        parameters=QUALIFICATION_PARAMETERS,
        timeout_seconds=120,
        actor={"actor_id": "maintainer-test", "role": "maintainer"},
        qualification={
            "mode": True,
            "authorized": True,
            "fixture_allowlisted": True,
            "fixture_id": artifact.fixture_id,
        },
    )
    decision = DeterministicRouter().route_qualification(
        request=request,
        artifact=artifact,
        tool_contract=contract,
        environment=environments.get("scRNAseq"),
        planning_gate=planning_gate,
        max_timeout_seconds=120,
    )
    return {
        "artifact": artifact,
        "contract": contract,
        "decision": decision,
        "environment_registry": environments,
        "planning_gate": planning_gate,
        "probe": probe,
        "profile": profile,
        "request": request,
    }
