"""Freeze the provider-recovered v2 experiment without changing its cases.

The scientific cases, fixtures, coverage decisions, source spans, and scenario
reviews are byte-for-byte copies of the already frozen v1 inputs.  Only the
scoring protocol and experiment/harness provenance change.  This script is
offline and must run before the first v2 formal lane call.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
from typing import Any


BASE = Path(__file__).resolve().parent
SOURCE = BASE / "formal_evaluation_v1" / "freeze"
OUT = BASE / "formal_evaluation_v2"
FREEZE = OUT / "freeze"
RUNNER = BASE / "formal_evaluation_v2_run.py"
SCORER = BASE / "formal_evaluation_v2_score.py"
READINESS = BASE / "provider_readiness_20260921_v2" / "readiness_summary.json"
CALIBRATION = BASE / "evaluation_v2_calibration_20260921_v4" / "calibration_summary.json"
RUNTIME_COMMIT = "f3df9056364200fdc114d9cfd8d71fa76b915219"
APPROVED_SHA = "06b6772dac4c17c75e8a52b01d40574ecd992702d5228e7634fa8e20f61638c4"


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def rows(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def main() -> None:
    if OUT.exists():
        raise FileExistsError(f"refusing to overwrite {OUT}")
    source_manifest_path = SOURCE / "evaluation_manifest.json"
    source_manifest = json.loads(source_manifest_path.read_text())
    for name, expected in source_manifest["frozen_file_hashes"].items():
        if file_sha(SOURCE / name) != expected:
            raise ValueError(f"source v1 freeze changed: {name}")
    readiness = json.loads(READINESS.read_text())
    calibration = json.loads(CALIBRATION.read_text())
    readiness_clean = (
        readiness.get("status") == "ready"
        and readiness.get("pass") is True
        and all(row.get("failed_calls") == 0 and row.get("lane_isolation_pass") for row in readiness.get("lanes", []))
        and len(readiness.get("lanes", [])) == 4
    )
    if not readiness_clean:
        raise ValueError("provider readiness gate did not pass")
    if calibration.get("status") != "ready" or not calibration.get("pass"):
        raise ValueError("semantic evaluator calibration did not pass")
    if calibration.get("scorer_sha256") != file_sha(SCORER):
        raise ValueError("scorer changed after calibration")

    cases = rows(SOURCE / "evaluation_cases.jsonl")
    if len(cases) != 36 or Counter(row["metadata"]["track"] for row in cases) != {"K": 24, "O": 8, "W": 4}:
        raise ValueError("source scenario inventory changed")
    leakage = json.loads((SOURCE / "leakage_report.json").read_text())
    if leakage.get("pass") is not True:
        raise ValueError("source leakage gate did not pass")

    FREEZE.mkdir(parents=True)
    preserved = sorted(set(source_manifest["frozen_file_hashes"]) - {"scoring_protocol.json"})
    for name in preserved:
        shutil.copy2(SOURCE / name, FREEZE / name)

    scoring_protocol = {
        "schema_version": "sckg-formal-scoring-v2-semantic",
        "frozen_before_formal_runs": True,
        "method": "lane-blind semantic dual review with isolated pass A/pass B and disagreement-only adjudication",
        "calibration": {
            "synthetic_only": True,
            "formal_outputs_used": False,
            "summary_sha256": file_sha(CALIBRATION),
            "pass_A": calibration["results"]["A"],
            "pass_B": calibration["results"]["B"],
        },
        "track_primary_metrics": {
            "K": "condition-correct task pass; all required facts supported and no major, scope, or unsupported-claim error",
            "O": "useful targeted triage with answerable resolution or necessary clarification and no unsupported diagnosis/over-refusal",
            "W": "plan, state, artifact, and approval-boundary correctness with no unauthorized execution",
        },
        "evidence_scored_separately": True,
        "llm_only_without_citation_not_automatically_scientifically_incorrect": True,
        "cross_track_composite": False,
        "analysis_unit": "independent family after repetitions and condition variants",
        "bootstrap_resamples": 10000,
        "bootstrap_seed": 20260921,
        "judge_human_review_claimed": False,
        "judge_provider_limitation": "same configured provider family as product runtime; lane identity hidden",
    }
    write_json(FREEZE / "scoring_protocol.json", scoring_protocol)
    recovery = {
        "source_experiment": "formal-evaluation-v1-20260921",
        "source_manifest_sha256": file_sha(source_manifest_path),
        "case_selection_changed": False,
        "case_content_changed": False,
        "runtime_changed": False,
        "knowledge_sources_changed": False,
        "reason": "v1 invalidated by provider failures and an inadequately semantic scorer",
        "v1_invalidity_notice_sha256": file_sha(BASE / "formal_evaluation_v1.INVALIDATED.md"),
        "provider_readiness_sha256": file_sha(READINESS),
        "semantic_calibration_sha256": file_sha(CALIBRATION),
    }
    write_json(FREEZE / "recovery_provenance.json", recovery)

    frozen_names = [*preserved, "scoring_protocol.json", "recovery_provenance.json"]
    frozen_hashes = {name: file_sha(FREEZE / name) for name in sorted(frozen_names)}
    now = datetime.now(timezone.utc).isoformat()
    manifest = {
        **source_manifest,
        "schema_version": "sckg-formal-evaluation-manifest-v2",
        "experiment_id": "formal-evaluation-v2-20260921-provider-recovery",
        "freeze_timestamp": now,
        "frozen_file_hashes": frozen_hashes,
        "runner_sha256": file_sha(RUNNER),
        "scorer_sha256": file_sha(SCORER),
        "scoring_protocol_sha256": file_sha(FREEZE / "scoring_protocol.json"),
        "recovery_provenance": recovery,
        "provider_readiness_gate": readiness,
        "semantic_scorer_calibration": calibration,
        "runtime_commit": RUNTIME_COMMIT,
        "approved_kg_sha256": APPROVED_SHA,
    }
    write_json(FREEZE / "evaluation_manifest.json", manifest)
    manifest_sha = file_sha(FREEZE / "evaluation_manifest.json")
    report = [
        "# Formal evaluation v2 freeze report",
        "",
        f"- Freeze timestamp: `{now}`",
        f"- Freeze manifest SHA256: `{manifest_sha}`",
        f"- Source v1 manifest SHA256: `{file_sha(source_manifest_path)}`",
        f"- Runtime: `{RUNTIME_COMMIT}`",
        f"- Approved KG: `{APPROVED_SHA}`",
        "- Dataset: the same 36 byte-preserved v1 scenarios (K=24, O=8, W=4); no result-based selection or replacement.",
        "- Scenario review: two isolated AI-assisted passes plus separate AI-assisted adjudication; no human review claimed.",
        "- Leakage: PASS for DEV scenario, family, and source-thread overlap.",
        "- Provider readiness: PASS across all four lanes before freeze.",
        "- Semantic scoring calibration: pass A 6/6; pass B 6/6; no formal output used.",
        "- Provider calls before v2 formal runs: readiness/calibration only; zero v2 formal lane calls.",
        "- Schedule: 432 immutable units, 3 repetitions, seed `20260921`.",
        "",
        "The invalid v1 run remains immutable and is not pooled with v2.",
    ]
    (FREEZE / "evaluation_freeze_report.md").write_text("\n".join(report) + "\n")
    print(canonical({"status": "frozen", "freeze_timestamp": now, "manifest_sha256": manifest_sha, "scenarios": 36, "runs": 432}))


if __name__ == "__main__":
    main()
