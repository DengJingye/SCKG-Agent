from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np

from core.representation_models import RepresentationLedger, RepresentationRecord
from engine.data_profiler import AnnDataProfiler


class AnnDataRepresentationProfiler:
    """Build a coexisting state ledger; never mutates the AnnData input."""

    def __init__(self, matrix_profiler: AnnDataProfiler | None = None) -> None:
        self.matrix_profiler = matrix_profiler or AnnDataProfiler()

    def profile(
        self,
        path: str | Path,
        *,
        artifact_id: str = "registered-anndata",
        batch_key: str | None = None,
    ) -> RepresentationLedger:
        import anndata as ad

        path = Path(path).expanduser().resolve(strict=True)
        profile = self.matrix_profiler.profile(path, batch_key=batch_key)
        if profile.object_type != "AnnData" or not profile.file_hash:
            raise ValueError("AnnData representation profiling requires a readable .h5ad")
        adata = ad.read_h5ad(path, backed="r")
        cell_hash = _index_hash(adata.obs_names.astype(str).tolist())
        gene_hash = _index_hash(adata.var_names.astype(str).tolist())
        records: list[RepresentationRecord] = []

        def add(
            representation_id: str,
            slot: str,
            value_state: str,
            *,
            provenance: list[str],
            cell: bool = True,
            gene: bool = True,
            metadata: dict[str, Any] | None = None,
            validated: bool = True,
            parents: list[str] | None = None,
        ) -> str:
            record_id = f"rep:{_digest([representation_id, slot, cell_hash, gene_hash])[:20]}"
            if any(item.representation_record_id == record_id for item in records):
                return record_id
            records.append(
                RepresentationRecord(
                    representation_record_id=record_id,
                    representation_id=representation_id,
                    schema_version="1.0",
                    value_state=value_state,
                    slot=slot,
                    provenance=provenance,
                    cell_index_hash=cell_hash if cell else None,
                    gene_index_hash=gene_hash if gene else None,
                    parent_record_ids=parents or [],
                    validated=validated,
                    metadata=metadata or {},
                )
            )
            return record_id

        registered = add(
            "registered_anndata",
            "artifact",
            "table",
            provenance=["data_registry"],
            metadata={"artifact_id": artifact_id, "source_hash": profile.file_hash},
        )
        raw_record: str | None = None
        if profile.selected_count_source:
            raw_record = add(
                "raw_counts",
                profile.selected_count_source,
                "nonnegative_integer",
                provenance=["count_source_validated"],
                metadata={"selected_count_source": profile.selected_count_source},
                parents=[registered],
            )
        matrix_by_id = {item.matrix_id: item for item in profile.matrix_profiles}
        for matrix_id, matrix_profile in matrix_by_id.items():
            if matrix_profile.inferred_state == "log_normalized":
                add(
                    "log1p_normalized",
                    matrix_id,
                    "nonnegative_continuous",
                    provenance=["deterministic_log_state_profile"],
                    metadata={"full_gene_matrix": matrix_id in {"X", "raw.X"}},
                    parents=[registered],
                )
            elif matrix_profile.inferred_state == "scaled":
                hvg_scoped = "highly_variable" in adata.var and bool(
                    np.asarray(adata.var["highly_variable"], dtype=bool).any()
                )
                add(
                    "scaled_hvg",
                    matrix_id,
                    "real_continuous",
                    provenance=["deterministic_scaled_state_profile"],
                    metadata={"hvg_scoped": hvg_scoped},
                    validated=hvg_scoped,
                    parents=[registered],
                )
            elif matrix_profile.inferred_state == "normalized":
                add(
                    "library_size_normalized",
                    matrix_id,
                    "nonnegative_continuous",
                    provenance=["deterministic_normalized_state_profile"],
                    parents=[registered],
                )

        if raw_record and _has_qc(adata):
            add("qc_metrics", "obs/var", "table", provenance=["scanpy_qc_fields_detected"], parents=[raw_record])
        if "filtered_counts" in adata.layers and matrix_by_id.get("layers/filtered_counts", None):
            add("filtered_counts", "layers/filtered_counts", "nonnegative_integer", provenance=["filtered_count_layer"], parents=[raw_record] if raw_record else [])
        if "highly_variable" in adata.var and bool(np.asarray(adata.var["highly_variable"], dtype=bool).any()):
            add("hvg_selection", "var/highly_variable", "boolean_mask", provenance=["hvg_mask_detected"], cell=False, parents=[])
        if "X_pca" in adata.obsm:
            pca = np.asarray(adata.obsm["X_pca"])
            add(
                "pca",
                "obsm/X_pca",
                "real_continuous",
                provenance=["finite_pca_detected", "pca_seed_bound"],
                gene=False,
                metadata={
                    "n_components": int(pca.shape[1]) if pca.ndim == 2 else 0,
                    **({"batch_key": profile.batch_key} if profile.batch_key else {}),
                },
                validated=bool(
                    pca.ndim == 2
                    and pca.shape[0] == adata.n_obs
                    and np.isfinite(pca).all()
                ),
            )
        integrated_keys = sorted(key for key in adata.obsm if key.casefold() in {"x_integrated", "x_pca_harmony", "x_scanorama"})
        for key in integrated_keys:
            values = np.asarray(adata.obsm[key])
            add(
                "integrated_representation",
                f"obsm/{key}",
                "real_continuous",
                provenance=["integration_key_detected", "validated_integration_action"],
                gene=False,
                metadata={
                    "integration_key": key,
                    **({"batch_key": profile.batch_key} if profile.batch_key else {}),
                },
                validated=bool(
                    values.ndim == 2
                    and values.shape[0] == adata.n_obs
                    and np.isfinite(values).all()
                    and profile.batch_key
                    and (profile.batch_count or 0) >= 2
                ),
            )
        if "connectivities" in adata.obsp and "distances" in adata.obsp:
            add("neighbor_graph", "obsp/connectivities", "graph", provenance=["neighbor_graph_pair_detected"], gene=False)
        if "X_umap" in adata.obsm:
            values = np.asarray(adata.obsm["X_umap"])
            add("umap", "obsm/X_umap", "real_continuous", provenance=["umap_detected"], gene=False, validated=bool(values.ndim == 2 and values.shape == (adata.n_obs, 2) and np.isfinite(values).all()))
        cluster_key = next((key for key in ("leiden", "louvain") if key in adata.obs), None)
        cluster_record = None
        if cluster_key:
            cluster_record = add("cluster_labels", f"obs/{cluster_key}", "categorical", provenance=["cluster_labels_detected"], gene=False)
        if "rank_genes_groups" in adata.uns and cluster_record:
            add("marker_result", "uns/rank_genes_groups", "table", provenance=["marker_result_detected", "full_gene_log1p_source"], parents=[cluster_record])
        if "cell_type" in adata.obs:
            add("confirmed_annotation", "obs/cell_type", "categorical", provenance=["existing_annotation_unreviewed"], gene=False, validated=False)

        warnings = list(profile.warnings)
        raw_count_scoped = {
            item
            for item in profile.blocking_errors
            if item == "count_source_unresolved"
            or item.endswith(":not_validated_raw_counts")
        }
        fatal = [item for item in profile.blocking_errors if item not in raw_count_scoped]
        if raw_count_scoped:
            warnings.append("count_source_unresolved_counts_dependent_steps_unavailable")
        return RepresentationLedger(
            ledger_id=f"ledger-{profile.file_hash[:16]}",
            profile_id=profile.profile_id,
            source_artifact_id=artifact_id,
            source_hash=profile.file_hash,
            cell_index_hash=cell_hash,
            gene_index_hash=gene_hash,
            records=records,
            metadata={
                "batch_key": profile.batch_key,
                "batch_count": profile.batch_count,
            },
            warnings=sorted(set(warnings)),
            blocking_errors=sorted(set(fatal)),
        )


def mark_descendants_stale(
    ledger: RepresentationLedger, *, parent_record_id: str, reason: str
) -> RepresentationLedger:
    descendants: set[str] = {parent_record_id}
    changed = True
    while changed:
        changed = False
        for item in ledger.records:
            if item.representation_record_id not in descendants and descendants.intersection(item.parent_record_ids):
                descendants.add(item.representation_record_id)
                changed = True
    records = []
    for item in ledger.records:
        if item.representation_record_id in descendants:
            records.append(item.model_copy(update={"status": "stale", "stale_reasons": [reason]}))
        else:
            records.append(item)
    return ledger.model_copy(update={"records": records})


def _has_qc(adata) -> bool:
    return any(key in adata.obs for key in ("total_counts", "n_genes_by_counts", "pct_counts_mt"))


def _index_hash(values: list[str]) -> str:
    return hashlib.sha256("\n".join(values).encode()).hexdigest()


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()
