from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any


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
    "dbr": 0.1,
    "clusters": False,
    "n_cores": 1,
    "random_state": 0,
}
DEFAULT_RSCRIPT = Path("/opt/anaconda3/envs/scDblFinder-R/bin/Rscript")
R_WRAPPER = Path(__file__).with_suffix(".R").resolve()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Fixed scDblFinder qualification adapter"
    )
    parser.add_argument("--request-json", required=True)
    args = parser.parse_args(argv)
    request_path = Path(args.request_json)
    if request_path.name != "worker_request.json" or request_path.parent != Path("."):
        raise ValueError("adapter request must be ./worker_request.json")
    request = json.loads(request_path.read_text(encoding="utf-8"))
    unknown = sorted(set(request) - ALLOWED_REQUEST_FIELDS)
    missing = sorted(ALLOWED_REQUEST_FIELDS - set(request))
    if unknown or missing:
        raise ValueError(
            f"invalid worker request fields; unknown={unknown}, missing={missing}"
        )
    if request["purpose"] != "synthetic_qualification":
        raise ValueError("Phase 5A scDblFinder adapter only permits synthetic qualification")
    if bool(request["public_dataset"]):
        raise ValueError("Phase 5A scDblFinder adapter forbids scientific or user datasets")

    run_dir = Path.cwd().resolve()
    input_path = Path(request["input_path"]).resolve(strict=True)
    if _sha256(input_path) != request["expected_input_hash"]:
        raise ValueError("input hash mismatch")
    parameters = validate_parameters(dict(request["parameters"]))
    rscript = DEFAULT_RSCRIPT.resolve()
    if not rscript.is_file():
        raise RuntimeError(f"Rscript unavailable at registered path: {rscript}")
    if not R_WRAPPER.is_file():
        raise RuntimeError("fixed scDblFinder R wrapper is missing")

    import anndata as ad
    import numpy as np
    from scipy import sparse
    from scipy.io import mmwrite

    adata = ad.read_h5ad(input_path)
    fixture = dict(adata.uns.get("sckg_fixture") or {})
    if fixture.get("fixture_id") != request["fixture_id"]:
        raise ValueError("fixture id mismatch")
    if not bool(fixture.get("maintainer_approved", False)):
        raise ValueError("adapter requires maintainer-approved fixture")
    if not bool(fixture.get("qualification_mode", False)):
        raise ValueError("adapter requires qualification mode")
    if not bool(fixture.get("synthetic", False)) or bool(
        fixture.get("user_data", True)
    ):
        raise ValueError("adapter only accepts synthetic non-user qualification data")
    if adata.n_obs != int(request["expected_cells"]):
        raise ValueError("expected cell count mismatch")
    matrix = adata.X.tocsr() if sparse.issparse(adata.X) else sparse.csr_matrix(adata.X)
    values = np.asarray(matrix.data, dtype=float)
    if (
        values.size == 0
        or not np.all(np.isfinite(values))
        or np.any(values < 0)
        or not np.allclose(values, np.rint(values), atol=1e-8)
    ):
        raise ValueError("input matrix must contain finite non-negative integer counts")

    r_input = (run_dir / "r_input").resolve()
    artifacts = (run_dir / "artifacts").resolve()
    _require_within(r_input, run_dir)
    _require_within(artifacts, run_dir)
    r_input.mkdir(exist_ok=True)
    artifacts.mkdir(exist_ok=True)
    matrix_path = r_input / "counts.mtx"
    cells_path = r_input / "cell_ids.tsv"
    truth_path = r_input / "ground_truth.tsv"
    mmwrite(matrix_path, matrix)
    cells_path.write_text(
        "\n".join(str(item) for item in adata.obs_names) + "\n",
        encoding="utf-8",
    )
    truth = adata.obs["ground_truth_doublet"].astype(bool).to_numpy()
    truth_path.write_text(
        "\n".join("true" if bool(item) else "false" for item in truth) + "\n",
        encoding="utf-8",
    )
    r_request = {
        "artifacts_dir": "artifacts",
        "cell_ids_path": "r_input/cell_ids.tsv",
        "counts_path": "r_input/counts.mtx",
        "expected_cells": adata.n_obs,
        "fixture_id": request["fixture_id"],
        "input_hash": request["expected_input_hash"],
        "parameters": parameters,
        "purpose": request["purpose"],
        "user_data_used": False,
    }
    r_request_path = run_dir / "r_request.json"
    r_request_path.write_text(
        json.dumps(r_request, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    command = build_rscript_argv(r_request_path.name, rscript_path=rscript)
    completed = subprocess.run(
        command,
        cwd=run_dir,
        stdin=subprocess.DEVNULL,
        shell=False,
        check=False,
        text=True,
    )
    return int(completed.returncode)


def build_rscript_argv(
    request_filename: str, *, rscript_path: Path = DEFAULT_RSCRIPT
) -> list[str]:
    if request_filename != "r_request.json":
        raise ValueError("R wrapper request filename is fixed")
    if not rscript_path.is_absolute():
        raise ValueError("Rscript path must be absolute")
    return [str(rscript_path), str(R_WRAPPER), request_filename]


def validate_parameters(parameters: dict[str, Any]) -> dict[str, Any]:
    unknown = sorted(set(parameters) - set(DEFAULT_PARAMETERS))
    if unknown:
        raise ValueError("unknown scDblFinder parameters: " + ", ".join(unknown))
    merged = {**DEFAULT_PARAMETERS, **parameters}
    dbr = merged["dbr"]
    if isinstance(dbr, bool) or not isinstance(dbr, (int, float)):
        raise ValueError("dbr must be numeric")
    if not 0.001 <= float(dbr) <= 0.5:
        raise ValueError("dbr outside allowed range")
    if merged["clusters"] is not False:
        raise ValueError("clusters must remain false in Phase 5A")
    for name, minimum, maximum in (
        ("n_cores", 1, 4),
        ("random_state", 0, 2_147_483_647),
    ):
        value = merged[name]
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{name} must be integer")
        if not minimum <= value <= maximum:
            raise ValueError(f"{name} outside allowed range")
    return merged


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
