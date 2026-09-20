"""Offline gate audit for the eight-unit DEV final freeze smoke."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import re

from eval.benchmark_v3.dev_final_freeze_smoke import RUN_MATRIX, RUNTIME_COMMIT
from eval.benchmark_v3.dev_pilot import BASE, sha, write
from eval.benchmark_v3.dev_scoring import validate_receipts


KEY_FACTS = {
    "dev-K01-hvg-input-a": {"matrix_state", "flavor"},
    "dev-K03-reference-annotation-b": {
        "mapping_table_provided",
        "reference_gene_namespace",
        "test_gene_namespace",
    },
}
MIXED_MARKERS = re.compile(
    r"因此|所以|由此|从而|进而|这(?:表明|说明|证明|意味着|可能)|"
    r"(?:符合|满足|意味着|说明|表明|证明|指向|需要|必须|应该|应当|可以直接|不能直接)"
)


def _directory(output: Path, case_id: str, lane: str) -> Path:
    return output / "runs" / f"{case_id}--{lane}--freeze-r0"


def _first_synthesis_payload(directory: Path) -> dict:
    receipt = json.loads((directory / "runtime_receipt.json").read_text())
    calls = [call for call in receipt["provider_calls"] if call["purpose"] == "synthesis"]
    if not calls:
        return {}
    response = json.loads((directory / f"calls/{calls[0]['call_id']}.response.json").read_text())
    content = str(response["choices"][0]["message"].get("content") or "")
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return {}


def _safe_context_authority(value: dict) -> bool:
    return (
        value.get("kind") in {"USER_PROVIDED_FACT", "OBSERVED_STATE"}
        and value.get("authority")
        in {"user_provided_context_only", "deterministic_runtime_observation"}
        and value.get("scientific_evidence") is False
    )


def audit(output: Path):
    validation = validate_receipts(output, 8)
    if not validation["pass"]:
        raise ValueError(validation["errors"])
    manifest = json.loads((output / "manifest.json").read_text())
    assert manifest["implementation_commit"] == RUNTIME_COMMIT
    assert manifest["selection"]["run_matrix"] == {
        key: list(value) for key, value in RUN_MATRIX.items()
    }

    lane_errors = []
    provider_models = Counter()
    k04_rows = []
    authority_rows = []
    mixed_rows = []
    evidence_rows = []

    for case_id, lanes in RUN_MATRIX.items():
        for lane in lanes:
            directory = _directory(output, case_id, lane)
            run = json.loads((directory / "run_record.json").read_text())
            product = json.loads((directory / "output.json").read_text())
            receipt = json.loads((directory / "runtime_receipt.json").read_text())
            isolation = json.loads((directory / "lane_isolation.json").read_text())
            if not isolation["pass"]:
                lane_errors.append({"run_id": run["run_id"], "errors": isolation["errors"]})
            for call in receipt["provider_calls"]:
                provider_models[(call["provider"], call["model"], call["model_revision"])] += 1

            context = product["context_pack"]["response_context"]
            facts = {
                fact["field"]: fact
                for fact in context["context_facts"]
                if fact.get("kind") in {"USER_PROVIDED_FACT", "OBSERVED_STATE"}
            }
            claims = product["context_pack"].get("answer_provenance", {}).get("claims", [])
            raw = _first_synthesis_payload(directory)
            raw_segments = raw.get("segments", []) if isinstance(raw.get("segments"), list) else []
            support = product["context_pack"].get("external_reasoning", {}).get("support_check", {})

            if case_id == "dev-K04-evidence-version-b":
                fact = facts.get("installed_version", {})
                raw_clarification = raw.get("clarification", {})
                if not isinstance(raw_clarification, dict):
                    raw_clarification = {}
                generated_installed_version_clarification = (
                    raw_clarification.get("missing_field") == "installed_version"
                )
                clarification_claims = [
                    claim
                    for claim in claims
                    if claim.get("knowledge_source") == "USER_CLARIFICATION"
                    and claim.get("missing_field") == "installed_version"
                ]
                targeted = bool(
                    clarification_claims
                    and re.search(r"(?:实际安装|当前环境|已安装).*Scanpy.*版本|Scanpy.*(?:实际安装|当前环境|已安装).*版本",
                                  run["observed"]["answer"])
                )
                k04_rows.append(
                    {
                        "run_id": run["run_id"],
                        "installed_version_value": fact.get("value"),
                        "installed_version_availability": fact.get("availability"),
                        "semantic_missing": fact.get("availability") == "missing"
                        and str(fact.get("value", "")).strip().casefold() == "null",
                        "clarification_field": clarification_claims[-1].get("missing_field")
                        if clarification_claims else None,
                        "generated_installed_version_clarification": generated_installed_version_clarification,
                        "targeted_clarification": targeted,
                        "generated_target_preserved": (
                            not generated_installed_version_clarification or targeted
                        ),
                        "support_check": support,
                        "not_rejected_as_available": support.get("reason")
                        != "clarification_field_already_available",
                    }
                )

            if case_id in KEY_FACTS:
                required = KEY_FACTS[case_id]
                context_present = required <= set(facts)
                context_safe = all(
                    fact.get("authority") == "user_provided_context_only"
                    and fact.get("scientific_evidence") is False
                    and fact.get("external_scientific_truth") is False
                    and fact.get("method_requirement_evidence") is False
                    and fact.get("execution_authorized") is False
                    for field, fact in facts.items()
                    if field in required
                )
                final_fact_claims = [
                    claim for claim in claims
                    if claim.get("knowledge_source") in {"USER_PROVIDED_FACT", "OBSERVED_STATE"}
                ]
                dependency_ids = {
                    str(fact_id)
                    for claim in claims
                    for fact_id in claim.get("context_fact_ids", [])
                }
                required_ids = {f"user:{field}" for field in required}
                dependency_preserved = bool(required_ids & dependency_ids)
                final_authority_safe = bool(final_fact_claims) and all(
                    claim.get("scientific_assertion") is False
                    and claim.get("trusted") is False
                    and claim.get("execution_authorized") is False
                    and not claim.get("citations")
                    and all(_safe_context_authority(value)
                            for value in claim.get("context_authority", {}).values())
                    for claim in final_fact_claims
                )
                authority_rows.append(
                    {
                        "run_id": run["run_id"],
                        "required_fields": sorted(required),
                        "context_present": context_present,
                        "context_authority_safe": context_safe,
                        "final_fact_claim_count": len(final_fact_claims),
                        "dependency_preserved": dependency_preserved,
                        "final_authority_safe": final_authority_safe,
                        "support_check_reason": support.get("reason"),
                        "not_rejected_for_missing_external_evidence": support.get("reason")
                        not in {
                            "context_fact_not_bound",
                            "context_fact_requires_registered_handle",
                            "context_fact_cannot_support_scientific_assertion",
                        },
                    }
                )

                raw_mixed = [
                    segment
                    for segment in raw_segments
                    if segment.get("basis") in {"USER_PROVIDED_FACT", "OBSERVED_STATE"}
                    and MIXED_MARKERS.search(str(segment.get("text") or ""))
                ]
                final_state = [
                    claim for claim in final_fact_claims
                    if claim.get("context_fact_ids")
                ]
                final_reasoned = [
                    claim for claim in claims
                    if claim.get("knowledge_source") == "MODEL_KNOWLEDGE"
                    and claim.get("reasoning_dependency") == "context_facts"
                    and claim.get("context_fact_ids")
                ]
                unsplit_mixed = [
                    claim for claim in final_state if MIXED_MARKERS.search(str(claim.get("text") or ""))
                ]
                mixed_rows.append(
                    {
                        "run_id": run["run_id"],
                        "raw_mixed_segments": len(raw_mixed),
                        "final_state_claims": len(final_state),
                        "final_reasoned_dependency_claims": len(final_reasoned),
                        "unsplit_mixed_state_claims": len(unsplit_mixed),
                        "pass": (
                            not unsplit_mixed
                            and (not raw_mixed or bool(final_state and final_reasoned))
                        ),
                    }
                )

                support_bases = []
                for call in receipt["provider_calls"]:
                    if call["purpose"] != "support_check":
                        continue
                    request = json.loads((directory / call["messages_ref"]).read_text())
                    user_payload = json.loads(request["messages"][-1]["content"])
                    support_bases.extend(
                        segment.get("basis") for segment in user_payload.get("segments", [])
                    )
                fact_claims_non_evidentiary = all(
                    claim.get("knowledge_source") not in {"KG_GROUNDED", "RETRIEVAL_GROUNDED"}
                    or bool(claim.get("citations"))
                    for claim in claims
                ) and all(
                    claim.get("knowledge_source") not in {"USER_PROVIDED_FACT", "OBSERVED_STATE"}
                    or (
                        claim.get("scientific_assertion") is False
                        and not claim.get("citations")
                        and claim.get("trusted") is False
                    )
                    for claim in claims
                )
                evidence_rows.append(
                    {
                        "run_id": run["run_id"],
                        "support_check_bases": support_bases,
                        "user_facts_excluded_from_support_check": not (
                            {"USER_PROVIDED_FACT", "OBSERVED_STATE"} & set(support_bases)
                        ),
                        "fact_claims_non_evidentiary": fact_claims_non_evidentiary,
                        "scientific_claims_require_citations": all(
                            claim.get("knowledge_source")
                            not in {"KG_GROUNDED", "RETRIEVAL_GROUNDED", "CAUTION_CONTEXT"}
                            or bool(claim.get("citations"))
                            for claim in claims
                        ),
                    }
                )

    k04_missing = len(k04_rows) == 4 and all(
        row["semantic_missing"] and row["not_rejected_as_available"] for row in k04_rows
    )
    # The runtime gate must allow and preserve a targeted installed-version
    # clarification; it does not require every stochastic lane to choose the
    # same clarification when their evidence inventories differ.
    clarification = (
        len(k04_rows) == 4
        and any(row["generated_installed_version_clarification"] for row in k04_rows)
        and all(
            row["not_rejected_as_available"] and row["generated_target_preserved"]
            for row in k04_rows
        )
    )
    authority = len(authority_rows) == 4 and all(
        row["context_present"]
        and row["context_authority_safe"]
        and row["final_authority_safe"]
        and row["dependency_preserved"]
        and row["not_rejected_for_missing_external_evidence"]
        for row in authority_rows
    )
    mixed = (
        len(mixed_rows) == 4
        and sum(row["raw_mixed_segments"] for row in mixed_rows) > 0
        and all(row["pass"] for row in mixed_rows)
    )
    evidence = len(evidence_rows) == 4 and all(
        row["user_facts_excluded_from_support_check"]
        and row["fact_claims_non_evidentiary"]
        and row["scientific_claims_require_citations"]
        for row in evidence_rows
    )
    lane_pass = not lane_errors
    receipt_pass = validation["pass"]
    ready = all((k04_missing, clarification, authority, mixed, evidence, lane_pass, receipt_pass))
    blockers = []
    for label, passed in (
        ("K04 null missingness", k04_missing),
        ("K04 targeted clarification", clarification),
        ("user fact authority propagation", authority),
        ("mixed segment separation", mixed),
        ("scientific evidence boundary", evidence),
        ("lane isolation", lane_pass),
        ("runtime receipts", receipt_pass),
    ):
        if not passed:
            blockers.append(label)
    return {
        "phase": "DEV-FINAL-FREEZE-SMOKE",
        "status": "PASS" if ready else "COMPLETE_WITH_BLOCKERS",
        "runtime_commit": RUNTIME_COMMIT,
        "runs_expected": 8,
        "runs_completed": sum(row["status"] == "completed" for row in validation["rows"]),
        "k04_null_missingness_pass": k04_missing,
        "targeted_clarification_pass": clarification,
        "user_fact_authority_pass": authority,
        "mixed_segment_gate_pass": mixed,
        "scientific_evidence_gate_pass": evidence,
        "lane_isolation_pass": lane_pass,
        "receipt_pass": receipt_pass,
        "dev_frozen": ready,
        "ready_for_evaluation_freeze": ready,
        "blockers": blockers,
        "k04_audit": k04_rows,
        "targeted_clarification_observed_lanes": [
            row["run_id"].split("--")[1]
            for row in k04_rows
            if row["generated_installed_version_clarification"]
        ],
        "authority_audit": authority_rows,
        "mixed_segment_audit": mixed_rows,
        "scientific_evidence_audit": evidence_rows,
        "lane_isolation_errors": lane_errors,
        "provider_models": [
            {
                "provider": key[0],
                "requested_model": key[1],
                "returned_model": key[2],
                "calls": count,
            }
            for key, count in provider_models.items()
        ],
        "formal_scoring_performed": False,
        "questions_or_knowledge_changed": False,
    }


def report(result):
    gates = [
        ("K04_NULL_MISSINGNESS_PASS", result["k04_null_missingness_pass"]),
        ("TARGETED_CLARIFICATION_PASS", result["targeted_clarification_pass"]),
        ("USER_FACT_AUTHORITY_PASS", result["user_fact_authority_pass"]),
        ("MIXED_SEGMENT_GATE_PASS", result["mixed_segment_gate_pass"]),
        ("SCIENTIFIC_EVIDENCE_GATE_PASS", result["scientific_evidence_gate_pass"]),
        ("LANE_ISOLATION_PASS", result["lane_isolation_pass"]),
        ("RECEIPT_PASS", result["receipt_pass"]),
    ]
    gate_lines = "\n".join(f"- {name}: `{str(value).lower()}`" for name, value in gates)
    return f"""# DEV final freeze smoke

Status: `{result['status']}`. Eight authorized units completed against runtime
`{result['runtime_commit']}`. This run does not rescore the complete DEV set.

## Gates

{gate_lines}

`DEV_FROZEN={str(result['dev_frozen']).lower()}` and
`READY_FOR_EVALUATION_FREEZE={str(result['ready_for_evaluation_freeze']).lower()}`.

The audit binds each decision to runtime context facts, normalized answer provenance,
support-check inputs, final output, lane-isolation captures, and runtime receipts.
No K01b control, W01/W02, full DEV rerun, formal scoring, question change, prompt
change, KG/RAG change, or seed expansion was performed.
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.output.resolve())
    write(args.output / "freeze_audit.json", result)
    with (args.output / "freeze_report.md").open("x", encoding="utf-8") as stream:
        stream.write(report(result))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
