from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from execution.approval_service import ApprovalService
from execution.data_registry import DataRegistry
from execution.execution_policy import ExecutionPolicy
from execution.research_workspace_service import ResearchWorkspaceService
from execution.runtime_pack_resolver import RuntimePackResolver


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="sckg-workspace-smoke-") as temporary:
        root = Path(temporary)
        input_root = root / "approved-inputs"
        source = _write_smoke_fixture(input_root / "pbmc_preview_smoke.h5ad")
        registry = DataRegistry(
            approved_input_roots=[input_root], registry_root=root / "registry"
        )
        approvals = ApprovalService(root=root / "approvals")
        service = ResearchWorkspaceService(
            data_registry=registry,
            approval_service=approvals,
            workspace_root=root / "workspace",
        )
        artifact = registry.register(
            user_id="smoke-user", path=source, artifact_id="pbmc-preview-smoke"
        )
        grant = approvals.grant_data_access(
            user_id="smoke-user", artifact_id=artifact.artifact_id
        )
        profile = service.profile(
            user_id="smoke-user",
            artifact_id=artifact.artifact_id,
            data_grant_id=grant.grant_id,
        )
        preview = service.build_preview(
            user_id="smoke-user",
            artifact_id=artifact.artifact_id,
            profile=profile,
            data_grant_id=grant.grant_id,
            max_cells=120,
            random_seed=20260812,
            stratify_key="batch",
        )
        notebook = service.compile_notebook(
            user_id="smoke-user",
            artifact_id=artifact.artifact_id,
            profile=profile,
            preview=preview,
            data_grant_id=grant.grant_id,
            parameters={"expected_doublet_rate": 0.08, "n_prin_comps": 10},
        )
        notebook_path = service.notebook_path(
            user_id="smoke-user",
            artifact_id=artifact.artifact_id,
            bundle=notebook,
        )
        clean_kernel = _execute_synthetic_notebook(
            notebook_path=notebook_path,
            runtime_python=RuntimePackResolver().python("doublet-python"),
            kernel_root=root / "jupyter",
        )
        summary = {
            "registered_artifact": artifact.artifact_id,
            "path_redacted": artifact.redacted_path,
            "backed_profile": profile.storage_mode == "backed_read_only",
            "full_matrix_materialized": profile.full_matrix_materialized,
            "selected_count_source": profile.selected_count_source,
            "preview_cells": preview.n_preview_cells,
            "preview_strata": preview.preview_strata_counts,
            "source_unchanged": preview.source_unchanged,
            "scientific_claim_allowed": preview.scientific_claim_allowed,
            "notebook_schema_valid": notebook_path.is_file(),
            "notebook_executed": notebook.executed,
            "clean_kernel_smoke": clean_kernel,
            "execution_request_count": notebook.execution_request_count,
            "execution_policy": ExecutionPolicy().mode.value,
        }
        required = {
            "backed_profile": True,
            "full_matrix_materialized": False,
            "source_unchanged": True,
            "scientific_claim_allowed": False,
            "notebook_schema_valid": True,
            "notebook_executed": False,
            "clean_kernel_smoke": True,
            "execution_request_count": 0,
            "execution_policy": "disabled",
        }
        if any(summary[key] != value for key, value in required.items()):
            raise AssertionError(summary)
        print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


def _write_smoke_fixture(path: Path) -> Path:
    import anndata as ad
    import numpy as np
    import pandas as pd
    from scipy import sparse

    rng = np.random.default_rng(20260812)
    path.parent.mkdir(parents=True, exist_ok=True)
    gene_rates = rng.gamma(shape=1.8, scale=1.2, size=500)
    cell_depth = rng.lognormal(mean=0.0, sigma=0.3, size=240)
    counts = rng.poisson(cell_depth[:, None] * gene_rates[None, :]).astype(np.int32)
    obs = pd.DataFrame(
        {"batch": ["batch_a"] * 120 + ["batch_b"] * 120},
        index=[f"cell_{index:04d}" for index in range(240)],
    )
    var = pd.DataFrame(index=[f"gene_{index:04d}" for index in range(500)])
    adata = ad.AnnData(
        X=sparse.csr_matrix(np.log1p(counts).astype(np.float32)),
        obs=obs,
        var=var,
    )
    adata.layers["counts"] = sparse.csr_matrix(counts)
    adata.write_h5ad(path)
    return path


def _execute_synthetic_notebook(
    *, notebook_path: Path, runtime_python: Path, kernel_root: Path
) -> bool:
    kernel_dir = kernel_root / "kernels" / "sckg-doublet-preview"
    kernel_dir.mkdir(parents=True)
    (kernel_dir / "kernel.json").write_text(
        json.dumps(
            {
                "argv": [
                    str(runtime_python),
                    "-m",
                    "ipykernel_launcher",
                    "-f",
                    "{connection_file}",
                ],
                "display_name": "scKG doublet preview smoke",
                "language": "python",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    environment = dict(os.environ)
    environment["JUPYTER_PATH"] = str(kernel_root)
    environment["PYTHONHASHSEED"] = "0"
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "jupyter",
            "nbconvert",
            "--to",
            "notebook",
            "--execute",
            "--inplace",
            "--ExecutePreprocessor.kernel_name=sckg-doublet-preview",
            "--ExecutePreprocessor.timeout=120",
            notebook_path.name,
        ],
        cwd=notebook_path.parent,
        env=environment,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=150,
        shell=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "clean-kernel notebook smoke failed: " + completed.stderr[-2000:]
        )
    output_dir = notebook_path.parent / "preview_outputs"
    required = [
        output_dir / "doublet_results.tsv",
        output_dir / "input_qc.png",
        output_dir / "doublet_score_histogram.png",
        output_dir / "doublet_score_manifold.png",
        output_dir / "parameters.json",
        output_dir / "runtime_warnings.json",
    ]
    payload = json.loads(notebook_path.read_text(encoding="utf-8"))
    inline_plot_count = sum(
        output.get("output_type") in {"display_data", "execute_result"}
        and "image/png" in (output.get("data") or {})
        for cell in payload.get("cells") or []
        for output in cell.get("outputs") or []
    )
    return inline_plot_count >= 3 and all(
        path.is_file() and path.stat().st_size > 0 for path in required
    )


if __name__ == "__main__":
    raise SystemExit(main())
