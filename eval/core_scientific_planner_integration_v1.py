"""Focused development evaluation for governed KG consumption by the planner.

The campaign is intentionally bounded to existing CapabilityPlanCompiler paths.
It does not create capability packs, promote candidate knowledge, or interpret
unreviewed CAN_FEED relations as executable planning edges.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.representation_models import RepresentationLedger, RepresentationRecord
from engine.capability_planner import CapabilityPlanCompiler


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = ROOT / "data/evaluation/core_scientific_planner_integration_v1"
CANDIDATE_ROOT = (
    ROOT / "data/evidence_candidates/scientific_kg_v1_uat_decision_rules"
)
P0B_COVERAGE = (
    ROOT / "data/evaluation/knowledge_foundation_p0b/core_tool_coverage_after.json"
)
CREATED_AT = datetime(2000, 1, 1, tzinfo=timezone.utc)
CELL_HASH = "c" * 64
GENE_HASH = "g" * 64
PARAMETER_HASH = "p" * 64
HARMONY_OPERATOR = "operator-revision:harmony.RunHarmony:2.0.5:uat-corrected"


class NoOpApplicability:
    def assess(self, *, action_id: str, ledger: RepresentationLedger):
        return None


def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def _record(
    record_id: str,
    representation_id: str,
    representation_type_id: str,
    *,
    value_state: str = "state_declared",
    transformations: list[str] | None = None,
    cell_hash: str | None = CELL_HASH,
    gene_hash: str | None = GENE_HASH,
    parameter_hash: str | None = None,
    status: str = "current",
    metadata: dict[str, Any] | None = None,
) -> RepresentationRecord:
    values = {
        "representation_type_id": representation_type_id,
        "lineage_id": "lineage:core-scientific-planner-integration-v1",
        "transformations": transformations or [],
    }
    values.update(metadata or {})
    return RepresentationRecord(
        representation_record_id=record_id,
        representation_id=representation_id,
        schema_version="1.0",
        value_state=value_state,
        slot=f"fixture/{representation_id}",
        provenance=["core_scientific_planner_integration_v1"],
        cell_index_hash=cell_hash,
        gene_index_hash=gene_hash,
        parameter_hash=parameter_hash,
        status=status,
        validated=True,
        stale_reasons=[] if status == "current" else ["upstream_changed"],
        metadata=values,
    )


def _ledger(case_id: str, records: list[RepresentationRecord]) -> RepresentationLedger:
    return RepresentationLedger(
        ledger_id=f"ledger:{case_id}",
        profile_id=f"profile:{case_id}",
        source_artifact_id=f"artifact:{case_id}",
        source_hash="s" * 64,
        cell_index_hash=CELL_HASH,
        gene_index_hash=GENE_HASH,
        records=records,
        created_at=CREATED_AT,
    )


def _graph(record_id: str, *, status: str = "current") -> RepresentationRecord:
    return _record(
        record_id,
        "neighbor_graph",
        "representation-type:neighbor_graph",
        value_state="graph",
        gene_hash=None,
        parameter_hash=PARAMETER_HASH,
        status=status,
        metadata={
            "neighbors_key": "neighbors",
            "connectivities_key": "connectivities",
            "distances_key": "distances",
            "component_roles": ["connectivities", "distances", "parameters"],
        },
    )


def cases() -> list[dict[str, Any]]:
    log_expression = _record(
        "rep:log", "log1p_normalized", "representation-type:log_expression",
        transformations=["normalized", "log1p"],
    )
    hvg = _record(
        "rep:hvg", "hvg_selection", "representation-type:hvg_mask",
        value_state="boolean_mask", transformations=["feature_selected"], cell_hash=None,
    )
    pca = _record(
        "rep:pca", "pca", "representation-type:pca_coordinates",
        value_state="real_continuous", gene_hash=None, parameter_hash=PARAMETER_HASH,
    )
    stale_pca = _record(
        "rep:pca:stale", "pca", "representation-type:pca_coordinates",
        value_state="real_continuous", gene_hash=None, parameter_hash=PARAMETER_HASH,
        status="stale",
    )
    harmony = _record(
        "rep:harmony", "integrated_representation", "representation-type:cell_embedding",
        value_state="real_continuous", gene_hash=None, parameter_hash="h" * 64,
        transformations=["integrated", "batch_corrected_embedding"],
        metadata={"producer_operator_revision_id": HARMONY_OPERATOR, "batch_key": "donor"},
    )
    normalized = _record(
        "rep:normalized", "library_size_normalized", "representation-type:expression_matrix",
        value_state="nonnegative_continuous", transformations=["normalized"],
    )
    integrated = _record(
        "rep:integrated", "integrated_representation", "representation-type:cell_embedding",
        value_state="real_continuous", gene_hash=None, parameter_hash="i" * 64,
        transformations=["integrated", "batch_corrected_embedding"],
    )
    definitions = [
        {
            "case_id": "scanpy-hvg-log-profile",
            "path": "Scanpy base chain",
            "ledger": _ledger("scanpy-hvg-log-profile", [log_expression]),
            "target": "hvg_selection",
            "options": {},
            "expected": {"blocked": False, "methods": ["scanpy_core.highly_variable_genes"], "reused": ["log1p_normalized"], "action": "REUSE_EXISTING", "forbidden_methods": []},
        },
        {
            "case_id": "scanpy-pca-log-hvg",
            "path": "Scanpy base chain",
            "ledger": _ledger("scanpy-pca-log-hvg", [log_expression, hvg]),
            "target": "pca",
            "options": {"preferred_method_ids": ["scanpy_core.pca_log_hvg"]},
            "expected": {"blocked": False, "methods": ["scanpy_core.pca_log_hvg"], "reused": ["hvg_selection", "log1p_normalized"], "action": "REUSE_EXISTING", "forbidden_methods": ["scanpy_core.highly_variable_genes"]},
        },
        {
            "case_id": "scanpy-neighbors-valid-pca",
            "path": "Scanpy base chain",
            "ledger": _ledger("scanpy-neighbors-valid-pca", [pca]),
            "target": "neighbor_graph",
            "options": {},
            "expected": {"blocked": False, "methods": ["scanpy_core.neighbors"], "reused": ["pca"], "action": "REUSE_EXISTING", "forbidden_methods": ["scanpy_core.pca_log_hvg", "scanpy_core.pca_scaled"]},
        },
        {
            "case_id": "scanpy-neighbors-stale-pca",
            "path": "Scanpy base chain",
            "ledger": _ledger("scanpy-neighbors-stale-pca", [stale_pca]),
            "target": "neighbor_graph",
            "options": {},
            "expected": {"blocked": True, "methods": [], "reused": [], "action": "BLOCK", "forbidden_methods": []},
        },
        {
            "case_id": "scanpy-graph-to-leiden",
            "path": "Scanpy base chain",
            "ledger": _ledger("scanpy-graph-to-leiden", [_graph("rep:graph:leiden")]),
            "target": "cluster_labels",
            "options": {},
            "expected": {"blocked": False, "methods": ["scanpy_core.leiden"], "reused": ["neighbor_graph"], "action": "REUSE_EXISTING", "forbidden_methods": ["scanpy_core.neighbors"]},
        },
        {
            "case_id": "scanpy-graph-to-umap",
            "path": "Scanpy base chain",
            "ledger": _ledger("scanpy-graph-to-umap", [_graph("rep:graph:umap")]),
            "target": "umap",
            "options": {},
            "expected": {"blocked": False, "methods": ["scanpy_core.umap"], "reused": ["neighbor_graph"], "action": "REUSE_EXISTING", "forbidden_methods": ["scanpy_core.neighbors"]},
        },
        {
            "case_id": "harmony-embedding-to-neighbors",
            "path": "Harmony to neighbors",
            "ledger": _ledger("harmony-embedding-to-neighbors", [harmony]),
            "target": "neighbor_graph",
            "options": {},
            "expected": {"blocked": False, "methods": ["scanpy_core.neighbors_integrated"], "reused": ["integrated_representation"], "action": "REUSE_EXISTING", "forbidden_methods": ["scanpy_core.pca_log_hvg", "scanpy_core.pca_scaled"]},
        },
        {
            "case_id": "scrublet-transformed-only",
            "path": "Scrublet applicability",
            "ledger": _ledger("scrublet-transformed-only", [normalized, integrated]),
            "target": "doublet_scores_and_calls",
            "options": {},
            "expected": {"blocked": True, "methods": [], "reused": [], "action": "BLOCK", "forbidden_methods": []},
        },
    ]
    return definitions


def _compile(case: dict[str, Any], *, kg_enabled: bool) -> dict[str, Any]:
    planner = (
        CapabilityPlanCompiler()
        if kg_enabled
        else CapabilityPlanCompiler(scientific_applicability=NoOpApplicability())
    )
    plan, result = planner.compile(
        pack_id="scanpy_core",
        pack_version="1.0.0",
        ledger=case["ledger"],
        target_representations=[case["target"]],
        requirement_id=f"core-scientific-planner-integration-v1:{case['case_id']}",
        options=case["options"],
    )
    return {
        "plan": plan.model_dump(mode="json"),
        "result": result.model_dump(mode="json"),
    }


def _behavior(output: dict[str, Any]) -> dict[str, Any]:
    result = output["result"]
    return {
        "blocked": result["blocked"],
        "planned_method_ids": result["planned_method_ids"],
        "reused_representation_ids": result["reused_representation_ids"],
    }


def _outcome(output: dict[str, Any]) -> str:
    result = output["result"]
    if result["blocked"]:
        return "BLOCK"
    if result["reused_representation_ids"]:
        return "REUSE_EXISTING"
    if len(result["planned_method_ids"]) > 1:
        return "SCHEDULE_PREREQUISITE"
    return "ALLOW"


def _evidence_valid(output: dict[str, Any]) -> bool:
    bindings = {
        row["claim_revision_id"]: row
        for row in _jsonl(CANDIDATE_ROOT / "exact_evidence_bindings.jsonl")
    }
    spans = {
        row["evidence_span_id"]: row
        for row in _jsonl(CANDIDATE_ROOT / "authoritative_evidence_spans.jsonl")
    }
    decisions = output["result"]["scientific_applicability_results"]
    if not decisions:
        return False
    for decision in decisions:
        if decision["knowledge_status"] != "candidate" or not decision["evidence_references"]:
            return False
        for ref in decision["evidence_references"]:
            binding = bindings.get(ref["claim_revision_id"])
            span = spans.get(ref["evidence_span_id"])
            if not binding or not span or not span["source_bound"]:
                return False
            if ref["evidence_span_id"] not in binding["evidence_span_ids"]:
                return False
            if any(ref[key] != span[key] for key in ("source_revision_id", "locator", "content_hash")):
                return False
    return True


def _readiness_matrix() -> dict[str, Any]:
    matrix = _json(P0B_COVERAGE)
    for row in matrix["paths"]:
        if row["ecosystem"] == "Scanpy":
            row["core_planner_integration_v1"] = "expanded"
            row["reason"] = (
                "The existing Scanpy Capability Pack now consumes source-bound candidate "
                "applicability for its log-profile HVG, PCA, neighbors, UMAP and Leiden "
                "inputs; conditional count-flavour HVG remains contract-unbound."
            )
        elif row["ecosystem"] in {"Harmony", "Scrublet"}:
            row["core_planner_integration_v1"] = "preserved"
        else:
            row["core_planner_integration_v1"] = "not_integrated"
    counts = {
        "authoritative_evidence_ready": sum(row["evidence_ready"] for row in matrix["paths"]),
        "planning_ready": sum(row["planning_ready"] for row in matrix["paths"]),
        "execution_ready": sum(row["execution_ready"] for row in matrix["paths"]),
        "retrieval_only": sum(row["primary_state"] == "retrieval-only" for row in matrix["paths"]),
        "candidate_only": sum(row["primary_state"] == "candidate-only" for row in matrix["paths"]),
        "not_ready": sum(row["primary_state"] == "not ready" for row in matrix["paths"]),
    }
    return {"definitions": matrix["definitions"], "counts": counts, "paths": matrix["paths"]}


def run() -> dict[str, Any]:
    rows = []
    for case in cases():
        baseline = _compile(case, kg_enabled=False)
        enabled = _compile(case, kg_enabled=True)
        expected = case["expected"]
        baseline_behavior = _behavior(baseline)
        enabled_behavior = _behavior(enabled)
        expected_behavior = {
            "blocked": expected["blocked"],
            "planned_method_ids": expected["methods"],
            "reused_representation_ids": expected["reused"],
        }
        behavior_correct = all(
            enabled_behavior[key] == value for key, value in expected_behavior.items()
        )
        forbidden = set(expected["forbidden_methods"])
        methods = set(enabled_behavior["planned_method_ids"])
        reused = set(enabled_behavior["reused_representation_ids"])
        expected_reused = set(expected["reused"])
        rows.append(
            {
                "case_id": case["case_id"],
                "path": case["path"],
                "target": case["target"],
                "expected": expected,
                "baseline": baseline,
                "kg_enabled": enabled,
                "baseline_behavior": baseline_behavior,
                "kg_behavior": enabled_behavior,
                "behavior_changed": baseline_behavior != enabled_behavior,
                "planner_action": _outcome(enabled),
                "checks": {
                    "requirement_state_correct": behavior_correct,
                    "decision_correct": _outcome(enabled) == expected["action"],
                    "unnecessary_recomputation": bool(methods & forbidden),
                    "incorrect_reuse": bool(reused - expected_reused),
                    "missing_prerequisite": not set(expected["methods"]) <= methods,
                    "unsafe_allow": expected["blocked"] and not enabled_behavior["blocked"],
                    "false_block": not expected["blocked"] and enabled_behavior["blocked"],
                    "explanation_evidence_fidelity": _evidence_valid(enabled),
                },
            }
        )
    metrics = {
        "requirement_state_correctness": [sum(row["checks"]["requirement_state_correct"] for row in rows), len(rows)],
        "allow_block_clarify_correctness": [sum(row["checks"]["decision_correct"] for row in rows), len(rows)],
        "unnecessary_recomputation": [sum(row["checks"]["unnecessary_recomputation"] for row in rows), len(rows)],
        "incorrect_reuse": [sum(row["checks"]["incorrect_reuse"] for row in rows), len(rows)],
        "missing_prerequisite": [sum(row["checks"]["missing_prerequisite"] for row in rows), len(rows)],
        "unsafe_allow": [sum(row["checks"]["unsafe_allow"] for row in rows), len(rows)],
        "false_block": [sum(row["checks"]["false_block"] for row in rows), len(rows)],
        "explanation_evidence_fidelity": [sum(row["checks"]["explanation_evidence_fidelity"] for row in rows), len(rows)],
        "behavior_changes_vs_noop": [sum(row["behavior_changed"] for row in rows), len(rows)],
    }
    readiness = _readiness_matrix()
    gaps = [
        {"path": "SoupX", "status": "NOT_READY", "owner": "governance_and_capability_pack", "reason": "The acquired SoupX claim is candidate_pending_review and isolated; no SoupX Capability Pack or ToolContract exists."},
        {"path": "CellTypist", "status": "NOT_READY", "owner": "reference_artifact_and_capability_pack", "reason": "A ToolContract exists, but immutable model revision resolution and a Capability Pack planner path are absent."},
        {"path": "SingleR", "status": "NOT_READY", "owner": "version_reference_and_capability_pack", "reason": "The reviewed candidate is 2.14.1, the ToolContract is 2.14.0, immutable reference identity is unresolved, and no Capability Pack exists."},
        {"path": "scVelo", "status": "NOT_READY", "owner": "tool_contract_and_capability_pack", "reason": "Candidate layer semantics exist, but no ToolContract or Capability Pack is production-consumed."},
        {"path": "CellRank", "status": "NOT_READY", "owner": "compatibility_contract_and_capability_pack", "reason": "The upstream scVelo/CellRank compatibility edge remains an explicit EvidenceGap; no ToolContract or Capability Pack exists."},
    ]
    success = all(
        row["checks"][key]
        for row in rows
        for key in ("requirement_state_correct", "decision_correct", "explanation_evidence_fidelity")
    ) and not any(
        row["checks"][key]
        for row in rows
        for key in ("unnecessary_recomputation", "incorrect_reuse", "missing_prerequisite", "unsafe_allow", "false_block")
    )
    result = {
        "schema_version": "core-scientific-planner-integration-v1",
        "status": "PASS_WITH_REMAINING_GAPS" if success else "NO_GO",
        "case_count": len(rows),
        "metrics": metrics,
        "cases": rows,
        "remaining_target_path_gaps": gaps,
        "readiness": readiness,
        "boundaries": {
            "candidate_knowledge_status_preserved": True,
            "can_feed_relations_actionable": False,
            "capability_plan_compiler_remains_single_planner": True,
            "kg_or_retrieval_content_modified": False,
        },
    }
    return result


def main() -> None:
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=False)
    result = run()
    _write(OUTPUT_ROOT / "per_case_results.json", result["cases"])
    _write(OUTPUT_ROOT / "readiness_matrix.json", result["readiness"])
    _write(OUTPUT_ROOT / "gap_register.json", result["remaining_target_path_gaps"])
    report = {key: value for key, value in result.items() if key != "cases"}
    _write(OUTPUT_ROOT / "report.json", report)
    manifest = {
        "schema_version": "core-scientific-planner-integration-v1-manifest",
        "status": result["status"],
        "artifacts": {
            path.name: _file_digest(path)
            for path in sorted(OUTPUT_ROOT.glob("*.json"))
        },
        "scientific_candidate_manifest_sha256": _file_digest(CANDIDATE_ROOT / "manifest.json"),
        "capability_pack_manifest_sha256": _file_digest(ROOT / "capability_packs/scanpy_core/1.0.0/manifest.json"),
    }
    _write(OUTPUT_ROOT / "manifest.json", manifest)
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
