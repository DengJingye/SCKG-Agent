from __future__ import annotations

import hashlib
import json
from pathlib import Path

from core.scientific_knowledge_conformance_models import ReferenceArtifact
from core.settings import PROJECT_ROOT
from data_pipeline.build_knowledge_foundation_p0b import (
    AUDIT_DIR,
    AUTHORITATIVE_SOURCE_MANIFEST,
    CORE_DIR,
    DEFAULT_OUTPUT_DIR,
    SOURCE_DOCUMENTS,
    UAT_DIR,
    build,
)
from data_pipeline.build_scientific_knowledge_conformance_v1_1 import CANONICAL_PATHS
from eval.knowledge_foundation_p0a import evaluate_knowledge_foundation_p0a


def _json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _jsonl(path: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_p0b_build_is_deterministic_and_has_no_canonical_side_effect(tmp_path: Path) -> None:
    before = {path: _sha(path) for path in CANONICAL_PATHS if path.exists()}
    generated = build(tmp_path)
    frozen = _json(DEFAULT_OUTPUT_DIR / "manifest.json")

    assert generated == frozen
    assert {path: _sha(path) for path in CANONICAL_PATHS if path.exists()} == before
    assert generated["canonical_promotion"] == "none"
    assert generated["retrieval_index_rebuilt"] is False
    for name, digest in generated["artifacts"].items():
        assert _sha(tmp_path / name) == digest
        assert (tmp_path / name).read_bytes() == (DEFAULT_OUTPUT_DIR / name).read_bytes()


def test_all_seventeen_canonical_software_documents_are_content_audited() -> None:
    rows = _jsonl(DEFAULT_OUTPUT_DIR / "source_revision_hardening.jsonl")

    assert len(rows) == 17
    assert len({row["source_document_id"] for row in rows}) == 17
    assert sum(row["content_integrity_status"] == "verified" for row in rows) == 16
    assert sum(row["content_integrity_status"] == "unresolved" for row in rows) == 1
    assert all(row["promotion_eligible"] is False for row in rows)
    assert sum(row["pinned_authoritative_revision"] is not None for row in rows) == 4
    assert not any(
        row["upstream_version_status"] == "immutable_locator_and_content_digest"
        for row in rows
        if not any(
            marker in row["origin_url"]
            for marker in ("/blob/v", "/tree/v", "/blob/refs/tags/")
        )
    )


def test_reference_artifact_families_validate_without_fabricated_revisions() -> None:
    rows = _jsonl(DEFAULT_OUTPUT_DIR / "reference_artifact_candidates.jsonl")
    requirements = _json(DEFAULT_OUTPUT_DIR / "reference_artifact_requirements.json")[
        "requirements"
    ]

    assert {row["ecosystem"] for row in rows} == {"CellTypist", "SingleR", "pySCENIC"}
    assert len(rows) == 6
    for row in rows:
        payload = {
            key: value
            for key, value in row.items()
            if key not in {"ecosystem", "knowledge_status", "review_status"}
        }
        ReferenceArtifact.model_validate(payload)
        assert row["knowledge_status"] == "candidate"
        assert row["review_status"] == "candidate_pending_review"
    assert all(row["reference_artifact_revision_id"] is None for row in requirements)
    assert all(row["applicability_action"] == "clarify_or_block" for row in requirements)
    assert any(
        row["revision_resolution_status"] == "schema_kind_and_evidence_gap"
        for row in requirements
    )


def test_only_three_required_compatibility_closures_are_packaged_and_none_is_actionable() -> None:
    packets = _jsonl(DEFAULT_OUTPUT_DIR / "compatibility_review_packets.jsonl")

    assert {row["closure"] for row in packets} == {
        "Harmony corrected embedding -> Scanpy neighbors",
        "Scanpy neighbor graph -> Leiden",
        "scVelo velocity/transition state -> CellRank",
    }
    assert all(row["actionable"] is False for row in packets)
    assert all(not row["review_decision_ids"] for row in packets)
    assert sum(row["relation"] is not None for row in packets) == 2
    assert sum(row["scientific_evidence_status"] == "evidence_gap" for row in packets) == 1
    assert all(
        row["proof"]["type_equality_only"] is False
        for row in packets
        if row["proof"] is not None
    )


def test_readiness_matrix_is_recomputed_without_gaming_production_readiness() -> None:
    result = _json(DEFAULT_OUTPUT_DIR / "core_tool_coverage_after.json")
    before = _json(AUDIT_DIR / "core_tool_coverage.json")

    assert result["summary_before"] == before["summary"]
    assert result["summary_after"] == before["summary"]
    assert result["summary_after"]["planning_ready"] == {"numerator": 3, "denominator": 14}
    assert result["summary_after"]["authoritative_evidence_ready"] == {
        "numerator": 13,
        "denominator": 14,
    }
    assert all(row["p0b_readiness_change"] == "none" for row in result["paths"])


def test_summary_passes_containment_gates_and_preserves_p0a() -> None:
    summary = _json(DEFAULT_OUTPUT_DIR / "summary.json")
    p0a = evaluate_knowledge_foundation_p0a()

    assert summary["decision"] == "PASS_WITH_REMAINING_GAPS"
    assert all(summary["gates"].values())
    assert summary["compatibility"]["actionable_unreviewed_CAN_FEED"] == 0
    assert summary["safety"]["candidate_to_trusted_leakage"] == 0
    assert summary["safety"]["canonical_promotion"] == "none"
    assert summary["reference_artifacts"]["fabricated_reference_artifact_revisions"] == 0
    assert p0a["decision"] == "PASS"


def test_manifest_pins_all_frozen_inputs_and_contains_no_absolute_paths() -> None:
    manifest = _json(DEFAULT_OUTPUT_DIR / "manifest.json")

    assert manifest["frozen_inputs"] == {
        "audit_core_tool_coverage_sha256": _sha(AUDIT_DIR / "core_tool_coverage.json"),
        "authoritative_source_manifest_sha256": _sha(AUTHORITATIVE_SOURCE_MANIFEST),
        "core_conformance_bundle_sha256": _sha(CORE_DIR / "conformance_bundle.json"),
        "core_source_manifest_sha256": _sha(CORE_DIR / "source_manifest.json"),
        "source_documents_v2_sha256": _sha(SOURCE_DOCUMENTS),
        "uat_relations_sha256": _sha(UAT_DIR / "derived_relations.jsonl"),
    }
    for path in DEFAULT_OUTPUT_DIR.iterdir():
        if path.is_file():
            assert str(PROJECT_ROOT) not in path.read_text(encoding="utf-8")
