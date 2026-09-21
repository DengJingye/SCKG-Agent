"""Verify the retained v2 formal run and its explicit scoring blocker."""
from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
from typing import Any


BASE = Path(__file__).resolve().parent
OUT = BASE / "formal_evaluation_v2"
FREEZE = OUT / "freeze"


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def main() -> None:
    manifest = json.loads((FREEZE / "evaluation_manifest.json").read_text())
    errors = []
    for name, expected in manifest["frozen_file_hashes"].items():
        if file_sha(FREEZE / name) != expected:
            errors.append(f"frozen hash mismatch: {name}")
    if file_sha(BASE / "formal_evaluation_v2_run.py") != manifest["runner_sha256"]:
        errors.append("runner hash mismatch")
    if file_sha(BASE / "formal_evaluation_v2_score.py") != manifest["scorer_sha256"]:
        errors.append("scorer hash mismatch")

    receipts = list(OUT.glob("runs/*/runtime_receipt.json"))
    lanes = Counter()
    statuses = Counter()
    provider_calls = Counter()
    for path in receipts:
        receipt = json.loads(path.read_text())
        lanes[receipt["lane"]] += 1
        statuses[receipt["status"]] += 1
        provider_calls.update(call["status"] for call in receipt["provider_calls"])
        isolation = json.loads((path.parent / "lane_isolation.json").read_text())
        if not isolation.get("pass"):
            errors.append(f"lane isolation failed: {receipt['run_id']}")
        for required in ("run_record.json", "output.json", "final_context.json"):
            if not (path.parent / required).exists():
                errors.append(f"missing {required}: {receipt['run_id']}")
    if len(receipts) != 432 or lanes != {"llm_only": 108, "generic_rag": 108, "legacy_kg": 108, "scientific_kg": 108}:
        errors.append("formal receipt inventory mismatch")
    if statuses != {"completed": 432} or provider_calls.get("failed", 0):
        errors.append("formal runtime/provider failure detected")

    review_receipts = list((OUT / "scoring_v2" / "reviews").glob("*/receipt.json"))
    if len(review_receipts) != 72 or any(json.loads(path.read_text()).get("status") != "completed" for path in review_receipts):
        errors.append("semantic review receipt inventory mismatch")
    if any(not (path.parent / "parsed.json").exists() for path in review_receipts):
        errors.append("semantic review parsed output missing")
    attempt_1 = json.loads((OUT / "scoring_v2" / "judge_attempt_1_completion.json").read_text())
    attempt_2 = json.loads((OUT / "scoring_v2" / "judge_attempt_2_completion.json").read_text())
    if attempt_1.get("status") != "blocked" or attempt_2.get("status") != "blocked":
        errors.append("scoring failure attempts were not retained")
    adjudication_receipts = list((OUT / "scoring_v2" / "adjudication").glob("*/receipt.json"))
    adjudication_errors = list((OUT / "scoring_v2" / "adjudication").glob("*/error.json"))
    if len(adjudication_receipts) != 1 or json.loads(adjudication_receipts[0].read_text()).get("status") != "failed":
        errors.append("expected one failed adjudication receipt")
    if len(adjudication_errors) != 1 or json.loads(adjudication_errors[0].read_text()).get("http_status") != 402:
        errors.append("expected retained HTTP 402 adjudication error")

    summary = json.loads((OUT / "formal_evaluation_summary.json").read_text())
    if summary.get("status") != "blocked" or summary.get("scores_emitted") is not False:
        errors.append("blocked summary invariant failed")
    verification = {
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "freeze_manifest_sha256": file_sha(FREEZE / "evaluation_manifest.json"),
        "runs": len(receipts),
        "lanes": dict(lanes),
        "run_statuses": dict(statuses),
        "product_provider_call_statuses": dict(provider_calls),
        "semantic_review_calls": len(review_receipts),
        "adjudication_http_402_retained": not errors or (
            len(adjudication_errors) == 1 and json.loads(adjudication_errors[0].read_text()).get("http_status") == 402
        ),
        "scores_emitted": False,
    }
    write(OUT / "postrun_verification.json", verification)
    if errors:
        raise SystemExit(json.dumps(errors))
    artifacts = {
        str(path.relative_to(OUT)): file_sha(path)
        for path in sorted(OUT.rglob("*"))
        if path.is_file() and path.name != "result_index.json"
    }
    write(OUT / "result_index.json", {"status": "blocked", "freeze_manifest_sha256": verification["freeze_manifest_sha256"], "artifacts": artifacts})
    print(json.dumps(verification, sort_keys=True))


if __name__ == "__main__":
    main()
