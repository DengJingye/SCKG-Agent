from data_pipeline.build_core_tool_source_manifest import build_manifest_rows
from data_pipeline.fetch_evidence_sources import fetch_sources
from data_pipeline.github_crawler import decode_github_readme_content


def test_core_source_manifest_builds_retrieval_only_github_readme_row():
    rows, summary = build_manifest_rows(
        [
            {
                "Tool": "Scanpy",
                "Code": "https://github.com/theislab/scanpy",
                "Platform": "Python",
            }
        ],
        core_tools=["Scanpy"],
    )

    assert summary["manifest_rows"] == 1
    row = rows[0]
    assert row["tool_name"] == "Scanpy"
    assert row["preferred_source_type"] == "github_readme"
    assert row["local_text_path"] == "data/evidence_sources/text/core_docs/Scanpy_github_readme.txt"
    assert "retrieval-only" in row["notes"]
    assert "does not promote formal evidence" in row["notes"]


def test_fetch_sources_uses_github_readme_fetcher(monkeypatch, tmp_path):
    long_readme = "Scanpy analyzes single-cell RNA-seq data with AnnData objects.\n\n" * 20

    class FakeGitHubCrawler:
        def fetch_readme_text(self, url, timeout=15):
            return {
                "repo_full_name": "theislab/scanpy",
                "readme_path": "README.md",
                "source_url": "https://github.com/theislab/scanpy/blob/main/README.md",
                "download_url": "https://raw.githubusercontent.com/theislab/scanpy/main/README.md",
                "text": long_readme,
            }

    import data_pipeline.fetch_evidence_sources as fetch_module

    monkeypatch.setattr(fetch_module, "GitHubCrawler", FakeGitHubCrawler)
    local_path = tmp_path / "scanpy_readme.txt"
    rows = [
        {
            "source_id": "SRC_CORE_1",
            "evidence_kind": "docs",
            "tool_name": "Scanpy",
            "record_id": "CORE_DOCS_Scanpy_github_readme",
            "source_title": "Scanpy official GitHub README",
            "source_url": "https://github.com/theislab/scanpy",
            "doi_or_pmid": "",
            "preferred_source_type": "github_readme",
            "local_text_path": str(local_path),
            "fetch_status": "not_fetched",
            "fetch_priority": "1",
            "notes": "",
        }
    ]

    summary = fetch_sources(rows, timeout=5)

    assert summary["fetched_github_readme"] == 1
    assert rows[0]["fetch_status"] == "fetched_github_readme"
    assert rows[0]["source_url"].endswith("/README.md")
    assert "AnnData objects" in local_path.read_text(encoding="utf-8")


def test_decode_github_readme_content_base64():
    decoded = decode_github_readme_content({"encoding": "base64", "content": "SGVsbG8gc2NLRwo="})

    assert decoded == "Hello scKG\n"
