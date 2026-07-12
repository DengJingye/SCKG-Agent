from __future__ import annotations

import hashlib
import json
from pathlib import Path

import anndata as ad
import numpy as np
import pandas as pd

from core.execution_models import (
    ScientificLabelReport,
    ScientificSplitArtifact,
    ScientificSplitManifest,
)


GSE108313_ACCESSION = "GSE108313"
SCIENTIFIC_SPLIT_SEED = 20260712
HTO_POSITIVE_FRACTION = 0.20
HTO_AMBIGUOUS_MARGIN = 0.05


class GSE108313Dataset:
    def label_and_filter(
        self,
        *,
        input_h5ad: Path,
        output_h5ad: Path,
        exclusion_path: Path,
        report_path: Path,
        positive_fraction_threshold: float = HTO_POSITIVE_FRACTION,
        ambiguous_margin: float = HTO_AMBIGUOUS_MARGIN,
    ) -> tuple[Path, ScientificLabelReport]:
        adata = ad.read_h5ad(input_h5ad)
        if "HTO_counts" not in adata.obsm:
            raise ValueError("HTO_counts missing from prepared dataset")
        hto_names = [str(item) for item in adata.uns.get("hto_names", [])]
        counts = np.asarray(adata.obsm["HTO_counts"])
        if counts.shape != (adata.n_obs, len(hto_names)):
            raise ValueError("RNA barcode and HTO matrix alignment mismatch")
        if len(set(adata.obs_names)) != adata.n_obs:
            raise ValueError("RNA barcodes must be unique")

        labels = classify_hto_counts(
            counts,
            hto_names,
            positive_fraction_threshold=positive_fraction_threshold,
            ambiguous_margin=ambiguous_margin,
        )
        labels.index = adata.obs_names
        adata.obs = adata.obs.join(labels)
        keep = adata.obs["gold_label"].isin(["singlet", "doublet"])
        excluded = adata.obs.loc[~keep, ["gold_label", "exclusion_reason", "hto_identity"]]
        filtered = adata[keep].copy()
        filtered.obs["ground_truth_doublet"] = (
            filtered.obs["gold_label"] == "doublet"
        ).astype(bool)
        filtered.uns["sckg_fixture"] = {
            "fixture_id": GSE108313_ACCESSION,
            "accession": GSE108313_ACCESSION,
            "synthetic": False,
            "public_dataset": True,
            "maintainer_approved": True,
            "qualification_mode": True,
            "scientific_pilot": True,
            "user_data": False,
        }
        output_h5ad.parent.mkdir(parents=True, exist_ok=True)
        filtered.write_h5ad(output_h5ad)
        excluded.to_csv(exclusion_path, sep="\t", index=True)

        reasons = {
            str(key): int(value)
            for key, value in excluded["exclusion_reason"].value_counts().items()
        }
        report = ScientificLabelReport(
            label_method="HTO fraction rule: >=20% positive; near-threshold single calls ambiguous",
            positive_fraction_threshold=positive_fraction_threshold,
            ambiguous_margin=ambiguous_margin,
            aligned_barcodes=adata.n_obs,
            singlet_count=int((filtered.obs["gold_label"] == "singlet").sum()),
            doublet_count=int((filtered.obs["gold_label"] == "doublet").sum()),
            excluded_count=int((~keep).sum()),
            exclusion_reasons=reasons,
            label_mapping={
                "one_positive_hto": "singlet",
                "two_or_more_positive_hto": "doublet",
                "no_positive_hto": "negative/excluded",
                "near_threshold_second_hto": "ambiguous/excluded",
            },
            limitations=scientific_pilot_limitations(),
        )
        report_path.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
        return output_h5ad, report

    def split(
        self,
        *,
        labeled_h5ad: Path,
        output_dir: Path,
        split_seed: int = SCIENTIFIC_SPLIT_SEED,
        evaluation_fraction: float = 0.30,
    ) -> ScientificSplitManifest:
        if not 0.0 < evaluation_fraction < 1.0:
            raise ValueError("evaluation_fraction must be in (0, 1)")
        adata = ad.read_h5ad(labeled_h5ad)
        required = {"gold_label", "hto_identity", "ground_truth_doublet"}
        if not required.issubset(adata.obs.columns):
            raise ValueError("labeled dataset is missing split fields")
        strata = (
            adata.obs["gold_label"].astype(str)
            + "|"
            + adata.obs["hto_identity"].astype(str)
        )
        rng = np.random.default_rng(split_seed)
        development_indices: list[int] = []
        evaluation_indices: list[int] = []
        for stratum in sorted(strata.unique()):
            indices = np.flatnonzero(strata.to_numpy() == stratum)
            indices = rng.permutation(indices)
            if len(indices) == 1:
                development_indices.extend(indices.tolist())
                continue
            n_evaluation = max(1, int(round(len(indices) * evaluation_fraction)))
            n_evaluation = min(n_evaluation, len(indices) - 1)
            evaluation_indices.extend(indices[:n_evaluation].tolist())
            development_indices.extend(indices[n_evaluation:].tolist())

        development_indices = sorted(development_indices)
        evaluation_indices = sorted(evaluation_indices)
        development = adata[development_indices].copy()
        evaluation = adata[evaluation_indices].copy()
        output_dir.mkdir(parents=True, exist_ok=True)
        development_path = output_dir / "development.h5ad"
        evaluation_path = output_dir / "evaluation.h5ad"
        _mark_split(development, "development", split_seed)
        _mark_split(evaluation, "evaluation", split_seed)
        development.write_h5ad(development_path)
        evaluation.write_h5ad(evaluation_path)

        development_artifact = _split_artifact(
            development, development_path, "development", split_seed
        )
        evaluation_artifact = _split_artifact(
            evaluation, evaluation_path, "evaluation", split_seed
        )
        overlap = set(development.obs_names).intersection(evaluation.obs_names)
        payload = {
            "accession": GSE108313_ACCESSION,
            "split_seed": split_seed,
            "stratification_fields": ["gold_label", "hto_identity"],
            "development": development_artifact.model_dump(mode="json"),
            "evaluation": evaluation_artifact.model_dump(mode="json"),
            "barcode_overlap_count": len(overlap),
        }
        hash_payload = {
            **payload,
            "development": development_artifact.model_dump(
                mode="json", exclude={"path"}
            ),
            "evaluation": evaluation_artifact.model_dump(
                mode="json", exclude={"path"}
            ),
        }
        manifest_hash = hashlib.sha256(
            json.dumps(hash_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        manifest = ScientificSplitManifest(
            **payload,
            manifest_hash=manifest_hash,
        )
        (output_dir / "split_manifest.json").write_text(
            manifest.model_dump_json(indent=2) + "\n", encoding="utf-8"
        )
        if overlap:
            raise RuntimeError("development/evaluation barcode leakage detected")
        return manifest


def classify_hto_counts(
    counts: np.ndarray,
    hto_names: list[str],
    *,
    positive_fraction_threshold: float = HTO_POSITIVE_FRACTION,
    ambiguous_margin: float = HTO_AMBIGUOUS_MARGIN,
) -> pd.DataFrame:
    counts = np.asarray(counts, dtype=np.float64)
    if counts.ndim != 2 or counts.shape[1] != len(hto_names):
        raise ValueError("HTO matrix shape does not match HTO names")
    if np.any(~np.isfinite(counts)) or np.any(counts < 0):
        raise ValueError("HTO counts must be finite and non-negative")
    totals = counts.sum(axis=1)
    fractions = np.divide(
        counts,
        totals[:, None],
        out=np.zeros_like(counts),
        where=totals[:, None] > 0,
    )
    records = []
    for total, row in zip(totals, fractions):
        positives = np.flatnonzero(row >= positive_fraction_threshold)
        ordered = np.argsort(row)[::-1]
        if total <= 0 or len(positives) == 0:
            label, reason, identity = "excluded", "negative", ""
        elif len(positives) >= 2:
            identity = "+".join(sorted(hto_names[index] for index in positives))
            label, reason = "doublet", ""
        else:
            second_fraction = row[ordered[1]] if len(ordered) > 1 else 0.0
            if second_fraction >= positive_fraction_threshold - ambiguous_margin:
                label, reason, identity = "excluded", "ambiguous", ""
            else:
                identity = hto_names[int(positives[0])]
                label, reason = "singlet", ""
        records.append(
            {
                "gold_label": label,
                "exclusion_reason": reason,
                "hto_identity": identity,
                "hto_total": int(total),
            }
        )
    return pd.DataFrame.from_records(records)


def scientific_pilot_limitations() -> list[str]:
    return [
        "HTO labels primarily identify cross-sample multiplets.",
        "Same-donor doublets may be labeled as singlets.",
        "Labels are produced by the recorded deterministic HTO fraction rule.",
        "Results apply only to GSE108313 PBMCs and the recorded preprocessing.",
        "The pilot cannot establish that any tool is generally optimal.",
    ]


def _mark_split(adata: ad.AnnData, split_role: str, split_seed: int) -> None:
    adata.uns["sckg_fixture"] = {
        "fixture_id": f"{GSE108313_ACCESSION}-{split_role}",
        "accession": GSE108313_ACCESSION,
        "synthetic": False,
        "public_dataset": True,
        "maintainer_approved": True,
        "qualification_mode": True,
        "scientific_pilot": True,
        "split_role": split_role,
        "split_seed": split_seed,
        "user_data": False,
    }


def _split_artifact(
    adata: ad.AnnData,
    path: Path,
    split_role: str,
    split_seed: int,
) -> ScientificSplitArtifact:
    barcodes = sorted(str(item) for item in adata.obs_names)
    barcode_hash = hashlib.sha256("\n".join(barcodes).encode("utf-8")).hexdigest()
    return ScientificSplitArtifact(
        artifact_id=f"gse108313-{split_role}",
        fixture_id=f"{GSE108313_ACCESSION}-{split_role}",
        split_role=split_role,
        path=str(path),
        probe_hash=_sha256(path),
        barcode_hash=barcode_hash,
        n_cells=adata.n_obs,
        singlet_count=int((adata.obs["gold_label"] == "singlet").sum()),
        doublet_count=int((adata.obs["gold_label"] == "doublet").sum()),
        split_seed=split_seed,
    )


def qualification_artifact(split: ScientificSplitArtifact):
    from core.execution_models import QualificationArtifact

    return QualificationArtifact(
        artifact_id=split.artifact_id,
        fixture_id=split.fixture_id,
        path=split.path,
        sha256=split.probe_hash,
        synthetic=False,
        public_dataset=True,
        user_data=False,
        accession=split.accession,
        allowlisted=True,
        expected_cells=split.n_cells,
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
