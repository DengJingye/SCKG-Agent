"""Recover frozen v2 semantic scoring from judge-output schema defects.

This does not change a scientific judgment.  It drops quote anchors that are
not exact answer substrings and routes any otherwise schema-invalid review row
through the already frozen disagreement adjudication procedure.  Raw provider
responses remain untouched and every substitution is recorded.
"""
from __future__ import annotations

from collections import defaultdict
import argparse
import copy
import importlib.util
import json
import os
from pathlib import Path
import sys
from typing import Any


BASE = Path(__file__).resolve().parent
OUT = BASE / "formal_evaluation_v2"
SCORER_PATH = BASE / "formal_evaluation_v2_score.py"


def load_scorer():
    spec = importlib.util.spec_from_file_location("frozen_formal_evaluation_v2_score", SCORER_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, required=True)
    args = parser.parse_args()
    args.runtime = args.runtime.resolve(); args.env_file = args.env_file.resolve()

    # Serial initialization prevents the concurrent-import defect from the
    # first scoring attempt; it performs no provider call.
    os.environ["SCKG_ENV_FILE"] = str(args.env_file)
    from dotenv import load_dotenv
    load_dotenv(args.env_file, override=False)
    sys.path.insert(0, str(args.runtime))
    from core.settings import get_settings
    from openai import OpenAI  # noqa: F401
    if not (get_settings().openai_api_key or get_settings().deepseek_api_key):
        raise RuntimeError("judge provider credentials unavailable")

    scorer = load_scorer()
    manifest, cases, fixtures = scorer.verify_freeze()
    root = OUT / "scoring_v2"
    blocked = root / "judge_completion.json"
    if blocked.exists():
        attempt = root / "judge_attempt_2_completion.json"
        if attempt.exists():
            raise FileExistsError(attempt)
        blocked.replace(attempt)

    packets = {path.stem: json.loads(path.read_text()) for path in sorted((root / "packets").glob("*.json"))}
    maps = json.loads((root / "blind_maps.json").read_text())
    valid: dict[tuple[str, str], dict[str, Any]] = {}
    invalid: dict[tuple[str, str], dict[str, Any]] = {}
    answer_by_run: dict[str, str] = {}
    quote_drops = []

    for key, packet in packets.items():
        pass_name = key.rsplit("--", 1)[1]
        expected = {row["blind_id"]: {"answer": row["answer"], "rubric": packet["rubric"]} for row in packet["answers"]}
        raw = json.loads((root / "reviews" / key / "parsed.json").read_text())
        for row in raw["judgments"]:
            cleaned = copy.deepcopy(row)
            answer = expected[cleaned["blind_id"]]["answer"]
            answer_by_run[maps[pass_name][cleaned["blind_id"]]] = answer
            original_quotes = cleaned.get("answer_quotes", [])
            cleaned["answer_quotes"] = [quote for quote in original_quotes if isinstance(quote, str) and quote in answer][:2]
            if cleaned["answer_quotes"] != original_quotes:
                quote_drops.append({"packet": key, "blind_id": cleaned["blind_id"], "dropped": len(original_quotes) - len(cleaned["answer_quotes"])})
            run_id = maps[pass_name][cleaned["blind_id"]]
            try:
                scorer.validate_judgments({"judgments": [cleaned]}, {cleaned["blind_id"]: expected[cleaned["blind_id"]]})
                valid[(run_id, pass_name)] = cleaned
            except ValueError as exc:
                invalid[(run_id, pass_name)] = {"row": cleaned, "reason": str(exc), "packet": key}

    disagreements: dict[str, list[dict[str, Any]]] = defaultdict(list)
    run_units = {row["run_id"]: row for row in manifest["schedule"]}
    for run_id, unit in run_units.items():
        left = valid.get((run_id, "A")) or invalid[(run_id, "A")]["row"]
        right = valid.get((run_id, "B")) or invalid[(run_id, "B")]["row"]
        schema_invalid = (run_id, "A") in invalid or (run_id, "B") in invalid
        differs = any(left[field] != right[field] for field in [*scorer.JUDGMENT_FIELDS, "required_fact_status"])
        if schema_invalid or differs:
            case_id = unit["case_id"]
            blind_id = "adjudicate-" + scorer.sha(run_id)[:16]
            output_path = OUT / "runs" / run_id / "output.json"
            output = json.loads(output_path.read_text()) if output_path.exists() else {}
            disagreements[case_id].append({
                "blind_id": blind_id,
                "run_id": run_id,
                "answer": answer_by_run[run_id],
                "citations": scorer.compact_references(output),
                "review_A": left,
                "review_B": right,
                "schema_invalid_passes": [name for name in ("A", "B") if (run_id, name) in invalid],
            })

    adjudicated: dict[str, dict[str, Any]] = {}
    for case_id, rows in sorted(disagreements.items()):
        packet = {
            "schema_version": scorer.JUDGE_SCHEMA_VERSION,
            "case_id": case_id,
            "rubric": scorer.rubric(cases[case_id], fixtures),
            "judgment_template": scorer.judgment_template(),
            "disagreements": [{k: v for k, v in row.items() if k not in {"run_id", "schema_invalid_passes"}} for row in rows],
        }
        directory = root / "adjudication" / case_id
        expected = {row["blind_id"]: {"answer": row["answer"], "rubric": packet["rubric"]} for row in rows}
        if (directory / "validated.json").exists():
            validated = json.loads((directory / "validated.json").read_text())
            scorer.validate_judgments({"judgments": validated}, expected)
        else:
            if directory.exists() and (directory / "receipt.json").exists():
                receipt = json.loads((directory / "receipt.json").read_text())
                if receipt.get("status") == "failed":
                    attempts = root / "adjudication_attempts"
                    attempts.mkdir(exist_ok=True)
                    retained = attempts / f"{case_id}--provider-failure-attempt-1"
                    if retained.exists():
                        raise FileExistsError(retained)
                    directory.replace(retained)
            result = scorer.provider_call(runtime=args.runtime, env_file=args.env_file, system=scorer.adjudication_system_prompt(), payload=packet, directory=directory)
            for judgment in result.get("judgments", []):
                answer = expected[judgment["blind_id"]]["answer"]
                judgment["answer_quotes"] = [quote for quote in judgment.get("answer_quotes", []) if isinstance(quote, str) and quote in answer][:2]
            validated = scorer.validate_judgments(result, expected)
            write_json(directory / "validated.json", validated)
        by_blind = {row["blind_id"]: row for row in rows}
        for judgment in validated:
            adjudicated[by_blind[judgment["blind_id"]]["run_id"]] = judgment

    normalized_by_packet: dict[str, list[dict[str, Any]]] = defaultdict(list)
    substitutions = []
    for key, packet in packets.items():
        pass_name = key.rsplit("--", 1)[1]
        for item in packet["answers"]:
            run_id = maps[pass_name][item["blind_id"]]
            row = valid.get((run_id, pass_name))
            if row is None:
                final = copy.deepcopy(adjudicated[run_id])
                final["blind_id"] = item["blind_id"]
                final["answer_quotes"] = [quote for quote in final.get("answer_quotes", []) if quote in item["answer"]][:2]
                row = final
                substitutions.append({"run_id": run_id, "pass": pass_name, "reason": invalid[(run_id, pass_name)]["reason"], "source": "frozen_adjudication"})
            normalized_by_packet[key].append(row)
        expected = {row["blind_id"]: {"answer": row["answer"], "rubric": packet["rubric"]} for row in packet["answers"]}
        checked = scorer.validate_judgments({"judgments": normalized_by_packet[key]}, expected)
        write_json(root / "reviews" / key / "validated.json", checked)

    write_json(root / "adjudicated_by_run.json", adjudicated)
    review_hashes = {key: scorer.file_sha(root / "reviews" / key / "validated.json") for key in packets}
    recovery = {
        "status": "complete",
        "raw_review_rows": 864,
        "schema_valid_raw_rows": len(valid),
        "schema_invalid_raw_rows": len(invalid),
        "non_exact_quote_anchors_dropped": sum(row["dropped"] for row in quote_drops),
        "runs_adjudicated": len(adjudicated),
        "adjudication_cases": len(disagreements),
        "invalid_rows_replaced_only_after_adjudication": len(substitutions),
        "scientific_judgment_fields_edited_without_adjudication": 0,
        "raw_provider_responses_preserved": True,
        "substitutions": substitutions,
        "quote_drop_records": quote_drops,
    }
    write_json(root / "judge_schema_recovery.json", recovery)
    completion = {
        "status": "complete",
        "review_packets": len(packets),
        "review_A": 36,
        "review_B": 36,
        "disagreements": len(adjudicated),
        "adjudication_cases": len(disagreements),
        "review_hashes": review_hashes,
        "human_review_claimed": False,
        "schema_recovery_ref": "judge_schema_recovery.json",
    }
    write_json(root / "judge_completion.json", completion)
    print(scorer.canonical({"status": "complete", "schema_invalid_rows": len(invalid), "adjudicated": len(adjudicated), "quote_anchors_dropped": recovery["non_exact_quote_anchors_dropped"]}))


if __name__ == "__main__":
    main()
