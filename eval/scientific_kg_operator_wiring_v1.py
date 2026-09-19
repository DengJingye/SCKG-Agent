from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.knowledge_intelligence_models import HybridRetrievalRequest
from engine.scientific_kg_evidence import ScientificKGEvidence, parse_scientific_query
from engine.scientific_subject_resolution import ScientificSubjectResolver
from eval import retrieval_benchmark_v1_1_dev as c6
from eval.dev_only_c7_loader import load_dev_pair
from eval.scientific_kg_direct_evidence_rootcause_v1 import run_dev_profiles


C7 = ROOT / "eval_v2/independent_retrieval_validation_v1"
ROOTCAUSE = ROOT / "data/evaluation/scientific_kg_direct_evidence_rootcause_v1"
BLOCKED = ROOT / "data/evaluation/scientific_kg_direct_evidence_abstention_v1"
OUTPUT = ROOT / "data/evaluation/scientific_kg_operator_wiring_v1"
PROTECTED = (
    C7,
    ROOTCAUSE,
    BLOCKED,
    ROOT / "data/indexes/retrieval_foundation_v1",
    ROOT / "data/knowledge_graph_v2",
    ROOT / "engine/capability_planner.py",
)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tree_hash(path: Path) -> str:
    if path.is_file():
        return sha(path)
    digest = hashlib.sha256()
    for item in sorted(value for value in path.rglob("*") if value.is_file()):
        digest.update(str(item.relative_to(path)).encode())
        digest.update(bytes.fromhex(sha(item)))
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows))


def supported_slice(adapter: ScientificKGEvidence) -> list[dict[str, Any]]:
    rows = []
    for revision in sorted(adapter.operators, key=lambda value: value.entity_id):
        claims = [
            claim
            for claim in adapter.bundle.atomic_claims
            if claim.subject_id == revision.entity_id
        ]
        bound = [
            claim
            for claim in claims
            if claim.claim_revision_id in adapter.bindings
            and adapter.bindings[claim.claim_revision_id].get("evidence_span_ids")
        ]
        rows.append({
            "scientific_subject": revision.operator_id,
            "operator_revision_exists": True,
            "operator_revision_id": revision.entity_id,
            "implemented_method_ids": revision.implements_method_ids,
            "direct_evidence_claim_count": len(claims),
            "bound_direct_evidence_claim_count": len(bound),
            "current_production_resolver_supported": True,
        })
    return rows


def synthetic_cases(adapter: ScientificKGEvidence) -> list[dict[str, Any]]:
    pca = next(item for item in adapter.operators if item.operator_id == "operator:scanpy.pp.pca")
    duplicate_revision = pca.model_copy(
        update={
            "entity_id": "operator-revision:scanpy.pp.pca:1.12.0:synthetic",
            "package_release_id": "package-release:scanpy:1.12.0",
        }
    )
    multi_revision = ScientificSubjectResolver(
        entities=adapter.bundle.entities,
        operator_revisions=[pca, duplicate_revision],
    )
    other_operator = pca.model_copy(
        update={
            "entity_id": "operator-revision:other.pca:1.0.0:synthetic",
            "operator_id": "operator:other.pca",
            "package_release_id": "package-release:other:1.0.0",
        }
    )
    multi_method = ScientificSubjectResolver(
        entities=adapter.bundle.entities,
        operator_revisions=[pca, other_operator],
    )
    parsed_hvg = parse_scientific_query("HVG input", extended=True)
    definitions = [
        ("exact_revision", adapter.subject_resolver, pca.entity_id, {}, "RESOLVED"),
        ("exact_api", adapter.subject_resolver, "scanpy.pp.pca input", {}, "RESOLVED"),
        ("package_operator", adapter.subject_resolver, "Scanpy PCA input", {}, "RESOLVED"),
        ("governed_alias", adapter.subject_resolver, "HVG input", {"parsed_operator_id": parsed_hvg["operator_id"]}, "RESOLVED"),
        ("method_name", adapter.subject_resolver, "principal component analysis input", {}, "RESOLVED"),
        ("legacy_bridge", adapter.subject_resolver, "What input is required?", {"subject_hints": ["Harmony"]}, "RESOLVED"),
        ("version_qualified", multi_revision, "scanpy.pp.pca version 1.11.2", {"explicit_version": "1.11.2"}, "RESOLVED"),
        ("ambiguous_method", multi_method, "principal component analysis input", {}, "AMBIGUOUS"),
    ]
    rows = []
    for case_id, resolver, text, kwargs, expected in definitions:
        result = resolver.resolve(text, **kwargs)
        rows.append({
            "case_id": case_id,
            "expected_status": expected,
            "observed": result.model_dump(),
            "passed": result.status == expected,
            "uses_dev_or_gold_metadata": False,
        })
    return rows


def classify_next_failure(diagnostic: dict[str, Any]) -> str:
    resolution = diagnostic.get("subject_resolution", {})
    if resolution.get("status") == "OUTSIDE_SCOPE":
        return "OUTSIDE_CURRENT_DIRECT_EVIDENCE_SCOPE"
    if resolution.get("status") == "AMBIGUOUS":
        return "MULTIPLE_OPERATOR_AMBIGUITY"
    if resolution.get("status") != "RESOLVED":
        return "SUBJECT_RESOLUTION_FAILED"
    paths = diagnostic.get("paths", [])
    fallback = diagnostic.get("fallback_reason", "")
    if fallback == "information_need_not_expressed_in_graph":
        return "CLAIM_TYPE_NOT_EXPRESSED"
    if not paths:
        return "CLAIM_NOT_FOUND"
    reasons = {
        gap.get("reason_code") or gap.get("reason", "")
        for gap in diagnostic.get("gaps", [])
    }
    if "GRAPH_EVIDENCE_NOT_IN_CORPUS" in reasons:
        return "EVIDENCE_NOT_IN_FROZEN_CORPUS"
    if "evidence_binding_missing" in reasons:
        return "EVIDENCE_BINDING_NOT_FOUND"
    if diagnostic.get("final_graph_chunk_ids"):
        return "RESOLVED"
    return "OTHER_EXPLICIT"


def run() -> dict[str, Any]:
    if OUTPUT.exists():
        raise FileExistsError("operator wiring output already exists")
    queries, gold, loader_audit = load_dev_pair(
        C7 / "query_set.jsonl",
        C7 / "gold.jsonl",
        C7 / "split_manifest.json",
    )
    protected_before = {
        str(path.relative_to(ROOT)): tree_hash(path)
        for path in PROTECTED
    }
    adapter = ScientificKGEvidence()
    service = c6._service(None)
    previous_paths = {
        row["query_id"]: row
        for row in (
            json.loads(line)
            for line in (ROOTCAUSE / "dev_resolution_paths.jsonl").read_text().splitlines()
        )
    }
    initial_wiring_ids = {
        row["query_id"]
        for row in (
            json.loads(line)
            for line in (ROOTCAUSE / "failure_attribution.jsonl").read_text().splitlines()
        )
        if row["after_earliest_failure"] == "IMPLEMENTATION_WIRING_ERROR"
    }
    dev_paths = []
    classifications = []
    for query in queries:
        request = HybridRetrievalRequest(
            query=query["query"],
            top_k=10,
            include_catalog=False,
            enable_sparse=True,
            enable_dense=False,
            use_kg=True,
            use_scientific_evidence=True,
        )
        result = service.search(request)
        diagnostic = result.scientific_evidence or {}
        resolution = diagnostic.get("subject_resolution", {})
        next_failure = classify_next_failure(diagnostic)
        row = {
            "query_id": query["query_id"],
            "information_need_status": (
                "RESOLVED"
                if diagnostic.get("parsed", {}).get("information_needs")
                else "UNRESOLVED"
            ),
            "subject_text": service._named_tools_in_query(query["query"]),
            "resolved_subject_type": resolution.get("resolved_subject_type", ""),
            "resolved_project": resolution.get("resolved_project", ""),
            "resolved_package": resolution.get("resolved_package", ""),
            "resolved_method": resolution.get("resolved_method", ""),
            "candidate_operator_ids": resolution.get("candidate_operator_ids", []),
            "candidate_operator_revision_ids": resolution.get("candidate_operator_revision_ids", []),
            "resolution_status": resolution.get("status", "UNRESOLVED"),
            "resolution_provenance": resolution.get("provenance", []),
            "earliest_failure": next_failure,
            "coverage_status": resolution.get("coverage_status", ""),
            "answerability": (
                result.answerability.model_dump(mode="json")
                if result.answerability is not None
                else None
            ),
        }
        dev_paths.append(row)
        if query["query_id"] in initial_wiring_ids:
            if resolution.get("status") == "OUTSIDE_SCOPE":
                classification = "F_OUTSIDE_CURRENT_DIRECT_EVIDENCE_SCOPE"
            elif resolution.get("status") == "AMBIGUOUS":
                classification = "G_AMBIGUOUS_SUBJECT"
            elif resolution.get("status") == "RESOLVED":
                classification = "H_TRUE_IMPLEMENTATION_WIRING_ERROR"
            elif resolution.get("candidate_operator_ids"):
                classification = "C_OPERATOR_EXISTS_BUT_REVISION_NOT_ADDRESSABLE"
            else:
                classification = "E_LEGACY_KG_ONLY_NOT_SCIENTIFIC_KG"
            classifications.append({
                "query_id": query["query_id"],
                "classification": classification,
                "coverage_status": resolution.get("coverage_status", ""),
                "candidate_operator_ids": resolution.get("candidate_operator_ids", []),
                "candidate_operator_revision_ids": resolution.get("candidate_operator_revision_ids", []),
            })
    class_counts = Counter(row["classification"] for row in classifications)
    resolution_counts = Counter(row["resolution_status"] for row in dev_paths)
    before_subject = sum(
        bool(row["parsed_scientific_subject"] or row["parsed_operator_id"])
        for row in previous_paths.values()
    )
    before_revision = sum(
        bool(row["selected_operator_revision"])
        for row in previous_paths.values()
    )
    before_operator = sum(
        bool(row["parsed_operator_id"])
        for row in previous_paths.values()
    )
    after_subject = sum(
        row["resolution_status"] in {"RESOLVED", "OUTSIDE_SCOPE", "AMBIGUOUS"}
        for row in dev_paths
    )
    after_revision = sum(
        bool(row["candidate_operator_revision_ids"])
        and row["resolution_status"] == "RESOLVED"
        for row in dev_paths
    )
    after_operator = sum(
        bool(row["candidate_operator_ids"])
        for row in dev_paths
    )
    synthetic = synthetic_cases(adapter)
    if not all(row["passed"] for row in synthetic):
        raise RuntimeError("synthetic_subject_resolution_failed")
    dev_rows, dev_summary = run_dev_profiles(queries, gold)
    protected_after = {
        str(path.relative_to(ROOT)): tree_hash(path)
        for path in PROTECTED
    }
    integrity = {
        "protected_before": protected_before,
        "protected_after": protected_after,
        "protected_equal": protected_before == protected_after,
        "sealed_payload_accessed": False,
        "sealed_validation_rerun": False,
        "frozen_c7_artifacts_changed": False,
        "corpus_changed": False,
        "kg_content_changed": False,
        "planner_changed": False,
        "canonical_promotion": "none",
    }
    if not integrity["protected_equal"]:
        raise RuntimeError("protected_artifact_drift")
    architecture = {
        "scientific_kg_asset_used": "MIXED",
        "legacy_kg_used_for_discovery": True,
        "legacy_kg_path": "data/knowledge_graph_v2",
        "scientific_kg_used_for_evidence": True,
        "scientific_kg_path": adapter.identity["path"],
        "scientific_kg_schema": adapter.identity["schema"],
        "identity_bridge_exists": True,
        "identity_bridge": "engine/scientific_subject_resolution.py::ScientificSubjectResolver",
        "owner_mismatch_before": "legacy Tool identity and Scientific KG OperatorRevision identity had no explicit bridge",
        "bridge_boundary": "identity_only_no_claim_scope_evidence_or_planner_authority",
    }
    OUTPUT.mkdir(parents=True, exist_ok=False)
    write_json(OUTPUT / "architecture_audit.json", architecture)
    write_json(OUTPUT / "supported_slice.json", {"rows": supported_slice(adapter)})
    write_json(OUTPUT / "synthetic_resolution_tests.json", {"rows": synthetic})
    write_jsonl(OUTPUT / "dev_resolution_paths.jsonl", dev_paths)
    write_json(OUTPUT / "failure_attribution.json", {
        "initial_implementation_wiring_error_count": len(initial_wiring_ids),
        "classification_counts": dict(sorted(class_counts.items())),
        "rows": classifications,
        "after_earliest_failure_counts": dict(sorted(Counter(row["earliest_failure"] for row in dev_paths).items())),
    })
    write_json(OUTPUT / "regression_summary.json", {
        "subject_resolution_before": before_subject,
        "subject_resolution_after": after_subject,
        "operator_resolution_before": before_operator,
        "operator_resolution_after": after_operator,
        "operator_revision_resolution_before": before_revision,
        "operator_revision_resolution_after": after_revision,
        "resolution_status_counts": dict(sorted(resolution_counts.items())),
        "dev_summary": dev_summary,
        "dev_rows": dev_rows,
    })
    write_json(OUTPUT / "integrity.json", integrity)
    manifest = {
        "schema_version": "scientific-kg-operator-wiring-v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "git_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "dev_query_count": len(queries),
        "loader_audit": loader_audit,
        "sealed_payload_accessed": False,
        "sealed_validation_rerun": False,
        "quarantined_after_disclosure": loader_audit["quarantine"],
        "one_owner": "engine/scientific_subject_resolution.py",
        "claim_scope_evidence_mapping_changed": False,
        "protected_sha256": protected_after,
    }
    write_json(OUTPUT / "manifest.json", manifest)
    return {
        "classification_counts": dict(sorted(class_counts.items())),
        "subject_before_after": [before_subject, after_subject],
        "revision_before_after": [before_revision, after_revision],
        "dev_summary": dev_summary,
        "sealed_payload_accessed": False,
    }


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2, sort_keys=True))
