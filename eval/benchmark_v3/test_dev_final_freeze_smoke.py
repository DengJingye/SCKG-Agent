"""Engineering invariants for the final DEV freeze smoke."""
import json

from eval.benchmark_v3.dev_final_freeze_smoke import RUN_MATRIX, RUNTIME_COMMIT
from eval.benchmark_v3.dev_pilot import BASE, sha
from eval.benchmark_v3.dev_scoring import validate_receipts


OUTPUT = BASE / "dev_final_freeze_smoke_20260921"


def test_exact_authorized_run_matrix():
    assert RUN_MATRIX == {
        "dev-K04-evidence-version-b": (
            "llm_only",
            "generic_rag",
            "legacy_kg",
            "scientific_kg",
        ),
        "dev-K01-hvg-input-a": ("generic_rag", "scientific_kg"),
        "dev-K03-reference-annotation-b": ("generic_rag", "scientific_kg"),
    }
    assert sum(map(len, RUN_MATRIX.values())) == 8


def test_manifest_matches_exact_matrix_and_frozen_inputs_when_available():
    if not (OUTPUT / "manifest.json").exists():
        return
    manifest = json.loads((OUTPUT / "manifest.json").read_text())
    assert manifest["implementation_commit"] == RUNTIME_COMMIT
    assert len(manifest["schedule"]) == 8
    pairs = {(row["case_id"], row["lane"]) for row in manifest["schedule"]}
    assert pairs == {(case_id, lane) for case_id, lanes in RUN_MATRIX.items() for lane in lanes}
    assert not any("dev-K01-hvg-input-b" in row["run_id"] for row in manifest["schedule"])
    assert not any("dev-W01" in row["run_id"] or "dev-W02" in row["run_id"]
                   for row in manifest["schedule"])
    prior = json.loads((BASE / "dev_pilot_20260921/inputs.json").read_text())
    current = json.loads((OUTPUT / "inputs.json").read_text())
    for case_id in RUN_MATRIX:
        assert current[case_id] == prior[case_id]
        hashes = {row["input_sha256"] for row in manifest["schedule"] if row["case_id"] == case_id}
        assert hashes == {sha(current[case_id]["rendered_query"].encode())}


def test_live_receipts_when_available():
    receipts = list((OUTPUT / "runs").glob("*/runtime_receipt.json")) if OUTPUT.exists() else []
    if len(receipts) != 8:
        return
    result = validate_receipts(OUTPUT, 8)
    assert result["pass"], result["errors"]
    assert all(row["status"] == "completed" for row in result["rows"])


def test_recorded_freeze_gates_when_available():
    path = OUTPUT / "freeze_audit.json"
    if not path.exists():
        return
    result = json.loads(path.read_text())
    assert result["status"] == "PASS"
    assert result["runs_completed"] == 8
    assert result["blockers"] == []
    for key in (
        "k04_null_missingness_pass",
        "targeted_clarification_pass",
        "user_fact_authority_pass",
        "mixed_segment_gate_pass",
        "scientific_evidence_gate_pass",
        "lane_isolation_pass",
        "receipt_pass",
        "dev_frozen",
        "ready_for_evaluation_freeze",
    ):
        assert result[key] is True
    assert len(result["k04_audit"]) == 4
    assert all(row["semantic_missing"] for row in result["k04_audit"])
    assert all(row["not_rejected_as_available"] for row in result["k04_audit"])
    assert result["targeted_clarification_observed_lanes"] == ["scientific_kg"]


def test_recorded_authority_and_mixed_segments_when_available():
    path = OUTPUT / "freeze_audit.json"
    if not path.exists():
        return
    result = json.loads(path.read_text())
    assert len(result["authority_audit"]) == 4
    assert all(row["context_present"] for row in result["authority_audit"])
    assert all(row["context_authority_safe"] for row in result["authority_audit"])
    assert all(row["dependency_preserved"] for row in result["authority_audit"])
    assert all(row["final_authority_safe"] for row in result["authority_audit"])
    assert sum(row["raw_mixed_segments"] for row in result["mixed_segment_audit"]) > 0
    assert all(row["pass"] for row in result["mixed_segment_audit"])
    assert all(row["unsplit_mixed_state_claims"] == 0
               for row in result["mixed_segment_audit"])
    assert all(row["user_facts_excluded_from_support_check"]
               for row in result["scientific_evidence_audit"])
    assert all(row["scientific_claims_require_citations"]
               for row in result["scientific_evidence_audit"])
