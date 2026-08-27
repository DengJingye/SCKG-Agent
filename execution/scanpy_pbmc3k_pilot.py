from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import anndata as ad
import pandas as pd

from core.annotation_method_models import AnnotationCandidateStatus, MarkerEvidenceCandidate
from core.capability_pack_registry import CapabilityPackRegistry
from core.capability_workspace_models import CapabilityWorkspaceRequest
from core.deterministic_router import DeterministicRouter
from core.execution_models import ExecutionRequest, QualificationArtifact
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
from execution.validators.capability import (
    ArtifactHashPrimitive,
    CapabilityValidationPipeline,
    ExecutionSuccessPrimitive,
    RequiredArtifactsPrimitive,
    ScanpyCoreScientificValidator,
)


PBMC3K_ACCESSION = "Scanpy-PBMC3K"
PBMC3K_EXPECTED = {
    "pbmc3k_raw.h5ad": {
        "sha256": "89a96f1beaa2dd83a687666d3f19a4513ac27a2a2d12581fcd77afed7ea653a1",
        "shape": [2700, 32738],
        "role": "raw_counts_full_workflow",
    },
    "pbmc3k.h5ad": {
        "sha256": "0db367b991dd95809732b218539ede489bea99113807f62ebd7ccc970025fe38",
        "shape": [2638, 1838],
        "role": "processed_resume_skip",
    },
}
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

PBMC_MARKER_PANEL = {
    "B cell": {"MS4A1", "CD79A", "CD79B", "CD37", "CD74", "HLA-DRA"},
    "CD4 T cell": {"IL7R", "CCR7", "LTB", "MAL", "LDHB", "LTST1"},
    "Cytotoxic lymphocyte": {"NKG7", "GNLY", "GZMB", "GZMH", "PRF1", "CTSW"},
    "Dendritic cell": {"FCER1A", "CST3", "CD1C", "CLEC10A"},
    "FCGR3A monocyte": {"FCGR3A", "MS4A7", "LST1", "IFITM3", "LGALS3"},
    "Platelet": {"PPBP", "PF4", "NRGN", "GNG11"},
    "CD14 monocyte": {"LYZ", "S100A8", "S100A9", "CTSS", "LGALS3", "FCN1"},
    "T cell": {"CD3D", "CD3E", "TRBC1", "TRBC2", "LCK", "IL32"},
}


def run_pbmc3k_pilot(
    *,
    input_root: str | Path,
    output_root: str | Path,
    package_root: str | Path,
    pilot_id: str,
) -> dict[str, Any]:
    input_root = Path(input_root).expanduser().resolve(strict=True)
    output_root = Path(output_root).expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=False)
    source_files = _verify_sources(input_root)
    source_hashes_before = {name: _sha256(path) for name, path in source_files.items()}

    manifest = {
        "schema_version": "sckg-pbmc3k-pilot-dataset-v1",
        "accession": PBMC3K_ACCESSION,
        "source_kind": "public_scanpy_official_dataset",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "files": PBMC3K_EXPECTED,
        "limitations": [
            "PBMC3k is a small public demonstration dataset.",
            "This run validates a dataset-scoped workflow, not broad biological performance.",
            "Marker-based labels remain candidates until explicit human confirmation.",
        ],
    }
    _write_json(output_root / "dataset_manifest.json", manifest)

    registry = DataRegistry(
        approved_input_roots=[input_root],
        registry_root=output_root / "data-registry",
    )
    raw_registered = registry.register(
        user_id="maintainer-pbmc3k-pilot",
        path=source_files["pbmc3k_raw.h5ad"],
        artifact_id=f"pbmc3k-raw-{pilot_id}",
    )
    processed_registered = registry.register(
        user_id="maintainer-pbmc3k-pilot",
        path=source_files["pbmc3k.h5ad"],
        artifact_id=f"pbmc3k-processed-{pilot_id}",
    )
    workspace = CapabilityWorkspaceService(
        data_registry=registry,
        notebook_compiler=GenericNotebookCompiler(
            NotebookRendererRegistry([ScanpyCoreNotebookRenderer()])
        ),
    )
    raw_prepared = workspace.prepare(
        _workspace_request(
            request_id=f"{pilot_id}-raw",
            artifact_id=raw_registered.artifact_id,
        ),
        notebook_path=output_root / "pbmc3k_raw_full_workflow.ipynb",
    )
    processed_prepared = workspace.prepare(
        _workspace_request(
            request_id=f"{pilot_id}-processed",
            artifact_id=processed_registered.artifact_id,
        ),
        notebook_path=output_root / "pbmc3k_processed_resume.ipynb",
    )
    if raw_prepared.workflow_plan is None or raw_prepared.status != "planned":
        raise RuntimeError("raw PBMC3k planning failed: " + ";".join(raw_prepared.blockers))
    if processed_prepared.workflow_plan is None or processed_prepared.status != "planned":
        raise RuntimeError(
            "processed PBMC3k resume planning failed: "
            + ";".join(processed_prepared.blockers)
        )

    raw_path = source_files["pbmc3k_raw.h5ad"]
    raw_profile = AnnDataProfiler().profile(raw_path)
    raw_ledger = AnnDataRepresentationProfiler().profile(
        raw_path, artifact_id=raw_registered.artifact_id
    )
    processed_path = source_files["pbmc3k.h5ad"]
    processed_profile = AnnDataProfiler().profile(processed_path)
    processed_ledger = AnnDataRepresentationProfiler().profile(
        processed_path, artifact_id=processed_registered.artifact_id
    )
    _write_json(output_root / "raw_data_profile.json", raw_profile.model_dump(mode="json"))
    _write_json(output_root / "processed_data_profile.json", processed_profile.model_dump(mode="json"))
    _write_json(output_root / "raw_representation_ledger.json", raw_ledger.model_dump(mode="json"))
    _write_json(
        output_root / "processed_representation_ledger.json",
        processed_ledger.model_dump(mode="json"),
    )

    run, validation, contract, environments = _execute_raw(
        pilot_id=pilot_id,
        raw_path=raw_path,
        artifact_id=raw_registered.artifact_id,
        plan_id=raw_prepared.workflow_plan.plan_id,
        run_root=output_root / "runs",
    )
    if not validation.passed:
        raise RuntimeError("PBMC3k validation failed: " + ";".join(validation.failures))

    output = ad.read_h5ad(run.artifact_paths["scanpy_core_output.h5ad"])
    execution_ledger = json.loads(
        Path(run.artifact_paths["representation_ledger.json"]).read_text(
            encoding="utf-8"
        )
    )
    marker_candidates = build_pbmc_marker_candidates(output)
    marker_record = RepresentationRecord(
        representation_record_id=f"marker-result-{pilot_id}",
        representation_id="marker_result",
        schema_version="1.0",
        value_state="table",
        slot="uns/rank_genes_groups",
        provenance=["full_gene_unscaled_log1p", "cluster_labels_validated"],
        cell_index_hash=execution_ledger["cell_index_hash"],
        gene_index_hash=execution_ledger["gene_index_hash"],
        parameter_hash=next(
            item["parameter_hash"]
            for item in execution_ledger["lineage"]
            if item["produces"] == "marker_result"
        ),
        validated=True,
    )
    annotation = AnnotationMethodFamilyService().marker_evidence_candidates(
        marker_record=marker_record,
        evidence_candidates=marker_candidates,
    )
    _write_json(
        output_root / "annotation_candidates.json",
        annotation.model_dump(mode="json"),
    )

    package_ledger = raw_ledger.model_copy(
        update={
            "metadata": {
                **raw_ledger.metadata,
                "dataset_manifest": manifest,
                "processed_resume": {
                    "artifact_id": processed_registered.artifact_id,
                    "source_hash": processed_ledger.source_hash,
                    "available_representations": sorted(processed_ledger.available_ids()),
                    "planned_methods": [
                        item.operation for item in processed_prepared.workflow_plan.steps
                    ],
                },
                "controlled_execution_lineage": execution_ledger,
                "annotation_candidate_set_hash": annotation.candidate_set_hash,
                "annotation_candidates": [
                    item.model_dump(mode="json") for item in annotation.candidates
                ],
                "annotation_confirmation_required": True,
            }
        }
    )
    trace_records = [
        {
            "trace_id": f"trace-{pilot_id}",
            "stage": "register_profile_plan",
            "status": "completed",
            "raw_plan_id": raw_prepared.workflow_plan.plan_id,
            "processed_plan_id": processed_prepared.workflow_plan.plan_id,
        },
        *[
            {
                "trace_id": f"trace-{pilot_id}",
                "stage": item["step_id"],
                "status": item["status"],
                "artifact_hash": item["artifact_hash"],
                "parameter_hash": item["parameter_hash"],
            }
            for item in execution_ledger["lineage"]
        ],
        {
            "trace_id": f"trace-{pilot_id}",
            "stage": "annotation_candidate_review",
            "status": "waiting_human_confirmation",
            "candidate_set_hash": annotation.candidate_set_hash,
        },
        {
            "trace_id": f"trace-{pilot_id}",
            "stage": "validation",
            "status": "completed",
            "validation_id": validation.validation_id,
        },
    ]
    plots = [
        Path(run.artifact_paths[name])
        for name in sorted(REQUIRED_SCANPY_ARTIFACTS)
        if name.endswith(".png")
    ]
    package = ReproducibilityPackager(package_root=Path(package_root)).build_capability_package(
        package_id=pilot_id,
        pack_manifest=CapabilityPackRegistry().load("scanpy_core", "1.0.0"),
        representation_ledger=package_ledger,
        workflow_plan=raw_prepared.workflow_plan,
        contract_snapshots=[contract],
        environment_snapshots=[environments.get(contract.environment_id)],
        trace_records=trace_records,
        validation_results=[validation],
        plot_paths=plots,
        limitations=manifest["limitations"]
        + [
            "No independent cell-type ground truth is evaluated in this pilot.",
            "Annotation candidates use a fixed marker panel and require human confirmation.",
            "The processed file is evaluated for deterministic resume/skip behavior only.",
            "Global ExecutionPolicy remains disabled.",
        ],
        rerun_command="python scripts/run_scanpy_pbmc3k_pilot.py",
        user_data_used=False,
    )
    source_unchanged = all(
        _sha256(source_files[name]) == digest
        for name, digest in source_hashes_before.items()
    )
    summary = {
        "pilot_id": pilot_id,
        "accession": PBMC3K_ACCESSION,
        "input_files": {
            name: {
                "sha256": source_hashes_before[name],
                "shape": PBMC3K_EXPECTED[name]["shape"],
                "role": PBMC3K_EXPECTED[name]["role"],
            }
            for name in sorted(source_files)
        },
        "raw_plan_methods": [
            item.operation for item in raw_prepared.workflow_plan.steps
        ],
        "processed_reused_representations": sorted(
            processed_prepared.representation_ledger.available_ids()
        ),
        "processed_resume_methods": [
            item.operation for item in processed_prepared.workflow_plan.steps
        ],
        "run_id": run.run_id,
        "run_status": run.status,
        "runtime_seconds": run.runtime_seconds,
        "peak_memory_mb": run.peak_memory_mb,
        "validation_passed": validation.passed,
        "validation_checks": validation.sanity_checks,
        "output_shape": [output.n_obs, output.n_vars],
        "cluster_count": int(output.obs["leiden"].nunique()),
        "marker_source": execution_ledger["marker_source"],
        "annotation_candidate_count": len(annotation.candidates),
        "annotation_candidates": [
            item.model_dump(mode="json") for item in annotation.candidates
        ],
        "annotation_confirmation_required": annotation.confirmation_required,
        "confirmed_annotation_present": "cell_type" in output.obs,
        "source_files_unchanged": source_unchanged,
        "artifacts_complete": REQUIRED_SCANPY_ARTIFACTS <= set(run.artifact_paths),
        "plot_paths": [str(path) for path in plots],
        "package_path": package.package_path,
        "package_complete": package.complete,
        "package_hashes_valid": package.manifest_hashes_valid,
        "reproducibility_level": "Level 2",
        "scientific_validation_status": "not_evaluated",
        "execution_policy": "disabled",
    }
    _write_json(output_root / "pilot_summary.json", summary)
    return summary


def build_pbmc_marker_candidates(output: ad.AnnData) -> list[MarkerEvidenceCandidate]:
    names = pd.DataFrame(output.uns["rank_genes_groups"]["names"])
    candidates: list[MarkerEvidenceCandidate] = []
    for cluster in names.columns:
        ranked = [str(value).upper() for value in names[cluster].head(40)]
        overlaps = {
            label: [gene for gene in ranked if gene in marker_set]
            for label, marker_set in PBMC_MARKER_PANEL.items()
        }
        label, genes = max(overlaps.items(), key=lambda item: (len(item[1]), item[0]))
        if not genes:
            candidates.append(
                MarkerEvidenceCandidate(
                    cluster_id=str(cluster),
                    candidate_label="Unresolved",
                    marker_genes=ranked[:5],
                    evidence_source_ids=[
                        f"scanpy-pbmc3k-marker-result:cluster-{cluster}"
                    ],
                    status=AnnotationCandidateStatus.UNKNOWN,
                )
            )
            continue
        candidates.append(
            MarkerEvidenceCandidate(
                cluster_id=str(cluster),
                candidate_label=label,
                marker_genes=genes,
                evidence_source_ids=["scanpy-official-pbmc3k-marker-panel-v1"],
            )
        )
    if not candidates:
        raise RuntimeError("PBMC3k marker panel did not support any annotation candidate")
    return candidates


def _workspace_request(*, request_id: str, artifact_id: str) -> CapabilityWorkspaceRequest:
    return CapabilityWorkspaceRequest(
        request_id=request_id,
        user_id="maintainer-pbmc3k-pilot",
        artifact_id=artifact_id,
        pack_id="scanpy_core",
        pack_version="1.0.0",
        mode="PLAN",
        requirement_id=f"requirement-{request_id}",
        target_representations=["annotation_candidates", "umap"],
        preferred_method_ids=["scanpy_core.scale_hvg", "scanpy_core.pca_scaled"],
    )


def _execute_raw(
    *,
    pilot_id: str,
    raw_path: Path,
    artifact_id: str,
    plan_id: str,
    run_root: Path,
):
    environments = EnvironmentRegistry()
    contracts = ToolContractRegistry(environment_registry=environments)
    contract = contracts.load("scanpy", "1.11.2")
    profile = AnnDataProfiler().profile(raw_path)
    artifact = QualificationArtifact(
        artifact_id=artifact_id,
        fixture_id=f"pbmc3k-raw-{pilot_id}",
        path=str(raw_path),
        sha256=_sha256(raw_path),
        synthetic=False,
        public_dataset=True,
        user_data=False,
        accession=PBMC3K_ACCESSION,
        allowlisted=True,
        expected_cells=profile.n_cells,
    )
    request = ExecutionRequest(
        request_id=f"request-{pilot_id}",
        run_id=f"run-{pilot_id}",
        trace_id=f"trace-{pilot_id}",
        plan_id=plan_id,
        step_id="scanpy-core-workflow",
        wrapper_id=contract.wrapper_id,
        environment_id=contract.environment_id,
        input_artifact_id=artifact.artifact_id,
        parameters={
            "scale": True,
            "min_genes": 200,
            "min_cells": 3,
            "max_pct_counts_mt": 5.0,
            "n_top_genes": 2000,
            "n_comps": 40,
            "n_neighbors": 10,
            "leiden_resolution": 0.8,
        },
        parameter_provenance={
            "source": "maintainer_pbmc3k_pilot_configuration",
            "scope": "dataset_scoped_real_data_engineering_pilot",
        },
        timeout_seconds=180,
        execution_seed=20260824,
        actor={"actor_id": "maintainer-pbmc3k-pilot", "role": "maintainer"},
        qualification={
            "mode": True,
            "purpose": "scientific_pilot",
            "authorized": True,
            "fixture_allowlisted": True,
            "fixture_id": artifact.fixture_id,
        },
    )
    planning_gate = contracts.planning_gate(contract, data_profile=profile)
    decision = DeterministicRouter().route_qualification(
        request=request,
        artifact=artifact,
        tool_contract=contract,
        environment=environments.get(contract.environment_id),
        planning_gate=planning_gate,
        max_timeout_seconds=180,
    )
    if not decision.execution_allowed:
        raise RuntimeError("PBMC3k qualification route blocked: " + ";".join(decision.reasons))
    run = LocalControlledExecutor(
        run_root=run_root,
        approved_input_root=raw_path.parent,
        environment_registry=environments,
    ).execute(
        request=request,
        artifact=artifact,
        contract=contract,
        router_decision=decision,
    )
    validation = CapabilityValidationPipeline(
        primitives=[
            ExecutionSuccessPrimitive(),
            RequiredArtifactsPrimitive(REQUIRED_SCANPY_ARTIFACTS),
            ArtifactHashPrimitive(),
        ],
        scientific_validator=ScanpyCoreScientificValidator(),
    ).validate(run)
    return run, validation, contract, environments


def _verify_sources(input_root: Path) -> dict[str, Path]:
    sources: dict[str, Path] = {}
    for name, expected in PBMC3K_EXPECTED.items():
        path = (input_root / name).resolve(strict=True)
        if path.parent != input_root:
            raise ValueError("PBMC3k source path escaped the approved input root")
        digest = _sha256(path)
        if digest != expected["sha256"]:
            raise ValueError(f"PBMC3k source hash mismatch: {name}")
        adata = ad.read_h5ad(path, backed="r")
        try:
            if [adata.n_obs, adata.n_vars] != expected["shape"]:
                raise ValueError(f"PBMC3k source shape mismatch: {name}")
        finally:
            adata.file.close()
        sources[name] = path
    return sources


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
