from __future__ import annotations

import json
import sys

import harmonypy
import numpy as np

from execution.wrappers.integration_common import (
    load_embedding_input,
    load_request,
    write_outputs,
)


ALLOWED_PARAMETERS = {
    "theta",
    "sigma",
    "max_iter_harmony",
    "max_iter_kmeans",
    "epsilon_harmony",
    "ncores",
}


def main(argv: list[str] | None = None) -> int:
    request, _, artifacts_dir = load_request(argv)
    parameters = dict(request["parameters"])
    unknown = sorted(set(parameters) - ALLOWED_PARAMETERS)
    if unknown:
        raise ValueError("unknown Harmony parameters: " + ", ".join(unknown))
    adata, embedding = load_embedding_input(request)
    result = harmonypy.run_harmony(
        embedding,
        adata.obs,
        "batch",
        theta=float(parameters["theta"]),
        sigma=float(parameters["sigma"]),
        max_iter_harmony=int(parameters["max_iter_harmony"]),
        max_iter_kmeans=int(parameters["max_iter_kmeans"]),
        epsilon_harmony=float(parameters["epsilon_harmony"]),
        random_state=int(request["execution_seed"]),
        ncores=int(parameters["ncores"]),
        verbose=False,
    )
    corrected = np.asarray(result.Z_corr, dtype=np.float64)
    metadata = write_outputs(
        artifacts_dir=artifacts_dir,
        adata=adata,
        embedding=corrected,
        request=request,
        tool_name="Harmony",
        tool_distribution="harmonypy",
        tool_version="2.0.0",
    )
    print(json.dumps(metadata, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
