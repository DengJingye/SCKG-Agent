from __future__ import annotations

import csv
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data/evaluation/scientific_knowledge_studio_v1"


def _json(name: str):
    return json.loads((OUTPUT / name).read_text(encoding="utf-8"))


def test_deliverable_set_is_complete_and_contains_no_pdf_or_full_text_dump() -> None:
    expected = {
        "manifest.json", "source_proposal.json", "evidence_summary.json",
        "proposal_summary.json", "candidate_diff.json", "validation_summary.json",
        "proposal_graph.json", "run_trace.json", "focused_test_summary.json",
        "regression_summary.json", "integrity.json", "human_sanity_review_template.csv",
        "human_sanity_review_summary.json",
    }
    assert {path.name for path in OUTPUT.iterdir() if path.is_file()} == expected
    assert not list(OUTPUT.glob("*.pdf"))
    assert not list(OUTPUT.glob("*full*text*"))


def test_first_real_pdf_run_is_page_preserving_and_has_exact_evidence() -> None:
    manifest = _json("manifest.json")
    evidence = _json("evidence_summary.json")
    assert manifest["page_count"] == 26
    assert manifest["parsed_pages"] == 26
    assert manifest["parse_gaps"] == 0
    assert manifest["evidence_span_proposals"] == 16
    assert any(row["validation_status"] == "VALID" for row in evidence["evidence_span_proposals"])
    segments = {row["segment_id"]: row for row in evidence["segments"]}
    for span in evidence["evidence_span_proposals"]:
        segment = segments[span["segment_id"]]
        assert segment["exact_text"][span["start_offset"] : span["end_offset"]] == span["exact_text"]


def test_real_semantic_proposals_are_structured_and_evidence_bound() -> None:
    proposal = _json("proposal_summary.json")
    assert len(proposal["entity_proposals"]) == 1
    assert len(proposal["atomic_claim_proposals"]) == 8
    assert len(proposal["scope_proposals"]) == 8
    assert proposal["relation_proposals"] == []
    assert proposal["real_llm_extraction"] == "NOT_RUN"
    evidence_ids = {row["proposal_id"] for row in _json("evidence_summary.json")["evidence_span_proposals"]}
    for group in ["entity_proposals", "atomic_claim_proposals", "scope_proposals"]:
        for row in proposal[group]:
            assert row["supporting_evidence_span_ids"]
            assert set(row["supporting_evidence_span_ids"]) <= evidence_ids


def test_invalid_items_are_preserved_instead_of_hidden() -> None:
    manifest = _json("manifest.json")
    validation = _json("validation_summary.json")
    assert manifest["validation"] == {"VALID": 23, "NEEDS_REVIEW": 0, "INVALID": 10}
    assert validation["counts"] == {"VALID": 23, "INVALID": 10}
    assert manifest["relation_proposals"] == 0


def test_identity_resolution_is_explicit_and_exact() -> None:
    manifest = _json("manifest.json")
    entity = _json("proposal_summary.json")["entity_proposals"][0]
    assert manifest["identity_resolution"]["EXACT_EXISTING_IDENTITY"] == 1
    assert entity["identity_resolution_status"] == "EXACT_EXISTING_IDENTITY"
    assert entity["existing_candidate_ids"] == ["software-project:soupx"]


def test_candidate_diff_uses_preview_wording_and_live_snapshot_counts() -> None:
    diff = _json("candidate_diff.json")
    assert diff["wording"] == "If accepted, proposed delta would be…"
    assert (diff["current_nodes"], diff["current_edges"], diff["current_candidate_claims"]) == (1651, 2429, 380)
    assert diff["entity_proposals"] == 1
    assert diff["relation_proposals"] == 0
    assert diff["atomic_claim_proposals"] == 8
    assert diff["evidence_span_proposals"] == 16


def test_run_trace_has_exact_eight_stage_order_and_hashes() -> None:
    trace = _json("run_trace.json")
    assert [row["stage"] for row in trace] == [
        "UPLOAD", "SOURCE_IDENTITY", "PARSE", "EVIDENCE_PROPOSAL",
        "SEMANTIC_EXTRACTION", "IDENTITY_RESOLUTION", "VALIDATION", "PREVIEW",
    ]
    assert all(len(row["content_hash"]) == 64 for row in trace)


def test_proposal_graph_contains_existing_new_evidence_and_source_classes() -> None:
    graph = _json("proposal_graph.json")
    classes = {row["visual_class"] for row in graph["nodes"]}
    assert {"EXISTING_KG", "NEW_PROPOSAL", "EVIDENCE_SPAN", "SOURCE"} <= classes
    ids = {row["node_id"] for row in graph["nodes"]}
    assert all(row["source"] in ids and row["target"] in ids for row in graph["edges"])


def test_integrity_covers_all_required_protected_groups() -> None:
    integrity = _json("integrity.json")
    assert integrity["status"] == "PASS"
    assert set(integrity["groups"]) == {
        "scientific_kg", "legacy_kg", "decision_graph", "rag_corpus", "rag_index",
        "planner", "benchmark_gold", "tool_contracts", "capability_packs",
    }
    flags = [key for key in integrity if key.endswith("_CHANGED") or key.endswith("_MUTATED")]
    assert flags
    assert all(integrity[key] is False for key in flags)
    assert integrity["quarantined_c7_payload_accessed"] is False


def test_human_sanity_sheet_records_user_supplied_bounded_review() -> None:
    with (OUTPUT / "human_sanity_review_template.csv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    counts = {}
    for row in rows:
        counts[row["item_type"]] = counts.get(row["item_type"], 0) + 1
        assert row["human_status"] in {"CORRECT", "PARTIAL", "INCORRECT", "UNCERTAIN"}
        assert row["human_notes"].strip()
    assert all(value <= 10 for value in counts.values())
    assert counts == {"entity": 1, "claim": 8, "evidence": 10}

    summary = _json("human_sanity_review_summary.json")
    assert summary["reviewer_source"] == "user_supplied_semantic_sanity_review"
    assert summary["status"] == "COMPLETED_PENDING_PDF_PAGE_CONFIRMATION"
    assert summary["not_formal_benchmark"] is True
    assert summary["not_ingestion_eval"] is True
    assert summary["final_pdf_page_confirmation_required"] is True
    assert summary["counts_by_type"] == {
        "entity": {"CORRECT": 0, "PARTIAL": 1, "INCORRECT": 0, "UNCERTAIN": 0, "total": 1},
        "claim": {"CORRECT": 3, "PARTIAL": 4, "INCORRECT": 1, "UNCERTAIN": 0, "total": 8},
        "evidence": {"CORRECT": 6, "PARTIAL": 3, "INCORRECT": 1, "UNCERTAIN": 0, "total": 10},
        "overall": {"CORRECT": 9, "PARTIAL": 8, "INCORRECT": 2, "UNCERTAIN": 0, "total": 19},
    }
    assert summary["findings"]["real_llm_extraction"] == "NOT_RUN"
    assert summary["candidate_staging_recommended_now"] is False


def test_review_annotations_do_not_create_governance_decisions() -> None:
    manifest = _json("manifest.json")
    assert manifest["human_sanity_review"] == "COMPLETED_PENDING_PDF_PAGE_CONFIRMATION"
    assert manifest["human_sanity_reviewer_source"] == "user_supplied_semantic_sanity_review"
    assert manifest["review_decision_created"] is False
    assert manifest["canonical_promotion"] == "none"
    assert manifest["trusted_knowledge_created"] is False


def test_committed_snapshot_contains_no_absolute_host_path_or_secret() -> None:
    for path in OUTPUT.iterdir():
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        assert "/Users/" not in text
        assert "file://" not in text
        assert "api_key" not in text.casefold()
        assert "bearer " not in text.casefold()
