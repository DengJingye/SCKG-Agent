from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Iterable

import anndata as ad
import numpy as np
from scipy import sparse

from core.execution_models import AnnotationDataProfile, AnnotationReferenceManifest
from engine.data_profiler import AnnDataProfiler


MIN_REFERENCE_OVERLAP_RATE = 0.20
MIN_REFERENCE_OVERLAP_GENES = 50


class AnnotationDataProfiler:
    """Deterministic annotation-specific compatibility checks for AnnData."""

    def __init__(self, *, base_profiler: AnnDataProfiler | None = None) -> None:
        self.base_profiler = base_profiler or AnnDataProfiler()

    def profile(
        self,
        file_path: str | Path,
        *,
        tool_name: str,
        reference: AnnotationReferenceManifest | None,
        explicit_species: str | None = None,
    ) -> AnnotationDataProfile:
        path = Path(file_path).expanduser()
        base = self.base_profiler.profile(path)
        blockers = [
            value
            for value in base.blocking_errors
            if value
            in {
                "invalid_file_extension",
                "input_file_missing",
                "input_path_not_file",
                "empty_anndata",
            }
            or value.startswith("anndata_read_failed")
        ]
        warnings: list[str] = []
        if blockers:
            return AnnotationDataProfile(
                profile_id=f"annotation-{base.profile_id}",
                file_path_redacted=base.file_path_redacted,
                file_hash=base.file_hash or "0" * 64,
                n_cells=base.n_cells,
                n_genes=base.n_genes,
                expression_source="X",
                expression_state="unknown",
                normalization_target="blocked",
                gene_identifier_type="unknown",
                species="unknown",
                blocking_errors=sorted(set(blockers)),
            )

        adata = ad.read_h5ad(path)
        x_profile = next(
            (item for item in base.matrix_profiles if item.matrix_id == "X"),
            None,
        )
        expression_state = (
            str(x_profile.inferred_state) if x_profile is not None else "unknown"
        )
        if expression_state == "log_normalized":
            expression_state = "log1p_normalized"
        if expression_state not in {
            "raw_counts",
            "log1p_normalized",
            "scaled",
            "unknown",
        }:
            expression_state = "unknown"

        genes = [str(value) for value in adata.var_names]
        duplicate_gene_count = len(genes) - len(set(genes))
        gene_identifier_type, inferred_species = _infer_gene_identity(genes)
        species = _normalize_species(explicit_species) or inferred_species
        tool_key = tool_name.casefold()
        normalization_target = _normalization_target(
            tool_key,
            expression_state,
            adata.X,
        )
        if normalization_target == "blocked":
            blockers.append("annotation_expression_state_invalid")
        if duplicate_gene_count:
            blockers.append("duplicate_gene_identifiers")
        if gene_identifier_type in {"mixed", "unknown"}:
            blockers.append("gene_identifier_type_unresolved")
        if species == "unknown":
            blockers.append("species_unresolved")

        reference_genes: set[str] = set()
        reference_id = ""
        reference_digest = ""
        if reference is None:
            blockers.append("annotation_reference_missing")
        else:
            reference_id = reference.reference_id
            reference_digest = reference.sha256
            blockers.extend(_reference_asset_issues(reference))
            reference_genes = _load_gene_list(reference.gene_list_path)
            if reference.tool_name.casefold() != tool_key:
                blockers.append("reference_tool_mismatch")
            if species != "unknown" and reference.species != species:
                blockers.append("reference_species_mismatch")
            if gene_identifier_type != reference.gene_identifier_type:
                blockers.append("reference_gene_identifier_mismatch")

        overlap = len(set(genes) & reference_genes)
        overlap_rate = overlap / len(reference_genes) if reference_genes else 0.0
        if reference_genes and (
            overlap < min(MIN_REFERENCE_OVERLAP_GENES, len(reference_genes))
            or overlap_rate < MIN_REFERENCE_OVERLAP_RATE
        ):
            blockers.append("reference_gene_overlap_insufficient")
        if expression_state == "raw_counts" and tool_key == "celltypist":
            warnings.append("celltypist_requires_deterministic_log1p_10000_transform")
        if expression_state == "raw_counts" and tool_key == "singler":
            warnings.append("singler_rank_scoring_accepts_counts_but_reference_is_logcounts")

        return AnnotationDataProfile(
            profile_id=f"annotation-{base.profile_id}",
            file_path_redacted=base.file_path_redacted,
            file_hash=base.file_hash,
            n_cells=base.n_cells,
            n_genes=base.n_genes,
            expression_source="X",
            expression_state=expression_state,
            normalization_target=normalization_target,
            gene_identifier_type=gene_identifier_type,
            species=species,
            duplicate_gene_count=duplicate_gene_count,
            reference_id=reference_id,
            reference_digest=reference_digest,
            reference_gene_count=len(reference_genes),
            overlapping_gene_count=overlap,
            gene_overlap_rate=overlap_rate,
            warnings=sorted(set(warnings)),
            blocking_errors=sorted(set(blockers)),
        )


def _normalization_target(tool: str, state: str, matrix) -> str:
    if state in {"scaled", "unknown"}:
        return "blocked"
    if tool == "singler":
        return "rank_based_compatible"
    if tool != "celltypist":
        return "blocked"
    if state == "raw_counts":
        return "normalize_log1p_10000"
    values = matrix[: min(256, matrix.shape[0])]
    values = values.toarray() if sparse.issparse(values) else np.asarray(values)
    if not np.isfinite(values).all() or np.any(values < 0):
        return "blocked"
    totals = np.expm1(values).sum(axis=1)
    positive = totals[totals > 0]
    if not positive.size:
        return "blocked"
    median = float(np.median(positive))
    return "ready_log1p_10000" if 8_000 <= median <= 12_000 else "blocked"


def _infer_gene_identity(genes: Iterable[str]) -> tuple[str, str]:
    values = [value.split(".", 1)[0] for value in genes if value]
    if not values:
        return "unknown", "unknown"
    human = sum(value.startswith("ENSG") and value[4:].isdigit() for value in values)
    mouse = sum(value.startswith("ENSMUSG") and value[6:].isdigit() for value in values)
    total = len(values)
    if human / total >= 0.95:
        return "ensembl_human", "human"
    if mouse / total >= 0.95:
        return "ensembl_mouse", "mouse"
    if human or mouse:
        return "mixed", "unknown"
    symbols = sum(
        value.replace("-", "").replace(".", "").isalnum()
        and not value.isdigit()
        for value in values
    )
    return ("gene_symbol", "unknown") if symbols / total >= 0.95 else ("unknown", "unknown")


def _normalize_species(value: str | None) -> str:
    text = str(value or "").strip().casefold()
    if text in {"human", "homo sapiens", "hsapiens"}:
        return "human"
    if text in {"mouse", "mus musculus", "mmusculus"}:
        return "mouse"
    return ""


def _reference_asset_issues(reference: AnnotationReferenceManifest) -> list[str]:
    issues: list[str] = []
    for path_text, expected, label in (
        (reference.local_path, reference.sha256, "reference"),
        (reference.gene_list_path, reference.gene_list_sha256, "reference_gene_list"),
    ):
        path = Path(path_text).expanduser()
        if not path.is_file():
            issues.append(f"{label}_missing")
        elif _sha256(path) != expected:
            issues.append(f"{label}_digest_mismatch")
    if reference.runtime_network_allowed:
        issues.append("reference_runtime_network_forbidden")
    return issues


def _load_gene_list(path_text: str) -> set[str]:
    path = Path(path_text).expanduser()
    if not path.is_file():
        return set()
    return {
        line.strip().split("\t", 1)[0]
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
