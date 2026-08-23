import csv
import json
from pathlib import Path

from engine.source_corpus_v2 import SourceCorpusBuilder, _heading


def _write_manifest(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = sorted({key for row in rows for key in row})
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


def test_source_documents_dedupe_by_doi_and_preserve_multiple_tools(tmp_path):
    text_path = tmp_path / "data" / "evidence_sources" / "shared.txt"
    text_path.parent.mkdir(parents=True)
    text_path.write_text(
        "Methods\n\n" + "Raw count input and doublet scoring are described here. " * 45,
        encoding="utf-8",
    )
    manifest = tmp_path / "data" / "evidence_candidates" / "sources.tsv"
    _write_manifest(
        manifest,
        [
            {
                "source_id": "old-a",
                "tool_name": "Scrublet",
                "record_id": "rec-a",
                "source_title": "Shared methods paper",
                "doi_or_pmid": "10.1000/shared",
                "source_url": "https://example.org/a",
                "preferred_source_type": "paper",
                "local_text_path": "data/evidence_sources/shared.txt",
            },
            {
                "source_id": "old-b",
                "tool_name": "DoubletFinder",
                "record_id": "rec-b",
                "source_title": "Shared methods paper",
                "doi_or_pmid": "https://doi.org/10.1000/shared",
                "source_url": "https://example.org/b",
                "preferred_source_type": "paper",
                "local_text_path": "data/evidence_sources/shared.txt",
            },
        ],
    )

    result = SourceCorpusBuilder(
        project_root=tmp_path,
        source_manifests=[manifest],
        target_tokens=120,
        max_tokens=180,
        overlap_tokens=20,
    ).build(write=True)

    assert len(result["source_documents"]) == 1
    document = result["source_documents"][0]
    assert document.doi == "10.1000/shared"
    assert document.referring_tool_names == ["DoubletFinder", "Scrublet"]
    assert result["chunks"]
    assert all(chunk.token_count <= 180 for chunk in result["chunks"])
    assert all(chunk.section == "Methods" for chunk in result["chunks"])
    assert (tmp_path / "data" / "indexes" / "source_documents_v2.jsonl").is_file()


def test_metadata_mismatch_is_quarantined_and_not_chunked(tmp_path):
    manifest = tmp_path / "sources.tsv"
    _write_manifest(
        manifest,
        [{
            "source_id": "bad",
            "tool_name": "SingleR",
            "record_id": "bad-record",
            "source_title": "Wrong paper",
            "source_url": "https://example.org/wrong",
            "validation_status": "source_metadata_mismatch",
            "validation_issue": "title_doi_mismatch",
        }],
    )

    result = SourceCorpusBuilder(
        project_root=tmp_path,
        source_manifests=[manifest],
    ).build(write=False)

    assert result["source_documents"][0].source_status == "quarantined"
    assert result["chunks"] == []


def test_explicit_quarantine_blocks_known_wrong_doi_even_when_manifest_is_unmarked(tmp_path):
    text_path = tmp_path / "wrong.txt"
    text_path.write_text("Methods\n\n" + "This is the wrong PanomiR source. " * 50, encoding="utf-8")
    manifest = tmp_path / "sources.tsv"
    _write_manifest(
        manifest,
        [{
            "source_id": "bad",
            "tool_name": "CellTypist",
            "record_id": "bad-benchmark",
            "source_title": "A benchmark title that does not match its DOI",
            "doi_or_pmid": "10.1093/bib/bbad418",
            "source_url": "https://doi.org/10.1093/bib/bbad418",
            "local_text_path": str(text_path),
        }],
    )
    quarantine = tmp_path / "quarantine.json"
    quarantine.write_text(
        json.dumps(
            {
                "records": [
                    {
                        "record_ids": ["bad-benchmark"],
                        "doi": "10.1093/bib/bbad418",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    result = SourceCorpusBuilder(
        project_root=tmp_path,
        source_manifests=[manifest],
        source_quarantine_path=quarantine,
    ).build(write=False)

    assert result["source_documents"][0].source_status == "quarantined"
    assert result["chunks"] == []


def test_reference_lines_and_gene_symbols_are_not_promoted_to_sections():
    assert _heading("48. Human BioMolecular Atlas Program. Nature https://nature.com") == ""
    assert _heading("GZMB") == ""
    assert _heading("2.1 Methods") == "2.1 Methods"
