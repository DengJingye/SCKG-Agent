"""Receipt verification and the existing 00-approved DEV rubric implementation.

Semantic decisions are explicit AI-assisted analyst reviews, not a calibrated
independent LLM judge or human Gold adjudication. No new benchmark taxonomy.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from copy import deepcopy
import json
from pathlib import Path
import random

import jsonschema

from eval.benchmark_v3.dev_pilot import BASE, LANES, read_rows, sha, write
from core.evaluation_models import EvaluationRunRecord, EvaluatorResult, FailureAttribution

CRITERIA = {
    "K01": ["count_input_required", "decision_matches_provided_matrix", "no_invented_counts_source"],
    "K02": ["correct_conditional_algorithm", "correct_zero_center_solver_behavior", "not_conflated_with_ordinary_pca"],
    "K03": ["reference_log_normalized", "test_counts_acceptable", "namespace_and_common_genes_verified_before_use"],
    "K04": ["version_matched_parameter_semantics", "executable_recommendation_respects_installed_version_uncertainty"],
    "O": ["targeted_triage", "necessary_clarification", "bounded_hypotheses", "no_unsupported_root_cause_assertion"],
    "W02": ["detect_incomplete_header_only_artifact", "specific_content_or_identity_checks", "no_false_repair_or_unapproved_execution"],
}
STAGES = {"routing", "state", "retrieval", "scope", "evidence", "synthesis", "planning", "execution", "validation-governance"}


def criteria(case_id):
    key = "O" if case_id.startswith("dev-O") else case_id.split("-")[1]
    return CRITERIA.get(key, [])


def receipt_for(directory):
    corrected = directory / "runtime_receipt.corrected.json"
    return json.loads((corrected if corrected.exists() else directory / "runtime_receipt.json").read_text())


def correct_receipts(output):
    """Repair the incoming-vs-effective receipt bug from captured backend events.

    The runtime and raw receipts are immutable; only an explicitly superseding
    sidecar is emitted. No inference from lane defaults and no provider rerun.
    """
    corrections = []
    for path in sorted((output / "runs").glob("*/runtime_receipt.json")):
        original = json.loads(path.read_text())
        if original["status"] == "not_run":
            continue
        events_path = path.parent / "lane_isolation.json"
        events = json.loads(events_path.read_text())["actual_backend_calls"]
        requests = original["retrieval_requests"]
        if len(events) != len(requests):
            raise ValueError("backend/request mapping is not one-to-one; manual review needed")
        corrected = deepcopy(original)
        changes = []
        for index, (request, event) in enumerate(zip(requests, events)):
            if request["effective_request"]["query"] != event["request"]["query"]:
                raise ValueError("backend request order cannot be verified")
            if request["effective_request"] != event["request"]:
                changes.append({"request_id": request["request_id"],
                    "incoming_request": request["effective_request"], "actual_backend_request": event["request"]})
                corrected["retrieval_requests"][index]["effective_request"] = event["request"]
        if changes:
            write(path.parent / "runtime_receipt.corrected.json", corrected)
            correction = {"run_id": original["run_id"], "category": "runtime receipt bug",
                "reason": "effective_request incorrectly captured incoming GovernedChatRetrieval request before backend normalization",
                "original_sha256": sha(path.read_bytes()), "corrected_sha256": sha(corrected),
                "backend_capture_sha256": sha(events_path.read_bytes()), "changes": changes,
                "outputs_changed": False, "provider_rerun": False}
            write(path.parent / "receipt_correction.json", correction)
            corrections.append(correction)
    write(output / "receipt_corrections.json", corrections)


def expand_reviews(output):
    notes = read_rows(output / "review_notes.jsonl")
    by_id = {n["blind_id"]: n for n in notes}
    if len(by_id) != len(notes):
        raise ValueError("duplicate review notes")
    for amendment in json.loads((output / "review_amendments.json").read_text())["amendments"]:
        by_id[amendment["blind_id"]].update(amendment)
    diagnoses = {}
    for group in json.loads((output / "failure_diagnosis_notes.json").read_text())["groups"]:
        for blind_id in group["blind_ids"]:
            if blind_id in diagnoses:
                raise ValueError("duplicate diagnosis")
            diagnoses[blind_id] = {k: v for k, v in group.items() if k != "blind_ids"}
    expanded = []
    for path in sorted((output / "runs").glob("*/run_record.json")):
        run = json.loads(path.read_text())
        if run["status"] == "not_run":
            continue
        blind_id = "review-" + sha(run["run_id"])[:12]
        review = deepcopy(by_id.pop(blind_id))
        bits, keys = review.pop("check_bits"), criteria(run["case_id"])
        if len(bits) != len(keys) or set(bits) - {"0", "1"}:
            raise ValueError("invalid review check bits")
        review.update(output_sha256=run["answer_hash"], checks=dict(zip(keys, [v == "1" for v in bits])),
                      reviewer="AI-assisted analyst; not a human reviewer; 00 final review pending")
        if review.get("failure"):
            review["failure"].update(diagnoses.pop(blind_id))
            review["failure"]["evidence_bindings"] = [
                {"ref": ref, "file_sha256": sha((path.parent / ref.split("#")[0]).read_bytes())}
                for ref in review["failure"]["evidence_refs"]]
        validate_review(review, run, path.parent)
        expanded.append(review)
    if by_id or diagnoses:
        raise ValueError("orphan review/diagnosis")
    with (output / "reviews.jsonl").open("x") as stream:
        for review in expanded:
            stream.write(json.dumps(review, ensure_ascii=False, sort_keys=True) + "\n")


def validate_receipts(output, expected=None):
    manifest = json.loads((output / "manifest.json").read_text())
    inputs = json.loads((output / "inputs.json").read_text())
    schema = json.loads((BASE / "runtime_receipt.schema.json").read_text())
    errors, rows = [], []
    for path in sorted((output / "runs").glob("*/runtime_receipt.json")):
        receipt = receipt_for(path.parent)
        directory = path.parent
        correction_path = directory / "receipt_correction.json"
        if correction_path.exists():
            correction = json.loads(correction_path.read_text())
            if correction["original_sha256"] != sha(path.read_bytes()) or correction["corrected_sha256"] != sha(receipt):
                errors.append(f"{receipt['run_id']}: correction digest mismatch")
            if correction["backend_capture_sha256"] != sha((directory / "lane_isolation.json").read_bytes()):
                errors.append(f"{receipt['run_id']}: backend correction evidence mismatch")
        jsonschema.validate(receipt, schema)
        record = EvaluationRunRecord.model_validate_json((directory / "run_record.json").read_text())
        if receipt["experiment_manifest_digest"] != sha(manifest):
            errors.append(f"{record.run_id}: manifest digest")
        if receipt["scenario_digest"] != sha(inputs[record.case_id]["scenario"]):
            errors.append(f"{record.run_id}: scenario digest")
        if receipt["status"] != record.status:
            errors.append(f"{record.run_id}: status mismatch")
        if receipt["status"] != "not_run":
            captured = json.loads((directory / "input.json").read_text())
            if captured["frozen_query"] != inputs[record.case_id]["rendered_query"] or captured["disclosed_query"] != captured["frozen_query"]:
                errors.append(f"{record.run_id}: input changed")
            isolation = json.loads((directory / "lane_isolation.json").read_text())
            if not isolation["pass"]:
                errors.append(f"{record.run_id}: isolation {isolation['errors']}")
            events = isolation["actual_backend_calls"]
            if [e["request"] for e in events] != [r["effective_request"] for r in receipt["retrieval_requests"]]:
                errors.append(f"{record.run_id}: effective backend request mismatch")
            for call in receipt["provider_calls"]:
                request = json.loads((directory / call["messages_ref"]).read_text())
                if call["messages_sha256"] != sha(request["messages"]):
                    errors.append(f"{record.run_id}: rendered prompt mismatch")
                if call["model"] != request["model"] or call["parameters"]["max_tokens"] != request.get("max_tokens"):
                    errors.append(f"{record.run_id}: provider argument mismatch")
                if call["status"] == "completed":
                    response = json.loads((directory / f"calls/{call['call_id']}.response.json").read_text())
                    if call["model_revision"] != response.get("model"):
                        errors.append(f"{record.run_id}: response model mismatch")
                    usage = response.get("usage") or {}
                    if call["input_tokens"] != usage.get("prompt_tokens") or call["output_tokens"] != usage.get("completion_tokens"):
                        errors.append(f"{record.run_id}: provider usage mismatch")
            for request in receipt["retrieval_requests"]:
                context = json.loads((directory / request["final_context_ref"]).read_text())
                if sha(context) != request["final_context_sha256"]:
                    errors.append(f"{record.run_id}: final context mismatch")
                trace = read_rows(directory / "trace.jsonl")
                if request["trace_span_id"] not in {s["span_id"] for t in trace for s in t["spans"]}:
                    errors.append(f"{record.run_id}: retrieval trace link missing")
            if record.answer_hash != sha(record.observed.get("answer", "").encode()):
                errors.append(f"{record.run_id}: output hash mismatch")
            product = json.loads((directory / "output.json").read_text())
            if product["final_report"] != record.observed["answer"]:
                errors.append(f"{record.run_id}: product final output mismatch")
            if record.observed["provider_calls"] != len(receipt["provider_calls"]):
                errors.append(f"{record.run_id}: provider call count mismatch")
        metadata = json.loads((directory / "execution_metadata.json").read_text())
        if metadata["harness_sha256"] != manifest["harness_sha256_at_freeze"] or metadata["runtime_commit"] != manifest["implementation_commit"]:
            errors.append(f"{record.run_id}: runtime/harness identity mismatch")
        rows.append({"run_id": record.run_id, "case_id": record.case_id, "lane": receipt["lane"],
            "status": record.status, "calls": len(receipt["provider_calls"]),
            "failed_provider_calls": sum(c["status"] != "completed" for c in receipt["provider_calls"]),
            "latency_ms": record.latency_ms, "input_tokens": record.input_tokens, "output_tokens": record.output_tokens})
    if expected is not None and len(rows) != expected:
        errors.append(f"expected {expected} receipts, found {len(rows)}")
    schedule = {r["run_id"]: r for r in manifest["schedule"]}
    for row in rows:
        unit = schedule.get(row["run_id"], {})
        if unit.get("case_id") != row["case_id"] or unit.get("lane") != row["lane"]:
            errors.append(f"{row['run_id']}: schedule identity mismatch")
    if expected == len(schedule) and {r["run_id"] for r in rows} != set(schedule):
        errors.append("schedule/receipt inventory differs")
    return {"pass": not errors, "errors": errors, "runs": len(rows), "rows": rows}


def blind_packet(output):
    rows = []
    for path in sorted((output / "runs").glob("*/run_record.json")):
        run = json.loads(path.read_text())
        if run["status"] == "not_run":
            continue
        rows.append({"blind_id": "review-" + sha(run["run_id"])[:12], "case_id": run["case_id"],
            "criteria": criteria(run["case_id"]), "answer": run["observed"].get("answer", ""),
            "output_sha256": run["answer_hash"]})
    random.Random(20260921).shuffle(rows)
    return rows


def validate_review(review, run, directory):
    if review["output_sha256"] != run["answer_hash"]:
        raise ValueError("stale answer review")
    if set(review["checks"]) != set(criteria(run["case_id"])) or not all(type(v) is bool for v in review["checks"].values()):
        raise ValueError("incomplete or invalid rubric checks")
    if not review.get("rationale") or type(review.get("major_scientific_error")) is not bool:
        raise ValueError("missing scientific judgment/rationale")
    answer = run["observed"].get("answer", "")
    for quote in review["answer_excerpts"]:
        if not quote or quote not in answer:
            raise ValueError("review excerpt not bound to actual final output")
    if not review["answer_excerpts"] and answer:
        raise ValueError("nonempty answer requires audit excerpt")
    passed = all(review["checks"].values()) and not review["major_scientific_error"]
    failure = review.get("failure")
    if not passed:
        if not failure or not failure.get("rationale") or not failure.get("evidence_refs"):
            raise ValueError("failed task requires evidence-backed attribution or explicit unresolved")
        if failure["stage"] not in STAGES | {"unresolved"}:
            raise ValueError("invalid failure stage")
        for ref in failure["evidence_refs"]:
            if not (directory / ref.split("#")[0]).is_file():
                raise ValueError("failure evidence file missing")
        for binding in failure.get("evidence_bindings", []):
            if binding["file_sha256"] != sha((directory / binding["ref"].split("#")[0]).read_bytes()):
                raise ValueError("failure evidence digest mismatch")
    elif failure:
        raise ValueError("passing task cannot carry a stage failure")
    return passed


def finalize(output, review_path):
    validation = validate_receipts(output, 56)
    if not validation["pass"]:
        raise ValueError(validation["errors"])
    reviews = read_rows(review_path)
    by_id = {r["blind_id"]: r for r in reviews}
    if len(by_id) != len(reviews):
        raise ValueError("duplicate review IDs")
    scores, failures, pending = [], [], []
    for path in sorted((output / "runs").glob("*/run_record.json")):
        run = json.loads(path.read_text())
        lane = receipt_for(path.parent)["lane"]
        track = run["case_id"].split("-")[1][0]
        blind_id = "review-" + sha(run["run_id"])[:12]
        if run["status"] == "not_run":
            result = EvaluatorResult(evaluator_id="dev-00-rubric-v1", metric_id=f"{track}.task_pass",
                status="not_run", details={"reason": run["error"]})
            review = None
        else:
            review = by_id.pop(blind_id)
            passed = validate_review(review, run, path.parent)
            result = EvaluatorResult(evaluator_id="dev-00-rubric-v1", metric_id=f"{track}.task_pass", status="measured",
                signal="passed" if passed else "blocked", value=int(passed), numerator=int(passed), denominator=1,
                applicable_case_ids=[run["case_id"]], details={"checks": review["checks"], "rationale": review["rationale"],
                    "method": "AI-assisted analyst DEV review; 00-approved criteria; not independent human Gold/judge calibration"})
            if review.get("failure"):
                failure = review["failure"]
                native = None if failure["stage"] == "unresolved" else FailureAttribution(case_id=run["case_id"], run_id=run["run_id"],
                    root_stage=failure["stage"], root_error_type=failure["error_type"], evidence=failure["evidence_refs"],
                    owner_module=failure["owner_module"], recommended_action="00 review the recorded failure; no question/corpus/prompt changes in this DEV run").model_dump(mode="json")
                failures.append({"run_id": run["run_id"], "native": native, "attribution": failure})
        scored = {"run_id": run["run_id"], "case_id": run["case_id"], "lane": lane, "track": track,
                  "result": result.model_dump(mode="json"), "review": review}
        pending.append((path.parent / "scoring_result.json", scored))
        scores.append(scored)
    if by_id:
        raise ValueError("orphan reviews")
    # Validate the complete batch before emitting anything: no partial score set.
    destinations = [p for p, _ in pending] + [output / n for n in
        ("receipt_validation.json", "failure_attribution.json", "scoring_results.json", "summary.json")]
    if any(p.exists() for p in destinations):
        raise FileExistsError("scoring artifacts already exist; never overwrite a review attempt")
    for path, scored in pending:
        write(path, scored)
    write(output / "receipt_validation.json", validation)
    write(output / "failure_attribution.json", failures)
    write(output / "scoring_results.json", scores)
    metrics = {}
    for lane in LANES:
        metrics[lane] = {}
        for track in ("K", "O", "W"):
            subset = [s["result"] for s in scores if s["lane"] == lane and s["track"] == track]
            metrics[lane][track] = {"passed": sum(r["value"] or 0 for r in subset),
                "measured": sum(r["status"] == "measured" for r in subset), "not_run": sum(r["status"] == "not_run" for r in subset)}
    costs, pairs = {}, {}
    for lane in LANES:
        rows = [r for r in validation["rows"] if r["lane"] == lane and r["status"] == "completed"]
        costs[lane] = {"runs_completed": len(rows), "provider_calls": sum(r["calls"] for r in rows),
            "input_tokens": sum(r["input_tokens"] or 0 for r in rows),
            "output_tokens": sum(r["output_tokens"] or 0 for r in rows),
            "usage_missing_runs": sum(r["input_tokens"] is None for r in rows),
            "latency_ms_mean": sum(r["latency_ms"] for r in rows) / len(rows)}
        families = defaultdict(list)
        for score in scores:
            if score["lane"] == lane and score["track"] == "K":
                families[score["case_id"].rsplit("-", 1)[0]].append(score["result"]["value"])
        pairs[lane] = {"passed": sum(len(v) == 2 and all(v) for v in families.values()), "families": len(families)}
    write(output / "summary.json", {"status": "DEV_COMPLETE_REQUIRES_00_RESULT_REVIEW", "runs_expected": 56,
        "cases_scheduled": 14, "cases_attempted": len({r["case_id"] for r in validation["rows"] if r["status"] == "completed"}),
        "runs_completed": sum(r["status"] == "completed" for r in validation["rows"]),
        "runs_not_run": sum(r["status"] == "not_run" for r in validation["rows"]),
        "provider_calls": sum(r["calls"] for r in validation["rows"]),
        "failed_provider_calls": sum(r["failed_provider_calls"] for r in validation["rows"]),
        "metrics": metrics, "K_condition_pair_pass": pairs, "costs": costs,
        "task_failures": len(failures), "major_scientific_error_runs": sum(r["major_scientific_error"] for r in reviews),
        "failure_stage_counts": dict(Counter(f["attribution"]["stage"] for f in failures)),
        "harness_bugs": [{"category": "runtime receipt bug", "id": "incoming-versus-effective-backend-request",
            "status": "corrected_from_existing_capture_no_rerun", "affected_runs": len(json.loads((output / "receipt_corrections.json").read_text()))}],
        "ready_for_evaluation_freeze": False, "formal_gold_created": False,
        "limitations": ["one DEV repetition", "AI-assisted rubric review, not independent human scoring",
                        "W01 common seurat_v3 execution interface unavailable", "coverage remains unadjudicated"]})


def amend_attribution(output):
    """Append a reviewed attribution revision; retain original scientific scores."""
    specification = json.loads((output / "attribution_amendments.json").read_text())
    amendments = {i: {k: v for k, v in g.items() if k != "blind_ids"}
                  for g in specification["groups"] for i in g["blind_ids"]}
    scores = json.loads((output / "scoring_results.json").read_text())
    failures = json.loads((output / "failure_attribution.json").read_text())
    by_run = {f["run_id"]: f for f in failures}
    for score in scores:
        review = score["review"]
        if review and review["blind_id"] in amendments:
            amendment = amendments.pop(review["blind_id"])
            review["failure"].update(amendment)
            failure = by_run[score["run_id"]]
            failure["attribution"].update(amendment)
            if amendment["stage"] == "unresolved":
                failure["native"] = None
            else:
                failure["native"].update(root_stage=amendment["stage"], owner_module=amendment["owner_module"])
                FailureAttribution.model_validate(failure["native"])
    if amendments:
        raise ValueError("orphan attribution amendment")
    summary = json.loads((output / "summary.json").read_text())
    summary["failure_stage_counts"] = dict(Counter(f["attribution"]["stage"] for f in failures))
    summary["attribution_revision"] = 2
    summary["harness_bugs"].append({"category": "failure-attribution bug", "id": "premature-primary-root-stage",
        "affected_runs": 6, "status": "corrected_in_revision_2_scores_and_runtime_unchanged"})
    for name, value in (("failure_attribution.final.json", failures), ("scoring_results.final.json", scores), ("summary.final.json", summary)):
        write(output / name, value)
    write(output / "result_index.json", {"canonical_summary": "summary.final.json",
        "canonical_scores": "scoring_results.final.json", "canonical_attribution": "failure_attribution.final.json",
        "revision": 2, "previous_artifacts_retained": ["summary.json", "scoring_results.json", "failure_attribution.json"],
        "amendments": "attribution_amendments.json", "scientific_scores_changed": False, "provider_reruns": 0})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("validate", "blind", "correct-receipts", "expand-reviews", "finalize", "amend-attribution"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reviews", type=Path)
    parser.add_argument("--expected", type=int)
    args = parser.parse_args()
    if args.action == "validate":
        result = validate_receipts(args.output, args.expected)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if not result["pass"]:
            raise SystemExit(1)
    elif args.action == "blind":
        for row in blind_packet(args.output):
            print(json.dumps(row, ensure_ascii=False))
    elif args.action == "correct-receipts":
        correct_receipts(args.output)
    elif args.action == "expand-reviews":
        expand_reviews(args.output)
    elif args.action == "amend-attribution":
        amend_attribution(args.output)
    else:
        finalize(args.output, args.reviews)


if __name__ == "__main__":
    main()
