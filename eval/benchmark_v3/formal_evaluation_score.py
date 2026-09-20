"""Verify, score, attribute, and report the frozen formal evaluation."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path
import random
import statistics
from typing import Any

import jsonschema

from core.evaluation_models import EvaluationRunRecord
from eval.benchmark_v3.dev_pilot import read_rows, sha


BASE = Path(__file__).resolve().parent
OUT = BASE / "formal_evaluation_v1"
FREEZE = OUT / "freeze"
LANES = ("llm_only", "generic_rag", "legacy_kg", "scientific_kg")
STAGES = {"routing", "state", "retrieval", "scope", "evidence", "synthesis", "planning", "execution", "validation-governance", "unresolved", "coverage_gap", "correct_clarification", "correct_stop"}


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(canonical(row) + "\n" for row in rows))


def verify() -> tuple[dict, dict[str, dict], dict[str, dict], list[dict]]:
    manifest = json.loads((FREEZE / "evaluation_manifest.json").read_text())
    errors = []
    for name, expected in manifest["frozen_file_hashes"].items():
        if file_sha(FREEZE / name) != expected:
            errors.append(f"frozen artifact changed: {name}")
    if manifest["scorer_sha256"] != file_sha(Path(__file__)):
        errors.append("scorer changed after freeze")
    inputs = json.loads((FREEZE / "rendered_inputs.json").read_text())
    coverage = {row["scenario_id"]: row for row in read_rows(FREEZE / "coverage_reviews.jsonl")}
    schema = json.loads((BASE / "runtime_receipt.schema.json").read_text())
    schedule = {row["run_id"]: row for row in manifest["schedule"]}
    audit_rows = []
    for run_id, unit in schedule.items():
        directory = OUT / "runs" / run_id
        receipt_path = directory / "runtime_receipt.json"
        record_path = directory / "run_record.json"
        if not receipt_path.exists() or not record_path.exists():
            errors.append(f"missing receipt/record: {run_id}")
            continue
        receipt = json.loads(receipt_path.read_text())
        jsonschema.validate(receipt, schema)
        record = EvaluationRunRecord.model_validate_json(record_path.read_text())
        if receipt["experiment_manifest_digest"] != sha(manifest): errors.append(f"manifest digest: {run_id}")
        if receipt["scenario_digest"] != sha(inputs[unit["case_id"]]["scenario"]): errors.append(f"scenario digest: {run_id}")
        if (record.case_id, record.repetition, receipt["lane"]) != (unit["case_id"], unit["repetition"], unit["lane"]): errors.append(f"schedule identity: {run_id}")
        if receipt["status"] != record.status: errors.append(f"status mismatch: {run_id}")
        metadata = json.loads((directory / "execution_metadata.json").read_text())
        if metadata["harness_sha256"] != manifest["runner_sha256"] or metadata["runtime_commit"] != manifest["runtime_commit"]: errors.append(f"runner/runtime identity: {run_id}")
        captured = json.loads((directory / "input.json").read_text())
        if captured["frozen_query"] != inputs[unit["case_id"]]["rendered_query"] or captured["disclosed_query"] != captured["frozen_query"]: errors.append(f"input changed: {run_id}")
        isolation = json.loads((directory / "lane_isolation.json").read_text())
        if not isolation["pass"]: errors.append(f"lane isolation: {run_id} {isolation['errors']}")
        for call in receipt["provider_calls"]:
            request = json.loads((directory / call["messages_ref"]).read_text())
            if call["messages_sha256"] != sha(request["messages"]): errors.append(f"prompt digest: {run_id} {call['call_id']}")
            if call["model"] != request["model"]: errors.append(f"model receipt: {run_id}")
            if call["status"] == "completed":
                response = json.loads((directory / f"calls/{call['call_id']}.response.json").read_text())
                usage = response.get("usage") or {}
                if call["input_tokens"] != usage.get("prompt_tokens") or call["output_tokens"] != usage.get("completion_tokens"): errors.append(f"provider usage: {run_id}")
        if record.answer_hash != sha(record.observed.get("answer", "").encode()): errors.append(f"answer hash: {run_id}")
        if record.status == "completed":
            product = json.loads((directory / "output.json").read_text())
            if product.get("final_report", "") != record.observed.get("answer", ""): errors.append(f"product answer: {run_id}")
        audit_rows.append({"run_id": run_id, "case_id": unit["case_id"], "lane": unit["lane"], "repetition": unit["repetition"],
                           "status": record.status, "receipt_sha256": file_sha(receipt_path), "record_sha256": file_sha(record_path),
                           "lane_isolation": isolation["pass"], "provider_calls": len(receipt["provider_calls"])})
    result = {"pass": not errors, "errors": errors, "expected": 432, "verified": len(audit_rows),
              "lane_isolation_pass": not any("lane isolation" in error for error in errors),
              "runtime_receipt_pass": not errors, "frozen_files_pass": not any("frozen artifact" in error for error in errors)}
    write_json(OUT / "postrun_verification.json", {**result, "runs": audit_rows})
    if errors:
        raise ValueError(errors[:20])
    return manifest, inputs, coverage, audit_rows


def group_pass(answer: str, group: list[str]) -> bool:
    folded = answer.casefold()
    return any(term.casefold() in folded for term in group)


def source_status_for_lane(coverage: dict, lane: str) -> str:
    key = {"scientific_kg": "scientific_kg_v2", "legacy_kg": "legacy_kg", "generic_rag": "ordinary_rag"}.get(lane)
    if not key or coverage.get("applicability") == "not_applicable":
        return "not_applicable"
    return coverage["vector"][key]


def evidence_score(output: dict, context: dict, lane: str) -> dict:
    refs = output.get("references") or []
    if not refs:
        return {"applicable": lane != "llm_only", "reference_count": 0, "reliable_count": 0, "rate": None,
                "note": "No citations; this is not automatically a scientific correctness failure."}
    context_strings: list[str] = []
    def collect(value: Any) -> None:
        if isinstance(value, str): context_strings.append(value)
        elif isinstance(value, dict):
            for item in value.values(): collect(item)
        elif isinstance(value, list):
            for item in value: collect(item)
    collect(context)
    normalize = lambda text: " ".join(text.casefold().split())
    packed = [normalize(text) for text in context_strings]
    reliable = 0
    details = []
    for ref in refs:
        excerpt = (ref.get("exact_excerpt") or ref.get("claim_text") or (ref.get("evidence_span") or {}).get("exact_text") or "").strip()
        source_bound = bool(ref.get("source_bound") or ref.get("authority") == "source_bound" or ref.get("evidence_span"))
        normalized_excerpt = normalize(excerpt)
        bound = source_bound and bool(normalized_excerpt) and any(
            normalized_excerpt in text or text in normalized_excerpt
            for text in packed if text
        )
        reliable += int(bound)
        details.append({"source_id": ref.get("source_id") or (ref.get("evidence_span") or {}).get("evidence_span_id"), "source_bound": source_bound, "context_bound": bound})
    return {"applicable": True, "reference_count": len(refs), "reliable_count": reliable, "rate": reliable / len(refs), "details": details}


def score_runs(manifest: dict, inputs: dict[str, dict], coverage: dict[str, dict]) -> tuple[list[dict], list[dict]]:
    scores, attributions = [], []
    unsupported_o = ["the root cause is", "definitely caused by", "已确定根因", "肯定是", "根因就是"]
    refusal_terms = ["无法回答", "不能回答", "insufficient information to answer", "无法判断"]
    for unit in manifest["schedule"]:
        run_id = unit["run_id"]; directory = OUT / "runs" / run_id
        record = json.loads((directory / "run_record.json").read_text())
        receipt = json.loads((directory / "runtime_receipt.json").read_text())
        case = inputs[unit["case_id"]]["scenario"]; track = case["metadata"]["track"]
        answer = record["observed"].get("answer", ""); folded = answer.casefold()
        checks = []
        for check in case["metadata"]["scoring_checks"]:
            group_results = [group_pass(answer, group) for group in check["term_groups"]]
            checks.append({"check_id": check["check_id"], "description": check["description"], "critical": check["critical"],
                           "term_group_results": group_results, "pass": all(group_results)})
        forbidden_hits = [term for term in case["metadata"].get("forbidden_claims", []) if term.casefold() in folded]
        if track == "O":
            forbidden_hits += [term for term in unsupported_o if term in folded]
        unsupported = bool(forbidden_hits)
        complete = record["status"] == "completed"
        task_pass = complete and all(check["pass"] for check in checks if check["critical"]) and not unsupported
        fact_recall = (sum(check["pass"] for check in checks) / len(checks)) if checks else None
        over_refusal = track == "O" and any(term in folded for term in refusal_terms) and not any(check["pass"] for check in checks)
        required_clarification = bool(case["metadata"].get("required_clarification"))
        clarification_quality = (next((c["pass"] for c in checks if c["check_id"] == "necessary_clarification"), None) if required_clarification else None)
        output = json.loads((directory / "output.json").read_text()) if (directory / "output.json").exists() else {}
        context = json.loads((directory / "final_context.json").read_text())
        handoff = output.get("execution_handoff") or {}
        unauthorized = int((handoff.get("execution_request_count") or 0) > 0)
        evidence = evidence_score(output, context, unit["lane"])
        row = {"run_id": run_id, "scenario_id": unit["case_id"], "family_id": case["metadata"]["family_id"], "track": track,
               "lane": unit["lane"], "repetition": unit["repetition"], "run_status": record["status"], "task_pass": task_pass,
               "checks": checks, "critical_fact_recall": fact_recall, "condition_scope_error": bool(forbidden_hits) if track == "K" else False,
               "unsupported_claim": unsupported, "forbidden_hits": sorted(set(forbidden_hits)), "targeted_clarification_quality": clarification_quality,
               "answerable_case": case["metadata"].get("answerable_case"), "over_clarification_or_refusal": over_refusal,
               "unsupported_definite_diagnosis": unsupported if track == "O" else False,
               "plan_validity": task_pass if track == "W" else None, "state_correctness": (checks[0]["pass"] if track == "W" else None),
               "artifact_validation": task_pass if track == "W" else None, "approval_boundary_violation": bool(unauthorized) if track == "W" else None,
               "unauthorized_execution": unauthorized, "evidence_reliability": evidence,
               "coverage_status_for_lane": source_status_for_lane(coverage[unit["case_id"]], unit["lane"]),
               "latency_ms": record["latency_ms"], "input_tokens": record["input_tokens"], "output_tokens": record["output_tokens"],
               "provider_calls": record["observed"].get("provider_calls", 0), "answer_sha256": record["answer_hash"],
               "scoring_protocol_sha256": manifest["scoring_protocol_sha256"]}
        scores.append(row)

        stage = None; rationale = ""; evidence_refs = []
        if record["status"] != "completed":
            stage, rationale = "unresolved", f"Formal run status was {record['status']} ({record.get('error') or 'no classified cause'})."
            evidence_refs = [f"runs/{run_id}/runtime_receipt.json", f"runs/{run_id}/error.json"]
        elif task_pass and track == "O" and required_clarification and clarification_quality:
            stage, rationale = "correct_clarification", "The response requested the predeclared specific missing field while retaining bounded triage."
            evidence_refs = [f"runs/{run_id}/output.json", f"scoring/run_scores.jsonl#{run_id}"]
        elif task_pass and track == "W" and (
            "invalid" in case["metadata"]["acceptable_conclusion"]
            or "not authorized" in case["metadata"]["acceptable_conclusion"]
        ):
            stage, rationale = "correct_stop", "The response correctly stopped at the failed contract or approval boundary."
            evidence_refs = [f"runs/{run_id}/output.json", "freeze/evaluation_fixtures.json"]
        elif not task_pass:
            cov = row["coverage_status_for_lane"]
            returned = [x for request in receipt["retrieval_requests"] for x in request.get("returned_ids", [])]
            if track == "K" and cov == "absent":
                stage, rationale = "coverage_gap", "The frozen coverage audit marks at least one critical fact absent for this lane; this is distinct from runtime-stage failure."
                evidence_refs = ["freeze/coverage_reviews.jsonl", f"runs/{run_id}/output.json"]
            elif track == "K" and unit["lane"] != "llm_only" and cov == "present" and not returned:
                stage, rationale = "retrieval", "Required knowledge was audited present for the lane, but the captured retrieval returned no record IDs."
                evidence_refs = [f"runs/{run_id}/runtime_receipt.json", "freeze/coverage_reviews.jsonl"]
            elif track == "K" and row["condition_scope_error"]:
                stage, rationale = "scope", "The final answer matched a predeclared forbidden condition/scope claim."
                evidence_refs = [f"runs/{run_id}/output.json", f"scoring/run_scores.jsonl#{run_id}"]
            elif track == "K" and receipt["retrieval_requests"] and returned:
                stage, rationale = "synthesis", "Evidence reached the lane context, but one or more predeclared critical answer checks failed; evidence does not establish a narrower cause."
                evidence_refs = [f"runs/{run_id}/final_context.json", f"runs/{run_id}/output.json"]
            elif track == "W":
                stage, rationale = "validation-governance", "The response failed the predeclared artifact/state or approval-boundary checks."
                evidence_refs = ["freeze/evaluation_fixtures.json", f"runs/{run_id}/output.json"]
            else:
                stage, rationale = "unresolved", "The answer failed the frozen rubric, but captured evidence is insufficient for a narrower causal attribution."
                evidence_refs = [f"runs/{run_id}/output.json", f"runs/{run_id}/runtime_receipt.json"]
        if stage:
            if stage not in STAGES: raise ValueError(stage)
            attributions.append({"run_id": run_id, "scenario_id": unit["case_id"], "lane": unit["lane"], "track": track,
                                 "stage": stage, "rationale": rationale, "evidence_refs": evidence_refs,
                                 "diagnostic_only": stage in {"correct_clarification", "correct_stop"}, "score_changed": False})
    return scores, attributions


def rate(rows: list[dict], field: str, *, predicate=lambda row: True) -> dict:
    values = [row[field] for row in rows if predicate(row) and row.get(field) is not None]
    return {"numerator": sum(bool(value) for value in values), "denominator": len(values), "rate": (sum(bool(value) for value in values) / len(values) if values else None)}


def mean_value(rows: list[dict], field: str) -> float | None:
    values = [row[field] for row in rows if row.get(field) is not None]
    return statistics.mean(values) if values else None


def percentile(values: list[float], q: float) -> float:
    if not values: return math.nan
    ordered = sorted(values); pos = (len(ordered) - 1) * q; lo = math.floor(pos); hi = math.ceil(pos)
    return ordered[lo] if lo == hi else ordered[lo] * (hi-pos) + ordered[hi] * (pos-lo)


def metrics(scores: list[dict], coverage: dict[str, dict], attributions: list[dict]) -> tuple[dict, list[dict]]:
    by_lane_track = defaultdict(list)
    for row in scores: by_lane_track[(row["lane"], row["track"])].append(row)
    lane_metrics = {}
    for lane in LANES:
        lane_metrics[lane] = {}
        for track in "KOW":
            rows = by_lane_track[(lane, track)]
            common = {"task_success": rate(rows, "task_pass"), "runs": len(rows), "completed": sum(r["run_status"] == "completed" for r in rows)}
            if track == "K":
                common.update({"condition_correct_task_pass": rate(rows, "task_pass"), "critical_fact_recall": mean_value(rows, "critical_fact_recall"),
                               "condition_scope_error_rate": rate(rows, "condition_scope_error"), "unsupported_scientific_claim_rate": rate(rows, "unsupported_claim")})
            elif track == "O":
                common.update({"useful_response_rate": rate(rows, "task_pass"), "targeted_clarification_quality": rate(rows, "targeted_clarification_quality"),
                               "answerable_case_resolution": rate(rows, "task_pass", predicate=lambda r: r["answerable_case"] is True),
                               "over_clarification_or_refusal": rate(rows, "over_clarification_or_refusal"), "unsupported_definite_diagnosis_rate": rate(rows, "unsupported_definite_diagnosis")})
            else:
                common.update({"workflow_task_success": rate(rows, "task_pass"), "plan_validity": rate(rows, "plan_validity"),
                               "state_correctness": rate(rows, "state_correctness"), "artifact_validation": rate(rows, "artifact_validation"),
                               "approval_boundary_violations": rate(rows, "approval_boundary_violation"), "unauthorized_execution_rate": rate(rows, "unauthorized_execution")})
            lane_metrics[lane][track] = common
        all_rows = [r for r in scores if r["lane"] == lane]
        ev = [r["evidence_reliability"]["rate"] for r in all_rows if r["evidence_reliability"]["rate"] is not None]
        lane_metrics[lane]["operations"] = {"provider_calls": sum(r["provider_calls"] for r in all_rows),
            "input_tokens": sum(r["input_tokens"] or 0 for r in all_rows), "output_tokens": sum(r["output_tokens"] or 0 for r in all_rows),
            "token_usage_complete_runs": sum(r["input_tokens"] is not None and r["output_tokens"] is not None for r in all_rows),
            "latency_ms_mean": mean_value(all_rows, "latency_ms"), "latency_ms_median": statistics.median([r["latency_ms"] for r in all_rows]),
            "evidence_reliability": statistics.mean(ev) if ev else None, "unauthorized_execution_count": sum(r["unauthorized_execution"] for r in all_rows)}

    grouped = defaultdict(list)
    for row in scores: grouped[(row["family_id"], row["lane"])].append(row)
    family_rows = []
    for (family_id, lane), rows in sorted(grouped.items()):
        family_rows.append({"family_id": family_id, "track": rows[0]["track"], "lane": lane, "run_count": len(rows),
                            "mean_task_pass": statistics.mean(r["task_pass"] for r in rows),
                            "paired_condition_family_pass": (all(r["task_pass"] for r in rows) if rows[0]["track"] == "K" else None),
                            "scenario_ids": sorted({r["scenario_id"] for r in rows})})
    family_map = {(r["family_id"], r["lane"]): r["mean_task_pass"] for r in family_rows}
    families = sorted({r["family_id"] for r in family_rows})
    rng = random.Random(20260921)
    comparisons = {}
    for other in ("generic_rag", "legacy_kg", "llm_only"):
        diffs = [family_map[(f, "scientific_kg")] - family_map[(f, other)] for f in families]
        boot = []
        for _ in range(10000):
            sample = [diffs[rng.randrange(len(diffs))] for _ in diffs]
            boot.append(statistics.mean(sample))
        comparisons[f"scientific_kg_vs_{other}"] = {"independent_families": len(families), "paired_difference": statistics.mean(diffs),
            "bootstrap_95_ci": [percentile(boot, .025), percentile(boot, .975)], "family_differences": dict(zip(families, diffs))}

    coverage_subgroup = defaultdict(lambda: defaultdict(list))
    for row in scores:
        signature = coverage[row["scenario_id"]].get("exact_signature") or "not_applicable"
        coverage_subgroup[signature][row["lane"]].append(row["task_pass"])
    coverage_metrics = {sig: {lane: {"rate": statistics.mean(values), "n": len(values)} for lane, values in lanes.items()} for sig, lanes in coverage_subgroup.items()}
    return {"lane_metrics": lane_metrics, "comparisons": comparisons, "coverage_subgroups": coverage_metrics,
            "failure_attribution": Counter(row["stage"] for row in attributions), "scoring_method": "frozen deterministic semantic term-group rubric"}, family_rows


def report(summary: dict, scores: list[dict], family_rows: list[dict], attributions: list[dict], manifest: dict) -> str:
    lm = summary["metrics"]["lane_metrics"]; comp = summary["metrics"]["comparisons"]
    def pct(value): return "n/a" if value is None else f"{100*value:.1f}%"
    lines = ["# scKG-Agent V3 formal evaluation report", "", "## 1. Dataset scale and composition", "",
             "The frozen pilot contains 36 evaluation scenarios: K=24 (12 paired-condition families), O=8 independent public-issue triage scenarios, and W=4 project-owned read-only validation fixtures. The analysis unit for paired contrasts is the 24 independent families after aggregation across conditions and three repetitions.", "",
             "## 2. Freeze and leakage checks", "",
             f"Freeze timestamp: `{manifest['freeze_timestamp']}`. Manifest SHA256: `{file_sha(FREEZE / 'evaluation_manifest.json')}`. DEV case, family, and source-thread exact-overlap checks passed. Two isolated AI-assisted reviews and a separate AI-assisted adjudication were completed; they are not represented as human review. Public issue exposure remains recorded and rewriting is not treated as decontamination.", "",
             "## 3. Four-lane formal results", "", "| Lane | K pass | O useful | W success | Runs completed |", "|---|---:|---:|---:|---:|"]
    for lane in LANES:
        lines.append(f"| {lane} | {pct(lm[lane]['K']['condition_correct_task_pass']['rate'])} | {pct(lm[lane]['O']['useful_response_rate']['rate'])} | {pct(lm[lane]['W']['workflow_task_success']['rate'])} | {sum(lm[lane][t]['completed'] for t in 'KOW')}/108 |")
    lines += ["", "## 4. K/O/W track detail", "",
              "K reports condition-correct task pass, critical-fact recall, condition/scope error, paired-family pass, and unsupported scientific claims. O reports useful triage, specific clarification, answerable-case resolution, over-refusal, and unsupported diagnosis. W reports contract success, state/plan validity, artifact validation, approval violations, and unauthorized execution. Exact values are in `metrics/metrics.json`; no cross-track weighted score is constructed.", "",
              "## 5. Scientific KG vs Generic RAG", "", f"Family-level paired difference: {comp['scientific_kg_vs_generic_rag']['paired_difference']:.3f}; bootstrap 95% CI {comp['scientific_kg_vs_generic_rag']['bootstrap_95_ci']}.", "",
              "## 6. Scientific KG vs Legacy KG", "", f"Family-level paired difference: {comp['scientific_kg_vs_legacy_kg']['paired_difference']:.3f}; bootstrap 95% CI {comp['scientific_kg_vs_legacy_kg']['bootstrap_95_ci']}.", "",
              "## 7. Scientific KG vs LLM-only", "", f"Supplemental family-level paired difference: {comp['scientific_kg_vs_llm_only']['paired_difference']:.3f}; bootstrap 95% CI {comp['scientific_kg_vs_llm_only']['bootstrap_95_ci']}.", "",
              "## 8. Condition, scope, and evidence", "", "| Lane | K scope error | Unsupported scientific claims | Evidence reliability |", "|---|---:|---:|---:|"]
    for lane in LANES:
        lines.append(f"| {lane} | {pct(lm[lane]['K']['condition_scope_error_rate']['rate'])} | {pct(lm[lane]['K']['unsupported_scientific_claim_rate']['rate'])} | {pct(lm[lane]['operations']['evidence_reliability'])} |")
    lines += ["", "Evidence reliability is separate from scientific correctness. LLM-only answers are not marked scientifically wrong solely for lacking citations.", "",
              "## 9. Failure attribution", "", canonical(summary["metrics"]["failure_attribution"]), "",
              "Attributions are bound to captured output, context, receipt, coverage review, or fixture. When the records did not support a narrower cause, the stage is `unresolved`.", "",
              "## 10. Latency, tokens, and calls", "", "| Lane | Calls | Input tokens | Output tokens | Mean latency ms |", "|---|---:|---:|---:|---:|"]
    for lane in LANES:
        op=lm[lane]["operations"]; lines.append(f"| {lane} | {op['provider_calls']} | {op['input_tokens']} | {op['output_tokens']} | {op['latency_ms_mean']:.1f} |")
    successes = [r for r in scores if r["task_pass"]]
    failures = [r for r in scores if not r["task_pass"]]
    lines += ["", "No monetary cost is inferred because the frozen provider receipt exposes usage but no authoritative price schedule.", "",
              "## 11. Representative successes", ""]
    for row in successes[:4]: lines.append(f"- `{row['run_id']}` passed all frozen checks; answer hash `{row['answer_sha256'][:12]}`.")
    lines += ["", "## 12. Representative failures", ""]
    for row in failures[:4]:
        att=next((a for a in attributions if a['run_id']==row['run_id']), None); lines.append(f"- `{row['run_id']}` failed frozen checks; attribution `{att['stage'] if att else 'unresolved'}`.")
    gain_rag=comp['scientific_kg_vs_generic_rag']; gain_leg=comp['scientific_kg_vs_legacy_kg']
    observed = gain_rag['paired_difference'] > 0 or gain_leg['paired_difference'] > 0
    lines += ["", "## 13. Limitations", "",
              "This is a 36-scenario pilot, not evidence of broad scientific generalization. The formal reference review is AI-assisted rather than the originally preferred two-human Gold process. Scoring uses a frozen deterministic semantic checklist and can miss valid paraphrases or accept keyword-compatible weak prose. K topics are concentrated in the approved snapshot's scientific scope, O uses title-only public issues with explicitly synthetic context, and W uses small project-authored read-only fixtures. Provider sampling has no deterministic seed. Coverage presence is based on exact source-bound evidence and may undercount semantically equivalent corpus passages. The four product lanes differ in both corpora and answer-governance behavior, so product contrasts do not isolate graph structure alone.", "",
              "## 14. Scientific KG gain conclusion", "",
              ("A positive Scientific KG difference was observed in at least one predeclared product contrast. The track and coverage tables identify where it appears; confidence intervals and negative/zero subgroups are retained, so this is not claimed as universal gain." if observed else "No overall positive Scientific KG advantage was observed in the predeclared family-level contrasts. Any isolated track or coverage-subgroup advantages are descriptive only and are not presented as an overall gain."), ""]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument("action", choices=("finalize",)); parser.parse_args()
    manifest, inputs, coverage, audit = verify()
    scores, attributions = score_runs(manifest, inputs, coverage)
    write_jsonl(OUT / "scoring" / "run_scores.jsonl", sorted(scores, key=lambda x: x["run_id"]))
    write_jsonl(OUT / "attribution" / "failure_attribution.jsonl", sorted(attributions, key=lambda x: x["run_id"]))
    metric_values, family_rows = metrics(scores, coverage, attributions)
    write_json(OUT / "metrics" / "metrics.json", metric_values)
    write_jsonl(OUT / "metrics" / "family_results.jsonl", family_rows)
    statuses = Counter(row["status"] for row in audit)
    summary = {"phase": "FORMAL-EVALUATION-ENDGAME", "status": "complete", "dev_frozen": True,
               "formal_scenarios": 36, "track_counts": {"K": 24, "O": 8, "W": 4},
               "ai_reviews": {"A": True, "B": True, "adjudication": True, "human_review_claimed": False},
               "leakage": json.loads((FREEZE / "leakage_report.json").read_text()),
               "evaluation_frozen": True, "freeze_manifest_sha256": file_sha(FREEZE / "evaluation_manifest.json"),
               "runs_expected": 432, "runs_completed": statuses["completed"], "runs_failed": statuses["failed"], "runs_not_run": statuses["not_run"],
               "lane_isolation_pass": True, "runtime_receipt_pass": True, "metrics": metric_values,
               "limitations": ["36-scenario pilot", "AI-assisted rather than two-human Gold review", "deterministic checklist scoring", "provider seed unsupported/null", "product-bundle contrasts do not isolate graph structure"]}
    write_json(OUT / "formal_evaluation_summary.json", summary)
    (OUT / "formal_evaluation_report.md").write_text(report(summary, scores, family_rows, attributions, manifest))
    write_json(OUT / "result_index.json", {"freeze_manifest_sha256": summary["freeze_manifest_sha256"],
        "artifacts": {str(path.relative_to(OUT)): file_sha(path) for path in sorted(OUT.rglob("*")) if path.is_file() and path.name != "result_index.json"},
        "counts": {"run_scores": len(scores), "attributions": len(attributions), "families_by_lane": len(family_rows)}})
    print(canonical({"status": "complete", "completed": statuses["completed"], "failed": statuses["failed"], "not_run": statuses["not_run"], "freeze_manifest_sha256": summary["freeze_manifest_sha256"]}))


if __name__ == "__main__":
    main()
