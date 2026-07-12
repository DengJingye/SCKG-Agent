from data_pipeline.download_evidence_pdfs import apply_bad_candidate_overrides


def test_pdf_downloader_quarantines_known_bad_candidate_url():
    candidates = [
        {
            "url": "https://academic.oup.com/bib/article-pdf/24/6/bbad418/53617507/bbad418.pdf",
            "source": "crossref_metadata_link",
            "candidate_kind": "primary_article",
        },
        {
            "url": "https://example.org/correct.pdf",
            "source": "unit_test",
            "candidate_kind": "primary_article",
        },
    ]

    valid, quarantined = apply_bad_candidate_overrides(
        candidates,
        {
            "invalid_url": "https://academic.oup.com/bib/article-pdf/24/6/bbad418/53617507/bbad418.pdf",
            "issue": "metadata_mismatch_pdf_title_or_doi",
        },
    )

    assert [row["url"] for row in valid] == ["https://example.org/correct.pdf"]
    assert quarantined[0]["issue"] == "metadata_mismatch_pdf_title_or_doi"
