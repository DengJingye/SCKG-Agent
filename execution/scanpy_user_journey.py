from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

import anndata as ad
import pandas as pd
from pydantic import Field

from core.annotation_method_models import MarkerEvidenceCandidate
from core.capability_pack_registry import CapabilityPackRegistry
from core.capability_workspace_models import CapabilityWorkspaceRequest
from core.deterministic_router import DeterministicRouter
from core.execution_models import ExecutionRequest, QualificationArtifact, StrictModel
from core.representation_models import RepresentationRecord
from core.tool_contract_registry import ToolContractRegistry
from engine.annotation_method_service import AnnotationMethodFamilyService
from engine.capability_workspace_service import CapabilityWorkspaceService
from engine.data_profiler import AnnDataProfiler
from engine.representation_profiler import AnnDataRepresentationProfiler
from execution.capability_notebook import GenericNotebookCompiler, NotebookRendererRegistry
from execution.data_registry import DataRegistry
from execution.environment_registry import EnvironmentRegistry
from execution.local_controlled_executor import LocalControlledExecutor
from execution.renderers.scanpy_core import ScanpyCoreNotebookRenderer
from execution.reproducibility_packager import ReproducibilityPackager
from execution.scanpy_synthetic_fixture import ScanpySyntheticFixtureManifest
from execution.validators.capability import (
    ArtifactHashPrimitive,
    CapabilityValidationPipeline,
    ExecutionSuccessPrimitive,
    RequiredArtifactsPrimitive,
    ScanpyCoreScientificValidator,
)


REQUIRED_SCANPY_ARTIFACTS = {
    "scanpy_core_output.h5ad",
    "representation_ledger.json",
    "parameters.json",
    "result_metadata.json",
    "qc_diagnostics.png",
    "pca_variance.png",
    "umap_clusters.png",
    "marker_diagnostics.png",
}


class ScanpyJourneyRouteResult(StrictModel):
    route_id: str
    scale_enabled: bool
    plan_id: str
    planned_method_ids: list[str]
    notebook_path: str
    run_id: str
    run_status: str
    validation_passed: bool
    input_cells: int
    output_cells: int
    output_genes: int
    source_unchanged: bool
    pca_source: str
    marker_source: str
    lineage_steps: list[str]
    lineage_hashes_valid: bool
    marker_candidate_count: int
    marker_candidate_labels: list[str]
    annotation_confirmation_required: bool
    final_annotation_present: bool
    plot_paths: list[str]
    artifact_paths: dict[str, str]


class ScanpySyntheticUserJourneyResult(StrictModel):
    journey_id: str
    fixture_id: str
    fixture_path: str
    fixture_hash: str
    registered_artifact_id: str
    data_profile_id: str
    initial_ledger_id: str
    routes: list[ScanpyJourneyRouteResult] = Field(min_length=2)
    source_unchanged: bool
    package_path: str
    package_complete: bool
    package_hashes_valid: bool
    execution_policy: str = "disabled"
    execution_request_count_before_qualification: int = 0
    scientific_claim_allowed: bool = False


def run_scanpy_synthetic_user_journey(
    *,
    journey_id: str,
    fixture_path: str | Path,
    fixture_manifest: ScanpySyntheticFixtureManifest,
    work_root: str | Path,
    package_root: str | Path | None = None,
) -> ScanpySyntheticUserJourneyResult:
    """Run the Post-S6 synthetic path through existing governed services."""

    source = Path(fixture_path).expanduser().resolve(strict=True)
    root = Path(work_root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=False)
    source_hash_before = _sha256(source)
    if source_hash_before != fixture_manifest.h5ad_sha256:
        raise ValueError("synthetic fixture hash does not match its manifest")

    user_id = "maintainer-synthetic-journey"
    data_registry = DataRegistry(
        approved_input_roots=[source.parent],
        registry_root=root / "data-registry",
    )
    registered = data_registry.register(
        user_id=user_id,
        path=source,
        artifact_id=f"artifact-{journey_id}",
    )
    pack_registry = CapabilityPackRegistry()
    workspace = CapabilityWorkspaceService(
        data_registry=data_registry,
        pack_registry=pack_registry,
        notebook_compiler=GenericNotebookCompiler(
            NotebookRendererRegistry([ScanpyCoreNotebookRenderer()])
        ),
    )
    initial_ledger = AnnDataRepresentationProfiler().profile(
        source,
        artifact_id=registered.artifact_id,
        batch_key="batch",
    )
    data_profile = AnnDataProfiler().profile(source, batch_key="batch")

    route_results: list[ScanpyJourneyRouteResult] = []
    validations = []
    trace_records: list[dict[str, Any]] = []
    package_plot_root = root / "package-plots"
    package_plot_root.mkdir()
    package_plots: list[Path] = []
    selected_plan = None
    execution_lineage: dict[str, list[dict[str, Any]]] = {}
    for scale_enabled in (False, True):
        route_id = "scale_on" if scale_enabled else "scale_off"
        preferred = (
            ["scanpy_core.scale_hvg", "scanpy_core.pca_scaled"]
            if scale_enabled
            else ["scanpy_core.pca_log_hvg"]
        )
        prepared = workspace.prepare(
            CapabilityWorkspaceRequest(
                request_id=f"{journey_id}-{route_id}-plan",
                user_id=user_id,
                artifact_id=registered.artifact_id,
                pack_id="scanpy_core",
                pack_version="1.0.0",
                mode="PLAN",
                requirement_id=f"requirement-{journey_id}-{route_id}",
                target_representations=["annotation_candidates", "umap"],
                preferred_method_ids=preferred,
                batch_key="batch",
            ),
            notebook_path=root / f"scanpy_core_{route_id}.ipynb",
        )
        if prepared.status != "planned" or prepared.workflow_plan is None:
            raise RuntimeError("Scanpy Core PLAN failed: " + ";".join(prepared.blockers))
        selected_plan = prepared.workflow_plan
        route = _run_route(
            journey_id=journey_id,
            route_id=route_id,
            scale_enabled=scale_enabled,
            source=source,
            fixture_manifest=fixture_manifest,
            artifact_id=registered.artifact_id,
            run_root=root / "runs",
            plan_id=prepared.workflow_plan.plan_id,
        )
        route_results.append(
            route[0].model_copy(
                update={
                    "planned_method_ids": [
                        item.operation for item in prepared.workflow_plan.steps
                    ],
                    "notebook_path": str(
                        (root / f"scanpy_core_{route_id}.ipynb").resolve()
                    ),
                }
            )
        )
        validations.append(route[1])
        execution_lineage[route_id] = route[2]
        for plot_text in route[0].plot_paths:
            source_plot = Path(plot_text)
            packaged_plot = package_plot_root / f"{route_id}_{source_plot.name}"
            shutil.copy2(source_plot, packaged_plot)
            package_plots.append(packaged_plot)
        trace_records.extend(
            [
                {
                    "trace_id": f"trace-{journey_id}-{route_id}",
                    "stage": "register_profile_plan",
                    "status": "completed",
                    "plan_id": prepared.workflow_plan.plan_id,
                },
                *[
                    {
                        "trace_id": f"trace-{journey_id}-{route_id}",
                        "stage": item["step_id"],
                        "status": item["status"],
                        "artifact_hash": item["artifact_hash"],
                        "parameter_hash": item["parameter_hash"],
                    }
                    for item in route[2]
                ],
                {
                    "trace_id": f"trace-{journey_id}-{route_id}",
                    "stage": "validation",
                    "status": "completed" if route[1].passed else "failed",
                },
            ]
        )

    if selected_plan is None:
        raise RuntimeError("Scanpy Core journey did not create a plan")
    package_ledger = initial_ledger.model_copy(
        update={
            "metadata": {
                **initial_ledger.metadata,
                "fixture_manifest": fixture_manifest.model_dump(mode="json"),
                "controlled_execution_lineage": execution_lineage,
                "scientific_claim_allowed": False,
            }
        }
    )
    environments = EnvironmentRegistry()
    contract = ToolContractRegistry(environment_registry=environments).load(
        "scanpy", "1.11.2"
    )
    package = ReproducibilityPackager(
        package_root=(Path(package_root) if package_root else root / "packages")
    ).build_capability_package(
        package_id=journey_id,
        pack_manifest=pack_registry.load("scanpy_core", "1.0.0"),
        representation_ledger=package_ledger,
        workflow_plan=selected_plan,
        contract_snapshots=[contract],
        environment_snapshots=[environments.get(contract.environment_id)],
        trace_records=[
            *trace_records,
            {"trace_id": f"trace-{journey_id}", "stage": "package", "status": "completed"},
        ],
        validation_results=validations,
        plot_paths=package_plots,
        limitations=[
            "Structured synthetic engineering fixture; not biological validation.",
            "Planted marker recovery only validates the expected engineering signal.",
            "Annotation candidates require explicit human confirmation and are not final labels.",
            "Global ExecutionPolicy remains disabled for ordinary users.",
        ],
        rerun_command="python scripts/run_post_s6_scanpy_user_journey.py",
        user_data_used=False,
    )
    source_unchanged = _sha256(source) == source_hash_before
    return ScanpySyntheticUserJourneyResult(
        journey_id=journey_id,
        fixture_id=fixture_manifest.fixture_id,
        fixture_path=str(source),
        fixture_hash=source_hash_before,
        registered_artifact_id=registered.artifact_id,
        data_profile_id=data_profile.profile_id,
        initial_ledger_id=initial_ledger.ledger_id,
        routes=route_results,
        source_unchanged=source_unchanged,
        package_path=package.package_path,
        package_complete=package.complete,
        package_hashes_valid=package.manifest_hashes_valid,
    )


def _run_route(
    *,
    journey_id: str,
    route_id: str,
    scale_enabled: bool,
    source: Path,
    fixture_manifest: ScanpySyntheticFixtureManifest,
    artifact_id: str,
    run_root: Path,
    plan_id: str,
):
    environments = EnvironmentRegistry()
    contracts = ToolContractRegistry(environment_registry=environments)
    contract = contracts.load("scanpy", "1.11.2")
    profile = AnnDataProfiler().profile(source, batch_key="batch")
    artifact = QualificationArtifact(
        artifact_id=artifact_id,
        fixture_id=fixture_manifest.fixture_id,
        path=str(source),
        sha256=fixture_manifest.h5ad_sha256,
        synthetic=True,
        allowlisted=True,
        expected_cells=fixture_manifest.shape[0],
    )
    run_id = f"{journey_id}-{route_id}"
    request = ExecutionRequest(
        request_id=f"request-{run_id}",
        run_id=run_id,
        trace_id=f"trace-{run_id}",
        plan_id=plan_id,
        step_id="scanpy-core-workflow",
        wrapper_id=contract.wrapper_id,
        environment_id=contract.environment_id,
        input_artifact_id=artifact_id,
        parameters={
            "scale": scale_enabled,
            "min_genes": 70,
            "min_cells": 3,
            "max_pct_counts_mt": 35.0,
            "n_top_genes": 90,
            "n_comps": 25,
            "n_neighbors": 12,
            "leiden_resolution": 0.55,
        },
        timeout_seconds=180,
        execution_seed=fixture_manifest.seed,
        actor={"actor_id": "maintainer-synthetic-journey", "role": "maintainer"},
        qualification={
            "mode": True,
            "authorized": True,
            "fixture_allowlisted": True,
            "fixture_id": fixture_manifest.fixture_id,
        },
    )
    planning_gate = contracts.planning_gate(contract, data_profile=profile)
    route = DeterministicRouter().route_qualification(
        request=request,
        artifact=artifact,
        tool_contract=contract,
        environment=environments.get(contract.environment_id),
        planning_gate=planning_gate,
        max_timeout_seconds=180,
    )
    run = LocalControlledExecutor(
        run_root=run_root,
        approved_input_root=source.parent,
        environment_registry=environments,
    ).execute(
        request=request,
        artifact=artifact,
        contract=contract,
        router_decision=route,
    )
    validation = CapabilityValidationPipeline(
        primitives=[
            ExecutionSuccessPrimitive(),
            RequiredArtifactsPrimitive(REQUIRED_SCANPY_ARTIFACTS),
            ArtifactHashPrimitive(),
        ],
        scientific_validator=ScanpyCoreScientificValidator(),
    ).validate(run)
    if not validation.passed:
        raise RuntimeError("Scanpy Core route validation failed: " + ";".join(validation.failures))

    output = ad.read_h5ad(run.artifact_paths["scanpy_core_output.h5ad"])
    ledger = json.loads(
        Path(run.artifact_paths["representation_ledger.json"]).read_text(
            encoding="utf-8"
        )
    )
    lineage = list(ledger["lineage"])
    marker_candidates = _build_marker_candidates(
        output=output,
        fixture_manifest=fixture_manifest,
    )
    marker_record = RepresentationRecord(
        representation_record_id=f"marker-result-{run_id}",
        representation_id="marker_result",
        schema_version="1.0",
        value_state="table",
        slot="uns/rank_genes_groups",
        provenance=["full_gene_unscaled_log1p", "cluster_labels_validated"],
        cell_index_hash=ledger["cell_index_hash"],
        gene_index_hash=ledger["gene_index_hash"],
        parameter_hash=next(
            item["parameter_hash"] for item in lineage if item["produces"] == "marker_result"
        ),
        validated=True,
    )
    annotation = AnnotationMethodFamilyService().marker_evidence_candidates(
        marker_record=marker_record,
        evidence_candidates=marker_candidates,
    )
    plot_paths = [Path(run.artifact_paths[name]) for name in sorted(REQUIRED_SCANPY_ARTIFACTS) if name.endswith(".png")]
    route_result = ScanpyJourneyRouteResult(
        route_id=route_id,
        scale_enabled=scale_enabled,
        plan_id=plan_id,
        planned_method_ids=[],
        notebook_path="",
        run_id=run.run_id,
        run_status=run.status,
        validation_passed=validation.passed,
        input_cells=fixture_manifest.shape[0],
        output_cells=output.n_obs,
        output_genes=output.n_vars,
        source_unchanged=_sha256(source) == fixture_manifest.h5ad_sha256,
        pca_source=ledger["pca_source"],
        marker_source=ledger["marker_source"],
        lineage_steps=[item["step_id"] for item in lineage],
        lineage_hashes_valid=bool(validation.sanity_checks["lineage_hashes_valid"]),
        marker_candidate_count=len(annotation.candidates),
        marker_candidate_labels=sorted(
            {item.candidate_label for item in annotation.candidates}
        ),
        annotation_confirmation_required=bool(
            annotation.eligible_for_confirmation and annotation.confirmation_required
        ),
        final_annotation_present="cell_type" in output.obs,
        plot_paths=[str(path) for path in plot_paths],
        artifact_paths=run.artifact_paths,
    )
    return route_result, validation, lineage


def _build_marker_candidates(
    *,
    output: ad.AnnData,
    fixture_manifest: ScanpySyntheticFixtureManifest,
) -> list[MarkerEvidenceCandidate]:
    names = pd.DataFrame(output.uns["rank_genes_groups"]["names"])
    marker_sets = {
        group: set(genes) for group, genes in fixture_manifest.marker_genes.items()
    }
    candidates: list[MarkerEvidenceCandidate] = []
    for cluster in names.columns:
        ranked = [str(value) for value in names[cluster].head(30)]
        overlaps = {
            group: [gene for gene in ranked if gene in genes]
            for group, genes in marker_sets.items()
        }
        best_group, best_genes = max(
            overlaps.items(), key=lambda item: (len(item[1]), item[0])
        )
        if not best_genes:
            continue
        candidates.append(
            MarkerEvidenceCandidate(
                cluster_id=str(cluster),
                candidate_label=best_group,
                marker_genes=best_genes,
                evidence_source_ids=[
                    f"synthetic-fixture-manifest:{fixture_manifest.h5ad_sha256}"
                ],
            )
        )
    if not candidates:
        raise RuntimeError("planted marker signal was not recovered for annotation review")
    return candidates


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
