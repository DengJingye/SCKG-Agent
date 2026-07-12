from data_pipeline.build_doublet_recovery_demo import metadata_text_only, source_text_status
from data_pipeline.download_evidence_pdfs import (
    dedupe_candidates,
    is_supplement_pdf_url,
    looks_like_pdf_url,
    suggested_pdf_filename,
)
from data_pipeline.ingest_evidence_pdfs import match_pdf_for_row


def test_crossref_metadata_source_is_not_full_text(tmp_path):
    path = tmp_path / "source.txt"
    path.write_text(
        "Title: Scrublet\n\n"
        "Boundary: Crossref metadata is evidence discovery text only. "
        "It is not a verified figure/table/section source span and cannot promote evidence.",
        encoding="utf-8",
    )
    source = {
        "fetch_status": "fetched_existing",
        "local_text_path": str(path),
    }

    assert metadata_text_only(source)
    assert source_text_status(source) == "metadata_text_available"


def test_pdf_ingest_matches_record_id_filename(tmp_path):
    pdf = tmp_path / "Scrublet_CAND_PUB_Scrublet_137a56b00546.pdf"
    pdf.write_bytes(b"%PDF-1.4 placeholder")
    row = {
        "tool_name": "Scrublet",
        "record_id": "CAND_PUB_Scrublet_137a56b00546",
        "source_title": "Scrublet: Computational Identification of Cell Doublets",
        "doi_or_pmid": "10.1016/j.cels.2018.11.005",
    }

    assert match_pdf_for_row(row, [pdf]) == pdf


def test_pdf_ingest_does_not_match_tool_name_only(tmp_path):
    pdf = tmp_path / "Seurat_HR_BMK_Seurat_scIB_integration_2022.pdf"
    pdf.write_bytes(b"%PDF-1.4 placeholder")
    row = {
        "tool_name": "Seurat",
        "record_id": "CAND_PUB_Seurat_v3_2019_Stuart",
        "source_title": "Comprehensive Integration of Single-Cell Data",
        "doi_or_pmid": "10.1016/j.cell.2019.05.031",
    }

    assert match_pdf_for_row(row, [pdf]) is None


def test_pdf_download_candidate_helpers_are_conservative():
    assert looks_like_pdf_url("https://example.org/article.pdf")
    assert looks_like_pdf_url("https://example.org/article.pdf?download=1")
    assert not looks_like_pdf_url("https://example.org/article")
    candidates = dedupe_candidates(
        [
            {"url": "https://example.org/a.pdf", "source": "first"},
            {"url": "https://example.org/a.pdf", "source": "second"},
            {"url": "", "source": "empty"},
        ]
    )

    assert candidates == [
        {
            "url": "https://example.org/a.pdf",
            "source": "first",
            "candidate_kind": "primary_article",
        }
    ]


def test_pdf_download_marks_supplement_candidates():
    assert is_supplement_pdf_url(
        "https://static-content.springer.com/esm/art%3A10.1038/foo/MediaObjects/foo_MOESM1_ESM.pdf"
    )
    assert not is_supplement_pdf_url("https://www.nature.com/articles/s41592-021-01336-8.pdf")


def test_pdf_download_filename_uses_tool_and_record_id():
    row = {
        "tool_name": "DoubletFinder",
        "record_id": "HR_BMK_DoubletFinder_doublet_detection_2020",
    }

    assert suggested_pdf_filename(row) == "DoubletFinder_HR_BMK_DoubletFinder_doublet_detection_2020.pdf"
