from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
from typing import Any

import anndata as ad
import numpy as np
import pandas as pd
from scipy import sparse

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
    "model": "celltypist-immune-all-low-v1",
    "mode": "best match",
    "p_thres": 0.5,
    "majority_voting": False,
    "min_prop": 0.0,
    "use_GPU": False,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fixed CellTypist 1.7.1 wrapper")
    parser.add_argument("--request-json", required=True)
    args = parser.parse_args(argv)
    request_path = Path(args.request_json)
    if request_path.name != "worker_request.json" or request_path.parent != Path("."):
        raise ValueError("wrapper request must be ./worker_request.json")
    request = json.loads(request_path.read_text(encoding="utf-8"))
    unknown = sorted(set(request) - ALLOWED_REQUEST_FIELDS)
    missing = sorted((ALLOWED_REQUEST_FIELDS - {"execution_seed"}) - set(request))
    if unknown or missing:
        raise ValueError(f"invalid worker request fields; unknown={unknown}, missing={missing}")
    parameters = validate_parameters(dict(request["parameters"]))
    manifest = _load_reference_manifest(parameters["model"])

    run_dir = Path.cwd().resolve()
    artifacts_dir = (run_dir / "artifacts").resolve()
    _require_within(artifacts_dir, run_dir)
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    input_path = Path(request["input_path"]).resolve(strict=True)
    if _sha256(input_path) != request["expected_input_hash"]:
        raise ValueError("input hash mismatch")
    model_path = Path(manifest.local_path).expanduser().resolve(strict=True)
    if _sha256(model_path) != manifest.sha256:
        raise ValueError("CellTypist model digest mismatch")
    if manifest.runtime_network_allowed:
        raise ValueError("runtime network must be disabled for annotation reference")

    adata = ad.read_h5ad(input_path)
    _validate_fixture(adata, request)
    _validate_expression(adata)
    if adata.n_obs != int(request["expected_cells"]):
        raise ValueError("expected cell count mismatch")

    import celltypist

    result = celltypist.annotate(
        adata,
        model=str(model_path),
        majority_voting=parameters["majority_voting"],
        mode=parameters["mode"],
        p_thres=parameters["p_thres"],
        min_prop=parameters["min_prop"],
    )
    labels = result.predicted_labels.copy()
    label_column = (
        "majority_voting"
        if parameters["majority_voting"] and "majority_voting" in labels
        else "predicted_labels"
    )
    predicted = labels[label_column].astype(str).to_numpy()
    scores = result.probability_matrix.copy()
    scores.index = adata.obs_names.astype(str)
    output = pd.DataFrame(
        {
            "cell_id": adata.obs_names.astype(str),
            "predicted_label": predicted,
            "unknown": predicted == "Unassigned",
        }
    )
    output.to_csv(artifacts_dir / "predicted_labels.tsv", sep="\t", index=False)
    scores.insert(0, "cell_id", scores.index)
    scores.to_csv(artifacts_dir / "annotation_scores.tsv", sep="\t", index=False)
    snapshot = {
        "parameters": parameters,
        "execution_seed": int(request.get("execution_seed", 0)),
        "reference_id": manifest.reference_id,
        "reference_digest": manifest.sha256,
    }
    metadata = {
        "tool_name": "CellTypist",
        "tool_version": importlib.metadata.version("celltypist"),
        "input_hash": request["expected_input_hash"],
        "cell_count": int(adata.n_obs),
        "cell_order_hash": _lines_hash(adata.obs_names.astype(str)),
        "reference_id": manifest.reference_id,
        "reference_digest": manifest.sha256,
        "runtime_network_used": False,
    }
    (artifacts_dir / "parameters.json").write_text(
        json.dumps(snapshot, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (artifacts_dir / "result_metadata.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(metadata, sort_keys=True))
    return 0


def validate_parameters(parameters: dict[str, Any]) -> dict[str, Any]:
    unknown = sorted(set(parameters) - set(DEFAULT_PARAMETERS))
    if unknown:
        raise ValueError("unknown CellTypist parameters: " + ", ".join(unknown))
    values = {**DEFAULT_PARAMETERS, **parameters}
    if values["mode"] not in {"best match", "prob match"}:
        raise ValueError("mode outside contract")
    for name in ("p_thres", "min_prop"):
        value = values[name]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{name} must be numeric")
        if not 0.0 <= float(value) <= 1.0:
            raise ValueError(f"{name} outside contract")
    for name in ("majority_voting", "use_GPU"):
        if not isinstance(values[name], bool):
            raise ValueError(f"{name} must be boolean")
    if values["use_GPU"]:
        raise ValueError("GPU execution is not qualified")
    if not isinstance(values["model"], str) or not values["model"]:
        raise ValueError("model must identify a registered local reference")
    return values


def _load_reference_manifest(reference_id: str) -> AnnotationReferenceManifest:
    manifest_path = os.environ.get("SCKG_CELLTYPIST_REFERENCE_MANIFEST")
    if not manifest_path:
        raise RuntimeError("CellTypist reference manifest was not supplied")
    manifest = AnnotationReferenceManifest.model_validate_json(
        Path(manifest_path).read_text(encoding="utf-8")
    )
    if manifest.reference_id != reference_id or manifest.tool_name != "CellTypist":
        raise ValueError("CellTypist reference selection mismatch")
    return manifest


def _validate_fixture(adata: ad.AnnData, request: dict[str, Any]) -> None:
    fixture = dict(adata.uns.get("sckg_fixture") or {})
    if fixture.get("fixture_id") != request["fixture_id"]:
        raise ValueError("fixture id mismatch")
    if not fixture.get("maintainer_approved") or not fixture.get("qualification_mode"):
        raise ValueError("wrapper requires a maintainer-approved qualification fixture")
    if fixture.get("user_data", True):
        raise ValueError("wrapper forbids user data")
    if request["purpose"] == "synthetic_qualification":
        if not fixture.get("synthetic"):
            raise ValueError("synthetic qualification requires synthetic data")
    elif request["purpose"] == "scientific_pilot":
        if request["accession"] != "Zheng68K" or not fixture.get("public_dataset"):
            raise ValueError("scientific pilot requires allowlisted Zheng68K")
    else:
        raise ValueError("unsupported annotation execution purpose")


def _validate_expression(adata: ad.AnnData) -> None:
    values = adata.X.data if sparse.issparse(adata.X) else np.asarray(adata.X).reshape(-1)
    values = np.asarray(values, dtype=float)
    if not values.size or not np.isfinite(values).all() or np.any(values < 0):
        raise ValueError("CellTypist input must be finite non-negative log1p expression")
    sample = adata.X[: min(256, adata.n_obs)]
    sample = sample.toarray() if sparse.issparse(sample) else np.asarray(sample)
    totals = np.expm1(sample).sum(axis=1)
    positive = totals[totals > 0]
    if not positive.size or not 8_000 <= float(np.median(positive)) <= 12_000:
        raise ValueError("CellTypist input must be log1p normalized to 10000 counts per cell")
    if not adata.var_names.is_unique:
        raise ValueError("duplicate gene identifiers are forbidden")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _lines_hash(values) -> str:
    return hashlib.sha256(
        ("\n".join(str(value) for value in values) + "\n").encode("utf-8")
    ).hexdigest()


def _require_within(path: Path, root: Path) -> None:
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError("wrapper output path escapes controlled run directory") from exc


if __name__ == "__main__":
    raise SystemExit(main())
