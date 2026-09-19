import json
from observability.research_source_links import source_links


def test_exact_identity_not_title_and_no_mutation(tmp_path):
    p = tmp_path / "sources.jsonl"
    p.write_text(json.dumps({"source_id": "s1", "canonical_title": "Official source",
                             "source_url": "https://example.org/paper"}))
    refs = [{"source_id": "s1", "index": 1, "source_span": "page:13"},
            {"source_id": "missing", "title": "Official source", "index": 2}]
    before = json.dumps(refs)
    result = source_links(refs, p)
    assert len(result) == 1
    assert result[0]["locator"] == "page:13"
    assert result[0]["url"] == "https://example.org/paper"
    assert json.dumps(refs) == before


def test_unsafe_or_ambiguous_sources_not_linked(tmp_path):
    p = tmp_path / "sources.jsonl"
    rows = [{"source_id": "bad", "source_url": "javascript:alert(1)"},
            {"source_id": "ambiguous", "source_url": "https://one.org"},
            {"source_id": "ambiguous", "source_url": "https://two.org"},
            {"source_id": "credentials", "source_url": "https://secret:key@example.org"}]
    p.write_text("\n".join(map(json.dumps, rows)))
    assert source_links([{"source_id": x} for x in ("bad", "ambiguous", "credentials")], p) == []


def test_missing_or_corrupt_manifest_is_not_fabricated(tmp_path):
    p = tmp_path / "sources.jsonl"
    assert source_links([{"source_id": "s1"}], p) == []
    p.write_text("broken")
    assert source_links([{"source_id": "s1"}], p) == []
