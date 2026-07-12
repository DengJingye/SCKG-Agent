from __future__ import annotations

import hashlib
import json
from pathlib import Path

import anndata as ad
import numpy as np
import pandas as pd
from scipy import sparse

from core.execution_models import ProbeSpec
from engine.data_profiler import AnnDataProfiler


PROBE_SEED = 20260711


class ProbeBuilder:
    """Build a synthetic engineering probe from an allowlisted raw-count fixture."""

    def build(
        self,
        *,
        source_path: Path,
        output_dir: Path,
        profile_id: str,
        fixture_id: str,
        max_cells: int = 40,
        synthetic_doublet_ratio: float = 0.25,
        random_seed: int = PROBE_SEED,
        split_role: str = "engineering",
        pairing_strategy: str = "random",
        cluster_key: str | None = None,
        allowed_output_root: Path | None = None,
    ) -> ProbeSpec:
        source_path = Path(source_path).resolve()
        output_dir = Path(output_dir).resolve()
        if allowed_output_root is not None:
            _require_within(output_dir, Path(allowed_output_root).resolve(), "probe output")
        if max_cells <= 1:
            raise ValueError("max_cells must be greater than one")
        if not 0.0 < synthetic_doublet_ratio <= 1.0:
            raise ValueError("synthetic_doublet_ratio must be in (0, 1]")
        if split_role not in {"engineering", "development", "evaluation"}:
            raise ValueError("unsupported probe split role")
        if pairing_strategy not in {
            "random",
            "within_cluster",
            "between_cluster",
            "mixed",
        }:
            raise ValueError("unsupported pairing strategy")

        source_hash_before = _sha256(source_path)
        profile = AnnDataProfiler().profile(source_path)
        if profile.is_blocked or profile.selected_count_source is None:
            raise ValueError("source fixture does not have a validated raw count matrix")
        adata = ad.read_h5ad(source_path)
        fixture_meta = dict(adata.uns.get("sckg_fixture") or {})
        if fixture_meta.get("fixture_id") != fixture_id:
            raise ValueError("fixture id does not match source metadata")
        if not bool(fixture_meta.get("synthetic", False)):
            raise ValueError("probe source must be synthetic")
        if not bool(fixture_meta.get("maintainer_approved", False)):
            raise ValueError("probe source must be maintainer approved")
        if bool(fixture_meta.get("user_data", True)):
            raise ValueError("user data is forbidden in qualification probes")

        matrix = _matrix_for_source(adata, profile.selected_count_source)
        rng = np.random.default_rng(random_seed)
        n_source = min(max_cells, adata.n_obs)
        selected_indices = np.sort(rng.choice(adata.n_obs, size=n_source, replace=False))
        selected = matrix[selected_indices]
        if not sparse.issparse(selected):
            selected = sparse.csr_matrix(selected)
        else:
            selected = selected.tocsr()

        n_doublets = max(1, int(round(n_source * synthetic_doublet_ratio)))
        selected_clusters = None
        if pairing_strategy != "random":
            if not cluster_key or cluster_key not in adata.obs:
                raise ValueError("cluster_key is required for cluster-aware pairing")
            selected_clusters = adata.obs.iloc[selected_indices][cluster_key].astype(str).to_numpy()
        pairs, pairing_classes = _build_pairs(
            rng=rng,
            n_source=n_source,
            n_doublets=n_doublets,
            pairing_strategy=pairing_strategy,
            clusters=selected_clusters,
        )
        synthetic = selected[pairs[:, 0]] + selected[pairs[:, 1]]
        probe_matrix = sparse.vstack([selected, synthetic], format="csr")

        selected_names = [str(adata.obs_names[index]) for index in selected_indices]
        singlet_obs = pd.DataFrame(
            {
                "ground_truth_doublet": False,
                "source_obs_id_a": selected_names,
                "source_obs_id_b": "",
            },
            index=[f"probe_singlet_{index:04d}" for index in range(n_source)],
        )
        doublet_obs = pd.DataFrame(
            {
                "ground_truth_doublet": True,
                "source_obs_id_a": [selected_names[left] for left in pairs[:, 0]],
                "source_obs_id_b": [selected_names[right] for right in pairs[:, 1]],
                "synthetic_pairing_class": pairing_classes,
            },
            index=[f"probe_doublet_{index:04d}" for index in range(n_doublets)],
        )
        probe_obs = pd.concat([singlet_obs, doublet_obs], axis=0)

        probe = ad.AnnData(X=probe_matrix, obs=probe_obs, var=adata.var.copy())
        probe.uns["sckg_fixture"] = {
            "fixture_id": fixture_id,
            "synthetic": True,
            "maintainer_approved": True,
            "qualification_mode": True,
            "user_data": False,
            "generation_method": "count_sum",
            "generation_version": "count-sum-v1",
            "random_seed": random_seed,
            "split_role": split_role,
            "pairing_strategy": pairing_strategy,
            "cluster_key": cluster_key or "",
        }
        output_dir.mkdir(parents=True, exist_ok=True)
        probe_path = output_dir / "qualification_probe.h5ad"
        metadata_path = output_dir / "probe_spec.json"
        probe.write_h5ad(probe_path)
        probe_hash = _sha256(probe_path)
        selected_hash = hashlib.sha256(
            json.dumps(
                {"indices": selected_indices.tolist(), "obs_names": selected_names},
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        ground_truth_hash = hashlib.sha256(
            json.dumps(
                {
                    "split_role": split_role,
                    "pairing_strategy": pairing_strategy,
                    "pairs": pairs.tolist(),
                    "pairing_classes": pairing_classes,
                    "source_obs_names": selected_names,
                },
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        source_hash_after = _sha256(source_path)
        spec = ProbeSpec(
            probe_id=f"probe_{probe_hash[:16]}",
            profile_id=profile_id,
            source_fixture_id=fixture_id,
            max_cells=max_cells,
            random_seed=random_seed,
            selected_obs_indices_hash=selected_hash,
            synthetic_doublet_ratio=synthetic_doublet_ratio,
            pairing_strategy=pairing_strategy,
            split_role=split_role,
            cluster_key=cluster_key,
            ground_truth_hash=ground_truth_hash,
            n_source_cells=n_source,
            n_synthetic_doublets=n_doublets,
            n_probe_cells=n_source + n_doublets,
            probe_artifact_path=str(probe_path),
            probe_hash=probe_hash,
            metadata_path=str(metadata_path),
            source_input_hash=source_hash_before,
            source_unchanged=source_hash_before == source_hash_after,
        )
        metadata_path.write_text(
            json.dumps(spec.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return spec


def _build_pairs(
    *,
    rng: np.random.Generator,
    n_source: int,
    n_doublets: int,
    pairing_strategy: str,
    clusters: np.ndarray | None,
) -> tuple[np.ndarray, list[str]]:
    if pairing_strategy == "random":
        pairs = [rng.choice(n_source, size=2, replace=False) for _ in range(n_doublets)]
        return np.asarray(pairs, dtype=np.int64), ["random"] * n_doublets

    assert clusters is not None
    cluster_values = sorted(set(clusters.tolist()))
    by_cluster = {
        cluster: np.flatnonzero(clusters == cluster) for cluster in cluster_values
    }
    within_clusters = [cluster for cluster, indices in by_cluster.items() if len(indices) >= 2]
    if pairing_strategy in {"within_cluster", "mixed"} and not within_clusters:
        raise ValueError("within-cluster pairing requires a cluster with at least two cells")
    if pairing_strategy in {"between_cluster", "mixed"} and len(cluster_values) < 2:
        raise ValueError("between-cluster pairing requires at least two clusters")

    pairs: list[np.ndarray] = []
    classes: list[str] = []
    for index in range(n_doublets):
        use_within = pairing_strategy == "within_cluster" or (
            pairing_strategy == "mixed" and index % 2 == 0
        )
        if use_within:
            cluster = str(rng.choice(within_clusters))
            pair = rng.choice(by_cluster[cluster], size=2, replace=False)
            classes.append("homotypic")
        else:
            chosen_clusters = rng.choice(cluster_values, size=2, replace=False)
            pair = np.asarray(
                [
                    rng.choice(by_cluster[str(chosen_clusters[0])]),
                    rng.choice(by_cluster[str(chosen_clusters[1])]),
                ]
            )
            classes.append("heterotypic")
        pairs.append(pair)
    return np.asarray(pairs, dtype=np.int64), classes


def _matrix_for_source(adata: ad.AnnData, matrix_id: str):
    if matrix_id == "X":
        return adata.X
    if matrix_id == "raw.X" and adata.raw is not None:
        return adata.raw.X
    if matrix_id.startswith("layers/"):
        return adata.layers[matrix_id.split("/", 1)[1]]
    raise ValueError(f"unsupported count source: {matrix_id}")


def _require_within(path: Path, root: Path, label: str) -> None:
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"{label} escapes allowed root") from exc


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
