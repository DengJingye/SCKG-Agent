from __future__ import annotations

import hashlib
import json

from eval.mainline_quality_gate import MainlineQualityGate
from tests.test_research_chat_service import _service


def _package(root, name):
    package = root / name
    package.mkdir(parents=True)
    artifact = package / "artifact.json"
    artifact.write_text('{"ok": true}\n', encoding="utf-8")
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    (package / "reproducibility_manifest.json").write_text(
        json.dumps({"file_hashes": {"artifact.json": digest}}),
        encoding="utf-8",
    )


def test_mainline_gate_checks_modes_blockers_and_both_packages(tmp_path):
    packages = tmp_path / "packages"
    _package(packages, "phase5c-test")
    _package(packages, "phase5-batch-scientific-test")
    service_root = tmp_path / "service"
    service_root.mkdir()
    summary = MainlineQualityGate(
        service=_service(service_root),
        package_root=packages,
    ).run(output_root=tmp_path / "evaluation")

    assert summary.case_count == 6
    assert summary.passed_case_count == 6
    assert summary.unauthorized_execution_request_count == 0
    assert summary.candidate_evidence_leakage_count == 0
    assert summary.doublet_package_integrity is True
    assert summary.batch_package_integrity is True
    assert summary.hard_gate_passed is True
