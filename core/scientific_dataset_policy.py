from __future__ import annotations


ALLOWLISTED_SCIENTIFIC_PILOT_ACCESSIONS = frozenset(
    {
        "GSE108313",
        "Scanpy-PBMC3K",
        "Zheng68K",
        "scIB-pancreas",
    }
)


def scientific_pilot_dataset_allowlisted(accession: str | None) -> bool:
    return accession in ALLOWLISTED_SCIENTIFIC_PILOT_ACCESSIONS
