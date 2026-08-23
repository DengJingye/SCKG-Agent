from __future__ import annotations

import hashlib
import json
from pathlib import Path

import anndata as ad
import numpy as np
import pandas as pd
from scipy import sparse

from core.execution_models import AnnotationProbeSpec, AnnotationReferenceManifest


CELL_TYPES = ("B_cell", "T_cell", "NK_cell", "Monocyte")
MARKER_GENES = {
    "B_cell": ("MS4A1", "CD79A", "CD37", "HLA-DRA"),
    "T_cell": ("CD3D", "CD3E", "TRBC1", "IL7R"),
    "NK_cell": ("NKG7", "GNLY", "KLRD1", "PRF1"),
    "Monocyte": ("LYZ", "S100A8", "S100A9", "CTSS"),
}


class AnnotationProbeBuilder:
    """Build deterministic marker-expression probes with isolated split hashes."""

    def build(
        self,
        *,
        output_dir: Path,
        split_role: str,
        random_seed: int,
        reference: AnnotationReferenceManifest,
        cells_per_type: int = 30,
        n_genes: int = 120,
        fixture_id: str = "phase27_annotation_synthetic",
        allowed_output_root: Path | None = None,
    ) -> AnnotationProbeSpec:
        if split_role not in {"development", "evaluation"}:
            raise ValueError("annotation probe split must be development or evaluation")
        if cells_per_type < 8 or n_genes < 32:
            raise ValueError("annotation probe is too small")
        if reference.species != "human" or reference.gene_identifier_type != "gene_symbol":
            raise ValueError("synthetic annotation probe requires a human gene-symbol reference")
        output_dir = Path(output_dir).resolve()
        root = Path(allowed_output_root or output_dir).resolve()
        _require_within(output_dir, root)
        output_dir.mkdir(parents=True, exist_ok=False)

        marker_values = [gene for values in MARKER_GENES.values() for gene in values]
        background = [f"GENE{index:04d}" for index in range(n_genes - len(marker_values))]
        genes = marker_values + background
        gene_index = {gene: index for index, gene in enumerate(genes)}
        rng = np.random.default_rng(random_seed)
        counts: list[np.ndarray] = []
        labels: list[str] = []
        cell_ids: list[str] = []
        for type_index, cell_type in enumerate(CELL_TYPES):
            matrix = rng.poisson(1.0, size=(cells_per_type, n_genes)).astype(np.int32)
            for marker in MARKER_GENES[cell_type]:
                matrix[:, gene_index[marker]] += rng.poisson(
                    12.0,
                    size=cells_per_type,
                )
            counts.append(matrix)
            labels.extend([cell_type] * cells_per_type)
            cell_ids.extend(
                f"{split_role}-{type_index}-{index:04d}"
                for index in range(cells_per_type)
            )
        raw = sparse.csr_matrix(np.vstack(counts))
        totals = np.asarray(raw.sum(axis=1)).reshape(-1)
        normalized = raw.multiply((10_000.0 / totals)[:, None])
        log1p = normalized.copy()
        log1p.data = np.log1p(log1p.data)
        obs = pd.DataFrame(
            {"ground_truth_cell_type": labels},
            index=pd.Index(cell_ids, name="cell_id"),
        )
        var = pd.DataFrame(index=pd.Index(genes, name="gene_symbol"))
        adata = ad.AnnData(X=log1p.tocsr(), obs=obs, var=var)
        adata.layers["counts"] = raw
        adata.uns["sckg_fixture"] = {
            "fixture_id": fixture_id,
            "synthetic": True,
            "maintainer_approved": True,
            "qualification_mode": True,
            "user_data": False,
            "public_dataset": False,
            "task": "cell_type_annotation",
            "split_role": split_role,
            "random_seed": random_seed,
            "reference_id": reference.reference_id,
            "reference_digest": reference.sha256,
        }
        artifact_path = output_dir / "annotation_probe.h5ad"
        adata.write_h5ad(artifact_path)
        probe_hash = _sha256(artifact_path)
        cell_hash = _text_hash(cell_ids)
        label_hash = _text_hash(
            [f"{cell_id}\t{label}" for cell_id, label in zip(cell_ids, labels)]
        )
        source_hash = _text_hash(
            [
                fixture_id,
                split_role,
                str(random_seed),
                str(cells_per_type),
                str(n_genes),
                reference.sha256,
            ]
        )
        metadata_path = output_dir / "probe_manifest.json"
        spec = AnnotationProbeSpec(
            probe_id=f"annotation-{split_role}-{random_seed}",
            profile_id=f"annotation-profile-{probe_hash[:16]}",
            source_fixture_id=fixture_id,
            split_role=split_role,
            random_seed=random_seed,
            n_cells=adata.n_obs,
            n_genes=adata.n_vars,
            n_cell_types=len(CELL_TYPES),
            expression_state="log1p_normalized",
            gene_identifier_type="gene_symbol",
            species="human",
            reference_id=reference.reference_id,
            reference_digest=reference.sha256,
            selected_cell_hash=cell_hash,
            ground_truth_hash=label_hash,
            probe_artifact_path=str(artifact_path),
            probe_hash=probe_hash,
            metadata_path=str(metadata_path),
            source_input_hash=source_hash,
        )
        metadata_path.write_text(
            json.dumps(spec.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return spec


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _text_hash(values: list[str]) -> str:
    return hashlib.sha256(("\n".join(values) + "\n").encode("utf-8")).hexdigest()


def _require_within(path: Path, root: Path) -> None:
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError("annotation probe output escapes controlled root") from exc
