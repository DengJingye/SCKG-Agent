from __future__ import annotations

import hashlib
import json
from pathlib import Path

from eval.pdf_knowledge_ingestion_capability_audit_v1 import (
    OUTPUT_DIR,
    REPORT_PATH,
    ROOT,
    STATUSES,
    build,
    capability_matrix,
)


def _json(name: str):
    return json.loads((OUTPUT_DIR / name).read_text(encoding="utf-8"))


def _path_like(value: str) -> bool:
    return "/" in value and not value.startswith("No ")


def test_01_every_required_stage_appears_exactly_once() -> None:
    rows = capability_matrix()
    assert len(rows) == 30
    assert [row["stage_number"] for row in rows] == list(range(1, 31))
    assert len({row["stage"] for row in rows}) == 30


def test_02_every_stage_has_one_allowed_status() -> None:
    rows = capability_matrix()
    assert all(row["status"] in STATUSES for row in rows)
    assert {row["status"] for row in rows} <= STATUSES
    assert sum(1 for row in rows if row["status"]) == 30


def test_03_every_implemented_stage_has_owner_or_module_path() -> None:
    implemented = {"IMPLEMENTED_PRODUCTION", "IMPLEMENTED_REUSABLE", "IMPLEMENTED_PILOT"}
    for row in capability_matrix():
        if row["status"] not in implemented:
            continue
        evidence = [row["owner"], *row["existing_implementation"]]
        assert any(_path_like(value) for value in evidence), row["stage"]


def test_04_all_referenced_module_paths_exist() -> None:
    for row in capability_matrix():
        for value in row["existing_implementation"]:
            if value.endswith(".py"):
                assert (ROOT / value).is_file(), (row["stage"], value)


def test_05_artifact_paths_exist_or_are_explicitly_optional() -> None:
    for row in capability_matrix():
        for artifact in row["persistent_artifacts"]:
            assert set(artifact) == {"path", "optional", "purpose"}
            if not artifact["optional"]:
                assert (ROOT / artifact["path"]).exists(), (row["stage"], artifact["path"])


def test_06_export_contains_no_absolute_host_paths() -> None:
    build(focused_tests="test fixture")
    files = [*OUTPUT_DIR.glob("*.json"), REPORT_PATH]
    assert files
    for path in files:
        content = path.read_text(encoding="utf-8")
        assert "/Users/" not in content
        assert "file://" not in content


def test_07_duplicate_authoritative_owners_are_warned() -> None:
    owner_map = _json("authoritative_owner_map.json")
    for row in owner_map["owners"]:
        if row["authoritative_owner"] is None and len(row["implementations"]) > 1:
            assert row["warning"] == "DUPLICATE_OWNER_RISK", row["concept"]


def test_08_unsafe_direct_canonical_mutation_is_flagged() -> None:
    llm = _json("llm_extraction_audit.json")
    relation = next(row for row in capability_matrix() if row["stage"] == "Relation extraction")
    assert llm["UNSAFE_DIRECT_KG_MUTATION"] is True
    assert relation["status"] == "UNSAFE_TO_REUSE"
    assert "UNSAFE_DIRECT_KG_MUTATION" in relation["risks"]


def test_09_soupx_pilot_stages_are_mapped_to_source_and_artifacts() -> None:
    audit = _json("soupX_pipeline_map.json")
    assert len(audit["pipeline"]) == 11
    assert audit["source_code_was_primary_evidence"] is True
    assert audit["candidate_boundary_preserved"] is True
    assert audit["canonical_promotion_performed"] is False
    for expected, row in enumerate(audit["pipeline"], 1):
        assert row["order"] == expected
        assert (ROOT / row["module"]).is_file()
        assert (ROOT / row["artifact"]).exists()


def test_10_minimal_pipeline_references_only_existing_components() -> None:
    pipeline = _json("minimal_reusable_pipeline.json")
    assert pipeline["feasible_as_is"] is False
    for row in pipeline["reuse"]:
        assert (ROOT / row["component"]).is_file(), row
    assert "legacy Neo4j loader" in pipeline["forbidden"]


def test_11_protected_kg_corpus_index_planner_and_gold_are_unchanged() -> None:
    integrity = _json("integrity.json")
    assert integrity["status"] == "PASS"
    assert integrity["changed"] == []
    assert integrity["missing"] == []
    for key in ("kg_content_changed", "corpus_changed", "index_changed", "planner_changed", "gold_changed"):
        assert integrity[key] is False
    assert integrity["canonical_promotion"] == "none"


def test_12_quarantined_c7_payload_was_not_accessed() -> None:
    integrity = _json("integrity.json")
    manifest = _json("manifest.json")
    assert integrity["quarantined_c7_payload_accessed"] is False
    assert manifest["quarantined_c7_payload_accessed"] is False
    assert all("sealed" not in value.casefold() for value in integrity["checked"])


def test_manifest_counts_hashes_and_read_only_exit_are_self_consistent() -> None:
    manifest = _json("manifest.json")
    assert manifest["total_stages"] == 30
    assert manifest["stage_counts"] == {
        "IMPLEMENTED_PILOT": 15,
        "IMPLEMENTED_PRODUCTION": 0,
        "IMPLEMENTED_REUSABLE": 2,
        "MISSING": 2,
        "PARTIAL": 9,
        "UNSAFE_TO_REUSE": 2,
    }
    assert manifest["implemented_or_pilot_stage_count"] == 17
    assert manifest["implemented_or_pilot_percent"] == 56.7
    assert manifest["midterm_single_pdf_demo_feasible"] is False
    assert manifest["audit_mode"] == "read_only"
    assert manifest["stopped"] is True
    for name, expected in manifest["artifacts"].items():
        actual = hashlib.sha256((OUTPUT_DIR / name).read_bytes()).hexdigest()
        assert actual == expected


def test_parser_review_and_candidate_governance_boundaries_are_explicit() -> None:
    parser = _json("pdf_parser_audit.json")
    review = _json("review_lifecycle_audit.json")
    deposit = _json("candidate_deposit_audit.json")

    assert parser["PDF_TEXT_EXTRACTION"] == "READY_WITH_LIMITATIONS"
    assert parser["PAGE_LOCATORS"] == "PARTIAL"
    assert parser["SCANNED_PDF_SUPPORT"] is False
    assert parser["PARSER_VERSION_RECORDED"] is False
    assert review["PROMOTION_UI_ALLOWED"] is False
    assert all(not row["SAFE_FOR_UI"] for row in review["actions"].values())
    assert deposit["candidate_can_overwrite_canonical"] is False
    assert deposit["candidate_can_enter_production_retrieval"] is False
    assert deposit["execution_authorized"] is False
