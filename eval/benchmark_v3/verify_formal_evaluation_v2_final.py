"""Verify final v2 scoring while proving formal product answers were untouched."""
from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path


BASE = Path(__file__).resolve().parent
OUT = BASE / "formal_evaluation_v2"
EXPECTED_RUNS_SHA = "a9a53ae83d105eede38cb681f1d98290d2961d1b865129c1f44524f2c0db0d9b"
EXPECTED_FREEZE_SHA = "7e6f4593b5218c5b5cb0d4770277277cc3b6af48cee487c8959097f47654ff6e"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def runs_digest() -> str:
    value = hashlib.sha256()
    for path in sorted(OUT.glob("runs/**/*")):
        if path.is_file():
            value.update(str(path.relative_to(OUT)).encode())
            value.update(hashlib.sha256(path.read_bytes()).digest())
    return value.hexdigest()


def main() -> None:
    errors = []
    manifest = json.loads((OUT / "freeze/evaluation_manifest.json").read_text())
    for name, expected in manifest["frozen_file_hashes"].items():
        if digest(OUT / "freeze" / name) != expected:
            errors.append(f"frozen hash mismatch: {name}")
    if digest(OUT / "freeze/evaluation_manifest.json") != EXPECTED_FREEZE_SHA:
        errors.append("freeze manifest digest changed")
    actual_runs_sha = runs_digest()
    if actual_runs_sha != EXPECTED_RUNS_SHA:
        errors.append("formal product answer tree changed during scoring recovery")

    receipts = [json.loads(path.read_text()) for path in OUT.glob("runs/*/runtime_receipt.json")]
    lanes = Counter(row["lane"] for row in receipts)
    provider_status = Counter(call["status"] for row in receipts for call in row["provider_calls"])
    if len(receipts) != 432 or lanes != {"llm_only": 108, "generic_rag": 108, "legacy_kg": 108, "scientific_kg": 108}:
        errors.append("formal run inventory mismatch")
    if Counter(row["status"] for row in receipts) != {"completed": 432} or provider_status != {"completed": 578}:
        errors.append("formal run/provider status mismatch")

    completion = json.loads((OUT / "scoring_v2/judge_completion.json").read_text())
    recovery = json.loads((OUT / "scoring_v2/judge_schema_recovery.json").read_text())
    summary = json.loads((OUT / "formal_evaluation_summary.json").read_text())
    scores = [json.loads(line) for line in (OUT / "scoring_v2/run_scores.jsonl").read_text().splitlines() if line.strip()]
    if completion.get("status") != "complete" or completion.get("disagreements") != 167 or completion.get("adjudication_cases") != 25:
        errors.append("adjudication completion mismatch")
    if recovery.get("scientific_judgment_fields_edited_without_adjudication") != 0 or recovery.get("invalid_rows_replaced_only_after_adjudication") != 64:
        errors.append("schema recovery invariant mismatch")
    if len(scores) != 432 or summary.get("status") != "complete" or summary.get("valid_for_scientific_conclusion") is not True:
        errors.append("final score inventory/validity mismatch")
    if summary.get("provider_failed_calls") != 0 or not summary["metrics"].get("lane_isolation_pass") or not summary["metrics"].get("runtime_receipt_pass"):
        errors.append("final runtime validity gate mismatch")

    result = {
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "freeze_manifest_sha256": EXPECTED_FREEZE_SHA,
        "runs_tree_sha256": actual_runs_sha,
        "formal_product_answers_rerun": False,
        "runs_completed": len(receipts),
        "product_provider_calls": dict(provider_status),
        "scored_runs": len(scores),
        "adjudicated_run_judgments": completion.get("disagreements"),
        "valid_for_scientific_conclusion": summary.get("valid_for_scientific_conclusion"),
    }
    (OUT / "postrun_verification.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    if errors:
        raise SystemExit(json.dumps(errors))
    artifacts = {
        str(path.relative_to(OUT)): digest(path)
        for path in sorted(OUT.rglob("*"))
        if path.is_file() and path.name != "result_index.json"
    }
    (OUT / "result_index.json").write_text(json.dumps({"status": "complete", "freeze_manifest_sha256": EXPECTED_FREEZE_SHA, "artifacts": artifacts}, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
