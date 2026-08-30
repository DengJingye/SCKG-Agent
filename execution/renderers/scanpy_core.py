from __future__ import annotations

import json
import re

from execution.capability_notebook import MaintainerTemplateRenderer


SCANPY_CORE_TEMPLATES = {
    "profile_anndata": "import scanpy as sc\nadata = sc.read_h5ad(INPUT_PATH)\nprint(adata)",
    "calculate_qc": (
        "qc_percent_top = [\n"
        "    int(value)\n"
        "    for value in STEP_PARAMETERS.get('percent_top', [50, 100, 200, 500])\n"
        "    if 0 < int(value) <= adata.n_vars\n"
        "]\n"
        "sc.pp.calculate_qc_metrics(\n"
        "    adata,\n"
        "    percent_top=qc_percent_top or None,\n"
        "    inplace=True,\n"
        ")\n"
        "print(f'QC metrics calculated; percent_top={qc_percent_top or None}')"
    ),
    "filter_counts": "sc.pp.filter_cells(adata, min_genes=STEP_PARAMETERS.get('min_genes', 1))\nsc.pp.filter_genes(adata, min_cells=STEP_PARAMETERS.get('min_cells', 1))",
    "doublet_detection_action": "# Delegated to the qualified Doublet Detection ActionBundle; this notebook cell does not execute another wrapper.",
    "confirm_doublet_exclusion": "# Review validated doublet calls and bind the confirmed selection hash before changing the cell set.",
    "normalize_total": "adata.layers['counts'] = adata.X.copy()\nsc.pp.normalize_total(adata, target_sum=STEP_PARAMETERS.get('target_sum', 10000.0))",
    "normalize_after_doublet_exclusion": "adata.layers['counts'] = adata.X.copy()\nsc.pp.normalize_total(adata, target_sum=STEP_PARAMETERS.get('target_sum', 10000.0))",
    "log1p": "sc.pp.log1p(adata)\nadata.layers['log1p'] = adata.X.copy()",
    "highly_variable_genes": "sc.pp.highly_variable_genes(adata, n_top_genes=STEP_PARAMETERS.get('n_top_genes', 2000))",
    "scale_hvg": "scaled = adata[:, adata.var['highly_variable']].copy()\nsc.pp.scale(scaled, max_value=STEP_PARAMETERS.get('max_value', 10.0))",
    "pca_scaled": "sc.tl.pca(scaled, n_comps=STEP_PARAMETERS.get('n_comps', 50))\nadata.obsm['X_pca'] = scaled.obsm['X_pca']",
    "pca_log_hvg": "sc.tl.pca(adata, mask_var='highly_variable', n_comps=STEP_PARAMETERS.get('n_comps', 50))",
    "neighbors": "sc.pp.neighbors(adata, use_rep='X_pca', n_neighbors=STEP_PARAMETERS.get('n_neighbors', 15))",
    "batch_integration_action": "# Delegated to the qualified Batch Integration ActionBundle; its validated embedding is registered in the RepresentationLedger.",
    "neighbors_integrated": "sc.pp.neighbors(adata, use_rep=INTEGRATED_REP_KEY, n_neighbors=STEP_PARAMETERS.get('n_neighbors', 15))",
    "umap": "sc.tl.umap(adata, random_state=STEP_PARAMETERS.get('random_state', 0))",
    "leiden": "sc.tl.leiden(adata, resolution=STEP_PARAMETERS.get('resolution', 1.0), random_state=STEP_PARAMETERS.get('random_state', 0))",
    "rank_markers": "# Marker testing uses full_gene_unscaled_log1p, never scaled or integrated values.\nsc.tl.rank_genes_groups(adata, groupby='leiden', layer='log1p', use_raw=False, method='wilcoxon')",
    "marker_evidence_annotation": "# Candidate labels require reviewed marker evidence and human confirmation.",
    "reference_annotation": "# Reference binding requires a versioned reference manifest and overlap checks.",
    "human_confirmation": "# Record the reviewed label decision; do not infer it from free-form model output.",
}


SCANPY_CORE_DIAGNOSTICS = {
    "calculate_qc": (
        "sc.pl.violin(\n"
        "    adata,\n"
        "    keys=['n_genes_by_counts', 'total_counts'],\n"
        "    jitter=0.35,\n"
        "    multi_panel=True,\n"
        "    show=False,\n"
        ")\n"
        "fig = plt.gcf()\n"
        "sckg_save_and_display(fig, '01_qc_distributions.png')"
    ),
    "highly_variable_genes": (
        "sc.pl.highly_variable_genes(adata, show=False)\n"
        "fig = plt.gcf()\n"
        "sckg_save_and_display(fig, '02_highly_variable_genes.png')"
    ),
    "pca_scaled": (
        "sc.pl.pca_variance_ratio(scaled, n_pcs=min(30, scaled.obsm['X_pca'].shape[1]), log=True, show=False)\n"
        "fig = plt.gcf()\n"
        "sckg_save_and_display(fig, '03_pca_variance.png')"
    ),
    "pca_log_hvg": (
        "sc.pl.pca_variance_ratio(adata, n_pcs=min(30, adata.obsm['X_pca'].shape[1]), log=True, show=False)\n"
        "fig = plt.gcf()\n"
        "sckg_save_and_display(fig, '03_pca_variance.png')"
    ),
    "rank_markers": (
        "sc.pl.rank_genes_groups(adata, n_genes=5, sharey=False, show=False)\n"
        "marker_fig = plt.gcf()\n"
        "sckg_save_and_display(marker_fig, '04_ranked_marker_genes.png')"
    ),
    "umap": (
        "batch_key = BATCH_KEY if BATCH_KEY and BATCH_KEY in adata.obs.columns else None\n"
        "color_keys = ['leiden'] + ([batch_key] if batch_key else [])\n"
        "sc.pl.umap(adata, color=color_keys, frameon=False, show=False)\n"
        "fig = plt.gcf()\n"
        "sckg_save_and_display(fig, '05_umap_clusters_and_batch.png')"
    ),
}


class ScanpyCoreNotebookRenderer(MaintainerTemplateRenderer):
    def __init__(self) -> None:
        super().__init__(
            SCANPY_CORE_TEMPLATES,
            kernel_name="sckg-doublet-python",
            kernel_display_name="scKG Doublet Python",
        )

    def bootstrap(self, context: dict[str, object]) -> list[dict[str, object]]:
        input_path = str(context.get("input_path") or "input.h5ad")
        output_dir = str(context.get("output_dir") or "scanpy_core_outputs")
        batch_key = str(context.get("batch_key") or "")
        source = (
            "from pathlib import Path\n"
            "import scanpy as sc\n"
            "import numpy as np\n"
            "import pandas as pd\n"
            "import matplotlib.pyplot as plt\n\n"
            "from IPython.display import display\n\n"
            "get_ipython().run_line_magic('matplotlib', 'inline')\n\n"
            f"INPUT_PATH = Path({json.dumps(input_path)})\n"
            f"OUTPUT_DIR = Path({json.dumps(output_dir)})\n"
            f"BATCH_KEY = {json.dumps(batch_key)}\n"
            "OUTPUT_DIR.mkdir(parents=True, exist_ok=True)\n\n"
            "def sckg_save_and_display(fig, filename):\n"
            "    path = OUTPUT_DIR / filename\n"
            "    fig.tight_layout()\n"
            "    fig.savefig(path, dpi=160, bbox_inches='tight')\n"
            "    display(fig)\n"
            "    plt.close(fig)\n"
            "    print(f'Saved diagnostic: {path}')\n\n"
            "adata = sc.read_h5ad(INPUT_PATH)\n"
            "print(adata)"
        )
        return [
            {
                "cell_type": "markdown",
                "id": "scanpy-core-setup-description",
                "metadata": {},
                "source": (
                    "## Setup and load AnnData\n\n"
                    "Run this cell first. It imports the qualified Scanpy runtime and "
                    "loads the registered input without modifying the source file."
                ),
            },
            {
                "cell_type": "code",
                "id": "scanpy-core-setup-code",
                "metadata": {},
                "execution_count": None,
                "outputs": [],
                "source": source,
            },
        ]

    def render(self, step, parameters, *, parameter_provenance=None):
        cells = super().render(
            step,
            parameters,
            parameter_provenance=parameter_provenance,
        )
        diagnostic_source = SCANPY_CORE_DIAGNOSTICS.get(step.operation)
        if diagnostic_source is None:
            return cells
        safe_id = re.sub(r"[^A-Za-z0-9_-]+", "-", step.method_id).strip("-")
        cells.extend(
            [
                {
                    "cell_type": "markdown",
                    "id": f"{safe_id}-diagnostic-description",
                    "metadata": {},
                    "source": (
                        "### Diagnostic plot\n\n"
                        "This uses the reviewed Scanpy `sc.pl` plotting API and renders inline. "
                        "A hidden PNG copy is retained only for reproducibility."
                    ),
                },
                {
                    "cell_type": "code",
                    "id": f"{safe_id}-diagnostic-code",
                    "metadata": {},
                    "execution_count": None,
                    "outputs": [],
                    "source": diagnostic_source,
                },
            ]
        )
        return cells
