from data_pipeline.ingest_evidence_pdfs import discover_pdf_files, ingest_pdfs


def test_discover_pdf_files_recurses_and_skips_quarantine(tmp_path):
    root_pdf = tmp_path / "root.pdf"
    nested_pdf = tmp_path / "news" / "nested.pdf"
    quarantined_pdf = tmp_path / "quarantine_bad_candidates" / "bad.pdf"
    nested_pdf.parent.mkdir()
    quarantined_pdf.parent.mkdir()
    for path in (root_pdf, nested_pdf, quarantined_pdf):
        path.write_bytes(b"%PDF-1.4\n")

    discovered = [path.relative_to(tmp_path).as_posix() for path in discover_pdf_files(tmp_path)]

    assert discovered == ["news/nested.pdf", "root.pdf"]


def test_ingest_pdfs_skips_bad_candidate_override(tmp_path):
    pdf_dir = tmp_path / "pdfs"
    pdf_dir.mkdir()
    (pdf_dir / "CellTypist_HR_BMK_CellTypist_annotation_2023.pdf").write_bytes(b"%PDF-1.4\n")
    rows = [
        {
            "tool_name": "CellTypist",
            "evidence_kind": "benchmark",
            "record_id": "HR_BMK_CellTypist_annotation_2023",
            "source_title": "Wrong candidate",
            "local_text_path": str(tmp_path / "text.txt"),
        }
    ]

    summary = ingest_pdfs(
        rows,
        pdf_dir=pdf_dir,
        bad_candidate_rows=[
            {
                "record_id": "HR_BMK_CellTypist_annotation_2023",
                "issue": "metadata_mismatch_pdf_title_or_doi",
                "notes": "PanomiR mismatch",
            }
        ],
    )

    assert summary["bad_candidate_override_rows"] == 1
    assert summary["matched_rows"] == 0
    assert summary["rows"][0]["pdf_status"] == "bad_candidate_override"
    assert summary["rows"][0]["candidate_issue"] == "metadata_mismatch_pdf_title_or_doi"
