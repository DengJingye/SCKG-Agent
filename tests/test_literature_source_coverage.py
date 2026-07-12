from data_pipeline.build_literature_source_coverage import build_coverage_rows, build_summary


def test_literature_source_coverage_treats_short_text_as_missing(tmp_path):
    short_text = tmp_path / "short.txt"
    short_text.write_text("Title only metadata", encoding="utf-8")
    long_text = tmp_path / "long.txt"
    long_text.write_text("Full source text paragraph. " * 100, encoding="utf-8")
    manifest_rows = [
        {
            "tool_name": "Scrublet",
            "evidence_kind": "publication",
            "record_id": "SHORT",
            "source_title": "Short source",
            "source_url": "https://doi.org/10.1/short",
            "doi_or_pmid": "10.1/short",
            "fetch_status": "fetched_text",
            "pdf_status": "missing_pdf",
            "local_text_path": str(short_text),
        },
        {
            "tool_name": "Scanpy",
            "evidence_kind": "publication",
            "record_id": "LONG",
            "source_title": "Long source",
            "source_url": "https://doi.org/10.1/long",
            "doi_or_pmid": "10.1/long",
            "fetch_status": "pdf_text_extracted",
            "pdf_status": "pdf_text_extracted",
            "local_text_path": str(long_text),
        },
    ]

    rows = build_coverage_rows(manifest_rows, checklist_rows=[])
    summary = build_summary(rows)
    by_record = {row["record_id"]: row for row in rows}

    assert by_record["SHORT"]["coverage_status"] == "source_text_too_short"
    assert by_record["LONG"]["coverage_status"] == "source_text_available"
    assert summary["source_text_available"] == 1
    assert summary["source_text_too_short"] == 1
    assert summary["manual_queue_rows"] == 1


def test_literature_source_coverage_applies_bad_candidate_override():
    rows = build_coverage_rows(
        [
            {
                "tool_name": "SingleR",
                "evidence_kind": "benchmark",
                "record_id": "HR_BMK_SingleR_annotation_2023",
                "source_title": "A comprehensive benchmarking of cell type annotation methods",
                "source_url": "https://doi.org/10.1093/bib/bbad418",
                "doi_or_pmid": "10.1093/bib/bbad418",
                "fetch_status": "not_fetched",
                "pdf_status": "missing_pdf",
                "local_text_path": "",
            }
        ],
        checklist_rows=[
            {
                "record_id": "HR_BMK_SingleR_annotation_2023",
                "action": "manual_download_or_browser_login",
                "selected_pdf_url": "https://academic.oup.com/bib/article-pdf/24/6/bbad418/53617507/bbad418.pdf",
                "primary_candidate_urls": "https://academic.oup.com/bib/article-pdf/24/6/bbad418/53617507/bbad418.pdf",
                "suggested_pdf_path": "data/evidence_sources/pdfs/SingleR.pdf",
            }
        ],
        bad_candidate_rows=[
            {
                "record_id": "HR_BMK_SingleR_annotation_2023",
                "issue": "metadata_mismatch_pdf_title_or_doi",
                "recommended_action": "resolve_wrong_doi_or_replace_source",
                "notes": "Candidate PDF title is PanomiR.",
            }
        ],
    )

    assert rows[0]["action"] == "resolve_wrong_doi_or_replace_source"
    assert rows[0]["suggested_pdf_path"] == ""
    assert rows[0]["selected_pdf_url"] == ""
    assert rows[0]["primary_candidate_urls"] == ""
    assert rows[0]["candidate_issue"] == "metadata_mismatch_pdf_title_or_doi"
    assert "PanomiR" in rows[0]["notes"]


def test_literature_source_coverage_marks_existing_pdf_extract_error():
    rows = build_coverage_rows(
        [
            {
                "tool_name": "Seurat",
                "evidence_kind": "publication",
                "record_id": "CAND_PUB_Seurat_v3_2019_Stuart",
                "source_title": "Comprehensive Integration of Single-Cell Data",
                "source_url": "https://doi.org/10.1016/j.cell.2019.05.031",
                "doi_or_pmid": "10.1016/j.cell.2019.05.031",
                "fetch_status": "not_fetched",
                "pdf_status": "extract_error",
                "pdf_path": "data/evidence_sources/pdfs/news/Seurat.pdf",
                "local_text_path": "",
                "notes": "pypdf failed: PdfReadError",
            }
        ],
        checklist_rows=[
            {
                "record_id": "CAND_PUB_Seurat_v3_2019_Stuart",
                "action": "manual_search_required",
                "notes": "old checklist note",
            }
        ],
    )

    assert rows[0]["action"] == "pdf_extraction_failed_use_alternate_text_or_repair"
    assert rows[0]["pdf_path"] == "data/evidence_sources/pdfs/news/Seurat.pdf"
    assert "pypdf failed" in rows[0]["notes"]
