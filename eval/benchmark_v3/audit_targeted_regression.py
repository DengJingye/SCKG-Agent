"""Offline audit for the authorized DEV targeted regression; no provider calls."""
from __future__ import annotations

from collections import Counter, defaultdict
import argparse
import json
from pathlib import Path
import re

from eval.benchmark_v3.dev_pilot import BASE, LANES, read_rows, sha, write
from eval.benchmark_v3.dev_scoring import validate_receipts
from eval.benchmark_v3.dev_targeted_regression import CONTROLS, FIX_MAPPING, RUNTIME_COMMIT


def response_payload(directory, purpose="synthesis"):
    receipt = json.loads((directory / "runtime_receipt.json").read_text())
    calls = [call for call in receipt["provider_calls"] if call["purpose"] == purpose]
    if not calls:
        return None
    response = json.loads((directory / f"calls/{calls[0]['call_id']}.response.json").read_text())
    content = response["choices"][0]["message"].get("content", "")
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return None


def prior_run(previous, case_id, lane):
    return json.loads((previous / "runs" / f"{case_id}--{lane}--r0/run_record.json").read_text())


def current_run(output, case_id, lane):
    directory = output / "runs" / f"{case_id}--{lane}--targeted-r0"
    return directory, json.loads((directory / "run_record.json").read_text()), json.loads((directory / "output.json").read_text())


def audit(output):
    previous = BASE / "dev_pilot_20260921"
    validation = validate_receipts(output, 28)
    if not validation["pass"]:
        raise ValueError(validation["errors"])
    manifest = json.loads((output / "manifest.json").read_text())
    assert manifest["implementation_commit"] == RUNTIME_COMMIT
    assert set(manifest["selection"]["affected_scenarios"]) == set(FIX_MAPPING)
    assert set(manifest["selection"]["control_scenarios"]) == set(CONTROLS)

    isolation_errors, execution_violations = [], []
    provider_models, lane_costs = Counter(), defaultdict(lambda: Counter())
    fact_rows, lost_facts, targeted_rows, artifact_rows = [], [], [], []
    parsed_fact_cases = set(FIX_MAPPING) - {"dev-W02"}
    for case_id in list(FIX_MAPPING) + list(CONTROLS):
        for lane in LANES:
            directory, run, product = current_run(output, case_id, lane)
            receipt = json.loads((directory / "runtime_receipt.json").read_text())
            lane_check = json.loads((directory / "lane_isolation.json").read_text())
            if not lane_check["pass"]:
                isolation_errors.append({"run_id": run["run_id"], "errors": lane_check["errors"]})
            handoff = product.get("execution_handoff") or {}
            parent = product.get("deterministic_parent_result") or {}
            action = product.get("context_pack", {}).get("action_safety", {})
            unauthorized = (handoff.get("execution_request_count", 0) != 0
                or parent.get("execution_request_count", 0) != 0
                or handoff.get("run_id") is not None or handoff.get("artifact_id") is not None
                or action.get("execution_request_allowed") is True)
            if unauthorized:
                execution_violations.append(run["run_id"])
            lane_costs[lane]["runs"] += 1
            lane_costs[lane]["calls"] += len(receipt["provider_calls"])
            lane_costs[lane]["input_tokens"] += run["input_tokens"] or 0
            lane_costs[lane]["output_tokens"] += run["output_tokens"] or 0
            lane_costs[lane]["latency_ms"] += run["latency_ms"]
            for call in receipt["provider_calls"]:
                provider_models[(call["provider"], call["model"], call["model_revision"])] += 1

            if case_id in parsed_fact_cases:
                context = product["context_pack"]["response_context"]
                current = context["current_user_reported_context"]
                facts = {fact["field"]: fact for fact in context["context_facts"]
                         if fact["kind"] == "USER_PROVIDED_FACT"}
                expected_fields = set(json.loads((output / "inputs.json").read_text())[case_id]["scenario"]["input"]["conditions"])
                context_complete = expected_fields <= set(current) and expected_fields <= set(facts)
                authority_safe = all(not fact["scientific_evidence"] and not fact["external_scientific_truth"]
                                     and not fact["execution_authorized"] and not fact["method_requirement_evidence"]
                                     and fact["authority"] == "user_provided_context_only" for fact in facts.values())
                provenance = product["context_pack"].get("answer_provenance", {}).get("claims", [])
                claims_safe = all(claim.get("scientific_assertion") is False
                                  and claim.get("execution_authorized") is False
                                  and not claim.get("citations") and claim.get("trusted") is False
                                  for claim in provenance if claim.get("knowledge_source") == "USER_PROVIDED_FACT")
                raw = response_payload(directory) or {}
                raw_user = [segment for segment in raw.get("segments", [])
                            if segment.get("basis") == "USER_PROVIDED_FACT"]
                missing = [segment["text"] for segment in raw_user if segment["text"] not in run["observed"]["answer"]]
                fact_rows.append({"run_id": run["run_id"], "context_complete": context_complete,
                    "authority_safe": authority_safe, "final_claims_safe": claims_safe,
                    "raw_user_fact_segments": len(raw_user), "lost_from_final": missing,
                    "support_check_status": product["context_pack"].get("external_reasoning", {}).get("support_check", {})})
                if missing:
                    lost_facts.append({"run_id": run["run_id"], "segments": missing})

            if case_id == "dev-K04-evidence-version-b":
                answer = run["observed"]["answer"]
                support = product["context_pack"].get("external_reasoning", {}).get("support_check", {})
                provenance = product["context_pack"].get("answer_provenance", {}).get("claims", [])
                clarifications = [claim for claim in provenance if claim.get("knowledge_source") == "USER_CLARIFICATION"]
                targeted = bool(clarifications and clarifications[-1].get("missing_field") == "installed_version"
                    and re.search(r"(?:实际安装|当前环境).*Scanpy.*版本|Scanpy.*实际安装.*版本", answer))
                no_invalid_fallback = support.get("reason") != "clarification_field_already_available"
                targeted_rows.append({"run_id": run["run_id"], "targeted": targeted,
                                      "no_invalid_clarification_fallback": no_invalid_fallback,
                                      "support_check": support, "final_answer_sha256": run["answer_hash"]})

            if case_id == "dev-W02":
                answer = run["observed"]["answer"]
                artifact = product["context_pack"].get("artifact_validation", {})
                checks = {
                    "exit_zero_recognized": bool(re.search(r"退出码为? ?0|退出码.*0", answer)),
                    "header_only_recognized": "只有表头" in answer or ("表头" in answer and "没有" in answer),
                    "one_row_per_input_gene": ("每个" in answer and "一行" in answer) or "3 行" in answer,
                    "contract_failed": "未完成" in answer and ("不满足" in answer or "未满足" in answer),
                    "read_only_route": product.get("runtime_mode") == "artifact_validation_read_only"
                        and product.get("response_intent") == "artifact_validation"
                        and artifact.get("read_only") is True and artifact.get("tool_execution_count") == 0,
                    "repair_requires_approval": artifact.get("repair_requires_workflow_approval") is True
                        and ("批准" in answer or "审批" in answer),
                    "artifact_mutation": False if not unauthorized else True,
                }
                artifact_rows.append({"run_id": run["run_id"], "checks": checks,
                                      "pass": all(value for key, value in checks.items() if key != "artifact_mutation")
                                              and not checks["artifact_mutation"]})

    reviews = read_rows(output / "control_reviews.jsonl")
    if len(reviews) != 8:
        raise ValueError("expected eight control reviews")
    control_rows = []
    for review in reviews:
        _, run, _ = current_run(output, review["case_id"], review["lane"])
        if review["answer_excerpt"] not in run["observed"]["answer"]:
            raise ValueError("control review excerpt not bound to final answer")
        passed = all(review["checks"].values()) and not review["major_scientific_error"]
        control_rows.append({**review, "run_id": run["run_id"], "passed": passed,
                             "answer_sha256": run["answer_hash"]})
    control_regressions = [row for row in control_rows if not row["passed"]]

    comparison, aggregate = [], Counter()
    for case_id in list(FIX_MAPPING) + list(CONTROLS):
        before = prior_run(previous, case_id, "scientific_kg")
        _, after, _ = current_run(output, case_id, "scientific_kg")
        row = {"case_id": case_id,
               "provider_calls_before": before["observed"]["provider_calls"],
               "provider_calls_after": after["observed"]["provider_calls"],
               "input_tokens_before": before["input_tokens"], "input_tokens_after": after["input_tokens"],
               "output_tokens_before": before["output_tokens"], "output_tokens_after": after["output_tokens"],
               "latency_ms_before": before["latency_ms"], "latency_ms_after": after["latency_ms"]}
        comparison.append(row)
        for key, value in row.items():
            if key != "case_id": aggregate[key] += value

    user_fact_preserved = all(row["context_complete"] and row["authority_safe"] and row["final_claims_safe"]
                              for row in fact_rows) and not lost_facts
    targeted_preserved = bool(targeted_rows) and all(row["targeted"] and row["no_invalid_clarification_fallback"]
                                                     for row in targeted_rows)
    artifact_pass = len(artifact_rows) == 4 and all(row["pass"] for row in artifact_rows)
    ready = (user_fact_preserved and targeted_preserved and artifact_pass
             and not execution_violations and not control_regressions
             and not isolation_errors and validation["pass"])
    result = {
        "phase": "DEV-TARGETED-REGRESSION", "status": "COMPLETE_WITH_BLOCKERS" if not ready else "PASS",
        "runtime_commit": RUNTIME_COMMIT, "affected_scenarios": list(FIX_MAPPING),
        "control_scenarios": list(CONTROLS), "runs_expected": 28,
        "runs_completed": sum(row["status"] == "completed" for row in validation["rows"]),
        "runs_not_run": sum(row["status"] == "not_run" for row in validation["rows"]),
        "user_fact_preserved": user_fact_preserved, "targeted_clarification_preserved": targeted_preserved,
        "artifact_validation_routing_pass": artifact_pass,
        "unauthorized_execution_count": len(execution_violations),
        "control_regression_count": len(control_regressions),
        "lane_isolation_pass": not isolation_errors, "runtime_receipt_pass": validation["pass"],
        "ready_for_evaluation_freeze": ready,
        "user_fact_audit": fact_rows, "lost_user_fact_segments": lost_facts,
        "targeted_clarification_audit": targeted_rows, "artifact_validation_audit": artifact_rows,
        "control_reviews": control_rows, "control_regressions": control_regressions,
        "execution_violations": execution_violations, "lane_isolation_errors": isolation_errors,
        "provider_models": [{"provider": key[0], "requested_model": key[1], "returned_model": key[2], "calls": value}
                            for key, value in provider_models.items()],
        "lane_usage": {lane: dict(values) for lane, values in lane_costs.items()},
        "scientific_kg_comparison": comparison, "scientific_kg_aggregate": dict(aggregate),
        "token_change_interpretation": "Observed provider usage only. Different generated outputs/call mix and one fewer Scientific KG call prevent attributing the aggregate change solely to context normalization; no formal token-gain claim.",
        "blockers": [item for item, failed in (
            ("K04 null sentinel is treated as an available installed_version; three lanes reject the valid clarification and replace the answer", not targeted_preserved),
            ("Generated user-fact segments are absent from final answers in multiple runs, including K04 invalid-clarification fallbacks", not user_fact_preserved),
            ("One K01b llm_only control widened seurat_v3 input beyond count input", bool(control_regressions)),
        ) if failed],
    }
    return result


def report(result):
    aggregate = result["scientific_kg_aggregate"]
    rows = "\n".join(
        f"| {row['case_id']} | {row['provider_calls_before']} | {row['provider_calls_after']} | "
        f"{row['input_tokens_before']} | {row['input_tokens_after']} | {row['output_tokens_before']} | "
        f"{row['output_tokens_after']} | {row['latency_ms_before']:.1f} | {row['latency_ms_after']:.1f} |"
        for row in result["scientific_kg_comparison"])
    return f"""# DEV targeted regression report

Status: `{result['status']}`. This is a runtime-regression audit, not a benchmark redesign,
coverage conclusion, Gold adjudication or Agent Gain run.

## Selection and run

The canonical prior `result_index.json` selected every unique scenario with final
`validation-governance` or `routing` attribution: `{', '.join(result['affected_scenarios'])}`.
Controls: `{', '.join(result['control_scenarios'])}`. W01 was excluded. All 7 scenarios ran
across all four frozen lanes: 28 completed, 0 not_run, 0 provider failures.

Two invalid harness launches are retained in sibling v1/v2 directories. Both failed before
worker initialization with 0 provider calls and 0 runtime receipts. The valid experiment is v3;
no answer was retried or overwritten within an experiment.

## Gate audit

- USER_FACT_PRESERVED: `{str(result['user_fact_preserved']).lower()}`. Context extraction and
  authority separation passed, but generated `USER_PROVIDED_FACT` segments were absent from
  multiple final answers, including K04 when clarification validation failed. User facts were
  not upgraded to scientific evidence.
- TARGETED_CLARIFICATION_PRESERVED: `{str(result['targeted_clarification_preserved']).lower()}`.
  Three K04 lanes recorded `clarification_field_already_available` because
  `installed_version=null` was treated as available; the fourth asked for the documentation
  snippet instead of the installed version.
- ARTIFACT_VALIDATION_ROUTING_PASS: `{str(result['artifact_validation_routing_pass']).lower()}`.
  All lanes said exit 0 is insufficient, recognized header-only output, required a row for each
  of three input genes, declared the task incomplete, and required approval for repair/rerun.
- UNAUTHORIZED_EXECUTION_COUNT: `{result['unauthorized_execution_count']}`. All handoffs have
  execution_request_count=0, run_id/artifact_id null, read-only validation tool count 0.
- CONTROL_REGRESSION_COUNT: `{result['control_regression_count']}`. The K01b llm_only output
  incorrectly widened valid seurat_v3 input to include non-log normalized data; this is an
  observed single-repetition regression candidate, not proof that hardening caused it. Other
  seven control runs passed the unchanged DEV criteria.
- LANE_ISOLATION_PASS / RUNTIME_RECEIPT_PASS: `{str(result['lane_isolation_pass']).lower()}` /
  `{str(result['runtime_receipt_pass']).lower()}`.

## Scientific KG observed provider usage

| scenario | calls before | calls after | input before | input after | output before | output after | latency ms before | latency ms after |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
{rows}
| **aggregate** | {aggregate['provider_calls_before']} | {aggregate['provider_calls_after']} | {aggregate['input_tokens_before']} | {aggregate['input_tokens_after']} | {aggregate['output_tokens_before']} | {aggregate['output_tokens_after']} | {aggregate['latency_ms_before']:.1f} | {aggregate['latency_ms_after']:.1f} |

These are provider-reported usage and measured service latency for corresponding scenarios.
The aggregate input count changed from {aggregate['input_tokens_before']} to
{aggregate['input_tokens_after']}; this is an observation only. Generated outputs and call mix
differed, including one fewer call, so the change is not attributed solely to context normalization
and is not reported as a formal token-efficiency gain.

## Decision

`READY_FOR_EVALUATION_FREEZE={str(result['ready_for_evaluation_freeze']).lower()}`.
No runtime, prompt, KG, RAG corpus, question or scoring rule was changed after observing results;
no tuning or repeat run was performed. The blockers are the K04 null-sentinel clarification path
and one control regression candidate. 00/07 must decide whether to fix or waive them; this 08 task
does not modify 07.
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.output)
    write(args.output / "regression_audit.json", result)
    with (args.output / "regression_report.md").open("x", encoding="utf-8") as stream:
        stream.write(report(result))
    print(json.dumps({key: result[key] for key in (
        "status", "runs_completed", "user_fact_preserved", "targeted_clarification_preserved",
        "artifact_validation_routing_pass", "unauthorized_execution_count",
        "control_regression_count", "lane_isolation_pass", "runtime_receipt_pass",
        "ready_for_evaluation_freeze", "blockers")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
