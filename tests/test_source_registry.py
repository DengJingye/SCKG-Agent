from data_pipeline.build_source_registry import (
    build_pdf_candidate_registry,
    build_source_registry,
    build_validation_report,
)


def test_source_registry_groups_same_doi_into_one_source(tmp_path):
    text_path = tmp_path / "source.txt"
    text_path.write_text("validated source text " * 100, encoding="utf-8")
    rows = [
        {
            "tool_name": "CellTypist",
            "evidence_kind": "benchmark",
            "record_id": "REC_CELLTYPIST",
            "source_title": "Benchmarking cell type annotation methods",
            "source_url": "https://doi.org/10.1234/shared",
            "doi_or_pmid": "10.1234/shared",
            "preferred_source_type": "doi_landing_or_open_html",
            "local_text_path": str(text_path),
            "pdf_status": "pdf_text_extracted",
            "pdf_path": "data/evidence_sources/pdfs/shared.pdf",
        },
        {
            "tool_name": "SingleR",
            "evidence_kind": "benchmark",
            "record_id": "REC_SINGLER",
            "source_title": "Benchmarking cell type annotation methods",
            "source_url": "https://doi.org/10.1234/shared",
            "doi_or_pmid": "https://doi.org/10.1234/shared",
            "preferred_source_type": "doi_landing_or_open_html",
            "local_text_path": str(text_path),
            "pdf_status": "pdf_text_extracted",
            "pdf_path": "data/evidence_sources/pdfs/shared.pdf",
        },
    ]

    registry = build_source_registry(rows)

    assert len(registry) == 1
    assert registry[0]["source_status"] == "source_text_available"
    assert registry[0]["validation_status"] == "validated_source_text_available"
    assert registry[0]["source_row_count"] == 2
    assert registry[0]["referring_record_ids"] == "REC_CELLTYPIST; REC_SINGLER"
    assert registry[0]["referring_tool_names"] == "CellTypist; SingleR"


def test_source_registry_quarantines_bad_doi_candidate_without_pdf_save_path():
    manifest_rows = [
        {
            "tool_name": "SingleR",
            "evidence_kind": "benchmark",
            "record_id": "HR_BMK_SingleR_annotation_2023",
            "source_title": "A comprehensive benchmarking of cell type annotation methods",
            "source_url": "https://doi.org/10.1093/bib/bbad418",
            "doi_or_pmid": "10.1093/bib/bbad418",
            "preferred_source_type": "doi_landing_or_open_html",
            "local_text_path": "",
            "pdf_status": "missing_pdf",
        }
    ]
    bad_rows = [
        {
            "record_id": "HR_BMK_SingleR_annotation_2023",
            "invalid_url": "https://academic.oup.com/bib/article-pdf/24/6/bbad418/53617507/bbad418.pdf",
            "issue": "metadata_mismatch_pdf_title_or_doi",
            "recommended_action": "resolve_wrong_doi_or_replace_source",
            "notes": "Candidate PDF title is PanomiR.",
        }
    ]

    registry = build_source_registry(manifest_rows, bad_rows)
    report = build_validation_report(registry)
    candidates = build_pdf_candidate_registry(
        manifest_rows,
        source_registry_rows=registry,
        download_summary={
            "rows": [
                {
                    "record_id": "HR_BMK_SingleR_annotation_2023",
                    "status": "dry_run_candidate_found",
                    "selected_pdf_url": "https://academic.oup.com/bib/article-pdf/24/6/bbad418/53617507/bbad418.pdf",
                    "candidate_urls": [
                        {
                            "url": "https://academic.oup.com/bib/article-pdf/24/6/bbad418/53617507/bbad418.pdf",
                            "source": "doi_landing_citation_pdf_url",
                            "candidate_kind": "primary_article",
                        }
                    ],
                }
            ]
        },
        bad_candidate_rows=bad_rows,
    )

    assert registry[0]["source_status"] == "source_metadata_mismatch"
    assert registry[0]["validation_status"] == "source_metadata_mismatch"
    assert registry[0]["local_pdf_path"] == ""
    assert registry[0]["local_text_path"] == ""
    assert report[0]["recommended_action"] == "correct_doi_or_replace_source"
    assert candidates[0]["validation_status"] == "source_metadata_mismatch"
    assert candidates[0]["quarantine"] == "true"
    assert candidates[0]["target_pdf"] == ""


def test_pdf_candidate_title_mismatch_enters_quarantine():
    manifest_rows = [
        {
            "tool_name": "CellTypist",
            "record_id": "REC1",
            "source_title": "A comprehensive benchmarking of cell type annotation methods",
            "source_url": "https://doi.org/10.1/example",
            "doi_or_pmid": "10.1/example",
        }
    ]
    registry = build_source_registry(manifest_rows)

    candidates = build_pdf_candidate_registry(
        manifest_rows,
        source_registry_rows=registry,
        download_summary={
            "rows": [
                {
                    "record_id": "REC1",
                    "status": "dry_run_candidate_found",
                    "candidate_urls": [
                        {
                            "url": "https://example.org/wrong.pdf",
                            "source": "unit_test",
                            "candidate_kind": "primary_article",
                            "candidate_title": "PanomiR systems biology framework for miRNAs",
                        }
                    ],
                }
            ]
        },
    )

    assert candidates[0]["validation_status"] == "source_metadata_mismatch"
    assert candidates[0]["validation_issue"] == "candidate_title_mismatch"
    assert candidates[0]["quarantine"] == "true"


def test_source_registry_marks_existing_pdf_extract_error_as_repair_not_download():
    rows = [
        {
            "tool_name": "Seurat",
            "evidence_kind": "publication",
            "record_id": "CAND_PUB_Seurat_v3_2019_Stuart",
            "source_title": "Comprehensive Integration of Single-Cell Data",
            "source_url": "https://doi.org/10.1016/j.cell.2019.05.031",
            "doi_or_pmid": "10.1016/j.cell.2019.05.031",
            "local_text_path": "",
            "pdf_status": "extract_error",
            "pdf_path": "data/evidence_sources/pdfs/news/Seurat.pdf",
            "notes": "pypdf failed: PdfReadError",
        }
    ]

    registry = build_source_registry(rows)
    report = build_validation_report(registry)

    assert registry[0]["source_status"] == "pdf_extraction_failed"
    assert registry[0]["validation_status"] == "pdf_exists_but_extract_failed"
    assert registry[0]["local_pdf_path"] == "data/evidence_sources/pdfs/news/Seurat.pdf"
    assert report[0]["recommended_action"] == "repair_extractor_or_use_html"
