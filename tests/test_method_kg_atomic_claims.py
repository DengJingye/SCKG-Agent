from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path

import pytest
from pydantic import ValidationError

from core.method_kg_claim_models import (
    ATOMIC_CLAIM_SCHEMA_VERSION,
    AtomicClaim,
    ClaimLinkedRelationCandidate,
    compute_atomic_claim_content_hash,
    compute_claim_relation_id,
    make_atomic_claim_id,
)
from data_pipeline.build_method_kg_atomic_claim_batch1 import (
    DEFAULT_EVIDENCE,
    DEFAULT_OUTPUT_DIR,
    build,
)
from data_pipeline.build_method_kg_batch1_review_packet import build_review_packet


def _jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _valid_claim() -> dict[str, object]:
    values: dict[str, object] = {
        "schema_version": ATOMIC_CLAIM_SCHEMA_VERSION,
        "subject_id": "tool:example",
        "subject_type": "Tool",
        "predicate": "supports_task",
        "object_id": "task:example",
        "object_value": None,
        "object_type": "Task",
        "claim_text": "Example supports an example task.",
        "polarity": "positive",
        "scope": "general",
        "modality": ["scRNA-seq"],
        "version": None,
        "source_span_id": "sourcev2:0123456789abcdef0123",
        "source_id": "SRCV2_example",
        "source_content_hash": "a" * 64,
        "review_status": "candidate_pending_review",
    }
    values["content_hash"] = compute_atomic_claim_content_hash(values)
    values["claim_id"] = make_atomic_claim_id(str(values["content_hash"]))
    return values


def test_atomic_claim_requires_exact_object_and_valid_hash() -> None:
    row = _valid_claim()
    assert AtomicClaim.model_validate(row).claim_id == row["claim_id"]

    invalid_object = dict(row, object_value="duplicate object")
    invalid_object["content_hash"] = compute_atomic_claim_content_hash(invalid_object)
    invalid_object["claim_id"] = make_atomic_claim_id(str(invalid_object["content_hash"]))
    with pytest.raises(ValidationError, match="exactly one"):
        AtomicClaim.model_validate(invalid_object)

    with pytest.raises(ValidationError, match="content_hash"):
        AtomicClaim.model_validate(dict(row, content_hash="b" * 64))


def test_review_status_transition_does_not_change_scientific_claim_identity() -> None:
    row = _valid_claim()
    reviewed = dict(row, review_status="human_reviewed")

    assert compute_atomic_claim_content_hash(reviewed) == row["content_hash"]
    assert AtomicClaim.model_validate(reviewed).claim_id == row["claim_id"]


def test_projected_relation_requires_claim_provenance() -> None:
    row: dict[str, object] = {
        "schema_version": "sckg-method-kg-claim-relation-v1",
        "relation_kind": "method_projection",
        "source_id": "tool:example",
        "source_type": "Tool",
        "relation": "SUPPORTS_TASK",
        "target_id": "task:example",
        "target_type": "Task",
        "derived_from_claim_ids": [],
        "evidence_span_ids": [],
        "review_status": "candidate_pending_review",
    }
    row["relation_id"] = compute_claim_relation_id(row)
    with pytest.raises(ValidationError, match="derived_from_claim_ids"):
        ClaimLinkedRelationCandidate.model_validate(row)


def test_prerequisite_projection_requires_input_and_output_claims() -> None:
    claim_id = str(_valid_claim()["claim_id"])
    row: dict[str, object] = {
        "schema_version": "sckg-method-kg-claim-relation-v1",
        "relation_kind": "method_projection",
        "source_id": "method:upstream",
        "source_type": "Method",
        "relation": "PREREQUISITE",
        "target_id": "method:downstream",
        "target_type": "Method",
        "derived_from_claim_ids": [claim_id],
        "evidence_span_ids": ["sourcev2:0123456789abcdef0123"],
        "review_status": "candidate_pending_review",
    }
    row["relation_id"] = compute_claim_relation_id(row)
    with pytest.raises(ValidationError, match="input and output"):
        ClaimLinkedRelationCandidate.model_validate(row)


def test_batch1_artifacts_are_deterministic_and_candidate_only(tmp_path: Path) -> None:
    canonical_paths = (
        Path("data/canonical_knowledge/manifest.json"),
        Path("data/knowledge_graph_v2/nodes.jsonl"),
        Path("data/knowledge_graph_v2/edges.jsonl"),
        Path("data/decision_graph_v3/nodes.jsonl"),
        Path("data/decision_graph_v3/edges.jsonl"),
    )
    canonical_before = {path: path.read_bytes() for path in canonical_paths}

    manifest = build(evidence_path=DEFAULT_EVIDENCE, output_dir=tmp_path)

    assert manifest["canonical_kg_modified"] is False
    assert manifest["retrieval_index_rebuilt"] is False
    assert manifest["claim_count"] == 48
    assert manifest["relation_count"] == 196
    assert manifest["evidence_gap_count"] == 13
    for filename in manifest["artifacts"]:
        assert (tmp_path / filename).read_bytes() == (DEFAULT_OUTPUT_DIR / filename).read_bytes()
    assert {path: path.read_bytes() for path in canonical_paths} == canonical_before


def test_batch1_claims_are_source_bound_resolvable_and_hash_valid() -> None:
    evidence = {row["chunk_id"]: row for row in _jsonl(DEFAULT_EVIDENCE)}
    claims = [AtomicClaim.model_validate(row) for row in _jsonl(DEFAULT_OUTPUT_DIR / "atomic_claims.batch1.jsonl")]

    assert len({claim.claim_id for claim in claims}) == len(claims) == 48
    assert {claim.subject_id for claim in claims} == {
        "method:hvg_selection",
        "method:pca",
        "method:neighbor_graph_construction",
        "method:umap",
        "method:leiden",
        "tool:harmony",
        "tool:scanorama",
        "tool:scrublet",
        "tool:celltypist",
        "tool:singler",
    }
    for claim in claims:
        span = evidence[claim.source_span_id]
        assert span["source_bound"] is True
        assert span["source_kind"] == "source_document"
        assert span["source_id"] == claim.source_id
        assert span["content_hash"] == claim.source_content_hash
        assert claim.content_hash == compute_atomic_claim_content_hash(claim.model_dump())
        assert claim.review_status == "candidate_pending_review"


def test_batch1_relation_topology_and_projection_provenance() -> None:
    claims = [AtomicClaim.model_validate(row) for row in _jsonl(DEFAULT_OUTPUT_DIR / "atomic_claims.batch1.jsonl")]
    relations = [
        ClaimLinkedRelationCandidate.model_validate(row)
        for row in _jsonl(DEFAULT_OUTPUT_DIR / "claim_linked_relations.batch1.jsonl")
    ]
    claim_ids = {claim.claim_id for claim in claims}
    evidence_by_claim = {claim.claim_id: claim.source_span_id for claim in claims}

    assert len({relation.relation_id for relation in relations}) == len(relations) == 196
    assert sum(relation.relation == "SUPPORTS" for relation in relations) == len(claims)
    assert sum(relation.relation == "SUBJECT" for relation in relations) == len(claims)
    assert sum(relation.relation == "OBJECT" for relation in relations) == len(claims)
    projections = [relation for relation in relations if relation.relation_kind == "method_projection"]
    assert len(projections) == len(claims) + 4
    for relation in projections:
        assert relation.derived_from_claim_ids
        assert relation.evidence_span_ids
        assert set(relation.derived_from_claim_ids) <= claim_ids
        assert {
            evidence_by_claim[claim_id] for claim_id in relation.derived_from_claim_ids
        } <= set(relation.evidence_span_ids)
        if relation.relation == "PREREQUISITE":
            assert len(relation.derived_from_claim_ids) == 2


def test_batch1_quality_gates_pass_but_promotion_remains_blocked() -> None:
    quality = json.loads((DEFAULT_OUTPUT_DIR / "provenance_quality_report.json").read_text())
    gaps = json.loads((DEFAULT_OUTPUT_DIR / "evidence_gaps.batch1.json").read_text())

    assert all(gate["passed"] for gate in quality["quality_gates"].values())
    assert quality["canonical_promotion_eligible_claim_ids"] == []
    assert quality["technically_valid_candidate_claim_ids"]
    assert quality["promotion_status"] == "candidate_only_human_review_required"
    assert len(gaps) == 13
    assert {issue["issue"] for issue in quality["baseline_integrity_issues"]} == {
        "source_bound_projection_mismatch",
        "scanpy_contract_missing_from_decision_snapshot",
        "stale_celltypist_singler_contract_versions",
        "input_fingerprint_drift",
        "scvi_vs_scvi_tools_identity",
        "monocle_vs_monocle3_identity",
    }


def test_human_review_packet_is_complete_blank_and_non_mutating(tmp_path: Path) -> None:
    for filename in (
        "atomic_claims.batch1.jsonl",
        "claim_linked_relations.batch1.jsonl",
        "provenance_quality_report.json",
    ):
        shutil.copy2(DEFAULT_OUTPUT_DIR / filename, tmp_path / filename)
    claims_before = (tmp_path / "atomic_claims.batch1.jsonl").read_bytes()
    relations_before = (tmp_path / "claim_linked_relations.batch1.jsonl").read_bytes()

    manifest = build_review_packet(candidate_dir=tmp_path, evidence_path=DEFAULT_EVIDENCE)

    with (tmp_path / "human_review_batch1.tsv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    with (tmp_path / "derived_prerequisite_review.tsv").open(
        encoding="utf-8", newline=""
    ) as handle:
        chains = list(csv.DictReader(handle, delimiter="\t"))
    assert len(rows) == manifest["claim_count"] == 48
    assert len(chains) == manifest["derived_prerequisite_count"] == 4
    assert manifest["review_decision_count"] == 0
    assert all(row["source_local_wording"] for row in rows)
    assert all(row["exact_evidence_locator"] for row in rows)
    assert all(row["projected_kg_relation"] for row in rows)
    assert all(row["review_decision"] == row["reviewer_reason"] == "" for row in rows)
    assert all(chain["producer_claim_id"] and chain["consumer_claim_id"] for chain in chains)
    assert all(
        chain["review_decision"] == chain["reviewer_reason"] == "" for chain in chains
    )
    assert (tmp_path / "atomic_claims.batch1.jsonl").read_bytes() == claims_before
    assert (tmp_path / "claim_linked_relations.batch1.jsonl").read_bytes() == relations_before
