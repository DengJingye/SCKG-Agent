from __future__ import annotations

import hashlib
import json
from pathlib import Path

import anndata as ad
import numpy as np
from scipy import sparse

from core.execution_models import (
    AnnotationDatasetManifest,
    AnnotationLabelMapping,
    AnnotationReferenceManifest,
    AnnotationSplitArtifact,
    AnnotationSplitManifest,
)


ZHENG68K_ACCESSION = "Zheng68K"
DEFAULT_SPLIT_SEED = 68_017


class Zheng68KDatasetService:
    """Validate and split a frozen Zheng68K AnnData without changing gold labels."""

    def validate(
        self,
        *,
        dataset_path: Path,
        label_key: str,
        source_url: str,
        license_name: str,
    ) -> AnnotationDatasetManifest:
        path = Path(dataset_path).expanduser().resolve(strict=True)
        if path.suffix.casefold() != ".h5ad":
            raise ValueError("Zheng68K processed dataset must be an h5ad file")
        adata = ad.read_h5ad(path)
        if adata.n_obs < 2 or adata.n_vars < 2:
            raise ValueError("Zheng68K processed dataset is empty")
        if label_key not in adata.obs:
            raise ValueError("Zheng68K label column is missing")
        labels = adata.obs[label_key].astype(str)
        if labels.isna().any() or labels.str.strip().eq("").any():
            raise ValueError("Zheng68K source labels contain missing values")
        fixture = dict(adata.uns.get("sckg_dataset") or {})
        if fixture.get("accession") != ZHENG68K_ACCESSION:
            raise ValueError("dataset accession is not frozen as Zheng68K")
        if fixture.get("user_data", True):
            raise ValueError("scientific pilot dataset cannot be user data")
        raw_counts_preserved = bool(
            "counts" in adata.layers
            or (
                adata.raw is not None
                and _looks_like_nonnegative_counts(adata.raw.X)
            )
            or _looks_like_nonnegative_counts(adata.X)
        )
        if not raw_counts_preserved:
            raise ValueError("Zheng68K raw counts are not preserved")
        return AnnotationDatasetManifest(
            title="10x Genomics PBMC 68k cell type annotation benchmark",
            source_url=source_url,
            license=license_name,
            processed_h5ad_path=str(path),
            processed_h5ad_sha256=_sha256(path),
            n_cells=int(adata.n_obs),
            n_genes=int(adata.n_vars),
            label_key=label_key,
            source_label_count=int(labels.nunique()),
            raw_counts_preserved=True,
        )

    def split(
        self,
        *,
        dataset_manifest: AnnotationDatasetManifest,
        label_mapping: AnnotationLabelMapping,
        reference: AnnotationReferenceManifest,
        output_dir: Path,
        split_seed: int = DEFAULT_SPLIT_SEED,
        development_fraction: float = 0.5,
    ) -> AnnotationSplitManifest:
        if not 0.2 <= development_fraction <= 0.8:
            raise ValueError("development fraction must be between 0.2 and 0.8")
        if label_mapping.ai_generated:
            raise ValueError("AI-generated label mappings cannot define pilot gold labels")
        path = Path(dataset_manifest.processed_h5ad_path).resolve(strict=True)
        if _sha256(path) != dataset_manifest.processed_h5ad_sha256:
            raise ValueError("frozen Zheng68K dataset digest mismatch")
        adata = ad.read_h5ad(path)
        source_labels = adata.obs[dataset_manifest.label_key].astype(str)
        unknown_sources = sorted(set(source_labels) - set(label_mapping.mapping))
        canonical = source_labels.map(label_mapping.mapping).fillna(
            label_mapping.unknown_label
        )
        if unknown_sources and label_mapping.unknown_label not in label_mapping.canonical_labels:
            raise ValueError("unmapped labels require an explicit canonical unknown label")

        development_indices, evaluation_indices = _stratified_indices(
            canonical.to_numpy(dtype=str),
            seed=split_seed,
            development_fraction=development_fraction,
        )
        output_dir = Path(output_dir).resolve()
        output_dir.mkdir(parents=True, exist_ok=False)
        development = adata[development_indices].copy()
        evaluation = adata[evaluation_indices].copy()
        development.obs["source_cell_type"] = source_labels.iloc[
            development_indices
        ].to_numpy()
        evaluation.obs["source_cell_type"] = source_labels.iloc[
            evaluation_indices
        ].to_numpy()
        development.obs["ground_truth_cell_type"] = canonical.iloc[
            development_indices
        ].to_numpy()
        evaluation.obs["ground_truth_cell_type"] = canonical.iloc[
            evaluation_indices
        ].to_numpy()
        _mark_scientific_fixture(
            development,
            split_role="development",
            split_seed=split_seed,
            reference=reference,
            mapping=label_mapping,
        )
        _mark_scientific_fixture(
            evaluation,
            split_role="evaluation",
            split_seed=split_seed,
            reference=reference,
            mapping=label_mapping,
        )
        development_path = output_dir / "development.h5ad"
        evaluation_path = output_dir / "evaluation.h5ad"
        development.write_h5ad(development_path)
        evaluation.write_h5ad(evaluation_path)
        development_artifact = _split_artifact(
            development,
            path=development_path,
            split_role="development",
            split_seed=split_seed,
            reference=reference,
            mapping=label_mapping,
        )
        evaluation_artifact = _split_artifact(
            evaluation,
            path=evaluation_path,
            split_role="evaluation",
            split_seed=split_seed,
            reference=reference,
            mapping=label_mapping,
        )
        overlap = set(development.obs_names).intersection(evaluation.obs_names)
        payload = {
            "schema_version": "1.0",
            "accession": ZHENG68K_ACCESSION,
            "dataset_sha256": dataset_manifest.processed_h5ad_sha256,
            "split_seed": split_seed,
            "label_key": dataset_manifest.label_key,
            "label_mapping_digest": label_mapping.mapping_digest,
            "stratification_fields": ["canonical_label"],
            "development": development_artifact.model_dump(
                mode="json", exclude={"path"}
            ),
            "evaluation": evaluation_artifact.model_dump(
                mode="json", exclude={"path"}
            ),
            "cell_overlap_count": len(overlap),
        }
        manifest = AnnotationSplitManifest(
            schema_version="1.0",
            accession=ZHENG68K_ACCESSION,
            dataset_sha256=dataset_manifest.processed_h5ad_sha256,
            split_seed=split_seed,
            label_key=dataset_manifest.label_key,
            label_mapping_digest=label_mapping.mapping_digest,
            stratification_fields=["canonical_label"],
            development=development_artifact,
            evaluation=evaluation_artifact,
            cell_overlap_count=len(overlap),
            manifest_hash=_canonical_hash(payload),
        )
        (output_dir / "split_manifest.json").write_text(
            manifest.model_dump_json(indent=2) + "\n",
            encoding="utf-8",
        )
        (output_dir / "label_mapping.json").write_text(
            label_mapping.model_dump_json(indent=2) + "\n",
            encoding="utf-8",
        )
        return manifest


def load_label_mapping(path: Path) -> AnnotationLabelMapping:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    expected = payload.pop("mapping_digest", "")
    actual = _canonical_hash(payload)
    if expected != actual:
        raise ValueError("annotation label mapping digest mismatch")
    mapping = AnnotationLabelMapping(**payload, mapping_digest=expected)
    if mapping.ai_generated:
        raise ValueError("AI-generated label mappings cannot define pilot gold labels")
    if set(mapping.mapping) != set(mapping.source_labels):
        raise ValueError("annotation label mapping must cover every declared source label")
    if not set(mapping.mapping.values()) <= set(mapping.canonical_labels):
        raise ValueError("annotation label mapping contains undeclared canonical labels")
    return mapping


def build_label_mapping(
    *,
    mapping_id: str,
    version: str,
    mapping: dict[str, str],
    unknown_label: str = "unknown",
) -> AnnotationLabelMapping:
    source_labels = sorted(mapping)
    canonical_labels = sorted(set(mapping.values()) | {unknown_label})
    payload = {
        "mapping_id": mapping_id,
        "version": version,
        "source_labels": source_labels,
        "canonical_labels": canonical_labels,
        "mapping": dict(sorted(mapping.items())),
        "unknown_label": unknown_label,
        "ai_generated": False,
    }
    return AnnotationLabelMapping(
        **payload,
        mapping_digest=_canonical_hash(payload),
    )


def scientific_pilot_limitations() -> list[str]:
    return [
        "Results are limited to the frozen Zheng68K PBMC dataset and preprocessing.",
        "The versioned deterministic label mapping defines evaluation labels; AI cannot rewrite gold labels.",
        "Reference coverage and label ontology constrain both tools.",
        "Unknown or unmapped labels remain unknown and are not silently reassigned.",
        "The pilot cannot establish that CellTypist or SingleR is universally optimal.",
    ]


def _stratified_indices(
    labels: np.ndarray,
    *,
    seed: int,
    development_fraction: float,
) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    development: list[int] = []
    evaluation: list[int] = []
    for label in sorted(set(labels)):
        indices = np.flatnonzero(labels == label)
        if len(indices) < 2:
            raise ValueError(f"label has fewer than two cells: {label}")
        shuffled = rng.permutation(indices)
        development_count = min(
            len(indices) - 1,
            max(1, int(round(len(indices) * development_fraction))),
        )
        development.extend(int(value) for value in shuffled[:development_count])
        evaluation.extend(int(value) for value in shuffled[development_count:])
    return np.asarray(sorted(development)), np.asarray(sorted(evaluation))


def _mark_scientific_fixture(
    adata: ad.AnnData,
    *,
    split_role: str,
    split_seed: int,
    reference: AnnotationReferenceManifest,
    mapping: AnnotationLabelMapping,
) -> None:
    adata.uns["sckg_fixture"] = {
        "fixture_id": f"Zheng68K-{split_role}",
        "accession": ZHENG68K_ACCESSION,
        "synthetic": False,
        "public_dataset": True,
        "maintainer_approved": True,
        "qualification_mode": True,
        "scientific_pilot": True,
        "task": "cell_type_annotation",
        "split_role": split_role,
        "split_seed": split_seed,
        "reference_id": reference.reference_id,
        "reference_digest": reference.sha256,
        "label_mapping_digest": mapping.mapping_digest,
        "user_data": False,
    }


def _split_artifact(
    adata: ad.AnnData,
    *,
    path: Path,
    split_role: str,
    split_seed: int,
    reference: AnnotationReferenceManifest,
    mapping: AnnotationLabelMapping,
) -> AnnotationSplitArtifact:
    labels = adata.obs["ground_truth_cell_type"].astype(str)
    return AnnotationSplitArtifact(
        artifact_id=f"Zheng68K-{split_role}",
        fixture_id=f"Zheng68K-{split_role}",
        split_role=split_role,
        path=str(path),
        probe_hash=_sha256(path),
        cell_id_hash=_lines_hash(adata.obs_names.astype(str)),
        label_hash=_lines_hash(labels),
        n_cells=int(adata.n_obs),
        n_labels=int(labels.nunique()),
        split_seed=split_seed,
        reference_id=reference.reference_id,
        reference_digest=reference.sha256,
        label_mapping_digest=mapping.mapping_digest,
    )


def _looks_like_nonnegative_counts(matrix) -> bool:
    values = matrix.data if sparse.issparse(matrix) else np.asarray(matrix).reshape(-1)
    values = np.asarray(values, dtype=float)
    if not values.size or not np.isfinite(values).all() or np.any(values < 0):
        return False
    return bool(np.allclose(values, np.rint(values), atol=1e-6))


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


def _canonical_hash(payload: dict) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
