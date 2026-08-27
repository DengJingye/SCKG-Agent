#!/usr/bin/env python
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import anndata as ad
import numpy as np
import pandas as pd

from core.annotation_method_models import MarkerEvidenceCandidate
from core.capability_pack_registry import CapabilityPackRegistry
from core.capability_workspace_models import CapabilityWorkspaceRequest
from core.deterministic_router import DeterministicRouter
from core.execution_models import (
    AnnotationDataProfile,
    ExecutionRequest,
    QualificationArtifact,
)
from core.representation_models import RepresentationLedger, RepresentationRecord
from core.tool_contract_registry import ToolContractRegistry
from engine.annotation_method_service import AnnotationMethodFamilyService
from engine.capability_planner import CapabilityPlanCompiler
from engine.capability_workspace_service import CapabilityWorkspaceService
from engine.data_profiler import AnnDataProfiler
from engine.representation_profiler import AnnDataRepresentationProfiler
from execution.capability_notebook import (
    GenericNotebookCompiler,
    MaintainerTemplateRenderer,
    NotebookRendererRegistry,
)
from execution.data_registry import DataRegistry
from execution.environment_registry import EnvironmentRegistry
from execution.local_controlled_executor import LocalControlledExecutor
from execution.renderers.scanpy_core import ScanpyCoreNotebookRenderer
from execution.reproducibility_packager import ReproducibilityPackager
from execution.validators.capability import (
    ArtifactHashPrimitive,
    CapabilityValidationPipeline,
    ExecutionSuccessPrimitive,
    RequiredArtifactsPrimitive,
    ScanpyCoreScientificValidator,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _build_fixture(path: Path) -> Path:
    rng = np.random.default_rng(20260824)
    batches = np.repeat(["batch-a", "batch-b", "batch-c"], 35)
    groups = np.tile(np.repeat(["A", "B", "C"], [12, 12, 11]), 3)
    counts = rng.poisson(1.2, size=(len(batches), 90)).astype(np.int32)
    counts[groups == "A", :15] += rng.poisson(5.0, size=((groups == "A").sum(), 15))
    counts[groups == "B", 15:30] += rng.poisson(5.0, size=((groups == "B").sum(), 15))
    counts[groups == "C", 30:45] += rng.poisson(5.0, size=((groups == "C").sum(), 15))
    adata = ad.AnnData(
        X=counts,
        obs=pd.DataFrame(
            {"batch": batches, "synthetic_group": groups},
            index=[f"cell-{index:03d}" for index in range(len(batches))],
        ),
        var=pd.DataFrame(index=[f"gene-{index:03d}" for index in range(90)]),
    )
    adata.layers["counts"] = counts.copy()
    adata.write_h5ad(path)
    return path


def _workspace_request(artifact_id: str, *, request_id: str, **updates):
    values = {
        "request_id": request_id,
        "user_id": "maintainer-smoke",
        "artifact_id": artifact_id,
        "pack_id": "scanpy_core",
        "pack_version": "1.0.0",
        "mode": "PLAN",
        "requirement_id": f"requirement-{request_id}",
        "target_representations": ["marker_result", "umap"],
    }
    values.update(updates)
    return CapabilityWorkspaceRequest(**values)


def _run_controlled_scanpy(
    *,
    smoke_root: Path,
    fixture: Path,
    artifact_id: str,
):
    profile = AnnDataProfiler().profile(fixture)
    artifact = QualificationArtifact(
        artifact_id=artifact_id,
        fixture_id="scanpy-core-synthetic-v1",
        path=str(fixture),
        sha256=_sha256(fixture),
        synthetic=True,
        allowlisted=True,
        expected_cells=105,
    )
    environments = EnvironmentRegistry()
    contracts = ToolContractRegistry(environment_registry=environments)
    contract = contracts.load("scanpy", "1.11.2")
    planning_gate = contracts.planning_gate(contract, data_profile=profile)
    run_id = smoke_root.name + "-run"
    request = ExecutionRequest(
        request_id=f"request-{run_id}",
        run_id=run_id,
        trace_id=f"trace-{run_id}",
        plan_id="scanpy-core-s6-controlled-plan",
        step_id="scanpy-core-workflow",
        wrapper_id=contract.wrapper_id,
        environment_id=contract.environment_id,
        input_artifact_id=artifact.artifact_id,
        parameters={"scale": True},
        timeout_seconds=180,
        execution_seed=20260824,
        actor={"actor_id": "maintainer-smoke", "role": "maintainer"},
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
        max_timeout_seconds=180,
    )
    run = LocalControlledExecutor(
        run_root=smoke_root / "runs",
        approved_input_root=fixture.parent,
        environment_registry=environments,
    ).execute(
        request=request,
        artifact=artifact,
        contract=contract,
        router_decision=decision,
    )
    required = {
        "scanpy_core_output.h5ad",
        "representation_ledger.json",
        "parameters.json",
        "result_metadata.json",
        "qc_diagnostics.png",
        "pca_variance.png",
        "umap_clusters.png",
        "marker_diagnostics.png",
    }
    validation = CapabilityValidationPipeline(
        primitives=[
            ExecutionSuccessPrimitive(),
            RequiredArtifactsPrimitive(required),
            ArtifactHashPrimitive(),
        ],
        scientific_validator=ScanpyCoreScientificValidator(),
    ).validate(run)
    return run, validation, contract, environments


def main() -> int:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    smoke_id = f"scanpy-core-s6-{stamp}"
    smoke_root = PROJECT_ROOT / ".sckg_exec" / "scanpy-core-smoke" / smoke_id
    input_root = smoke_root / "inputs"
    input_root.mkdir(parents=True)
    fixture = _build_fixture(input_root / "scanpy-core-synthetic.h5ad")

    data_registry = DataRegistry(
        approved_input_roots=[input_root],
        registry_root=smoke_root / "data-registry",
    )
    registered = data_registry.register(
        user_id="maintainer-smoke",
        path=fixture,
        artifact_id=f"artifact-{smoke_id}",
    )
    compiler = GenericNotebookCompiler(
        NotebookRendererRegistry([ScanpyCoreNotebookRenderer()])
    )
    workspace = CapabilityWorkspaceService(
        data_registry=data_registry,
        notebook_compiler=compiler,
    )
    minimal = workspace.prepare(
        _workspace_request(registered.artifact_id, request_id="minimal"),
        notebook_path=smoke_root / "minimal.ipynb",
    )
    composed = workspace.prepare(
        _workspace_request(
            registered.artifact_id,
            request_id="composed",
            batch_key="batch",
            enable_doublet_detection=True,
            enable_batch_integration=True,
        ),
        notebook_path=smoke_root / "composed.ipynb",
    )
    blocked_run = workspace.prepare(
        _workspace_request(
            registered.artifact_id,
            request_id="blocked-run",
            mode="RUN",
        ),
        notebook_path=smoke_root / "blocked-run.ipynb",
    )

    run, validation, contract, environments = _run_controlled_scanpy(
        smoke_root=smoke_root,
        fixture=fixture,
        artifact_id=registered.artifact_id,
    )
    ledger = AnnDataRepresentationProfiler().profile(
        fixture,
        artifact_id=registered.artifact_id,
        batch_key="batch",
    )

    marker_record = RepresentationRecord(
        representation_record_id="smoke-marker-result",
        representation_id="marker_result",
        schema_version="1.0",
        value_state="table",
        slot="uns/rank_genes_groups",
        provenance=["full_gene_unscaled_log1p", "cluster_labels_validated"],
        cell_index_hash=ledger.cell_index_hash,
        gene_index_hash=ledger.gene_index_hash,
        validated=True,
    )
    annotation_service = AnnotationMethodFamilyService()
    marker_annotation = annotation_service.marker_evidence_candidates(
        marker_record=marker_record,
        evidence_candidates=[
            MarkerEvidenceCandidate(
                cluster_id="0",
                candidate_label="T cell",
                marker_genes=["CD3D"],
                evidence_source_ids=["reviewed-marker-fixture"],
            )
        ],
    )
    reference_annotation = annotation_service.reference_candidates(
        profile=AnnotationDataProfile(
            profile_id="annotation-smoke-profile",
            file_path_redacted=".../scanpy-core-synthetic.h5ad",
            file_hash=_sha256(fixture),
            n_cells=105,
            n_genes=90,
            expression_source="layers/log1p",
            expression_state="log1p_normalized",
            normalization_target="ready_log1p_10000",
            gene_identifier_type="gene_symbol",
            species="human",
            reference_id="immune-reference-v1",
            reference_digest="d" * 64,
            reference_gene_count=90,
            overlapping_gene_count=90,
            gene_overlap_rate=1.0,
        ),
        binding_id="celltypist.reference_annotation",
    )

    pack_registry = CapabilityPackRegistry()
    mock_manifest = pack_registry.load("mock_r_capability", "1.0.0")
    mock_ledger = RepresentationLedger(
        ledger_id="mock-r-smoke-ledger",
        profile_id="mock-r-smoke-profile",
        source_artifact_id="mock-r-smoke-artifact",
        source_hash="1" * 64,
        cell_index_hash="2" * 64,
        gene_index_hash="3" * 64,
        records=[
            RepresentationRecord(
                representation_record_id="mock-r-smoke-input",
                representation_id="mock_r_input",
                schema_version="1.0",
                value_state="table",
                slot="input/table",
                provenance=["mock_input_reviewed"],
                validated=True,
            )
        ],
    )
    mock_plan, mock_result = CapabilityPlanCompiler(pack_registry).compile(
        pack_id="mock_r_capability",
        pack_version="1.0.0",
        ledger=mock_ledger,
        target_representations=["mock_r_table"],
        requirement_id="mock-r-smoke",
    )
    GenericNotebookCompiler(
        NotebookRendererRegistry(
            [
                MaintainerTemplateRenderer(
                    {"identity": "result <- input_table"},
                    renderer_id="mock_r_renderer",
                    language_name="R",
                )
            ]
        )
    ).compile(
        plan=mock_plan,
        step_contracts=pack_registry.load_step_contracts(mock_manifest),
        output_path=smoke_root / "mock-r.ipynb",
        title="Mock R extensibility",
    )

    plot_paths = [
        Path(run.artifact_paths[name])
        for name in [
            "qc_diagnostics.png",
            "pca_variance.png",
            "umap_clusters.png",
            "marker_diagnostics.png",
        ]
    ]
    package = ReproducibilityPackager().build_capability_package(
        package_id=smoke_id,
        pack_manifest=pack_registry.load("scanpy_core", "1.0.0"),
        representation_ledger=ledger,
        workflow_plan=minimal.workflow_plan,
        contract_snapshots=[contract],
        environment_snapshots=[environments.get("scRNAseq")],
        trace_records=[
            {"trace_id": run.trace_id, "stage": "profile", "status": "completed"},
            {"trace_id": run.trace_id, "stage": "plan", "status": minimal.status},
            {"trace_id": run.trace_id, "stage": "execution", "status": run.status},
            {
                "trace_id": run.trace_id,
                "stage": "validation",
                "status": "completed" if validation.passed else "failed",
            },
            {"trace_id": run.trace_id, "stage": "package", "status": "completed"},
        ],
        validation_results=[validation],
        plot_paths=plot_paths,
        limitations=[
            "Synthetic engineering smoke; not a biological performance conclusion.",
            "Reference-based annotation remains planning-only and execution-disabled.",
            "Global ExecutionPolicy remains disabled for ordinary users.",
        ],
        rerun_command="python scripts/run_scanpy_core_capability_smoke.py",
        user_data_used=False,
    )

    summary = {
        "smoke_id": smoke_id,
        "minimal_plan": {
            "status": minimal.status,
            "method_count": len(minimal.workflow_plan.steps),
            "notebook_created": bool(minimal.notebook_artifact),
        },
        "composed_plan": {
            "status": composed.status,
            "actions": composed.composition.selected_action_bundle_refs,
            "doublet": "scanpy_core.doublet_detection_action"
            in composed.composition.selected_method_ids,
            "batch_integration": "scanpy_core.batch_integration_action"
            in composed.composition.selected_method_ids,
        },
        "controlled_execution": {
            "status": run.status,
            "validation_passed": validation.passed,
            "artifact_count": len(run.artifact_paths),
            "plots_complete": all(path.is_file() for path in plot_paths),
        },
        "annotation": {
            "marker_candidates_waiting_human_confirmation": (
                marker_annotation.eligible_for_confirmation
                and marker_annotation.confirmation_required
            ),
            "reference_binding_blocked": bool(reference_annotation.blocking_reasons),
            "execution_request_count": 0,
        },
        "blocked_run": {
            "status": blocked_run.status,
            "blockers": blocked_run.blockers,
            "execution_request_count": blocked_run.execution_request_count,
        },
        "mock_r_extensibility": {
            "planning_passed": not mock_result.blocked,
            "method_ids": mock_result.planned_method_ids,
            "execution_eligible": pack_registry.gate(mock_manifest).execution_eligible,
        },
        "package": {
            "path": package.package_path,
            "level": package.reproducibility_level,
            "complete": package.complete,
            "manifest_hashes_valid": package.manifest_hashes_valid,
            "user_data_copied": package.user_data_copied,
        },
        "execution_policy": "disabled",
    }
    (smoke_root / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    checks = [
        minimal.status == "planned",
        composed.status == "planned",
        run.status == "succeeded",
        validation.passed,
        blocked_run.execution_request_count == 0,
        marker_annotation.execution_request_count == 0,
        reference_annotation.execution_request_count == 0,
        not mock_result.blocked,
        package.complete,
        package.manifest_hashes_valid,
        not package.user_data_copied,
    ]
    return 0 if all(checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
