from __future__ import annotations

import hashlib
import json
from pathlib import Path

import anndata as ad
import numpy as np
from scipy import sparse

from engine.workflow_code_service import WorkflowCodeService
from examples.workflows.scrublet_doublet_workflow import select_count_matrix


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_workflow_code_bundle_is_allowlisted_and_source_bound():
    bundle = WorkflowCodeService().get_bundle(
        task_id="doublet_detection",
        preferred_tool="Scrublet",
    )

    assert bundle is not None
    assert bundle.tool_name == "Scrublet"
    assert bundle.runtime_pack == "doublet-python"
    assert "--demo" in bundle.demo_command
    assert "def run_scrublet" in bundle.code
    assert WorkflowCodeService().get_bundle(task_id="rna_velocity") is None
    assert (
        WorkflowCodeService().get_bundle(
            task_id="doublet_detection",
            preferred_tool="DoubletFinder",
        )
        is None
    )
    harmony = WorkflowCodeService().get_bundle(
        task_id="batch_integration",
        preferred_tool="Harmony",
    )
    assert harmony is not None
    assert harmony.runtime_pack == "batch-cpu"
    assert "def run_harmony" in harmony.code
    assert "--batch-key batch" in harmony.data_command


def test_workflow_code_smoke_status_requires_matching_recipe_digest(tmp_path):
    recipe = tmp_path / "examples/workflows/scrublet_doublet_workflow.py"
    recipe.parent.mkdir(parents=True)
    source = (PROJECT_ROOT / "examples/workflows/scrublet_doublet_workflow.py").read_text(
        encoding="utf-8"
    )
    recipe.write_text(source, encoding="utf-8")
    digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
    summary = tmp_path / "data/evaluation/workflow_code_smoke_v1/summary.json"
    summary.parent.mkdir(parents=True)
    summary.write_text(
        json.dumps({"recipe_sha256": digest, "smoke_passed": True}),
        encoding="utf-8",
    )

    bundle = WorkflowCodeService(project_root=tmp_path).get_bundle(
        task_id="doublet_detection"
    )

    assert bundle is not None
    assert bundle.smoke_tested is True
    summary.write_text(
        json.dumps({"recipe_sha256": "wrong", "smoke_passed": True}),
        encoding="utf-8",
    )
    assert (
        WorkflowCodeService(project_root=tmp_path)
        .get_bundle(task_id="doublet_detection")
        .smoke_tested
        is False
    )


def test_recipe_prefers_counts_layer_and_blocks_scaled_matrix():
    counts = sparse.csr_matrix(np.asarray([[1, 0], [0, 2]], dtype=np.int32))
    adata = ad.AnnData(X=np.log1p(counts.toarray()))
    adata.layers["counts"] = counts

    matrix, source = select_count_matrix(adata)

    assert source == "layers/counts"
    assert sparse.issparse(matrix)

    scaled = ad.AnnData(X=np.asarray([[-1.0, 0.5], [0.2, 1.3]]))
    try:
        select_count_matrix(scaled)
    except ValueError as exc:
        assert "No valid raw-count source" in str(exc)
    else:
        raise AssertionError("scaled input should be blocked")


def test_followup_source_is_not_repeated_in_app_routing():
    app_source = (PROJECT_ROOT / "app.py").read_text(encoding="utf-8")
    function_source = app_source.split(
        "def _contextualized_followup_query", 1
    )[1].split("\ndef ", 1)[0]

    assert "return suggestion.strip()" in function_source
    assert "基于上一轮用户问题" not in function_source
