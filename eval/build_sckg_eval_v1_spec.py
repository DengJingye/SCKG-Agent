"""Build the scKG-Eval v1 specification from declared suites and existing artifacts.

The builder is intentionally specification-only.  It reads existing evidence,
validates paths and writes registries; it does not execute any benchmark.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from eval.scientific_kg_inventory_snapshot_v1 import protected_identity


OUTPUT = ROOT / "data/evaluation/sckg_eval_v1"
SPEC_PATH = ROOT / "docs/evaluation/SCKG_EVAL_V1_SPEC.md"
MATRIX_PATH = ROOT / "docs/status/MIDTERM_EVALUATION_MATRIX_V1.md"

STATUSES = {
    "CURRENT_MEASURED", "FROZEN_HISTORICAL", "DEVELOPMENT_RESULT", "PILOT",
    "PARTIAL", "NOT_RUN", "QUARANTINED",
}


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def read_json(path: str) -> dict[str, Any]:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_head() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()


def tracked(path: str) -> bool:
    result = subprocess.run(
        ["git", "ls-files", "--error-unmatch", path], cwd=ROOT,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


def metric(
    metric_id: str,
    suite: str,
    name: str,
    definition: str,
    numerator: str,
    denominator: str,
    unit: str,
    direction: str,
    valid_scope: str,
    invalid_interpretations: list[str],
    aggregation_unit: str,
    status: str,
) -> dict[str, Any]:
    return {
        "metric_id": metric_id,
        "suite": suite,
        "name": name,
        "definition": definition,
        "numerator": numerator,
        "denominator": denominator,
        "unit": unit,
        "higher_or_lower_better": direction,
        "valid_scope": valid_scope,
        "invalid_interpretations": invalid_interpretations,
        "aggregation_unit": aggregation_unit,
        "status": status,
    }


def count_metric(metric_id: str, suite: str, name: str, definition: str, unit: str, status: str) -> dict[str, Any]:
    return metric(
        metric_id, suite, name, definition, "count of matching records", "not applicable",
        unit, "descriptive", f"{suite} inventory or error accounting",
        ["scientific correctness", "overall system accuracy"], unit, status,
    )


def rate_metric(
    metric_id: str,
    suite: str,
    name: str,
    definition: str,
    numerator: str,
    denominator: str,
    unit: str,
    direction: str,
    status: str,
    invalid: list[str] | None = None,
) -> dict[str, Any]:
    return metric(
        metric_id, suite, name, definition, numerator, denominator, "rate", direction,
        f"frozen {suite} cases at the declared {unit} aggregation level",
        invalid or ["overall system accuracy", "independent evidence without a valid split"],
        unit, status,
    )


def metric_registry() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for metric_id, name, definition, unit in (
        ("kg_total_nodes", "Total nodes", "Physical nodes in the declared Scientific KG layer set.", "node"),
        ("kg_total_edges", "Total edges", "Physical edges in the declared Scientific KG layer set.", "relation"),
        ("kg_entity_type_count", "Entity type count", "Distinct node record types in the inventory view.", "entity type"),
        ("kg_relation_type_count", "Relation type count", "Distinct edge predicates in the inventory view.", "relation type"),
        ("kg_invalid_endpoint_count", "Invalid endpoint count", "Relations whose source or target cannot be resolved in their layer.", "relation"),
        ("kg_orphan_claim_count", "Orphan claim count", "Claims whose subject identity is missing from the same layer.", "AtomicClaimRevision"),
        ("kg_claim_without_scope_count", "Claim without scope count", "Claims lacking a resolvable ApplicabilityScope.", "AtomicClaimRevision"),
        ("kg_claim_without_evidence_count", "Claim without evidence count", "Claims lacking a supporting EvidenceAssessment reference.", "AtomicClaimRevision"),
        ("kg_dangling_evidence_span_count", "Dangling EvidenceSpan count", "Materialized spans not referenced by an EvidenceAssessment.", "EvidenceSpan"),
        ("kg_unresolved_source_revision_count", "Unresolved SourceRevision count", "Evidence spans whose SourceRevision cannot be resolved.", "EvidenceSpan"),
        ("kg_broken_rag_mapping_count", "Broken RAG mapping count", "Evidence-bound units without an exact frozen-corpus mapping.", "claim-evidence pair"),
        ("kg_duplicate_canonical_identity_count", "Duplicate canonical identity count", "Adjudicated canonical identities with more than one active canonical record.", "canonical identity"),
        ("kg_candidate_count", "Candidate count", "Scientific claim revisions in candidate state.", "AtomicClaimRevision"),
        ("kg_reviewed_count", "Reviewed count", "Scientific claim revisions with a completed review decision.", "AtomicClaimRevision"),
        ("kg_trusted_canonical_count", "Trusted or canonical count", "Scientific claim revisions promoted to trusted or canonical state.", "AtomicClaimRevision"),
        ("kg_rejected_count", "Rejected count", "Scientific claim revisions rejected by governance review.", "AtomicClaimRevision"),
        ("kg_superseded_count", "Superseded count", "Scientific claim revisions superseded by a governed successor.", "AtomicClaimRevision"),
    ):
        rows.append(count_metric(metric_id, "KG-Eval", name, definition, unit, "CURRENT_MEASURED"))
    rows.append(rate_metric(
        "kg_schema_conformance_rate", "KG-Eval", "Schema conformance rate",
        "Fraction of records that validate against the declared ontology schema.",
        "schema-valid records", "all evaluated records", "record", "higher", "CURRENT_MEASURED",
    ))
    for metric_id, name, definition in (
        ("kg_claim_evidence_binding_precision", "Claim-evidence binding precision", "Fraction of evaluated bindings that directly support the bound claim."),
        ("kg_evidence_resolvability", "Evidence resolvability", "Fraction of evidence references resolving through span and source identity."),
        ("kg_source_correctness", "Source correctness", "Fraction of evaluated evidence bindings pointing to the adjudicated source work or revision."),
        ("kg_scope_correctness", "Scope correctness", "Fraction of evaluated claims whose explicit applicability scope matches gold."),
        ("kg_version_correctness", "Version correctness", "Fraction of evaluated claims and evidence bindings with the correct version boundary."),
    ):
        rows.append(rate_metric(metric_id, "KG-Eval", name, definition, "correct evaluated units", "all adjudicated evaluated units", "claim-evidence pair", "higher", "PARTIAL"))
    for level in range(5):
        rows.append(count_metric(
            f"kg_readiness_l{level}_count", "KG-Eval", f"L{level} readiness count",
            f"OperatorRevisions whose highest exclusive readiness is L{level}.", "OperatorRevision", "CURRENT_MEASURED",
        ))
        rows.append(rate_metric(
            f"kg_readiness_l{level}_rate", "KG-Eval", f"L{level} readiness rate",
            f"Fraction of audited OperatorRevisions whose highest exclusive readiness is L{level}.",
            f"OperatorRevisions at L{level}", "all audited OperatorRevisions", "OperatorRevision", "descriptive", "CURRENT_MEASURED",
            ["scientific correctness", "coverage outside the audited operator slice"],
        ))

    for metric_id, name, unit in (
        ("ingestion_entity_precision", "Entity precision", "entity"),
        ("ingestion_entity_recall", "Entity recall", "entity"),
        ("ingestion_entity_f1", "Entity F1", "entity"),
        ("ingestion_relation_precision", "Relation precision", "relation"),
        ("ingestion_relation_recall", "Relation recall", "relation"),
        ("ingestion_relation_f1", "Relation F1", "relation"),
        ("ingestion_claim_precision", "AtomicClaim precision", "AtomicClaimRevision"),
        ("ingestion_claim_recall", "AtomicClaim recall", "AtomicClaimRevision"),
        ("ingestion_claim_f1", "AtomicClaim F1", "AtomicClaimRevision"),
        ("ingestion_evidence_span_exact_match", "EvidenceSpan exact match", "EvidenceSpan"),
        ("ingestion_evidence_span_overlap", "EvidenceSpan overlap", "EvidenceSpan"),
        ("ingestion_claim_evidence_alignment", "Claim-evidence alignment accuracy", "claim-evidence pair"),
        ("ingestion_scope_accuracy", "Scope accuracy", "AtomicClaimRevision"),
        ("ingestion_version_accuracy", "Version accuracy", "AtomicClaimRevision"),
        ("ingestion_duplicate_detection_accuracy", "Duplicate detection accuracy", "candidate record pair"),
        ("ingestion_hallucinated_candidate_rate", "Hallucinated candidate rate", "candidate record"),
        ("ingestion_admin_review_acceptance_rate", "Admin review acceptance rate", "reviewed candidate"),
    ):
        direction = "lower" if metric_id == "ingestion_hallucinated_candidate_rate" else "higher"
        rows.append(rate_metric(
            metric_id, "Ingestion-Eval", name,
            f"Gold-aligned {name.lower()} for PDF or authoritative-source extraction into Candidate Scientific KG.",
            "correct or matched extracted units", "all applicable predicted or gold units as declared by the metric", unit,
            direction, "NOT_RUN", ["trusted knowledge quality", "automatic promotion authority", "overall system accuracy"],
        ))

    retrieval = (
        ("retrieval_hit_at_5", "Hit@5", "queries with accepted evidence in top 5", "all parent information needs", "higher"),
        ("retrieval_hit_at_10", "Hit@10", "queries with accepted evidence in top 10", "all parent information needs", "higher"),
        ("retrieval_mrr_at_10", "MRR@10", "sum of reciprocal first-accepted-evidence ranks through 10", "all parent information needs", "higher"),
        ("retrieval_source_correctness", "Source correctness", "returned evidence with correct source", "all adjudicated returned evidence", "higher"),
        ("retrieval_scope_correctness", "Scope correctness", "returned evidence with correct scope", "all adjudicated returned evidence", "higher"),
        ("retrieval_version_correctness", "Version correctness", "returned evidence with correct version", "all adjudicated returned evidence", "higher"),
        ("retrieval_evidence_binding_correctness", "Evidence-binding correctness", "returned evidence with correct claim binding", "all adjudicated returned evidence", "higher"),
        ("retrieval_abstention_accuracy", "Abstention accuracy", "unsupported needs correctly abstained", "all gold-abstention needs", "higher"),
        ("retrieval_false_certainty_rate", "False-certainty rate", "unsupported needs answered with certainty", "all gold-abstention needs", "lower"),
        ("retrieval_scientific_kg_participation", "Scientific KG participation", "needs with a verified Scientific KG path", "all evaluated needs", "descriptive"),
        ("retrieval_helped_rate", "HELPED rate", "paired needs improved by Scientific KG", "all paired needs", "higher"),
        ("retrieval_neutral_rate", "NEUTRAL rate", "paired needs unchanged by Scientific KG", "all paired needs", "descriptive"),
        ("retrieval_hurt_rate", "HURT rate", "paired needs degraded by Scientific KG", "all paired needs", "lower"),
    )
    for metric_id, name, numerator, denominator, direction in retrieval:
        rows.append(rate_metric(metric_id, "Retrieval-Eval", name, f"{name} at the parent scientific information-need level.", numerator, denominator, "parent scientific information need", direction, "PARTIAL"))
    rows.append(count_metric("retrieval_false_filter_event_count", "Retrieval-Eval", "False-filter event count", "Accepted evidence removed by a filter for an invalid reason.", "parent scientific information need", "PARTIAL"))

    agent = (
        ("agent_intent_accuracy", "Intent accuracy", "correct intent proposals", "tasks with intent gold", "higher"),
        ("agent_action_selection_accuracy", "Action selection accuracy", "tasks with correct selected action", "all conversation tasks", "higher"),
        ("agent_tool_trigger_precision", "Tool trigger precision", "permitted triggered tools", "all triggered tools", "higher"),
        ("agent_tool_trigger_recall", "Tool trigger recall", "required tools triggered", "all required tools", "higher"),
        ("agent_parameter_correctness", "Parameter correctness", "correct required parameters", "all required parameters", "higher"),
        ("agent_data_binding_accuracy", "Data binding accuracy", "tasks with correct artifact binding", "tasks requiring data binding", "higher"),
        ("agent_clarification_accuracy", "Clarification accuracy", "correct clarification decisions", "clarification-required tasks", "higher"),
        ("agent_block_accuracy", "Block accuracy", "correct block decisions", "block-required tasks", "higher"),
        ("agent_unnecessary_tool_call_rate", "Unnecessary tool call rate", "unnecessary calls", "all observed calls", "lower"),
        ("agent_unauthorized_execution_rate", "Unauthorized execution rate", "unauthorized executions", "all conversation tasks", "lower"),
        ("agent_false_terminal_completion_rate", "Declared-complete-with-terminal-unmet rate", "tasks declared complete with unmet terminal", "all completion declarations", "lower"),
    )
    for metric_id, name, numerator, denominator, direction in agent:
        rows.append(rate_metric(metric_id, "Agent-Eval", name, f"{name} for conversation tasks, reported separately for proposal, governance correction, actual call, and final state.", numerator, denominator, "conversation task", direction, "DEVELOPMENT_RESULT", ["LLM accuracy when deterministic correction is included", "overall scientific correctness"] ))

    planner = (
        ("planner_action_precision", "Action precision", "gold-allowed proposed actions", "all proposed actions", "higher"),
        ("planner_action_recall", "Action recall", "required actions proposed", "all required actions", "higher"),
        ("planner_reuse_accuracy", "Reuse accuracy", "scenarios with correct reuse", "reuse-addressable scenarios", "higher"),
        ("planner_recompute_accuracy", "Recompute accuracy", "scenarios with correct recomputation", "recompute-required scenarios", "higher"),
        ("planner_block_accuracy", "Block accuracy", "scenarios with correct block", "block-required scenarios", "higher"),
        ("planner_invalid_reuse_rate", "Invalid reuse rate", "invalid reused representations", "all reuse decisions", "lower"),
        ("planner_unnecessary_step_rate", "Unnecessary step rate", "unnecessary steps", "all proposed steps", "lower"),
        ("planner_dependency_correctness", "Dependency correctness", "dependency constraints satisfied", "all required dependency constraints", "higher"),
    )
    for metric_id, name, numerator, denominator, direction in planner:
        rows.append(rate_metric(metric_id, "Planner-Eval", name, f"{name} over frozen data-state scenarios.", numerator, denominator, "data-state scenario", direction, "PILOT", ["broad planner accuracy", "independent validation", "LLM-only behavior"] ))

    justification = (
        ("justification_scientific_evidence_recall", "Scientific evidence recall", "required scientific evidence atoms returned", "all required scientific evidence atoms", "higher"),
        ("justification_decision_evidence_precision", "Decision-evidence precision", "returned references directly supporting the decision atom", "all returned scientific references", "higher"),
        ("justification_extra_nondecision_evidence_rate", "Extra non-decision evidence rate", "non-decision evidence references", "all returned scientific references", "lower"),
        ("justification_runtime_citation_abstention", "Runtime citation abstention", "runtime-owned atoms without scientific citations", "all runtime-owned atoms", "higher"),
        ("justification_ownership_fidelity", "Ownership fidelity", "atoms with correct evidence owner", "all DecisionJustificationAtoms", "higher"),
        ("justification_scope_fidelity", "Scope fidelity", "scientific atoms with correct scope", "all scope-addressable scientific atoms", "higher"),
        ("justification_epistemic_fidelity", "Epistemic fidelity", "atoms preserving candidate/trusted status", "all epistemic-state atoms", "higher"),
        ("justification_representation_linkage", "Representation linkage", "runtime atoms linked to the correct representation", "all representation-addressable atoms", "higher"),
        ("justification_evidence_resolvability", "Evidence resolvability", "references resolving through frozen bindings", "all returned scientific references", "higher"),
        ("justification_negative_control_pass_rate", "Negative-control pass rate", "single-fault mutations with expected first failure", "all single-fault mutations", "higher"),
        ("justification_behavior_invariance", "Behavior invariance", "scenarios with unchanged behavior digest", "all paired projection scenarios", "higher"),
    )
    for metric_id, name, numerator, denominator, direction in justification:
        rows.append(rate_metric(metric_id, "Justification-Eval", name, f"{name} at DecisionJustificationAtom level.", numerator, denominator, "DecisionJustificationAtom or paired mutation", direction, "FROZEN_HISTORICAL", ["overall answer accuracy", "new independent evidence", "unscoped citation quality"] ))

    e2e = (
        ("e2e_plan_compile_rate", "Plan compile rate", "tasks with compiled plan", "all dataset-task units", "higher"),
        ("e2e_notebook_compile_rate", "Notebook compile rate", "tasks with compiled notebook", "all dataset-task units", "higher"),
        ("e2e_execution_success_rate", "Execution success rate", "tasks completing execution without unplanned errors", "all execution-attempted units", "higher"),
        ("e2e_terminal_completion_rate", "Terminal-state completion rate", "tasks satisfying declared scientific terminal", "all dataset-task units", "higher"),
        ("e2e_artifact_integrity_rate", "Artifact integrity rate", "artifacts matching frozen identities", "all checked artifacts", "higher"),
        ("e2e_input_mutation_rate", "Input mutation rate", "input artifacts unexpectedly mutated", "all protected input artifacts", "lower"),
        ("e2e_scientific_validation_pass_rate", "Scientific validation pass rate", "tasks passing scientific validation", "all validation-addressable tasks", "higher"),
        ("e2e_human_confirmation_completion_rate", "Human confirmation completion rate", "tasks with required human confirmation completed", "all human-confirmation-required tasks", "higher"),
    )
    for metric_id, name, numerator, denominator, direction in e2e:
        rows.append(rate_metric(metric_id, "E2E-Eval", name, f"{name} for dataset by scientific-task units.", numerator, denominator, "dataset x scientific task", direction, "PARTIAL", ["LLM planning accuracy", "scientific success when terminal is BLOCKED", "production deployment readiness"] ))

    trace = (
        ("trace_stage_coverage", "Trace stage coverage", "required stages represented", "all required stages", "higher"),
        ("trace_referential_integrity", "Referential integrity", "trace references resolving to artifacts", "all trace references", "higher"),
        ("trace_first_causal_failure_accuracy", "First causal failure accuracy", "scenarios with correct first cause", "all injected-failure scenarios", "higher"),
        ("trace_owner_attribution_accuracy", "Owner attribution accuracy", "failures assigned to correct owner", "all injected-failure scenarios", "higher"),
        ("trace_missing_span_rate", "Missing span rate", "required trace spans missing", "all required trace spans", "lower"),
        ("trace_ordering_accuracy", "Trace ordering accuracy", "required stage-order constraints satisfied", "all order constraints", "higher"),
        ("trace_replay_consistency", "Replay consistency", "replays preserving deterministic trace facts", "all deterministic replay pairs", "higher"),
    )
    for metric_id, name, numerator, denominator, direction in trace:
        rows.append(rate_metric(metric_id, "Trace-Eval", name, f"{name} for trace or injected-failure scenarios.", numerator, denominator, "trace or injected-failure scenario", direction, "NOT_RUN", ["runtime success", "scientific correctness", "benchmark result before injected cases are frozen"] ))

    regression = (
        ("regression_unit_pass_rate", "Unit pass rate", "passing unit tests", "all executed unit tests", "higher"),
        ("regression_integration_pass_rate", "Integration pass rate", "passing integration tests", "all executed integration tests", "higher"),
        ("regression_regression_pass_rate", "Regression pass rate", "passing regression tests", "all executed regression tests", "higher"),
        ("regression_artifact_integrity", "Artifact integrity", "protected artifacts unchanged", "all protected artifacts", "higher"),
        ("regression_deterministic_replay", "Deterministic replay", "matching deterministic replays", "all replay pairs", "higher"),
        ("regression_cold_reload_consistency", "Cold reload consistency", "cold reloads matching expected output", "all cold reload checks", "higher"),
    )
    for metric_id, name, numerator, denominator, direction in regression:
        rows.append(rate_metric(metric_id, "Regression-Eval", name, f"Engineering-only {name.lower()}.", numerator, denominator, "test or replay", direction, "CURRENT_MEASURED", ["scientific accuracy", "independent validation", "sum across overlapping test selections"] ))
    rows.append(count_metric("regression_new_regression_count", "Regression-Eval", "New regression count", "Previously passing governed checks that now fail.", "test", "CURRENT_MEASURED"))
    rows.append(count_metric("regression_historical_baseline_failure_count", "Regression-Eval", "Historical baseline failure count", "Known historical baseline or stale-lock failures retained separately.", "test", "CURRENT_MEASURED"))
    for row in rows:
        if row["suite"] == "Regression-Eval" and "scientific accuracy" not in row["invalid_interpretations"]:
            row["invalid_interpretations"].append("scientific accuracy")
    return rows


def suites(metrics: list[dict[str, Any]]) -> list[dict[str, Any]]:
    configs = [
        ("KG-Eval", "Scientific KG structure, semantic completeness, evidence grounding, governance, and readiness.", ["node", "relation", "AtomicClaimRevision", "claim-evidence pair", "OperatorRevision"], "CURRENT_MEASURED", "Scientific KG Inventory Snapshot v1", "No canonical cross-layer identity merge; correctness metrics remain partial.", []),
        ("Ingestion-Eval", "PDF or authoritative source to Candidate Scientific KG extraction quality.", ["document"], "PLANNED_PILOT_NOT_RUN", "Specification only", "Freeze gold for 3-5 manually annotated authoritative PDFs before extraction.", ["entity", "relation", "claim", "EvidenceSpan"]),
        ("Retrieval-Eval", "Retrieval, grounding, abstention, and Scientific KG contribution per information need.", ["parent scientific information need"], "PARTIAL_CURRENT_AND_HISTORICAL", "Independent Retrieval Validation v1 plus current direct-evidence audits", "Disclosed SEALED cases are quarantined from future post-fix validation.", []),
        ("Agent-Eval", "Intent, action, tool, parameter, binding, clarification, blocking, and terminal behavior.", ["conversation task"], "DEVELOPMENT_RESULT", "36-case Agent Tool Selection Eval v1", "Development cases are visible and are not independent validation.", ["LLM proposal", "governance correction", "actual tool call", "final task state"]),
        ("Planner-Eval", "State-aware reuse, recompute, block, action, and dependency decisions.", ["data-state scenario"], "PILOT_PARTIAL", "Four paired KG/planner scenarios and PBMC raw/processed replay evidence", "No frozen broad planner benchmark yet.", []),
        ("Justification-Eval", "Decision-local evidence ownership, fidelity, resolvability, and robustness.", ["DecisionJustificationAtom"], "FROZEN_HISTORICAL", "12 atoms, 8 single-fault mutations, and 4 behavior-invariance pairs", "Strong formal historical evidence; not new independent validation.", []),
        ("E2E-Eval", "Engineering, data-state, scientific terminal, and human terminal outcomes.", ["dataset x scientific task"], "CURRENT_MEASURED_PARTIAL", "Raw and Processed PBMC3k current-version replay v2", "Annotation terminals remain BLOCKED; execution is not full scientific completion.", []),
        ("Trace-Eval", "Trace completeness, causal localization, ownership, ordering, and replay consistency.", ["trace or injected-failure scenario"], "SPEC_DEFINED_BENCHMARK_NOT_RUN", "Specification only", "No frozen injected-failure campaign has been run.", []),
        ("Regression-Eval", "Engineering stability and artifact integrity.", ["test or deterministic replay"], "CURRENT_MEASURED_ENGINEERING", "Checkpoint-focused and regression test artifacts", "Overlapping test counts must not be summed or called scientific accuracy.", []),
    ]
    baselines = {
        "Retrieval-Eval": ["BM25", "Dense", "Hybrid", "Scientific KG + Hybrid"],
        "Agent-Eval": ["LLM proposal", "deterministic governance correction", "actual tool call"],
        "Planner-Eval": ["pre-KG planner", "current KG-enabled planner", "frozen state gold"],
        "Justification-Eval": ["global evidence bag", "decision-local evidence projection"],
        "Ingestion-Eval": ["manual gold", "candidate extractor"],
        "Trace-Eval": ["expected injected first cause", "observed first cause"],
        "Regression-Eval": ["previous frozen checkpoint"],
    }
    result = []
    for suite_id, purpose, primary_units, status, strongest, gap, nested in configs:
        row = {
            "suite_id": suite_id,
            "purpose": purpose,
            "primary_units": primary_units,
            "nested_units": nested,
            "status": status,
            "metric_ids": [row["metric_id"] for row in metrics if row["suite"] == suite_id],
            "baselines_or_ablations": baselines.get(suite_id, []),
            "current_strongest_evidence": strongest,
            "main_gap": gap,
            "global_score_eligible": False,
        }
        if suite_id == "Ingestion-Eval":
            row["future_dataset_spec"] = {
                "document_count": "3-5",
                "document_type": "manually annotated authoritative PDFs",
                "gold_freeze_rule": "gold must be frozen before extraction",
            }
        elif suite_id == "Retrieval-Eval":
            row["result_classifications"] = [
                "DEVELOPMENT", "REGRESSION", "HISTORICAL_SEALED", "QUARANTINED_AFTER_DISCLOSURE"
            ]
        elif suite_id == "Agent-Eval":
            row["observation_layers"] = [
                "LLM proposal", "deterministic governance correction", "actual tool call", "final task state"
            ]
        elif suite_id == "Planner-Eval":
            row["test_case_schema"] = [
                "case_id", "input_artifact", "current_representation_records", "representation_status",
                "identity_hashes", "target_state", "gold_reuse", "gold_recompute", "gold_block",
                "required_actions", "forbidden_actions",
            ]
            row["mapped_cases"] = [
                "Raw PBMC3k", "Processed PBMC3k", "valid graph -> Leiden", "stale graph",
                "Harmony -> neighbors", "transformed expression -> Scrublet",
            ]
        elif suite_id == "Justification-Eval":
            row["formal_assets"] = {"decision_atoms": 12, "single_fault_mutations": 8, "paired_scenarios": 4}
        elif suite_id == "E2E-Eval":
            row["evaluation_layers"] = ["engineering", "data_state", "scientific_terminal", "human_terminal"]
            row["mapped_cases"] = ["Raw PBMC3k", "Processed PBMC3k"]
        elif suite_id == "Trace-Eval":
            row["test_case_schema"] = [
                "case_id", "parent_scenario_id", "injected_failure_type", "expected_first_causal_failure",
                "expected_owner", "required_stages", "required_references", "ordering_constraints", "replay_id",
            ]
            row["future_failure_types"] = [
                "route_failure", "missing_artifact", "stale_representation", "scientific_subject_unresolved",
                "evidence_unresolved", "public_filter_rejection", "policy_deny", "notebook_failure",
                "terminal_state_unmet", "review_rejected",
            ]
        elif suite_id == "Regression-Eval":
            row["overlap_policy"] = "do not sum overlapping test selections"
        result.append(row)
    return result


def split_taxonomy() -> dict[str, Any]:
    return {
        "schema_version": "sckg-eval-split-taxonomy-v1",
        "splits": {
            "DEV": {
                "definition": "Visible during development and repeatable for diagnosis or tuning.",
                "may_inform_changes": True,
                "independent_claim_allowed": False,
            },
            "REGRESSION": {
                "definition": "Known expected answer retained to prevent recurrence of a fixed defect.",
                "may_inform_changes": True,
                "independent_claim_allowed": False,
            },
            "SEALED": {
                "definition": "Hidden before the formal run, immutable after freeze, and unavailable for post-run tuning.",
                "may_inform_changes": False,
                "independent_claim_allowed": True,
                "disclosure_policy": "Disclosure quarantines cases from future post-fix validation while preserving the historical run.",
            },
            "EXTERNAL": {
                "definition": "External benchmark, new dataset, or new user independent from local development.",
                "may_inform_changes": False,
                "independent_claim_allowed": True,
            },
        },
        "inheritance_rule": "Nested atoms, mutations, paraphrases, and replicates inherit the parent split.",
    }


def evidence_entry(
    evidence_id: str,
    suite: str,
    path: str,
    status: str,
    result_type: str,
    interpretation: str,
    split: str,
    verified_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "evidence_id": evidence_id,
        "evaluation_suite": suite,
        "artifact_path": path,
        "artifact_sha256": sha256(ROOT / path) if (ROOT / path).is_file() else None,
        "artifact_tracking": "TRACKED" if tracked(path) else "UNTRACKED_WORKSPACE",
        "status": status,
        "result_type": result_type,
        "split": split,
        "interpretation": interpretation,
        "verified_result": verified_result or {},
    }


def evidence_map() -> list[dict[str, Any]]:
    node_counts = read_json("data/evaluation/scientific_kg_inventory_snapshot_v1/node_type_counts.json")["scientific_kg"]
    relation_counts = read_json("data/evaluation/scientific_kg_inventory_snapshot_v1/relation_type_counts.json")["scientific_kg"]
    governance = read_json("data/evaluation/scientific_kg_inventory_snapshot_v1/governance_counts.json")
    readiness = read_json("data/evaluation/scientific_kg_inventory_snapshot_v1/readiness_counts.json")
    neighbors = read_json("data/evaluation/scientific_kg_neighbors_direct_evidence_repair_v1/manifest.json")
    agent_summary = read_json("data/evaluation/agent_tool_selection_v1/live-20260919-36-configured/summary.json")
    replay = read_json("data/evaluation/current_version_pbmc3k_replay_v2/20260919-current-01/summary.json")
    paired = read_json("data/evaluation/scientific_kg_contribution_v1_corrected/report.json")
    justification_before = read_json("data/evaluation/scientific_decision_justification_fidelity_v1_1/report.json")
    justification_after = read_json("data/evaluation/scientific_decision_justification_fidelity_v1_2/report.json")
    celltypist = read_json("data/evaluation/celltypist_runtime_qualification_v1/manifest.json")

    def fraction(report: dict[str, Any], *keys: str) -> str:
        value: Any = report
        for key in keys:
            value = value[key]
        return f"{value['numerator']}/{value['denominator']}"

    before_precision = fraction(justification_before, "metrics", "evidence_fidelity", "scientific_decision_evidence_precision")
    before_recall = fraction(justification_before, "metrics", "evidence_fidelity", "scientific_evidence_recall")
    before_behavior = fraction(justification_before, "metrics", "behavior_digest_invariance")
    after_precision = fraction(justification_after, "metrics", "evidence_fidelity", "scientific_decision_evidence_precision")
    after_recall = fraction(justification_after, "metrics", "evidence_fidelity", "scientific_evidence_recall")
    after_behavior = fraction(justification_after, "metrics", "behavior_digest_invariance")
    rows = [
        evidence_entry("kg_inventory_snapshot_v1", "KG-Eval", "data/evaluation/scientific_kg_inventory_snapshot_v1/manifest.json", "CURRENT_MEASURED", "READ_ONLY_INVENTORY", "Current quantitative fact source; physical coverage is not scientific correctness.", "REGRESSION", {"physical_nodes": sum(node_counts.values()), "physical_edges": sum(relation_counts.values()), "candidate_claims": governance["candidate_claims"], "l4_operator_revisions": readiness["highest_exclusive"]["L4"], "audited_operator_revisions": readiness["operator_revision_count"]}),
        evidence_entry("retrieval_benchmark_v1_dev", "Retrieval-Eval", "eval_v2/retrieval_benchmark_v1_dev/report.json", "DEVELOPMENT_RESULT", "DEVELOPMENT_BENCHMARK", "Visible development benchmark; not independent evidence.", "DEV"),
        evidence_entry("independent_retrieval_validation_v1_historical", "Retrieval-Eval", "eval_v2/independent_retrieval_validation_v1/report.json", "FROZEN_HISTORICAL", "HISTORICAL_SEALED_RUN", "The formal historical run remains valid for its frozen SUT.", "SEALED"),
        evidence_entry("independent_retrieval_validation_v1_disclosed_cases", "Retrieval-Eval", "eval_v2/independent_retrieval_validation_v1/query_set.jsonl", "QUARANTINED", "DISCLOSED_CASE_SET", "Disclosed cases cannot support future post-fix validation; this does not invalidate the separate historical run.", "SEALED"),
        evidence_entry("direct_evidence_coverage_audit_v1", "KG-Eval", "data/evaluation/scientific_kg_direct_evidence_coverage_audit_v1/manifest.json", "FROZEN_HISTORICAL", "READINESS_AUDIT", "Historical direct-evidence readiness audit, superseded as current inventory by Checkpoint 1.", "REGRESSION"),
        evidence_entry("narrow_direct_evidence_qualification_v1", "Retrieval-Eval", "data/evaluation/scientific_kg_narrow_direct_evidence_qualification_v1/manifest.json", "PARTIAL", "PRODUCT_CHAIN_QUALIFICATION", "Known repository evidence qualification; explicitly not an independent benchmark.", "REGRESSION"),
        evidence_entry("neighbors_direct_evidence_repair_v1", "Retrieval-Eval", "data/evaluation/scientific_kg_neighbors_direct_evidence_repair_v1/manifest.json", "CURRENT_MEASURED", "FOCUSED_REPAIR_QUALIFICATION", "Focused current repair evidence, not broad retrieval accuracy.", "REGRESSION", {"repair_status": neighbors["repair_status"]}),
        evidence_entry("agent_tool_selection_eval_v1", "Agent-Eval", "data/evaluation/agent_tool_selection_v1/live-20260919-36-configured/summary.json", "DEVELOPMENT_RESULT", "REAL_LLM_DEVELOPMENT_EVAL", "Separates proposal, governed, actual-call, and terminal metrics; hand-authored visible cases.", "DEV", {"parent_cases": agent_summary["parent_cases_recorded"]}),
        evidence_entry("pbmc3k_replay_v2", "E2E-Eval", "data/evaluation/current_version_pbmc3k_replay_v2/20260919-current-01/summary.json", "CURRENT_MEASURED", "REAL_DATA_PRODUCT_REPLAY", "Engineering execution is separated from BLOCKED scientific and human terminals.", "REGRESSION", {"status": replay["status"], "raw_and_processed": set(replay["datasets"]) == {"raw", "processed"}, "full_scientific_task_completed": all(row["FULL_SCIENTIFIC_TASK_COMPLETED"] for row in replay["datasets"].values())}),
        evidence_entry("scientific_kg_contribution_paired_ablation", "Planner-Eval", "data/evaluation/scientific_kg_contribution_v1_corrected/report.json", "PILOT", "PAIRED_SYNTHETIC_ABLATION", "Four unchanged synthetic fixtures; evidence concerns behavior and explanation/provenance only.", "DEV", {"paired_scenarios": len(paired["paired"])}),
        evidence_entry("justification_fidelity_v1_1", "Justification-Eval", "data/evaluation/scientific_decision_justification_fidelity_v1_1/report.json", "FROZEN_HISTORICAL", "FORMAL_FAILURE_BASELINE", "Frozen formal baseline before decision-local projection.", "REGRESSION", {"precision": before_precision, "extra_nondecision_evidence": len(justification_before["failures"]), "recall": before_recall, "behavior_invariance": before_behavior}),
        evidence_entry("decision_local_projection_v1_2", "Justification-Eval", "data/evaluation/scientific_decision_justification_fidelity_v1_2/report.json", "FROZEN_HISTORICAL", "FORMAL_PAIRED_RESULT", "Frozen decision-local projection result over 12 atoms and 8 single-fault mutations.", "REGRESSION", {"precision": after_precision, "extra_nondecision_evidence": len(justification_after["failures"]), "recall": after_recall, "behavior_invariance": after_behavior}),
        evidence_entry("soupx_evidence_gap_acquisition_pilot", "Ingestion-Eval", "data/evaluation/evidence_gap_acquisition_pilot_v1_repaired/summary.json", "PILOT", "PDF_ACQUISITION_PILOT", "Bounded SoupX PDF/source acquisition and EvidenceSpan pilot; not extraction precision/recall.", "DEV"),
        evidence_entry("soupx_candidate_deposition_reuse_pilot", "Ingestion-Eval", "data/evaluation/candidate_knowledge_deposition_pilot_v1/summary.json", "PILOT", "CANDIDATE_EVOLUTION_PILOT", "Candidate deposition and second-query reuse without canonical promotion.", "DEV"),
        evidence_entry("celltypist_runtime_qualification_v1", "E2E-Eval", "data/evaluation/celltypist_runtime_qualification_v1/manifest.json", "PILOT", "RUNTIME_QUALIFICATION", "Candidate-only runtime qualification within its declared scope.", "REGRESSION", {"status": celltypist["status"]}),
        evidence_entry("core_scientific_planner_integration_v1", "Planner-Eval", "data/evaluation/core_scientific_planner_integration_v1/report.json", "PARTIAL", "PLANNER_INTEGRATION_PILOT", "Pilot state-aware cases; not a broad frozen planner benchmark.", "DEV"),
        evidence_entry("neighbors_regression_checkpoint", "Regression-Eval", "data/evaluation/scientific_kg_neighbors_direct_evidence_repair_v1/regression.json", "CURRENT_MEASURED", "ENGINEERING_REGRESSION", "Engineering stability only; test counts are not scientific accuracy.", "REGRESSION"),
        evidence_entry("ingestion_eval_v1_planned", "Ingestion-Eval", "data/evaluation/sckg_eval_v1/suite_manifest.json", "NOT_RUN", "SPECIFICATION_PLACEHOLDER", "Gold PDF pilot must be frozen before a formal run.", "DEV"),
        evidence_entry("trace_eval_v1_planned", "Trace-Eval", "data/evaluation/sckg_eval_v1/suite_manifest.json", "NOT_RUN", "SPECIFICATION_PLACEHOLDER", "Injected-failure benchmark is defined but has not run.", "DEV"),
    ]
    return rows


def matrix(suite_rows: list[dict[str, Any]], evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    current_sets = {
        "KG-Eval": "Inventory Snapshot v1; 8 audited OperatorRevisions",
        "Ingestion-Eval": "SoupX bounded pilots; formal 3-5 PDF gold not frozen",
        "Retrieval-Eval": "Development benchmarks, historical sealed C7, current direct-evidence regression",
        "Agent-Eval": "36 visible development conversation tasks",
        "Planner-Eval": "Raw/Processed PBMC3k and four state-aware synthetic scenarios",
        "Justification-Eval": "12 atoms, 8 mutations, 4 paired scenarios",
        "E2E-Eval": "Raw and Processed PBMC3k current-version replay v2",
        "Trace-Eval": "No formal injected-failure set",
        "Regression-Eval": "Checkpoint-focused unit/integration/regression selections",
    }
    primary = {
        "KG-Eval": "integrity + L0-L4 readiness",
        "Ingestion-Eval": "entity/relation/claim F1 + evidence alignment",
        "Retrieval-Eval": "Hit@5/10, MRR@10, abstention, false certainty",
        "Agent-Eval": "action/tool/binding/clarification/block accuracy",
        "Planner-Eval": "reuse/recompute/block + invalid reuse",
        "Justification-Eval": "decision-evidence precision and evidence recall",
        "E2E-Eval": "terminal completion separated from execution",
        "Trace-Eval": "first causal failure and owner attribution",
        "Regression-Eval": "pass rates and artifact integrity",
    }
    strongest_ids = {
        "KG-Eval": "kg_inventory_snapshot_v1",
        "Ingestion-Eval": "soupx_candidate_deposition_reuse_pilot",
        "Retrieval-Eval": "neighbors_direct_evidence_repair_v1",
        "Agent-Eval": "agent_tool_selection_eval_v1",
        "Planner-Eval": "scientific_kg_contribution_paired_ablation",
        "Justification-Eval": "decision_local_projection_v1_2",
        "E2E-Eval": "pbmc3k_replay_v2",
        "Trace-Eval": "none",
        "Regression-Eval": "neighbors_regression_checkpoint",
    }
    result = []
    for suite in suite_rows:
        result.append({
            "suite": suite["suite_id"], "current_test_set": current_sets[suite["suite_id"]],
            "primary_metric": primary[suite["suite_id"]], "current_status": suite["status"],
            "current_strongest_evidence": strongest_ids[suite["suite_id"]], "main_gap": suite["main_gap"],
        })
    return result


def integrity(suite_rows: list[dict[str, Any]], metrics: list[dict[str, Any]], evidence: list[dict[str, Any]], before: dict[str, Any]) -> dict[str, Any]:
    required_fields = {
        "metric_id", "suite", "name", "definition", "numerator", "denominator", "unit",
        "higher_or_lower_better", "valid_scope", "invalid_interpretations", "aggregation_unit", "status",
    }
    ids = [row["metric_id"] for row in metrics]
    artifact_missing = [row["artifact_path"] for row in evidence if not (ROOT / row["artifact_path"]).exists()]
    absolute_paths = [row["artifact_path"] for row in evidence if Path(row["artifact_path"]).is_absolute()]
    quarantined_current = [row["evidence_id"] for row in evidence if row["status"] == "QUARANTINED" and "CURRENT" in row["result_type"]]
    regression_scientific = [row["metric_id"] for row in metrics if row["suite"] == "Regression-Eval" and "scientific" not in " ".join(row["invalid_interpretations"]).casefold()]
    dev_independent = [row["evidence_id"] for row in evidence if row["status"] in {"DEVELOPMENT_RESULT", "PILOT", "PARTIAL"} and "independent" in row["result_type"].casefold()]
    checks = {
        "all_9_suites_exist": len(suite_rows) == 9,
        "metric_ids_unique": len(ids) == len(set(ids)),
        "every_metric_has_required_fields": all(required_fields <= row.keys() and all(row[field] != "" for field in required_fields) for row in metrics),
        "every_metric_has_definition": all(row["definition"] for row in metrics),
        "every_metric_has_aggregation_unit": all(row["aggregation_unit"] for row in metrics),
        "every_mapped_artifact_exists": not artifact_missing,
        "no_quarantined_evaluation_marked_current": not quarantined_current,
        "no_regression_count_as_scientific_metric": not regression_scientific,
        "no_dev_result_mislabeled_independent": not dev_independent,
        "no_suite_missing_status": all(row["status"] for row in suite_rows),
        "no_absolute_host_path": not absolute_paths,
        "no_global_score": all(row["global_score_eligible"] is False for row in suite_rows),
        "all_evidence_statuses_allowed": all(row["status"] in STATUSES for row in evidence),
    }
    return {
        "schema_version": "sckg-eval-v1-integrity",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "details": {
            "missing_artifacts": artifact_missing,
            "absolute_paths": absolute_paths,
            "quarantined_marked_current": quarantined_current,
            "regression_metrics_missing_scientific_accuracy_boundary": regression_scientific,
            "dev_or_pilot_mislabeled_independent": dev_independent,
        },
        "protected_before": before,
    }


def render_spec(suite_rows: list[dict[str, Any]], metrics: list[dict[str, Any]], taxonomy: dict[str, Any], evidence: list[dict[str, Any]]) -> str:
    lines = [
        "# scKG-Eval v1 Specification", "",
        "Status: specification and metric registry complete; no new benchmark campaign was run.", "",
        "scKG-Eval evaluates nine distinct layers. It does not combine them into a global score. Scale describes coverage and workload; it does not establish scientific correctness.", "",
        "## Statistical and interpretation rules", "",
        "- Use the declared primary unit for denominators and uncertainty. Nested atoms, mutations, paraphrases, and repeated calls are not independent samples.",
        "- Report development, regression, sealed, and external evidence separately.",
        "- Deterministic governance correction, actual tool calls, and final task state remain separate from the LLM proposal.",
        "- Engineering execution and scientific or human terminal completion remain separate.",
        "- A BLOCKED scientific terminal is not SUCCESS.",
        "- Regression test counts describe engineering stability and must not be presented as scientific accuracy.", "",
        "## Split taxonomy", "",
        "| Split | Definition | May inform changes | Independent claim |", "| --- | --- | --- | --- |",
    ]
    for split, row in taxonomy["splits"].items():
        lines.append(f"| {split} | {row['definition']} | {str(row['may_inform_changes']).lower()} | {str(row['independent_claim_allowed']).lower()} |")
    lines.extend(["", "A disclosed SEALED case is quarantined from future post-fix validation. Its already completed historical run remains historical evidence for the frozen SUT.", ""])
    for suite in suite_rows:
        lines.extend([
            f"## {suite['suite_id']}", "", suite["purpose"], "",
            f"Primary unit: **{', '.join(suite['primary_units'])}**.",
            f"Current status: **{suite['status']}**.",
            f"Strongest evidence: {suite['current_strongest_evidence']}.",
            f"Main gap: {suite['main_gap']}", "",
            "Metrics:", "",
        ])
        for row in (item for item in metrics if item["suite"] == suite["suite_id"]):
            lines.append(f"- `{row['metric_id']}` — {row['definition']}")
        if suite["baselines_or_ablations"]:
            lines.extend(["", "Baselines or ablations: " + ", ".join(suite["baselines_or_ablations"]) + "."])
        if suite["suite_id"] == "Planner-Eval":
            lines.extend(["", "Required case schema: `case_id`, `input_artifact`, `current_representation_records`, `representation_status`, `identity_hashes`, `target_state`, `gold_reuse`, `gold_recompute`, `gold_block`, `required_actions`, `forbidden_actions`."])
        if suite["suite_id"] == "Trace-Eval":
            lines.extend(["", "Future failures include route failure, missing artifact, stale representation, unresolved subject or evidence, public-filter rejection, policy denial, notebook failure, unmet terminal, and rejected review."])
        lines.append("")
    counts = Counter(row["status"] for row in evidence)
    lines.extend([
        "## Existing evidence ledger", "",
        f"Mapped records: **{len(evidence)}**. Status counts: " + ", ".join(f"{key}={counts[key]}" for key in sorted(counts)) + ".", "",
        "The machine-readable ledger records artifact tracking state. `UNTRACKED_WORKSPACE` means the artifact exists locally but is not yet committed; it must not be described as repository-frozen evidence.", "",
        "## Formal justification result", "",
        "The frozen decision-local projection changed scientific decision-evidence precision from **5/17 to 5/5**, extra non-decision evidence from **12 to 0**, while recall remained **5/5** and behavior invariance remained **4/4**. These are formal historical results over the declared frozen atoms and scenarios.", "",
        "## Prohibited interpretations", "",
        "- Do not call node or edge count scientific correctness.",
        "- Do not call governance-corrected Agent behavior LLM accuracy.",
        "- Do not aggregate the nine suites into one accuracy number.",
        "- Do not reuse disclosed C7 cases as future independent validation.",
        "- Do not sum overlapping regression test selections.", "",
    ])
    return "\n".join(lines)


def render_matrix(rows: list[dict[str, Any]]) -> str:
    lines = [
        "# Midterm Evaluation Matrix v1", "",
        "| Suite | Current test set | Primary metric | Current status | Current strongest evidence | Main gap |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(row[key]).replace("|", "\\|") for key in ("suite", "current_test_set", "primary_metric", "current_status", "current_strongest_evidence", "main_gap")) + " |")
    lines.extend(["", "No suite contributes to a global score. Each status and denominator must be reported independently.", ""])
    return "\n".join(lines)


def main() -> int:
    before = protected_identity()
    metrics = metric_registry()
    suite_rows = suites(metrics)
    taxonomy = split_taxonomy()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    # The planned-suite evidence entries point here, so write this first.
    suite_manifest = {
        "schema_version": "sckg-eval-v1-suite-manifest",
        "git_head": git_head(),
        "suite_count": len(suite_rows),
        "global_score_defined": False,
        "new_large_experiment_run": False,
        "suites": suite_rows,
    }
    write_json(OUTPUT / "suite_manifest.json", suite_manifest)
    evidence = evidence_map()
    matrix_rows = matrix(suite_rows, evidence)
    audit = integrity(suite_rows, metrics, evidence, before)
    write_json(OUTPUT / "metric_registry.json", {"schema_version": "sckg-eval-v1-metric-registry", "metric_count": len(metrics), "metrics": metrics})
    write_json(OUTPUT / "split_taxonomy.json", taxonomy)
    write_json(OUTPUT / "existing_evidence_map.json", {
        "schema_version": "sckg-eval-v1-existing-evidence-map",
        "record_count": len(evidence),
        "mapped_existing_evaluation_count": sum(row["status"] != "NOT_RUN" for row in evidence),
        "planned_not_run_count": sum(row["status"] == "NOT_RUN" for row in evidence),
        "records": evidence,
    })
    write_json(OUTPUT / "evaluation_matrix.json", {"schema_version": "sckg-eval-v1-evaluation-matrix", "rows": matrix_rows})
    after = protected_identity()
    audit["protected_after"] = after
    audit["protected_unchanged"] = before == after
    audit["checks"]["protected_artifacts_unchanged"] = before == after
    audit["status"] = "PASS" if all(audit["checks"].values()) else "FAIL"
    write_json(OUTPUT / "integrity.json", audit)
    SPEC_PATH.parent.mkdir(parents=True, exist_ok=True)
    SPEC_PATH.write_text(render_spec(suite_rows, metrics, taxonomy, evidence), encoding="utf-8")
    MATRIX_PATH.parent.mkdir(parents=True, exist_ok=True)
    MATRIX_PATH.write_text(render_matrix(matrix_rows), encoding="utf-8")
    generated = [*sorted(OUTPUT.glob("*.json")), SPEC_PATH, MATRIX_PATH]
    print(json.dumps({
        "status": audit["status"], "suite_count": len(suite_rows), "metric_count": len(metrics),
        "mapped_existing_evaluations": sum(row["status"] != "NOT_RUN" for row in evidence),
        "registry_records": len(evidence),
        "status_counts": dict(sorted(Counter(row["status"] for row in evidence).items())),
        "generated_sha256": {str(path.relative_to(ROOT)): sha256(path) for path in generated},
    }, sort_keys=True))
    return 0 if audit["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
