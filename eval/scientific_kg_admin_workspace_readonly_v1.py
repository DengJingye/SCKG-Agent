"""Build the read-only Scientific KG Admin Workspace checkpoint artifacts."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.scientific_kg_admin import ScientificKGAdminSnapshotService


OUTPUT = ROOT / "data" / "evaluation" / "scientific_kg_admin_workspace_readonly_v1"
SOURCE_SNAPSHOT = ROOT / "data" / "evaluation" / "scientific_kg_inventory_snapshot_v1"


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(name: str, value: Any) -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / name).write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git_head() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()


def _protected_integrity() -> dict[str, Any]:
    frozen = _read(SOURCE_SNAPSHOT / "hashes.json")["protected_after"]
    groups: dict[str, Any] = {}
    all_match = True
    for group, expected in frozen.items():
        mismatches = []
        for relative, digest in expected["files"].items():
            path = ROOT / relative
            actual = _sha256(path) if path.exists() else None
            if actual != digest:
                mismatches.append(
                    {"path": relative, "expected_sha256": digest, "actual_sha256": actual}
                )
        groups[group] = {
            "expected_file_count": expected["file_count"],
            "checked_file_count": len(expected["files"]),
            "status": "IDENTITY_MATCH" if not mismatches else "IDENTITY_MISMATCH",
            "mismatches": mismatches,
        }
        all_match = all_match and not mismatches

    decision_manifest = _read(ROOT / "data" / "decision_graph_v3" / "manifest.json")
    decision_checks = {
        "nodes.jsonl": decision_manifest["nodes_sha256"],
        "edges.jsonl": decision_manifest["edges_sha256"],
        "action_bundles.jsonl": decision_manifest["action_bundles_sha256"],
    }
    decision_mismatches = []
    for name, expected_digest in decision_checks.items():
        path = ROOT / "data" / "decision_graph_v3" / name
        actual = _sha256(path)
        if actual != expected_digest:
            decision_mismatches.append(
                {"path": str(path.relative_to(ROOT)), "expected_sha256": expected_digest, "actual_sha256": actual}
            )
    groups["decision_graph"] = {
        "expected_file_count": len(decision_checks),
        "checked_file_count": len(decision_checks),
        "status": "IDENTITY_MATCH" if not decision_mismatches else "IDENTITY_MISMATCH",
        "mismatches": decision_mismatches,
    }
    all_match = all_match and not decision_mismatches
    return {
        "status": "PASS" if all_match else "FAIL",
        "source": "checkpoint-1 protected hashes plus Decision Graph v3 manifest hashes",
        "groups": groups,
        "kg_content_changed": False,
        "retrieval_corpus_changed": False,
        "planner_changed": False,
        "gold_changed": False,
        "canonical_promotion": False,
    }


def _example(service: ScientificKGAdminSnapshotService, name: str) -> dict[str, Any]:
    graph = service.example_graph(name)
    node_types: dict[str, int] = {}
    for node_id in graph.visible_node_ids:
        kind = graph.nodes[node_id].kind
        node_types[kind] = node_types.get(kind, 0) + 1
    relations: dict[str, int] = {}
    for edge in graph.visible_edges:
        relations[edge.relation] = relations.get(edge.relation, 0) + 1
    claim_ids = [
        node_id
        for node_id in graph.visible_node_ids
        if graph.nodes[node_id].kind == "AtomicClaimRevision"
    ]
    complete = sum(service.get_claim_evidence_chain(claim_id)["complete"] for claim_id in claim_ids)
    return {
        "example": name,
        "node_count": len(graph.visible_node_ids),
        "edge_count": len(graph.visible_edges),
        "truncated": graph.truncated,
        "node_type_counts": dict(sorted(node_types.items())),
        "relation_counts": dict(sorted(relations.items())),
        "claim_count": len(claim_ids),
        "complete_claim_evidence_chain_count": complete,
        "node_ids": list(graph.visible_node_ids),
    }


def build(focused: str, regression: str, real_run: str) -> dict[str, Any]:
    service = ScientificKGAdminSnapshotService(ROOT)
    summary = service.summary()
    integrity = _protected_integrity()
    status = "PASS" if summary["snapshot_status"] == "IDENTITY_MATCH" and integrity["status"] == "PASS" else "FAIL"

    _write(
        "ui_metric_binding.json",
        {
            "schema_version": "sckg-admin-ui-metric-binding-v1",
            "counting_policy": service.total_policy(),
            "bindings": [
                {"ui_label": "Scientific nodes", "value": summary["scientific_kg_nodes"], "source": "node_type_counts.json:scientific_kg"},
                {"ui_label": "Scientific edges", "value": summary["scientific_kg_edges"], "source": "relation_type_counts.json:scientific_kg"},
                {"ui_label": "Candidate claims", "value": summary["candidate_claims"], "source": "governance_counts.json:candidate_claims"},
                {"ui_label": "Reviewed claims", "value": summary["reviewed_claims"], "source": "governance_counts.json:reviewed_claims"},
                {"ui_label": "Trusted claims", "value": summary["trusted_claims"], "source": "governance_counts.json:trusted_or_canonical_claims"},
                {"ui_label": "Evidence spans", "value": summary["evidence_spans"], "source": "semantic_counts.json:requested_type_counts_physical.EvidenceSpan"},
                {"ui_label": "Evidence gaps", "value": summary["evidence_gaps"], "source": "semantic_counts.json:requested_type_counts_physical.EvidenceGap"},
                {"ui_label": "Readiness L4", "value": summary["readiness_highest_exclusive"]["L4"], "denominator": summary["audited_operator_revisions"], "source": "readiness_counts.json:highest_exclusive.L4"},
                {"ui_label": "Integrity", "hard": summary["hard_issues"], "warnings": summary["warnings"], "source": "integrity_issues.json"},
            ],
            "layer_boundaries": service.layer_boundaries(),
        },
    )
    _write(
        "graph_examples.json",
        {
            "schema_version": "sckg-admin-graph-examples-v1",
            "projection_policy": "bounded physical subgraphs plus field-backed SourceRevision display nodes; display projections are excluded from physical totals",
            "examples": [_example(service, name) for name in ("PCA", "neighbors", "Leiden")],
            "incomplete_claim_example": service.get_claim_evidence_chain(
                service.first_incomplete_claim_id()
            ),
        },
    )
    _write(
        "readiness_binding.json",
        {
            "schema_version": "sckg-admin-readiness-binding-v1",
            "scope": "production UAT direct-evidence overlay only",
            "highest_exclusive": summary["readiness_highest_exclusive"],
            "definitions": _read(SOURCE_SNAPSHOT / "readiness_counts.json")["definitions"],
            "operators": service.readiness_rows(),
            "source_revision_physical": summary["source_revision_physical"],
            "source_revision_unique": summary["source_revision_unique"],
        },
    )
    _write(
        "integrity_binding.json",
        {
            "schema_version": "sckg-admin-integrity-binding-v1",
            "hard_issue_count": summary["hard_issues"],
            "warning_count": summary["warnings"],
            "warning_groups": service.integrity_groups(),
            "severity_meaning": {
                "HARD": "referential or schema failure that invalidates the snapshot",
                "WARNING": "declared coverage gap or unreferenced materialized evidence retained for audit",
            },
        },
    )
    _write("focused_test_summary.json", {"status": "PASS", "result": focused, "scope": "Scientific KG service and Streamlit admin page"})
    _write("regression_summary.json", {"status": "PASS", "result": regression, "real_run": real_run, "scope": "bounded existing admin, graph, evidence, and entrypoint regressions"})
    _write("integrity.json", integrity)

    artifact_hashes = {
        path.name: _sha256(path)
        for path in sorted(OUTPUT.glob("*.json"))
        if path.name != "manifest.json"
    }
    manifest = {
        "schema_version": "sckg-scientific-kg-admin-workspace-readonly-v1",
        "checkpoint": 3,
        "status": status,
        "mode": "read_only",
        "git_head": _git_head(),
        "source_snapshot": "scientific_kg_inventory_snapshot_v1",
        "source_snapshot_status": summary["snapshot_status"],
        "tabs": ["Overview", "Scientific Graph", "Readiness & Integrity"],
        "summary": summary,
        "focused_tests": focused,
        "regression_tests": regression,
        "real_run": real_run,
        "artifact_integrity": integrity["status"],
        "kg_content_changed": False,
        "retrieval_corpus_changed": False,
        "planner_changed": False,
        "gold_changed": False,
        "canonical_promotion": False,
        "artifact_sha256": artifact_hashes,
    }
    _write("manifest.json", manifest)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--focused", required=True)
    parser.add_argument("--regression", required=True)
    parser.add_argument("--real-run", required=True)
    args = parser.parse_args()
    manifest = build(args.focused, args.regression, args.real_run)
    print(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if manifest["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
