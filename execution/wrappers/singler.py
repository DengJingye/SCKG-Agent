from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any

import anndata as ad
import numpy as np
from scipy import sparse
from scipy.io import mmwrite

from core.execution_models import AnnotationReferenceManifest


ALLOWED_REQUEST_FIELDS = {
    "accession",
    "expected_cells",
    "expected_input_hash",
    "execution_seed",
    "fixture_id",
    "input_path",
    "parameters",
    "public_dataset",
    "purpose",
}
DEFAULT_PARAMETERS: dict[str, Any] = {
    "reference_id": "singler-immune-reference-v1",
    "label_field": "label.main",
    "assay_type_test": "logcounts",
    "assay_type_reference": "logcounts",
    "de_method": "classic",
    "fine_tune": True,
    "prune": True,
}
R_WRAPPER = Path(__file__).with_suffix(".R").resolve()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fixed SingleR 2.14.0 adapter")
    parser.add_argument("--request-json", required=True)
    args = parser.parse_args(argv)
    request_path = Path(args.request_json)
    if request_path.name != "worker_request.json" or request_path.parent != Path("."):
        raise ValueError("adapter request must be ./worker_request.json")
    request = json.loads(request_path.read_text(encoding="utf-8"))
    unknown = sorted(set(request) - ALLOWED_REQUEST_FIELDS)
    missing = sorted((ALLOWED_REQUEST_FIELDS - {"execution_seed"}) - set(request))
    if unknown or missing:
        raise ValueError(f"invalid worker request fields; unknown={unknown}, missing={missing}")
    parameters = validate_parameters(dict(request["parameters"]))
    manifest = _load_reference_manifest(parameters["reference_id"])
    reference_path = Path(manifest.local_path).expanduser().resolve(strict=True)
    if _sha256(reference_path) != manifest.sha256:
        raise ValueError("SingleR reference digest mismatch")

    run_dir = Path.cwd().resolve()
    input_path = Path(request["input_path"]).resolve(strict=True)
    if _sha256(input_path) != request["expected_input_hash"]:
        raise ValueError("input hash mismatch")
    adata = ad.read_h5ad(input_path)
    _validate_fixture(adata, request)
    if adata.n_obs != int(request["expected_cells"]):
        raise ValueError("expected cell count mismatch")
    if not adata.var_names.is_unique:
        raise ValueError("duplicate gene identifiers are forbidden")
    values = adata.X.data if sparse.issparse(adata.X) else np.asarray(adata.X).reshape(-1)
    if not np.asarray(values).size or not np.isfinite(values).all():
        raise ValueError("SingleR input expression must be finite")

    r_input = (run_dir / "r_input").resolve()
    artifacts = (run_dir / "artifacts").resolve()
    _require_within(r_input, run_dir)
    _require_within(artifacts, run_dir)
    r_input.mkdir(exist_ok=True)
    artifacts.mkdir(exist_ok=True)
    matrix = adata.X.tocsr() if sparse.issparse(adata.X) else sparse.csr_matrix(adata.X)
    mmwrite(r_input / "expression.mtx", matrix)
    (r_input / "cell_ids.tsv").write_text(
        "\n".join(adata.obs_names.astype(str)) + "\n",
        encoding="utf-8",
    )
    (r_input / "gene_ids.tsv").write_text(
        "\n".join(adata.var_names.astype(str)) + "\n",
        encoding="utf-8",
    )
    if "ground_truth_cell_type" in adata.obs:
        (r_input / "ground_truth.tsv").write_text(
            "\n".join(adata.obs["ground_truth_cell_type"].astype(str)) + "\n",
            encoding="utf-8",
        )
    r_request = {
        "artifacts_dir": "artifacts",
        "cell_ids_path": "r_input/cell_ids.tsv",
        "expression_path": "r_input/expression.mtx",
        "gene_ids_path": "r_input/gene_ids.tsv",
        "expected_cells": int(adata.n_obs),
        "input_hash": request["expected_input_hash"],
        "parameters": parameters,
        "reference_path": str(reference_path),
        "reference_id": manifest.reference_id,
        "reference_digest": manifest.sha256,
    }
    (run_dir / "r_request.json").write_text(
        json.dumps(r_request, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    rscript = Path(os.environ.get("SCKG_SINGLER_RSCRIPT", "")).expanduser()
    if not rscript.is_absolute() or not rscript.is_file():
        raise RuntimeError("registered SingleR Rscript is unavailable")
    completed = subprocess.run(
        [str(rscript), str(R_WRAPPER), "r_request.json"],
        cwd=run_dir,
        stdin=subprocess.DEVNULL,
        shell=False,
        check=False,
        text=True,
    )
    return int(completed.returncode)


def validate_parameters(parameters: dict[str, Any]) -> dict[str, Any]:
    unknown = sorted(set(parameters) - set(DEFAULT_PARAMETERS))
    if unknown:
        raise ValueError("unknown SingleR parameters: " + ", ".join(unknown))
    values = {**DEFAULT_PARAMETERS, **parameters}
    if values["de_method"] not in {"classic", "wilcox"}:
        raise ValueError("de_method outside contract")
    for name in ("fine_tune", "prune"):
        if not isinstance(values[name], bool):
            raise ValueError(f"{name} must be boolean")
    for name in (
        "reference_id",
        "label_field",
        "assay_type_test",
        "assay_type_reference",
    ):
        if not isinstance(values[name], str) or not values[name]:
            raise ValueError(f"{name} must be a non-empty string")
    return values


def _load_reference_manifest(reference_id: str) -> AnnotationReferenceManifest:
    path_text = os.environ.get("SCKG_SINGLER_REFERENCE_MANIFEST")
    if not path_text:
        raise RuntimeError("SingleR reference manifest was not supplied")
    manifest = AnnotationReferenceManifest.model_validate_json(
        Path(path_text).read_text(encoding="utf-8")
    )
    if manifest.reference_id != reference_id or manifest.tool_name != "SingleR":
        raise ValueError("SingleR reference selection mismatch")
    if manifest.runtime_network_allowed:
        raise ValueError("runtime network must be disabled for annotation reference")
    return manifest


def _validate_fixture(adata: ad.AnnData, request: dict[str, Any]) -> None:
    fixture = dict(adata.uns.get("sckg_fixture") or {})
    if fixture.get("fixture_id") != request["fixture_id"]:
        raise ValueError("fixture id mismatch")
    if not fixture.get("maintainer_approved") or not fixture.get("qualification_mode"):
        raise ValueError("adapter requires a maintainer-approved qualification fixture")
    if fixture.get("user_data", True):
        raise ValueError("adapter forbids user data")
    if request["purpose"] == "synthetic_qualification":
        if not fixture.get("synthetic"):
            raise ValueError("synthetic qualification requires synthetic data")
    elif request["purpose"] == "scientific_pilot":
        if request["accession"] != "Zheng68K" or not fixture.get("public_dataset"):
            raise ValueError("scientific pilot requires allowlisted Zheng68K")
    else:
        raise ValueError("unsupported annotation execution purpose")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _require_within(path: Path, root: Path) -> None:
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError("adapter path escapes controlled run directory") from exc


if __name__ == "__main__":
    raise SystemExit(main())
