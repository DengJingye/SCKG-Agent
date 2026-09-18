from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = (
    ROOT
    / "data/evaluation/celltypist_runtime_qualification_v1/manifest.json"
)
EXPECTED_MODEL_SHA = (
    "290874d35dac039d4c9218c343fde4aac"
    "1077709b72a331ce7266f6828c36502"
)


def _payload() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def test_celltypist_qualification_freezes_exact_alias_artifact_binding():
    payload = _payload()
    reference = payload["reference_pack"]

    assert payload["status"] == "PASS"
    assert payload["candidate_only"] is True
    assert reference["contract_alias"] == "celltypist-immune-all-low-v1"
    assert reference["resolved_artifact"] == "Immune_All_Low.pkl"
    assert reference["resolved_artifact_version"] == "v2"
    assert reference["artifact_sha256"] == EXPECTED_MODEL_SHA
    assert "unchanged" in reference["alias_resolution"]


def test_celltypist_qualification_uses_compatible_isolated_runtime():
    payload = _payload()
    runtime = payload["runtime"]

    assert runtime["python"] == "3.9.23"
    assert runtime["celltypist"] == "1.7.1"
    assert runtime["scikit_learn"] == "0.24.1"
    assert runtime["conda_explicit_sha256"]
    assert all(payload["checks"].values())


def test_celltypist_feature_compatibility_and_determinism_are_explicit():
    payload = _payload()
    smoke = payload["smoke"]

    assert smoke["executions"] == smoke["successful_executions"] == 2
    assert smoke["compatible_overlap_genes"] == 6639
    assert smoke["compatible_overlap_rate"] == 1.0
    assert smoke["incompatible_overlap_genes"] == 0
    assert smoke["incompatible_blocker"] == "reference_gene_overlap_insufficient"
    assert len(smoke["output_digests"]) == 4


def test_celltypist_qualification_does_not_claim_planner_or_promotion_readiness():
    payload = _payload()

    assert set(payload["boundaries"].values()) == {False}
    assert payload["scope"]["species"] == "human"
    assert payload["scope"]["biological_scope"] == "pan-immune"
    assert "all tissues" in payload["scope"]["not_asserted"]


def test_celltypist_committed_audit_has_no_host_local_absolute_paths():
    text = MANIFEST.read_text(encoding="utf-8")

    assert "/Users/" not in text
    assert "/tmp/" not in text
