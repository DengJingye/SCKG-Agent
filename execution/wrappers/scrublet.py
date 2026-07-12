from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.metadata
import json
from pathlib import Path
from typing import Any

import anndata as ad
import numpy as np
from scipy import sparse


ALLOWED_REQUEST_FIELDS = {
    "accession",
    "expected_cells",
    "expected_input_hash",
    "fixture_id",
    "input_path",
    "parameters",
    "public_dataset",
    "purpose",
}

DEFAULT_PARAMETERS: dict[str, Any] = {
    "distance_metric": "euclidean",
    "expected_doublet_rate": 0.1,
    "log_transform": False,
    "mean_center": True,
    "min_cells": 3,
    "min_counts": 3,
    "min_gene_variability_pctl": 85.0,
    "n_prin_comps": 30,
    "normalize_variance": True,
    "random_state": 0,
    "sim_doublet_ratio": 2.0,
    "stdev_doublet_rate": 0.02,
    "svd_solver": "arpack",
    "synthetic_doublet_umi_subsampling": 1.0,
    "use_approx_neighbors": True,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fixed Scrublet 0.2.3 qualification wrapper")
    parser.add_argument("--request-json", required=True)
    args = parser.parse_args(argv)
    request_path = Path(args.request_json)
    if request_path.name != "worker_request.json" or request_path.parent != Path("."):
        raise ValueError("wrapper request must be ./worker_request.json")
    request = json.loads(request_path.read_text(encoding="utf-8"))
    unknown = sorted(set(request) - ALLOWED_REQUEST_FIELDS)
    missing = sorted(ALLOWED_REQUEST_FIELDS - set(request))
    if unknown or missing:
        raise ValueError(f"invalid worker request fields; unknown={unknown}, missing={missing}")

    run_dir = Path.cwd().resolve()
    artifacts_dir = (run_dir / "artifacts").resolve()
    _require_within(artifacts_dir, run_dir)
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    input_path = Path(request["input_path"]).resolve()
    if _sha256(input_path) != request["expected_input_hash"]:
        raise ValueError("input hash mismatch")

    adata = ad.read_h5ad(input_path)
    fixture = dict(adata.uns.get("sckg_fixture") or {})
    if fixture.get("fixture_id") != request["fixture_id"]:
        raise ValueError("fixture id mismatch")
    if not bool(fixture.get("maintainer_approved", False)):
        raise ValueError("wrapper requires maintainer-approved input")
    if not bool(fixture.get("qualification_mode", False)):
        raise ValueError("wrapper requires qualification mode")
    if bool(fixture.get("user_data", True)):
        raise ValueError("wrapper forbids user data")
    purpose = request["purpose"]
    if purpose == "synthetic_qualification":
        if not bool(fixture.get("synthetic", False)):
            raise ValueError("synthetic qualification requires synthetic fixture")
    elif purpose == "scientific_pilot":
        if bool(fixture.get("synthetic", True)):
            raise ValueError("scientific pilot requires real public dataset")
        if not bool(fixture.get("public_dataset", False)):
            raise ValueError("scientific pilot requires public dataset")
        if request["accession"] != "GSE108313" or fixture.get("accession") != "GSE108313":
            raise ValueError("scientific dataset is not allowlisted")
    else:
        raise ValueError("unsupported execution purpose")
    if adata.n_obs != int(request["expected_cells"]):
        raise ValueError("expected cell count mismatch")
    _validate_raw_counts(adata.X)
    parameters = validate_parameters(dict(request["parameters"]))

    import scrublet

    scrub = scrublet.Scrublet(
        adata.X,
        sim_doublet_ratio=parameters["sim_doublet_ratio"],
        expected_doublet_rate=parameters["expected_doublet_rate"],
        stdev_doublet_rate=parameters["stdev_doublet_rate"],
        random_state=parameters["random_state"],
    )
    scores, predicted = scrub.scrub_doublets(
        synthetic_doublet_umi_subsampling=parameters[
            "synthetic_doublet_umi_subsampling"
        ],
        use_approx_neighbors=parameters["use_approx_neighbors"],
        distance_metric=parameters["distance_metric"],
        min_counts=parameters["min_counts"],
        min_cells=parameters["min_cells"],
        min_gene_variability_pctl=parameters["min_gene_variability_pctl"],
        log_transform=parameters["log_transform"],
        mean_center=parameters["mean_center"],
        normalize_variance=parameters["normalize_variance"],
        n_prin_comps=parameters["n_prin_comps"],
        svd_solver=parameters["svd_solver"],
        verbose=False,
    )
    scores = np.asarray(scores, dtype=float)
    predicted = np.asarray(predicted)
    if scores.shape != (adata.n_obs,) or predicted.shape != (adata.n_obs,):
        raise ValueError("Scrublet output length mismatch")

    result_path = artifacts_dir / "doublet_results.tsv"
    with result_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            delimiter="\t",
            fieldnames=[
                "obs_id",
                "doublet_score",
                "predicted_doublet",
                "ground_truth_doublet",
            ],
        )
        writer.writeheader()
        ground_truth = adata.obs["ground_truth_doublet"].astype(bool).to_numpy()
        for obs_id, score, label, truth in zip(
            adata.obs_names,
            scores,
            predicted,
            ground_truth,
        ):
            writer.writerow(
                {
                    "obs_id": str(obs_id),
                    "doublet_score": repr(float(score)),
                    "predicted_doublet": "true" if bool(label) else "false",
                    "ground_truth_doublet": "true" if bool(truth) else "false",
                }
            )

    parameter_path = artifacts_dir / "parameters.json"
    parameter_path.write_text(
        json.dumps(parameters, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    metadata = {
        "fixture_id": request["fixture_id"],
        "input_hash": request["expected_input_hash"],
        "n_cells": adata.n_obs,
        "n_genes": adata.n_vars,
        "output_fields": [
            "obs_id",
            "doublet_score",
            "predicted_doublet",
            "ground_truth_doublet",
        ],
        "qualification_mode": True,
        "scrublet_actually_executed": True,
        "scrublet_version": importlib.metadata.version("scrublet"),
        "execution_purpose": purpose,
        "public_dataset": bool(request["public_dataset"]),
        "accession": request["accession"],
        "synthetic_fixture": bool(fixture.get("synthetic", False)),
        "user_data_used": False,
    }
    metadata_path = artifacts_dir / "result_metadata.json"
    metadata_path.write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(metadata, sort_keys=True))
    return 0


def validate_parameters(parameters: dict[str, Any]) -> dict[str, Any]:
    unknown = sorted(set(parameters) - set(DEFAULT_PARAMETERS))
    if unknown:
        raise ValueError("unknown Scrublet parameters: " + ", ".join(unknown))
    merged = dict(DEFAULT_PARAMETERS)
    merged.update(parameters)
    _number(merged, "expected_doublet_rate", 0.001, 0.25)
    _number(merged, "stdev_doublet_rate", 0.001, 0.2)
    _number(merged, "sim_doublet_ratio", 1.0, 10.0)
    _number(merged, "synthetic_doublet_umi_subsampling", 0.1, 1.0)
    _integer(merged, "random_state", 0, 2_147_483_647)
    _integer(merged, "min_counts", 1, 20)
    _integer(merged, "min_cells", 1, 20)
    _number(merged, "min_gene_variability_pctl", 0.0, 100.0)
    _integer(merged, "n_prin_comps", 2, 100)
    for name in ("log_transform", "mean_center", "normalize_variance", "use_approx_neighbors"):
        if not isinstance(merged[name], bool):
            raise ValueError(f"{name} must be boolean")
    if merged["distance_metric"] not in {"euclidean", "cosine"}:
        raise ValueError("distance_metric is not allowlisted")
    if merged["svd_solver"] != "arpack":
        raise ValueError("svd_solver is not allowlisted")
    return merged


def _validate_raw_counts(matrix: Any) -> None:
    values = np.asarray(matrix.data if sparse.issparse(matrix) else matrix).reshape(-1)
    if values.size == 0:
        raise ValueError("empty count matrix")
    if not np.all(np.isfinite(values)):
        raise ValueError("count matrix contains non-finite values")
    if np.any(values < 0):
        raise ValueError("count matrix contains negative values")
    if not np.allclose(values, np.rint(values), atol=1e-8):
        raise ValueError("count matrix is not integer-valued")


def _number(values: dict[str, Any], name: str, minimum: float, maximum: float) -> None:
    value = values[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be numeric")
    if not minimum <= float(value) <= maximum:
        raise ValueError(f"{name} outside allowed range")


def _integer(values: dict[str, Any], name: str, minimum: int, maximum: int) -> None:
    value = values[name]
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be integer")
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} outside allowed range")


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
        raise ValueError("artifact output escapes run directory") from exc


if __name__ == "__main__":
    raise SystemExit(main())
