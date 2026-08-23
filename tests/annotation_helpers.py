from __future__ import annotations

import hashlib
from pathlib import Path

from core.execution_models import AnnotationReferenceManifest


GENES = [
    "MS4A1",
    "CD79A",
    "CD37",
    "HLA-DRA",
    "CD3D",
    "CD3E",
    "TRBC1",
    "IL7R",
    "NKG7",
    "GNLY",
    "KLRD1",
    "PRF1",
    "LYZ",
    "S100A8",
    "S100A9",
    "CTSS",
    *[f"GENE{index:04d}" for index in range(104)],
]


def build_reference(
    root: Path,
    *,
    tool_name: str = "CellTypist",
    reference_id: str | None = None,
) -> AnnotationReferenceManifest:
    root.mkdir(parents=True, exist_ok=True)
    reference_path = root / (
        "model.pkl" if tool_name == "CellTypist" else "reference.rds"
    )
    reference_path.write_bytes(f"{tool_name}-test-reference\n".encode("utf-8"))
    gene_list_path = root / "genes.tsv"
    gene_list_path.write_text("\n".join(GENES) + "\n", encoding="utf-8")
    return AnnotationReferenceManifest(
        reference_id=reference_id
        or (
            "celltypist-immune-all-low-v1"
            if tool_name == "CellTypist"
            else "singler-immune-reference-v1"
        ),
        tool_name=tool_name,
        reference_type=(
            "celltypist_model"
            if tool_name == "CellTypist"
            else "singler_reference"
        ),
        version="test-v1",
        species="human",
        tissue_scope=["immune", "PBMC"],
        label_ontology_version="sckg-cell-labels-v1",
        gene_identifier_type="gene_symbol",
        gene_count=len(GENES),
        labels=["B_cell", "T_cell", "NK_cell", "Monocyte"],
        local_path=str(reference_path),
        sha256=_sha256(reference_path),
        gene_list_path=str(gene_list_path),
        gene_list_sha256=_sha256(gene_list_path),
        source_url="https://example.invalid/versioned-test-reference",
        license="test-only",
        qualification_status="verified",
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
