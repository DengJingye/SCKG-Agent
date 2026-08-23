import json
from pathlib import Path

import nbformat
import pytest

from engine.data_intelligence import AnnDataBackedAdapter
from execution.notebook_shadow import NotebookShadowCompiler, scrublet_step_contract
from execution.representative_preview import RepresentativePreviewBuilder
from tests.fixtures.anndata_factory import write_phase1_fixtures


def _case(tmp_path):
    source = write_phase1_fixtures(tmp_path / "fixtures")["counts_layer"]
    profile = AnnDataBackedAdapter().profile(
        path=source, artifact_id="pbmc", owner_user_id="alice"
    )
    preview = RepresentativePreviewBuilder().build(
        source_path=source,
        profile=profile,
        output_dir=tmp_path / "preview",
        allowed_output_root=tmp_path,
        max_cells=24,
    )
    return profile, preview, tmp_path / "preview" / "representative_preview.h5ad"


def test_step_contract_is_derived_from_scrublet_contract():
    step = scrublet_step_contract()
    assert step.tool_contract_id == "scrublet:0.2.3"
    assert step.requires_matrix_state == "raw_counts"
    assert step.parameters["expected_doublet_rate"].user_confirmation_required
    assert step.parameters["n_prin_comps"].minimum == 2
    assert step.source_refs


def test_notebook_shadow_contains_governed_metadata_and_does_not_execute(tmp_path):
    profile, preview, preview_path = _case(tmp_path)
    bundle = NotebookShadowCompiler().compile_scrublet(
        profile=profile,
        preview=preview,
        preview_path=preview_path,
        output_dir=tmp_path / "notebook",
        allowed_output_root=tmp_path,
        parameters={"expected_doublet_rate": 0.08, "n_prin_comps": 10},
        task_context={
            "conversation_id": "conversation-1",
            "source_query": "为 10x PBMC 生成 doublet detection workflow",
            "task_family": "doublet_detection",
            "tool_name": "Scrublet",
        },
    )
    notebook_path = tmp_path / "notebook" / "analysis_preview.ipynb"
    notebook = nbformat.read(notebook_path, as_version=4)

    assert bundle.executed is False
    assert bundle.execution_request_count == 0
    assert notebook.metadata["sckg"]["shadow_mode"] is True
    assert notebook.metadata["sckg"]["tool_contract_id"] == "scrublet:0.2.3"
    assert notebook.metadata["sckg"]["task_context_digest"] == bundle.task_context_digest
    assert bundle.task_context["conversation_id"] == "conversation-1"
    assert bundle.task_context["task_family"] == "doublet_detection"
    assert bundle.parameter_snapshot["expected_doublet_rate"] == 0.08
    assert (
        bundle.parameter_provenance["expected_doublet_rate"]
        == "user_confirmed_override"
    )
    assert (
        bundle.parameter_provenance["distance_metric"]
        == "scrublet:0.2.3:1.2.0-phase3a-qualified:default"
    )
    assert set(bundle.cell_source_digests) == {cell.id for cell in notebook.cells}
    assert all(cell.metadata["sckg"]["trusted"] for cell in notebook.cells)
    assert all(
        cell.metadata["sckg"]["source_digest"] == bundle.cell_source_digests[cell.id]
        for cell in notebook.cells
    )
    assert all("!pip" not in cell.source and "subprocess" not in cell.source for cell in notebook.cells)
    notebook_preview = tmp_path / "notebook" / "representative_preview.h5ad"
    assert notebook_preview.is_file()
    assert notebook_preview.is_symlink() is False
    parameters = json.loads((tmp_path / "notebook" / "parameters.json").read_text())
    assert parameters["expected_doublet_rate"] == 0.08
    assert (tmp_path / "notebook" / "notebook_manifest.json").is_file()
    assert any(
        cell.cell_type == "markdown" and "Governed step contract" in cell.source
        for cell in notebook.cells
    )
    assert any(
        cell.cell_type == "markdown" and "Why the DataProfile matters" in cell.source
        for cell in notebook.cells
    )
    assert any(
        cell.cell_type == "markdown"
        and "Parameter snapshot and provenance" in cell.source
        and "user_confirmed_override" in cell.source
        for cell in notebook.cells
    )
    assert any(
        cell.cell_type == "markdown" and "## 1. Set up the analysis" in cell.source
        for cell in notebook.cells
    )
    assert any(
        cell.cell_type == "markdown" and "## 5. Inspect Scrublet diagnostics" in cell.source
        for cell in notebook.cells
    )
    diagnostic_cell = next(
        cell
        for cell in notebook.cells
        if cell.metadata["sckg"]["cell_role"] == "validation_and_artifacts"
    )
    assert "display(results.head(10))" in diagnostic_cell.source
    score_diagnostics = next(
        cell
        for cell in notebook.cells
        if cell.metadata["sckg"]["cell_role"] == "score_diagnostics"
    )
    assert "Scrublet score distribution" in score_diagnostics.source
    assert "Ranked doublet scores" in score_diagnostics.source
    assert "Predicted calls" in score_diagnostics.source
    assert "display(Image(filename=str(figure_path)))" in score_diagnostics.source
    manifold_diagnostics = next(
        cell
        for cell in notebook.cells
        if cell.metadata["sckg"]["cell_role"] == "manifold_diagnostics"
    )
    assert "manifold_obs_" in manifold_diagnostics.source
    assert "doublet_score_manifold.png" in manifold_diagnostics.source
    assert "display(Image(filename=str(manifold_path)))" in manifold_diagnostics.source


def test_notebook_rejects_invalid_parameter_and_output_escape(tmp_path):
    profile, preview, preview_path = _case(tmp_path)
    compiler = NotebookShadowCompiler()
    with pytest.raises(ValueError, match="above_maximum"):
        compiler.compile_scrublet(
            profile=profile,
            preview=preview,
            preview_path=preview_path,
            output_dir=tmp_path / "invalid",
            allowed_output_root=tmp_path,
            parameters={"n_prin_comps": 1000},
        )
    with pytest.raises(ValueError, match="escapes"):
        compiler.compile_scrublet(
            profile=profile,
            preview=preview,
            preview_path=preview_path,
            output_dir=tmp_path.parent / "outside-notebook",
            allowed_output_root=tmp_path,
        )


def test_notebook_trust_downgrades_modified_and_untracked_cells(tmp_path):
    profile, preview, preview_path = _case(tmp_path)
    compiler = NotebookShadowCompiler()
    bundle = compiler.compile_scrublet(
        profile=profile,
        preview=preview,
        preview_path=preview_path,
        output_dir=tmp_path / "notebook",
        allowed_output_root=tmp_path,
    )
    notebook_path = tmp_path / "notebook" / "analysis_preview.ipynb"

    clean = compiler.inspect_trust(notebook_path=notebook_path, bundle=bundle)
    assert clean.system_verified is True
    assert {item.status for item in clean.cells} == {"VERIFIED"}

    payload = json.loads(notebook_path.read_text(encoding="utf-8"))
    payload["cells"][2]["source"] += "\n# local edit"
    payload["cells"].append(
        {
            "cell_type": "code",
            "id": "custom-cell",
            "metadata": {},
            "execution_count": None,
            "outputs": [],
            "source": "print('custom')",
        }
    )
    notebook_path.write_text(json.dumps(payload), encoding="utf-8")

    changed = compiler.inspect_trust(notebook_path=notebook_path, bundle=bundle)
    assert changed.system_verified is False
    assert changed.execution_allowed is False
    assert payload["cells"][2]["id"] in changed.modified_cell_ids
    assert changed.untracked_cell_ids == ["custom-cell"]
    assert "maintainer_cell_modified" in changed.issues
    assert "untracked_cell_present" in changed.issues
