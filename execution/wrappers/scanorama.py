from __future__ import annotations

import json
import sys

import numpy as np
import scanorama

from execution.wrappers.integration_common import (
    load_embedding_input,
    load_request,
    write_outputs,
)


ALLOWED_PARAMETERS = {"knn", "sigma", "approx", "alpha", "batch_size"}


def main(argv: list[str] | None = None) -> int:
    request, _, artifacts_dir = load_request(argv)
    parameters = dict(request["parameters"])
    unknown = sorted(set(parameters) - ALLOWED_PARAMETERS)
    if unknown:
        raise ValueError("unknown Scanorama parameters: " + ", ".join(unknown))
    adata, embedding = load_embedding_input(request)
    np.random.seed(int(request["execution_seed"]))

    batch_values = adata.obs["batch"].astype(str).to_numpy()
    batch_names = sorted(set(batch_values.tolist()))
    grouped_indices = [np.flatnonzero(batch_values == name) for name in batch_names]
    grouped_embeddings = [embedding[index].copy() for index in grouped_indices]
    corrected_groups = scanorama.assemble(
        grouped_embeddings,
        verbose=0,
        knn=int(parameters["knn"]),
        sigma=float(parameters["sigma"]),
        approx=bool(parameters["approx"]),
        alpha=float(parameters["alpha"]),
        batch_size=int(parameters["batch_size"]),
        ds_names=batch_names,
    )
    corrected = np.empty_like(embedding)
    for indices, values in zip(grouped_indices, corrected_groups):
        corrected[indices] = np.asarray(values, dtype=np.float64)
    metadata = write_outputs(
        artifacts_dir=artifacts_dir,
        adata=adata,
        embedding=corrected,
        request=request,
        tool_name="Scanorama",
        tool_distribution="scanorama",
        tool_version="1.7.4",
    )
    print(json.dumps(metadata, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
