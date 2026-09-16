from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.trace_context import load_traces
from data_pipeline import build_candidate_knowledge_review_queue_v1 as queue


def _json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _jsonl(path: Path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_review_item_exposes_complete_governed_provenance():
    candidate = queue.load_and_validate_candidate()
    item = queue.build_review_item(candidate)
    assert item["knowledge_status"] == "candidate_pending_review"
    assert item["software_context"] == {
        "package": "SoupX",
        "version": "1.6.2",
        "package_release_id": "package-release:soupx:1.6.2",
    }
    assert item["evidence_assessment"]["stance"] == "supports"
    assert item["evidence_span"]["evidence_span_id"].startswith("evidence-span:cp5:")
    assert item["source_artifact"]["sha256"] == (
        "dabbfdf10c0ab46efee927026f77494e1df096999742f86705b91dcd0b1dac19"
    )
    assert item["duplicate_status"]["status"] == "unique"
    assert item["conflict_status"]["status"] == "none_detected"


def test_review_surface_maps_actions_to_existing_governance_records():
    item = queue.build_review_item(queue.load_and_validate_candidate())
    assert item["allowed_reviewer_actions"] == [
        "PROMOTE",
        "REJECT",
        "NEEDS_REVISION",
        "MERGE",
        "SUPERSEDE",
    ]
    assert item["authoritative_decision_model"] == "sckg-review-decision-v1.1"
    assert item["action_bindings"]["PROMOTE"]["review_decision"] == "accepted"
    assert "KnowledgeChangeSet" in item["action_bindings"]["PROMOTE"]["additional_requirement"]
    assert "SupersessionRecord" in item["action_bindings"]["SUPERSEDE"]["additional_requirement"]


def test_support_and_reuse_cannot_auto_promote_candidate():
    item = queue.build_review_item(queue.load_and_validate_candidate())
    assert item["evidence_assessment"]["stance"] == "supports"
    assert item["provenance"]["prior_candidate_reuse_count"] == 1
    assert item["provenance"]["external_reacquisition_count"] == 0
    assert queue.promotion_gate(item, review_decision=None, knowledge_change_set=None) == {
        "allowed": False,
        "reason": "qualified_review_decision_missing",
    }
    assert item["promotion_guard"]["promotion_allowed_now"] is False
    assert item["promotion_guard"]["execution_authority_granted"] is False


def test_complete_review_queue_and_final_reuse(tmp_path):
    summary = queue.run_review_queue(output_root=tmp_path)
    assert summary["status"] == "PASS"
    assert summary["review_item_count"] == 1
    assert summary["knowledge_status"] == "candidate_pending_review"
    assert summary["canonical_promotion_performed"] is False
    assert summary["review_decision_created"] is False
    assert summary["knowledge_change_set_created"] is False
    assert summary["canonical_snapshot_created"] is False
    assert summary["execution_authority_granted"] is False
    assert summary["final_reuse"]["candidate_claim_reused"] is True
    assert summary["final_reuse"]["evidence_span_reused"] is True
    assert summary["final_reuse"]["source_artifact_reused"] is True
    assert summary["final_reuse"]["external_reacquisition_count"] == 0
    assert summary["final_reuse"]["knowledge_status"] == "candidate_pending_review"
    assert len(_jsonl(tmp_path / "review_queue.jsonl")) == 1
    assert _json(tmp_path / "provenance_audit.json")["broken_id_count"] == 0


def test_review_trace_is_bounded_and_reconstructable(tmp_path):
    queue.run_review_queue(output_root=tmp_path)
    traces = load_traces(tmp_path / "trace.jsonl")
    assert len(traces) == 1
    assert [span["stage"] for span in traces[0]["spans"]] == [
        "REQUEST",
        "STATE_INSPECTION",
        "VALIDATION",
        "RETRIEVAL",
        "DECISION",
        "VALIDATION",
    ]
    raw = (tmp_path / "trace.jsonl").read_text(encoding="utf-8")
    assert "tod Table of droplets" not in raw
    assert "/Users/" not in raw
    assert "review-item:cp7:soupx:soupchannel-inputs:1.6.2" in raw
    assert "candidate_pending_review" in raw


def test_review_queue_is_write_once(tmp_path):
    queue.run_review_queue(output_root=tmp_path)
    with pytest.raises(FileExistsError, match="already_completed"):
        queue.run_review_queue(output_root=tmp_path)
