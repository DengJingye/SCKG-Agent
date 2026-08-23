from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

from core.research_workspace_models import (
    DataAssetProfile,
    NotebookCellTrustRecord,
    NotebookShadowBundle,
    NotebookTrustReport,
    RepresentativePreviewManifest,
    StepContract,
    StepParameterSpec,
)
from core.tool_contract_registry import ToolContractRegistry


TEMPLATE_VERSION = "scrublet-preview-notebook-v3"


def scrublet_step_contract(
    registry: ToolContractRegistry | None = None,
) -> StepContract:
    registry = registry or ToolContractRegistry()
    contract = registry.load("Scrublet", "0.2.3")
    properties = contract.parameter_schema["properties"]
    parameters: dict[str, StepParameterSpec] = {}
    for name, value in sorted(contract.default_parameters.items()):
        schema = properties[name]
        parameters[name] = StepParameterSpec(
            parameter_type=_parameter_type(schema["type"]),
            default=value,
            minimum=schema.get("minimum"),
            maximum=schema.get("maximum"),
            enum=list(schema.get("enum") or []),
            provenance=f"{contract.contract_id}:{contract.contract_version}:default",
            user_confirmation_required=name in {"expected_doublet_rate"},
        )
    digest = hashlib.sha256(
        json.dumps(
            {
                "template": TEMPLATE_VERSION,
                "contract": contract.model_dump(mode="json"),
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return StepContract(
        step_id="doublet.scrublet.preview",
        step_version="1.0.0-shadow",
        tool_contract_version=contract.contract_version,
        parameters=parameters,
        input_artifacts=["representative_preview_h5ad"],
        output_artifacts=[
            "doublet_results_tsv",
            "input_qc_png",
            "doublet_score_histogram_png",
            "doublet_score_manifold_png",
            "parameter_snapshot_json",
            "runtime_warnings_json",
        ],
        validators=[
            "cell_order_preserved",
            "score_finite_and_in_range",
            "label_count_matches_cells",
        ],
        source_refs=list(contract.source_refs),
        template_digest=digest,
    )


class NotebookShadowCompiler:
    """Compile a fixed, reviewable notebook. This class never executes it."""

    def __init__(self, *, contract_registry: ToolContractRegistry | None = None):
        self.contract_registry = contract_registry or ToolContractRegistry()

    def compile_scrublet(
        self,
        *,
        profile: DataAssetProfile,
        preview: RepresentativePreviewManifest,
        preview_path: Path,
        output_dir: Path,
        allowed_output_root: Path,
        parameters: dict[str, Any] | None = None,
        task_context: dict[str, str | None] | None = None,
    ) -> NotebookShadowBundle:
        if preview.artifact_id != profile.artifact_id:
            raise ValueError("preview and profile artifact ids differ")
        preview_path = Path(preview_path).resolve(strict=True)
        if _sha256(preview_path) != preview.preview_hash:
            raise ValueError("preview hash changed")
        output_root = Path(allowed_output_root).resolve()
        output_dir = Path(output_dir).resolve()
        _require_within(output_dir, output_root, "notebook output")
        if output_dir.exists():
            raise FileExistsError("notebook output directory already exists")
        output_dir.mkdir(parents=True)

        notebook_preview_path = output_dir / "representative_preview.h5ad"
        shutil.copy2(preview_path, notebook_preview_path)

        tool_contract = self.contract_registry.load("Scrublet", "0.2.3")
        step = scrublet_step_contract(self.contract_registry)
        supplied_parameters = dict(parameters or {})
        merged = self.contract_registry.validate_parameters(
            tool_contract, supplied_parameters
        )
        parameter_provenance = {
            name: _parameter_provenance(
                name=name,
                value=value,
                supplied_parameters=supplied_parameters,
                step=step,
            )
            for name, value in sorted(merged.items())
        }
        parameter_hash = _digest_json(merged)
        normalized_task_context = {
            str(key): (None if value is None else str(value))
            for key, value in sorted((task_context or {}).items())
        }
        task_context_digest = (
            _digest_json(normalized_task_context) if normalized_task_context else None
        )
        cells = _cells(
            preview_filename=notebook_preview_path.name,
            parameters=merged,
            parameter_provenance=parameter_provenance,
            profile=profile,
            preview=preview,
            task_context=normalized_task_context,
            step=step,
        )
        cell_source_digests = {
            cell["id"]: _source_digest(cell["source"]) for cell in cells
        }
        for cell in cells:
            cell["metadata"]["sckg"]["source_digest"] = cell_source_digests[
                cell["id"]
            ]
        notebook = {
            "cells": cells,
            "metadata": {
                "kernelspec": {
                    "display_name": "scKG doublet Python runtime",
                    "language": "python",
                    "name": "sckg-doublet-python",
                },
                "language_info": {"name": "python", "pygments_lexer": "ipython3"},
                "sckg": {
                    "schema_version": "sckg-notebook-shadow-v2",
                    "shadow_mode": True,
                    "trusted_code_source": "maintainer_step_template",
                    "artifact_id": profile.artifact_id,
                    "profile_id": profile.profile_id,
                    "source_hash": profile.source_hash,
                    "preview_id": preview.preview_id,
                    "preview_hash": preview.preview_hash,
                    "step_id": step.step_id,
                    "step_version": step.step_version,
                    "tool_contract_id": step.tool_contract_id,
                    "tool_contract_version": step.tool_contract_version,
                    "step_template_digest": step.template_digest,
                    "parameter_hash": parameter_hash,
                    "task_context_digest": task_context_digest,
                    "cell_source_digests": cell_source_digests,
                    "execution_request_count": 0,
                },
            },
            "nbformat": 4,
            "nbformat_minor": 5,
        }
        notebook_path = output_dir / "analysis_preview.ipynb"
        notebook_path.write_text(
            json.dumps(notebook, ensure_ascii=False, indent=1) + "\n",
            encoding="utf-8",
        )
        (output_dir / "step_contract.json").write_text(
            step.model_dump_json(indent=2) + "\n", encoding="utf-8"
        )
        (output_dir / "parameters.json").write_text(
            json.dumps(merged, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        bundle = NotebookShadowBundle(
            notebook_id=f"notebook-{_sha256(notebook_path)[:16]}",
            owner_user_id=profile.owner_user_id,
            artifact_id=profile.artifact_id,
            preview_id=preview.preview_id,
            profile_id=profile.profile_id,
            source_hash=profile.source_hash,
            notebook_path_redacted=f".../{notebook_path.name}",
            notebook_hash=_sha256(notebook_path),
            preview_hash=preview.preview_hash,
            step_contract_id=step.step_id,
            step_contract_version=step.step_version,
            tool_contract_version=step.tool_contract_version,
            step_template_digest=step.template_digest,
            parameter_hash=parameter_hash,
            parameter_snapshot=merged,
            parameter_provenance=parameter_provenance,
            task_context=normalized_task_context,
            task_context_digest=task_context_digest,
            cell_source_digests=cell_source_digests,
            cell_count=len(notebook["cells"]),
            code_cell_count=sum(
                cell["cell_type"] == "code" for cell in notebook["cells"]
            ),
            limitations=[
                "This notebook is a shadow preview artifact and was not executed by compilation.",
                "Only maintainer-authored StepTemplate cells are governed; edited or custom cells are untrusted.",
                "Preview outputs are engineering checks, not full-data scientific conclusions.",
                "Full-data execution still requires the existing plan-specific approval and controlled executor.",
                "The notebook directory contains a controlled preview copy, never the original source dataset.",
            ],
        )
        (output_dir / "notebook_manifest.json").write_text(
            bundle.model_dump_json(indent=2) + "\n", encoding="utf-8"
        )
        return bundle

    def inspect_trust(
        self, *, notebook_path: Path, bundle: NotebookShadowBundle
    ) -> NotebookTrustReport:
        notebook_path = Path(notebook_path).resolve(strict=True)
        payload = json.loads(notebook_path.read_text(encoding="utf-8"))
        expected = dict(bundle.cell_source_digests)
        cells: list[NotebookCellTrustRecord] = []
        modified: list[str] = []
        untracked: list[str] = []
        for index, cell in enumerate(payload.get("cells") or []):
            cell_id = str(cell.get("id") or f"cell-{index}")
            metadata = cell.get("metadata") or {}
            sckg = metadata.get("sckg") or {}
            role = str(sckg.get("cell_role") or "untracked")
            current_digest = _source_digest(cell.get("source") or "")
            expected_digest = expected.get(cell_id)
            if expected_digest is None:
                status = "UNTRACKED"
                untracked.append(cell_id)
            elif expected_digest != current_digest:
                status = "MODIFIED"
                modified.append(cell_id)
            else:
                status = "VERIFIED"
            cells.append(
                NotebookCellTrustRecord(
                    cell_id=cell_id,
                    cell_role=role,
                    source_digest=current_digest,
                    expected_source_digest=expected_digest,
                    status=status,
                )
            )
        notebook_hash_matches = _sha256(notebook_path) == bundle.notebook_hash
        issues: list[str] = []
        if not notebook_hash_matches:
            issues.append("notebook_hash_changed")
        if modified:
            issues.append("maintainer_cell_modified")
        if untracked:
            issues.append("untracked_cell_present")
        if set(expected) - {item.cell_id for item in cells}:
            issues.append("maintainer_cell_missing")
        return NotebookTrustReport(
            notebook_id=bundle.notebook_id,
            notebook_hash_matches=notebook_hash_matches,
            system_verified=not issues,
            cells=cells,
            modified_cell_ids=modified,
            untracked_cell_ids=untracked,
            issues=issues,
        )


def _cells(
    *,
    preview_filename: str,
    parameters: dict[str, Any],
    parameter_provenance: dict[str, str],
    profile: DataAssetProfile,
    preview: RepresentativePreviewManifest,
    task_context: dict[str, str | None],
    step: StepContract,
) -> list[dict[str, Any]]:
    metadata = lambda role: {
        "sckg": {
            "step_id": step.step_id,
            "step_version": step.step_version,
            "cell_role": role,
            "trusted": True,
            "source": "maintainer_step_template",
        }
    }
    selected_matrix = next(
        (
            item
            for item in profile.matrices
            if item.matrix_id == profile.selected_count_source
        ),
        None,
    )
    matrix_state = (
        str(
            getattr(
                selected_matrix.inferred_state,
                "value",
                selected_matrix.inferred_state,
            )
        )
        if selected_matrix is not None
        else "unknown"
    )
    source_query = _markdown_inline(task_context.get("source_query") or "Direct Stepwise Analysis request")
    parameter_rows = "\n".join(
        f"| `{_markdown_inline(name)}` | `{_markdown_inline(json.dumps(value, ensure_ascii=False))}` | "
        f"{_markdown_inline(parameter_provenance[name])} |"
        for name, value in sorted(parameters.items())
    )
    return [
        _markdown_cell(
            "# scKG Doublet Detection Preview\n\n"
            "**PREVIEW ONLY.** This notebook checks data structure, code, runtime, and artifact contracts. "
            "It is not a full-data scientific result.\n\n"
            f"**Conversation task:** {source_query}\n\n"
            "### What you will do\n\n"
            "1. Inspect the representative raw-count matrix.\n"
            "2. Review parameters and their provenance.\n"
            "3. Run Scrublet one step at a time.\n"
            "4. Validate the output schema.\n"
            "5. Inspect input QC, score, call and manifold diagnostics.\n\n"
            "Run cells from top to bottom. You may change values in the `PARAMETERS` cell for local exploration; "
            "edited cells are no longer a system-verified execution source.",
            metadata=metadata("provenance"),
        ),
        _markdown_cell(
            "## Why the DataProfile matters\n\n"
            "The read-only DataProfile decides which matrix is safe to pass to a raw-count-only tool. "
            "It prevents normalized or scaled `X` from being silently treated as counts, selects a valid "
            "`layers['counts']`/`raw.X` source when available, and blocks the workflow when the count source is unresolved.\n\n"
            f"| Check | Value |\n|---|---|\n"
            f"| Source cells | {profile.n_cells:,} |\n"
            f"| Preview cells | {preview.n_preview_cells:,} |\n"
            f"| Genes | {profile.n_genes:,} |\n"
            f"| Selected count source | `{_markdown_inline(profile.selected_count_source or 'unresolved')}` |\n"
            f"| Inferred matrix state | `{_markdown_inline(matrix_state)}` |\n"
            f"| Source file modified | `False` |\n\n"
            "For the built-in demo, the registered file is deterministic synthetic data. For a registered user dataset, "
            "the preview is a deterministic representative subset copied into this notebook workspace; the original file is not modified.",
            metadata=metadata("data_profile_summary"),
        ),
        _markdown_cell(
            "## Governed step contract\n\n"
            f"- Step: `{step.step_id}` (`{step.step_version}`)\n"
            f"- Tool contract: `{step.tool_contract_id}` (`{step.tool_contract_version}`)\n"
            "- Required input: non-negative raw count matrix\n"
            "- Parameter defaults are copied from the reviewed ToolContract; `expected_doublet_rate` must be checked for the real capture.\n"
            "- Sources: " + ", ".join(f"`{item}`" for item in step.source_refs),
            metadata=metadata("contract_and_sources"),
        ),
        _markdown_cell(
            "## Parameter snapshot and provenance\n\n"
            "These values are validated against the reviewed Scrublet 0.2.3 ToolContract. "
            "They are not generated ad hoc by an LLM. Contract defaults are informed by the tool API/docs and the reviewed source dossier; "
            "a value marked `user_confirmed_override` was changed in Stepwise Analysis. "
            "`expected_doublet_rate` must be checked against the real 10x loading/recovery for each capture.\n\n"
            "| Parameter | Value | Provenance |\n|---|---:|---|\n"
            + parameter_rows,
            metadata=metadata("parameter_provenance"),
        ),
        _markdown_cell(
            "## 1. Set up the analysis\n\n"
            "This cell imports the existing Runtime Pack. It never installs packages. "
            "All outputs stay inside `preview_outputs/` next to this notebook.",
            metadata=metadata("setup_explanation"),
        ),
        _code_cell(
            "from pathlib import Path\n"
            "import json\n"
            "import warnings\n"
            "import numpy as np\n"
            "import pandas as pd\n"
            "import anndata as ad\n"
            "import matplotlib.pyplot as plt\n"
            "from IPython.display import Image, display\n"
            "import scrublet as scr\n\n"
            f"PREVIEW_PATH = Path({preview_filename!r})\n"
            "OUTPUT_DIR = Path('preview_outputs')\n"
            "OUTPUT_DIR.mkdir(exist_ok=True)",
            metadata=metadata("imports_and_paths"),
        ),
        _markdown_cell(
            "### Parameters\n\n"
            "The values below start from the reviewed Scrublet ToolContract. "
            "For real 10x data, check `expected_doublet_rate` against the loading and recovery for each capture.",
            metadata=metadata("parameters_explanation"),
        ),
        _code_cell(
            "PARAMETERS = " + repr(parameters) + "\n"
            "print(json.dumps(PARAMETERS, indent=2, sort_keys=True))",
            metadata=metadata("parameters"),
        ),
        _markdown_cell(
            "## 2. Load and inspect the Preview\n\n"
            "The assertions confirm that this is a representative Preview and cannot be promoted to a full-data conclusion. "
            "The summary and QC plots help catch implausible library sizes or detected-gene distributions before running Scrublet.",
            metadata=metadata("input_explanation"),
        ),
        _code_cell(
            "adata = ad.read_h5ad(PREVIEW_PATH)\n"
            "assert bool(adata.uns['sckg_preview']['preview_only']) is True\n"
            "assert bool(adata.uns['sckg_preview']['scientific_claim_allowed']) is False\n"
            "preview_summary = pd.DataFrame({\n"
            "    'value': [adata.n_obs, adata.n_vars, adata.uns['sckg_preview']['selected_count_source']],\n"
            "}, index=['cells', 'genes', 'selected_count_source'])\n"
            "display(preview_summary)",
            metadata=metadata("load_and_validate_input"),
        ),
        _code_cell(
            "library_size = np.asarray(adata.X.sum(axis=1)).ravel()\n"
            "detected_genes = np.asarray((adata.X > 0).sum(axis=1)).ravel()\n"
            "fig, axes = plt.subplots(1, 2, figsize=(11, 3.8))\n"
            "axes[0].hist(library_size, bins=30, color='#287271', edgecolor='white')\n"
            "axes[0].set(title='UMI counts per cell', xlabel='UMI counts', ylabel='cells')\n"
            "axes[1].hist(detected_genes, bins=30, color='#4C78A8', edgecolor='white')\n"
            "axes[1].set(title='Detected genes per cell', xlabel='detected genes', ylabel='cells')\n"
            "fig.suptitle('Input Preview QC', fontsize=14)\n"
            "input_qc_path = OUTPUT_DIR / 'input_qc.png'\n"
            "fig.tight_layout(); fig.savefig(input_qc_path, dpi=160, bbox_inches='tight')\n"
            "plt.close(fig)\n"
            "display(Image(filename=str(input_qc_path)))",
            metadata=metadata("input_qc_diagnostics"),
        ),
        _markdown_cell(
            "## 3. Run Scrublet\n\n"
            "Scrublet simulates doublets from observed profiles, embeds observed and simulated cells, "
            "and estimates a score from their neighbourhoods. Initialization and scoring are separate so errors are easier to locate.",
            metadata=metadata("scrublet_explanation"),
        ),
        _code_cell(
            "scrub = scr.Scrublet(\n"
            "    adata.X,\n"
            "    sim_doublet_ratio=PARAMETERS['sim_doublet_ratio'],\n"
            "    expected_doublet_rate=PARAMETERS['expected_doublet_rate'],\n"
            "    stdev_doublet_rate=PARAMETERS['stdev_doublet_rate'],\n"
            "    random_state=PARAMETERS['random_state'],\n"
            ")\n"
            "scrub",
            metadata=metadata("scrublet_initialization"),
        ),
        _code_cell(
            "with warnings.catch_warnings(record=True) as caught_warnings:\n"
            "    warnings.simplefilter('always', RuntimeWarning)\n"
            "    scores, predicted = scrub.scrub_doublets(\n"
            "        synthetic_doublet_umi_subsampling=PARAMETERS['synthetic_doublet_umi_subsampling'],\n"
            "        use_approx_neighbors=PARAMETERS['use_approx_neighbors'],\n"
            "        distance_metric=PARAMETERS['distance_metric'],\n"
            "        min_counts=PARAMETERS['min_counts'],\n"
            "        min_cells=PARAMETERS['min_cells'],\n"
            "        min_gene_variability_pctl=PARAMETERS['min_gene_variability_pctl'],\n"
            "        log_transform=PARAMETERS['log_transform'],\n"
            "        mean_center=PARAMETERS['mean_center'],\n"
            "        normalize_variance=PARAMETERS['normalize_variance'],\n"
            "        n_prin_comps=min(PARAMETERS['n_prin_comps'], max(2, min(adata.n_obs, adata.n_vars) - 1)),\n"
            "        svd_solver=PARAMETERS['svd_solver'],\n"
            "        verbose=False,\n"
            "    )\n"
            "runtime_warnings = sorted({str(item.message) for item in caught_warnings if issubclass(item.category, RuntimeWarning)})\n"
            "(OUTPUT_DIR / 'runtime_warnings.json').write_text(json.dumps(runtime_warnings, indent=2) + '\\n')\n"
            "print(f'Scrublet completed; {len(runtime_warnings)} distinct numeric warning(s) retained in preview_outputs/runtime_warnings.json')",
            metadata=metadata("scrublet_preview"),
        ),
        _markdown_cell(
            "## 4. Validate and save the result table\n\n"
            "The checks below require one finite score and one boolean call per input cell. "
            "The table and exact parameter snapshot are then saved as portable artifacts.",
            metadata=metadata("validation_explanation"),
        ),
        _code_cell(
            "scores = np.asarray(scores, dtype=float)\n"
            "predicted = np.asarray(predicted, dtype=bool)\n"
            "assert scores.shape == (adata.n_obs,) and predicted.shape == (adata.n_obs,)\n"
            "assert np.isfinite(scores).all() and ((scores >= 0) & (scores <= 1)).all()\n"
            "results = pd.DataFrame({'obs_id': adata.obs_names.astype(str), 'doublet_score': scores, 'predicted_doublet': predicted})\n"
            "results.to_csv(OUTPUT_DIR / 'doublet_results.tsv', sep='\\t', index=False)\n"
            "(OUTPUT_DIR / 'parameters.json').write_text(json.dumps(PARAMETERS, indent=2, sort_keys=True) + '\\n')\n"
            "display(results.head(10))",
            metadata=metadata("validation_and_artifacts"),
        ),
        _markdown_cell(
            "## 5. Inspect Scrublet diagnostics\n\n"
            "Use all three panels together: the score distribution shows separation and the learned threshold; "
            "the rank plot exposes a high-score tail; the call counts reveal whether the predicted rate is plausible. "
            "No single panel establishes biological accuracy.",
            metadata=metadata("score_diagnostics_explanation"),
        ),
        _code_cell(
            "threshold = float(getattr(scrub, 'threshold_', np.nan))\n"
            "fig, axes = plt.subplots(1, 3, figsize=(15, 4.2))\n"
            "axes[0].hist(results['doublet_score'], bins=30, color='#287271', edgecolor='white')\n"
            "if np.isfinite(threshold):\n"
            "    axes[0].axvline(threshold, color='#C95D3A', linestyle='--', linewidth=2, label=f'threshold={threshold:.3f}')\n"
            "    axes[0].legend(frameon=False)\n"
            "axes[0].set(title='Scrublet score distribution', xlabel='doublet score', ylabel='cells')\n"
            "ranked_scores = np.sort(results['doublet_score'].to_numpy())[::-1]\n"
            "axes[1].plot(np.arange(1, len(ranked_scores) + 1), ranked_scores, color='#4C78A8', linewidth=2)\n"
            "if np.isfinite(threshold):\n"
            "    axes[1].axhline(threshold, color='#C95D3A', linestyle='--', linewidth=2)\n"
            "axes[1].set(title='Ranked doublet scores', xlabel='cell rank', ylabel='doublet score')\n"
            "call_counts = results['predicted_doublet'].map({False: 'Singlet', True: 'Doublet'}).value_counts().reindex(['Singlet', 'Doublet'], fill_value=0)\n"
            "bars = axes[2].bar(call_counts.index, call_counts.values, color=['#4C78A8', '#E07A5F'])\n"
            "axes[2].bar_label(bars, padding=3)\n"
            "axes[2].set(title='Predicted calls', ylabel='cells')\n"
            "fig.suptitle('Representative Preview diagnostics', fontsize=14)\n"
            "figure_path = OUTPUT_DIR / 'doublet_score_histogram.png'\n"
            "fig.tight_layout(); fig.savefig(figure_path, dpi=160, bbox_inches='tight')\n"
            "plt.close(fig)\n"
            "display(Image(filename=str(figure_path)))",
            metadata=metadata("score_diagnostics"),
        ),
        _markdown_cell(
            "### Score manifold\n\n"
            "This view projects Scrublet's observed-cell manifold onto its first two components. "
            "Colour shows the score; outlined points are predicted doublets. Treat clusters and boundaries as engineering diagnostics, not cell types.",
            metadata=metadata("manifold_explanation"),
        ),
        _code_cell(
            "manifold = np.asarray(getattr(scrub, 'manifold_obs_', np.empty((0, 0))))\n"
            "if manifold.ndim == 2 and manifold.shape[0] == adata.n_obs and manifold.shape[1] >= 2:\n"
            "    fig, ax = plt.subplots(figsize=(7, 5.2))\n"
            "    points = ax.scatter(manifold[:, 0], manifold[:, 1], c=scores, cmap='viridis', s=24, alpha=0.8)\n"
            "    if predicted.any():\n"
            "        ax.scatter(manifold[predicted, 0], manifold[predicted, 1], facecolors='none', edgecolors='#E07A5F', s=70, linewidths=1.2, label='predicted doublet')\n"
            "        ax.legend(frameon=False)\n"
            "    fig.colorbar(points, ax=ax, label='doublet score')\n"
            "    ax.set(title='Scrublet score manifold', xlabel='component 1', ylabel='component 2')\n"
            "    manifold_path = OUTPUT_DIR / 'doublet_score_manifold.png'\n"
            "    fig.tight_layout(); fig.savefig(manifold_path, dpi=160, bbox_inches='tight')\n"
            "    plt.close(fig)\n"
            "    display(Image(filename=str(manifold_path)))\n"
            "else:\n"
            "    print('Scrublet manifold is unavailable for this Preview; score diagnostics remain valid.')",
            metadata=metadata("manifold_diagnostics"),
        ),
        _markdown_cell(
            "## 6. Interpretation boundary\n\n"
            "Check input QC first, then the score tail, learned threshold, predicted call rate and manifold together. "
            "Unexpected numeric warnings, a missing score tail or an implausible call rate require review. "
            "Do not promote the Preview threshold or labels to a full-data conclusion without the governed RUN workflow, "
            "capture-specific parameter review and validation package.",
            metadata=metadata("limitations"),
        ),
    ]


def _parameter_provenance(
    *,
    name: str,
    value: Any,
    supplied_parameters: dict[str, Any],
    step: StepContract,
) -> str:
    spec = step.parameters[name]
    if name not in supplied_parameters:
        return spec.provenance
    if value != spec.default:
        return "user_confirmed_override"
    if spec.user_confirmation_required:
        return "user_confirmed_contract_default"
    return spec.provenance


def _markdown_inline(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("`", "'").replace("\n", " ").strip()


def _markdown_cell(source: str, *, metadata: dict[str, Any]) -> dict[str, Any]:
    return {
        "cell_type": "markdown",
        "id": metadata["sckg"]["cell_role"][:64],
        "metadata": metadata,
        "source": source,
    }


def _code_cell(source: str, *, metadata: dict[str, Any]) -> dict[str, Any]:
    return {
        "cell_type": "code",
        "id": metadata["sckg"]["cell_role"][:64],
        "execution_count": None,
        "metadata": metadata,
        "outputs": [],
        "source": source,
    }


def _parameter_type(value: str) -> str:
    return {"integer": "integer", "number": "number", "boolean": "boolean", "string": "string"}[value]


def _digest_json(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _source_digest(value: object) -> str:
    if isinstance(value, list):
        normalized = "".join(str(item) for item in value)
    else:
        normalized = str(value)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _require_within(path: Path, root: Path, label: str) -> None:
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"{label} escapes allowed root") from exc
