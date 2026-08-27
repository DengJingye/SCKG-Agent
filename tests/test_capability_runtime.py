from __future__ import annotations

import hashlib
import json
import re

import anndata as ad
import numpy as np
import pandas as pd

from core.capability_pack_registry import CapabilityPackRegistry
from core.deterministic_router import DeterministicRouter
from core.execution_models import ExecutionRequest, QualificationArtifact
from core.tool_contract_registry import ToolContractRegistry
from engine.capability_planner import CapabilityPlanCompiler
from engine.data_profiler import AnnDataProfiler
from execution.capability_adapters import (
    ExecutionAdapterRegistry,
    PythonModuleExecutionAdapter,
    RScriptExecutionAdapter,
)
from execution.capability_notebook import GenericNotebookCompiler, NotebookRendererRegistry
from execution.environment_registry import EnvironmentRegistry
from execution.local_controlled_executor import LocalControlledExecutor
from execution.renderers.scanpy_core import ScanpyCoreNotebookRenderer
from execution.validators.capability import (
    ArtifactHashPrimitive,
    CapabilityValidationPipeline,
    ExecutionSuccessPrimitive,
    RequiredArtifactsPrimitive,
    ScanpyCoreScientificValidator,
)
from core.representation_models import RepresentationLedger, RepresentationRecord


def _synthetic_scanpy_fixture(path, *, seed=20260823):
    rng = np.random.default_rng(seed)
    cells_per_group = 35
    groups = np.repeat(["A", "B", "C"], cells_per_group)
    counts = rng.poisson(1.2, size=(len(groups), 72)).astype(np.int32)
    counts[groups == "A", :12] += rng.poisson(5.0, size=((groups == "A").sum(), 12))
    counts[groups == "B", 12:24] += rng.poisson(5.0, size=((groups == "B").sum(), 12))
    counts[groups == "C", 24:36] += rng.poisson(5.0, size=((groups == "C").sum(), 12))
    adata = ad.AnnData(
        X=counts,
        obs=pd.DataFrame({"synthetic_group": groups}, index=[f"cell_{i:03d}" for i in range(len(groups))]),
        var=pd.DataFrame(index=[f"gene_{i:03d}" for i in range(counts.shape[1])]),
    )
    adata.layers["counts"] = counts.copy()
    adata.write_h5ad(path)
    return path


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _raw_ledger():
    cell_hash = "c" * 64
    gene_hash = "g" * 64
    return RepresentationLedger(
        ledger_id="runtime-ledger",
        profile_id="runtime-profile",
        source_artifact_id="runtime-fixture",
        source_hash="s" * 64,
        cell_index_hash=cell_hash,
        gene_index_hash=gene_hash,
        records=[
            RepresentationRecord(
                representation_record_id="rep-raw",
                representation_id="raw_counts",
                schema_version="1.0",
                value_state="nonnegative_integer",
                slot="layers/counts",
                provenance=["count_source_validated"],
                cell_index_hash=cell_hash,
                gene_index_hash=gene_hash,
                validated=True,
            )
        ],
    )


def test_generic_notebook_compiles_registry_steps_without_execution(tmp_path):
    registry = CapabilityPackRegistry()
    manifest = registry.load("scanpy_core", "1.0.0")
    contracts = registry.load_step_contracts(manifest)
    plan, result = CapabilityPlanCompiler(registry).compile(
        pack_id="scanpy_core",
        pack_version="1.0.0",
        ledger=_raw_ledger(),
        target_representations=["marker_result", "umap"],
        requirement_id="runtime-notebook",
    )
    compiler = GenericNotebookCompiler(
        NotebookRendererRegistry([ScanpyCoreNotebookRenderer()])
    )
    output = compiler.compile(
        plan=plan,
        step_contracts=contracts,
        output_path=tmp_path / "scanpy_core.ipynb",
        title="Scanpy Core synthetic workflow",
    )

    assert result.blocked is False
    assert output["execution_request_count"] == 0
    text = (tmp_path / "scanpy_core.ipynb").read_text(encoding="utf-8")
    assert "import scanpy as sc" in text
    assert "adata = sc.read_h5ad(INPUT_PATH)" in text
    assert "percent_top=qc_percent_top or None" in text
    assert "full_gene_unscaled_log1p" in text
    assert "rank_genes_groups" in text
    assert "layer='log1p', use_raw=False" in text
    assert "01_qc_distributions.png" in text
    assert "02_highly_variable_genes.png" in text
    assert "03_pca_variance.png" in text
    assert "04_ranked_marker_genes.png" in text
    assert "05_umap_clusters_and_batch.png" in text
    assert "display(fig)" in text
    assert "run_line_magic('matplotlib', 'inline')" in text
    assert "sc.pl.violin" in text
    assert "sc.pl.highly_variable_genes" in text
    assert "sc.pl.pca_variance_ratio" in text
    assert "sc.pl.umap" in text
    assert ".sckg_notebook_artifacts" in text
    assert "sc.settings.override" not in text
    assert '"execution_request_count": 0' in text
    notebook = json.loads(text)
    assert all(
        re.fullmatch(r"[A-Za-z0-9_-]+", cell["id"])
        for cell in notebook["cells"]
    )


def test_python_and_rscript_adapters_share_one_registry(tmp_path):
    python = tmp_path / "python"
    rscript = tmp_path / "Rscript"
    script = tmp_path / "worker.R"
    for path in (python, rscript, script):
        path.write_text("", encoding="utf-8")
    adapters = ExecutionAdapterRegistry()
    adapters.register(PythonModuleExecutionAdapter("python-adapter", python, "pkg.worker"))
    adapters.register(RScriptExecutionAdapter("r-adapter", rscript, script))

    assert adapters.get("python-adapter").command("request.json")[-2:] == ["--request-json", "request.json"]
    assert adapters.get("r-adapter").command("request.json")[-2:] == ["--request-json", "request.json"]


def _run_scanpy(tmp_path, *, scale: bool, run_id: str):
    input_root = tmp_path / "inputs"
    input_root.mkdir(exist_ok=True)
    fixture = _synthetic_scanpy_fixture(input_root / f"{run_id}.h5ad")
    profile = AnnDataProfiler().profile(fixture)
    artifact = QualificationArtifact(
        artifact_id=f"artifact-{run_id}",
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
    gate = contracts.planning_gate(contract, data_profile=profile)
    request = ExecutionRequest(
        request_id=f"request-{run_id}",
        run_id=run_id,
        trace_id=f"trace-{run_id}",
        plan_id="scanpy-core-s3-plan",
        step_id="scanpy-core-workflow",
        wrapper_id=contract.wrapper_id,
        environment_id=contract.environment_id,
        input_artifact_id=artifact.artifact_id,
        parameters={"scale": scale},
        timeout_seconds=180,
        execution_seed=20260823,
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
        planning_gate=gate,
        max_timeout_seconds=180,
    )
    run = LocalControlledExecutor(
        run_root=tmp_path / "runs",
        approved_input_root=input_root,
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
    return run, validation


def test_scanpy_core_controlled_adapter_scale_on(tmp_path):
    run, validation = _run_scanpy(tmp_path, scale=True, run_id="scanpy-scale-on")
    assert run.status == "succeeded"
    assert validation.passed is True
    assert validation.sanity_checks["marker_source"] == "full_gene_unscaled_log1p"
    assert any(name.startswith("checkpoints/") for name in run.artifact_paths)


def test_scanpy_core_controlled_adapter_scale_off(tmp_path):
    run, validation = _run_scanpy(tmp_path, scale=False, run_id="scanpy-scale-off")
    assert run.status == "succeeded"
    assert validation.passed is True
    assert validation.sanity_checks["full_gene_log_preserved"] is True
