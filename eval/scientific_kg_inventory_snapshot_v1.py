"""Recompute the read-only Scientific KG inventory and ontology audit.

This checkpoint deliberately inventories frozen assets.  It does not merge
identities, promote candidates, rebuild retrieval, or mutate KG content.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.knowledge_intelligence_models import HybridRetrievalRequest
from data_pipeline.build_scientific_kg_v1_inventory import LAYERS, build_inventory
from engine.evidence_discovery_index import EvidenceChunk, load_chunks
from engine.hybrid_retrieval import HybridRetrievalService
from engine.scientific_kg_evidence import ScientificKGEvidence
from eval import retrieval_benchmark_v1_1_dev as retrieval_foundation


OUTPUT_DIR = ROOT / "data/evaluation/scientific_kg_inventory_snapshot_v1"
REPORT_PATH = ROOT / "docs/status/SCIENTIFIC_KG_INVENTORY_SNAPSHOT_V1.md"
LEGACY_DIR = ROOT / "data/knowledge_graph_v2"
EVIDENCE_ROOT = ROOT / "data/evidence_candidates"
UAT_ROOT = EVIDENCE_ROOT / "scientific_kg_v1_uat_decision_rules"


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_head() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()


def tree_identity(paths: Iterable[Path]) -> dict[str, Any]:
    files: list[Path] = []
    for path in paths:
        if path.is_file():
            files.append(path)
        elif path.is_dir():
            files.extend(item for item in path.rglob("*") if item.is_file() and "__pycache__" not in item.parts)
    entries = {
        str(path.relative_to(ROOT)): sha256(path)
        for path in sorted(set(files))
    }
    digest = hashlib.sha256(
        "".join(f"{name}\0{value}\n" for name, value in entries.items()).encode()
    ).hexdigest()
    return {"file_count": len(entries), "tree_sha256": digest, "files": entries}


def protected_paths() -> dict[str, list[Path]]:
    return {
        "scientific_kg": [EVIDENCE_ROOT / layer.directory for layer in LAYERS],
        "legacy_tool_kg": [LEGACY_DIR],
        "retrieval_corpus": [retrieval_foundation.INDEX_DIR],
        "planner": [ROOT / "engine/execution_planner.py", ROOT / "engine/capability_planner.py"],
        "gold": [ROOT / "eval_v2/gold", ROOT / "eval_v2/retrieval_benchmark_v1_1_dev/gold.jsonl"],
        "contracts": [ROOT / "contracts", ROOT / "capability_packs"],
    }


def protected_identity() -> dict[str, Any]:
    return {name: tree_identity(paths) for name, paths in protected_paths().items()}


def _ids(records: list[dict[str, Any]], *keys: str) -> set[str]:
    return {
        str(record[key])
        for record in records
        for key in keys
        if record.get(key)
    }


def load_scientific_layers() -> list[dict[str, Any]]:
    loaded = []
    for layer in LAYERS:
        root = EVIDENCE_ROOT / layer.directory
        bundle = read_json(root / "conformance_bundle.json")
        evidence = read_jsonl(root / layer.evidence_file)
        gaps: list[dict[str, Any]] = []
        if layer.gap_file:
            payload = read_json(root / layer.gap_file)
            gaps = payload.get("gaps", payload if isinstance(payload, list) else [])
        loaded.append({"layer": layer, "root": root, "bundle": bundle, "evidence": evidence, "gaps": gaps})
    return loaded


def legacy_inventory() -> tuple[dict[str, Any], dict[str, int], dict[str, int]]:
    nodes_path = LEGACY_DIR / "nodes.jsonl"
    edges_path = LEGACY_DIR / "edges.jsonl"
    manifest = read_json(LEGACY_DIR / "manifest.json")
    quality = read_json(LEGACY_DIR / "quality_report.json")
    if sha256(nodes_path) != manifest["nodes_sha256"] or sha256(edges_path) != manifest["edges_sha256"]:
        raise RuntimeError("Legacy Tool KG manifest digest mismatch")
    nodes = read_jsonl(nodes_path)
    edges = read_jsonl(edges_path)
    node_counts = Counter(row["node_type"] for row in nodes)
    relation_counts = Counter(row["relation"] for row in edges)
    node_ids = [row["node_id"] for row in nodes]
    edge_ids = [row["edge_id"] for row in edges]
    node_id_set = set(node_ids)
    dangling = [row["edge_id"] for row in edges if row["source_id"] not in node_id_set or row["target_id"] not in node_id_set]
    summary = {
        "substrate": "Legacy Tool KG",
        "role": "discovery_and_catalog",
        "snapshot_id": manifest["snapshot_id"],
        "nodes": len(nodes),
        "edges": len(edges),
        "entity_type_count": len(node_counts),
        "relation_type_count": len(relation_counts),
        "duplicate_node_ids": len(node_ids) - len(node_id_set),
        "duplicate_edge_ids": len(edge_ids) - len(set(edge_ids)),
        "dangling_edges": len(dangling),
        "quality_report_passed": bool(
            quality.get("integrity_passed", quality.get("passed", quality.get("status") == "PASS"))
        ),
        "manifest_counts_match": manifest["node_count"] == len(nodes) and manifest["edge_count"] == len(edges),
    }
    return summary, dict(sorted(node_counts.items())), dict(sorted(relation_counts.items()))


def semantic_counts(layers: list[dict[str, Any]], graph: dict[str, Any]) -> dict[str, Any]:
    requested = (
        "SoftwareProject", "Package", "PackageRelease", "Operator", "OperatorRevision",
        "Method", "MethodVariant", "RepresentationType", "RepresentationConstraint",
        "ApplicabilityScope", "AtomicClaimRevision", "EvidenceSpan", "SourceRevision",
        "EvidenceAssessment", "EvidenceGap",
    )
    physical: Counter[str] = Counter()
    distinct: dict[str, set[str]] = defaultdict(set)
    source_revision_rows: list[dict[str, Any]] = []
    legacy_source_rows: list[dict[str, Any]] = []
    source_document_refs: set[str] = set()

    for item in layers:
        bundle = item["bundle"]
        for entity in bundle.get("entities", []):
            kind = entity["record_type"]
            physical[kind] += 1
            distinct[kind].add(entity["entity_id"])
        mappings = (
            ("RepresentationType", "representation_types", "representation_type_id"),
            ("RepresentationConstraint", "representation_constraints", "constraint_id"),
            ("ApplicabilityScope", "scopes", "scope_id"),
            ("AtomicClaimRevision", "atomic_claims", "claim_revision_id"),
            ("EvidenceAssessment", "evidence_assessments", "assessment_id"),
        )
        for kind, field, key in mappings:
            rows = bundle.get(field, [])
            physical[kind] += len(rows)
            distinct[kind].update(str(row[key]) for row in rows)
        physical["EvidenceSpan"] += len(item["evidence"])
        distinct["EvidenceSpan"].update(_ids(item["evidence"], "evidence_span_id"))
        physical["EvidenceGap"] += len(item["gaps"])
        distinct["EvidenceGap"].update(_ids(item["gaps"], "gap_id"))
        for row in item["evidence"]:
            value = row.get("source_document_id") or row.get("source_record_id")
            if value:
                source_document_refs.add(str(value))

        authoritative = item["root"] / "authoritative_source_manifest.json"
        if authoritative.exists():
            payload = read_json(authoritative)
            rows = payload.get("sources", [payload])
            source_revision_rows.extend(row for row in rows if row.get("source_revision_id"))
        source_manifest = item["root"] / "source_manifest.json"
        if source_manifest.exists():
            legacy_source_rows.extend(read_json(source_manifest).get("sources", []))

    physical["SourceRevision"] = len(source_revision_rows)
    distinct["SourceRevision"].update(_ids(source_revision_rows, "source_revision_id"))
    return {
        "counting_policy": "physical frozen-layer records; distinct IDs shown separately; no cross-layer identity merge",
        "requested_type_counts_physical": {key: physical[key] for key in requested},
        "requested_type_counts_distinct_id": {key: len(distinct[key]) for key in requested},
        "strict_source_revision_records": len(source_revision_rows),
        "strict_source_revision_distinct_ids": len(distinct["SourceRevision"]),
        "legacy_core_source_records": len(legacy_source_rows),
        "source_document_or_record_references": len(source_document_refs),
        "graph_record_type_counts": graph["inventory"]["graph_node_counts_by_type"],
        "note": "Legacy core Source records and source-document references are not retyped as SourceRevision.",
    }


def governance_counts(layers: list[dict[str, Any]], graph: dict[str, Any]) -> dict[str, Any]:
    claims = [claim for item in layers for claim in item["bundle"].get("atomic_claims", [])]
    reviews = [row for item in layers for row in item["bundle"].get("review_decisions", [])]
    supersessions = [row for item in layers for row in item["bundle"].get("supersessions", [])]
    decisions = Counter(str(row.get("decision", row.get("status", "unknown"))).casefold() for row in reviews)
    reviewed_claim_ids = {str(row.get("claim_revision_id")) for row in reviews if row.get("claim_revision_id")}
    trusted_words = {"trusted", "canonical", "approved", "approve", "promoted"}
    rejected_words = {"rejected", "reject"}
    trusted = sum(count for key, count in decisions.items() if key in trusted_words)
    rejected = sum(count for key, count in decisions.items() if key in rejected_words)
    return {
        "candidate_claims": len(claims),
        "reviewed_claims": len(reviewed_claim_ids),
        "trusted_or_canonical_claims": trusted,
        "rejected_claims": rejected,
        "superseded_claims": len(supersessions),
        "review_decisions": len(reviews),
        "candidate_derived_relations": sum(len(item["bundle"].get("derived_relations", [])) for item in layers),
        "trusted_source_evidence_nodes": graph["inventory"]["evidence"]["trusted_source_evidence_nodes"],
        "interpretation": "Trusted source evidence describes provenance quality; it does not promote candidate scientific claims.",
    }


def _exact_mapped_chunks(span: dict[str, Any], chunks: dict[str, EvidenceChunk]) -> list[str]:
    span_id = span["evidence_span_id"]
    return sorted(
        chunk.chunk_id
        for chunk in chunks.values()
        if span_id in {chunk.chunk_id, chunk.evidence_id, chunk.source_record_id}
        and (chunk.source_document_id or chunk.source_id) == span["source_revision_id"]
        and chunk.source_span == span["locator"]
        and chunk.content_hash == span["content_hash"]
        and chunk.chunk_text == span["source_excerpt"]
        and chunk.source_bound
        and chunk.retrieval_status == "retrieval_only"
        and str(chunk.recommendation_eligible).casefold() != "true"
    )


def readiness_counts() -> tuple[dict[str, Any], dict[str, Any]]:
    adapter = ScientificKGEvidence()
    chunks = {row.chunk_id: row for row in load_chunks(retrieval_foundation.INDEX_DIR / "evidence_chunks.jsonl")}
    service = object.__new__(HybridRetrievalService)
    service._chunks_by_id = chunks
    assessments_by_claim: dict[str, list[Any]] = defaultdict(list)
    for assessment in adapter.bundle.evidence_assessments:
        assessments_by_claim[assessment.claim_revision_id].append(assessment)

    rows = []
    mapped_spans: set[str] = set()
    bound_spans: set[str] = set()
    mapped_claims: set[str] = set()
    for operator in adapter.operators:
        claims = [claim for claim in adapter.bundle.atomic_claims if claim.subject_id == operator.entity_id]
        has_l1 = bool(claims) and all(claim.scope_id in adapter.scopes for claim in claims)
        operator_bound: set[str] = set()
        operator_mapped: set[str] = set()
        operator_claims_mapped: set[str] = set()
        binding_errors: Counter[str] = Counter()
        for claim in claims:
            binding = adapter.bindings.get(claim.claim_revision_id)
            for span_id in (binding or {}).get("evidence_span_ids", []):
                span, error = adapter._span_binding(claim, binding, span_id)
                if error:
                    binding_errors[error] += 1
                    continue
                operator_bound.add(span_id)
                bound_spans.add(span_id)
                mapped = _exact_mapped_chunks(span, chunks)
                if mapped:
                    operator_mapped.update(mapped)
                    mapped_spans.add(span_id)
                    mapped_claims.add(claim.claim_revision_id)
                    operator_claims_mapped.add(claim.claim_revision_id)
        resolution = adapter.subject_resolver.resolve(operator.entity_id)
        request = HybridRetrievalRequest(query=operator.entity_id, include_catalog=False, enable_dense=False)
        eligible = service._filter_ranked(
            [(chunk_id, 1.0) for chunk_id in sorted(operator_mapped)],
            request=request,
            task_ids=set(),
            candidate_tools=set(),
            scientific_claim_owned_chunk_ids=set(operator_mapped),
        )
        has_l2 = bool(operator_bound)
        has_l3 = bool(operator_mapped)
        has_l4 = resolution.status == "RESOLVED" and bool(eligible)
        level = "L4" if has_l4 else "L3" if has_l3 else "L2" if has_l2 else "L1" if has_l1 else "L0"
        rows.append({
            "operator_revision_id": operator.entity_id,
            "highest_level": level,
            "claim_count": len(claims),
            "evidence_bound_span_count": len(operator_bound),
            "mapped_claim_count": len(operator_claims_mapped),
            "exact_mapped_chunk_count": len(operator_mapped),
            "publicly_eligible_chunk_count": len(eligible),
            "subject_resolution": resolution.status,
            "binding_errors": dict(sorted(binding_errors.items())),
        })
    highest = Counter(row["highest_level"] for row in rows)
    order = ["L0", "L1", "L2", "L3", "L4"]
    thresholds = {f"{level}_or_higher": sum(highest[item] for item in order[order.index(level):]) for level in order}
    all_bound = set(adapter.spans)
    all_claims = {claim.claim_revision_id for claim in adapter.bundle.atomic_claims}
    summary = {
        "scope": "production UAT direct-evidence overlay only",
        "definitions": {
            "L0": "registered OperatorRevision identity",
            "L1": "claim and ApplicabilityScope present",
            "L2": "at least one integrity-verified EvidenceSpan and SourceRevision binding",
            "L3": "at least one exact mapping into the frozen retrieval corpus",
            "L4": "subject resolves and at least one mapped chunk survives the current public filter",
        },
        "operator_revision_count": len(rows),
        "highest_exclusive": {level: highest[level] for level in order},
        "threshold_counts": thresholds,
        "operator_revisions_without_any_mapped_direct_evidence": sum(not row["exact_mapped_chunk_count"] for row in rows),
        "bound_evidence_spans_without_exact_frozen_rag_chunk": len(all_bound - mapped_spans),
        "claims_without_exact_frozen_rag_chunk": len(all_claims - mapped_claims),
        "broad_candidate_coverage_is_readiness": False,
    }
    return summary, {"operators": rows}


def integrity_issues(layers: list[dict[str, Any]], graph: dict[str, Any], readiness: dict[str, Any]) -> dict[str, Any]:
    per_layer = []
    all_hard: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    cross_layer_ids: dict[str, list[str]] = defaultdict(list)
    for item in layers:
        layer_id = item["layer"].layer_id
        bundle = item["bundle"]
        entities = bundle.get("entities", [])
        claims = bundle.get("atomic_claims", [])
        assessments = bundle.get("evidence_assessments", [])
        relations = bundle.get("derived_relations", [])
        scopes = {row["scope_id"] for row in bundle.get("scopes", [])}
        entity_ids = _ids(entities, "entity_id")
        object_ids = entity_ids | _ids(bundle.get("representation_types", []), "representation_type_id") | _ids(bundle.get("representation_constraints", []), "constraint_id")
        claim_ids = _ids(claims, "claim_revision_id")
        evidence_ids = _ids(item["evidence"], "evidence_span_id")
        assessment_claims = _ids(assessments, "claim_revision_id")
        referenced_evidence = {str(value) for row in assessments for value in row.get("evidence_span_ids", [])}
        orphan = sorted(row["claim_revision_id"] for row in claims if row["subject_id"] not in entity_ids)
        no_scope = sorted(row["claim_revision_id"] for row in claims if row.get("scope_id") not in scopes)
        no_assessment = sorted(claim_ids - assessment_claims)
        missing_spans = sorted(referenced_evidence - evidence_ids)
        dangling_spans = sorted(evidence_ids - referenced_evidence)
        invalid_endpoints = sorted(
            row["relation_id"] for row in relations
            if row.get("source_id") not in object_ids or row.get("target_id") not in object_ids
        )
        within_ids = [
            *(str(row["entity_id"]) for row in entities if row.get("entity_id")),
            *(str(row["claim_revision_id"]) for row in claims if row.get("claim_revision_id")),
            *(str(row["evidence_span_id"]) for row in item["evidence"] if row.get("evidence_span_id")),
        ]
        duplicate_ids = len(within_ids) - len(set(within_ids))
        for value in set(within_ids):
            cross_layer_ids[value].append(layer_id)
        hard = {
            "orphan_claims": orphan,
            "claims_without_scope": no_scope,
            "claims_without_evidence_assessment": no_assessment,
            "invalid_relation_endpoints": invalid_endpoints,
            "duplicate_ids_within_layer": duplicate_ids,
        }
        if any(bool(value) for value in hard.values()):
            all_hard.append({"layer_id": layer_id, **hard})
        if missing_spans:
            warnings.append({"layer_id": layer_id, "type": "referenced_evidence_span_not_materialized_in_layer", "count": len(missing_spans), "ids": missing_spans})
        if dangling_spans:
            warnings.append({"layer_id": layer_id, "type": "materialized_evidence_span_not_referenced_by_assessment", "count": len(dangling_spans), "ids": dangling_spans})
        per_layer.append({
            "layer_id": layer_id,
            "claims": len(claims), "evidence_spans": len(evidence_ids),
            "orphan_claims": len(orphan), "claims_without_scope": len(no_scope),
            "claims_without_evidence_assessment": len(no_assessment),
            "referenced_spans_not_materialized": len(missing_spans),
            "materialized_spans_not_referenced": len(dangling_spans),
            "invalid_relation_endpoints": len(invalid_endpoints),
            "duplicate_ids_within_layer": duplicate_ids,
        })
    graph_ids = {row["graph_node_id"] for row in graph["nodes"]}
    graph_dangling = [row["graph_edge_id"] for row in graph["edges"] if row["source_graph_node_id"] not in graph_ids or row["target_graph_node_id"] not in graph_ids]
    overlapping = {key: sorted(value) for key, value in cross_layer_ids.items() if len(value) > 1}
    return {
        "status": "PASS_WITH_DECLARED_WARNINGS" if not all_hard and not graph_dangling else "FAIL",
        "hard_issue_count": len(all_hard) + len(graph_dangling),
        "hard_issues": all_hard,
        "consolidated_graph_dangling_edges": graph_dangling,
        "per_layer": per_layer,
        "warning_count": sum(item["count"] for item in warnings),
        "warnings": warnings,
        "cross_layer_identity_overlap_count": len(overlapping),
        "cross_layer_identity_overlap_note": "Expected under physical-layer counting; identities were not merged.",
        "broken_rag_mapping": {
            "operator_revisions_without_any_mapped_direct_evidence": readiness["operator_revisions_without_any_mapped_direct_evidence"],
            "bound_evidence_spans_without_exact_frozen_rag_chunk": readiness["bound_evidence_spans_without_exact_frozen_rag_chunk"],
            "claims_without_exact_frozen_rag_chunk": readiness["claims_without_exact_frozen_rag_chunk"],
        },
    }


def render_report(snapshot: dict[str, Any]) -> str:
    legacy = snapshot["legacy_summary"]
    scientific = snapshot["scientific_summary"]
    semantic = snapshot["semantic_counts"]
    governance = snapshot["governance_counts"]
    readiness = snapshot["readiness_counts"]
    integrity = snapshot["integrity_issues"]
    physical = semantic["requested_type_counts_physical"]
    lines = [
        "# Scientific KG Inventory & Ontology Audit — Snapshot v1", "",
        f"Checkpoint: `1`", f"Git HEAD: `{snapshot['git_head']}`",
        "Mode: read-only inventory; no identity merge, promotion, retrieval rebuild, or KG content change.", "",
        "## Two substrates", "",
        "| Substrate | Role | Nodes | Edges | Entity types | Relation types |", "| --- | --- | ---: | ---: | ---: | ---: |",
        f"| Legacy Tool KG | discovery/catalog | {legacy['nodes']} | {legacy['edges']} | {legacy['entity_type_count']} | {legacy['relation_type_count']} |",
        f"| Scientific KG | ontology-backed decision knowledge, four physical frozen layers | {scientific['nodes']} | {scientific['edges']} | {scientific['entity_type_count']} | {scientific['relation_type_count']} |", "",
        "The Scientific KG total is a physical-layer inventory. Overlapping identities remain separate until adjudicated identity mappings exist.", "",
        "## Scientific semantic inventory", "", "| Type | Physical records | Distinct IDs |", "| --- | ---: | ---: |",
    ]
    for key, value in physical.items():
        lines.append(f"| {key} | {value} | {semantic['requested_type_counts_distinct_id'][key]} |")
    lines.extend([
        "", f"Strict `SourceRevision` records: **{semantic['strict_source_revision_records']}** physical / **{semantic['strict_source_revision_distinct_ids']}** distinct. Core also has **{semantic['legacy_core_source_records']}** legacy Source records; these are reported separately.", "",
        "## Governance", "", "| State | Count |", "| --- | ---: |",
        f"| Candidate claims | {governance['candidate_claims']} |",
        f"| Reviewed claims | {governance['reviewed_claims']} |",
        f"| Trusted/canonical claims | {governance['trusted_or_canonical_claims']} |",
        f"| Rejected claims | {governance['rejected_claims']} |",
        f"| Superseded claims | {governance['superseded_claims']} |",
        f"| Trusted source-evidence nodes | {governance['trusted_source_evidence_nodes']} |", "",
        governance["interpretation"], "", "## Production readiness (UAT overlay only)", "",
        "| Highest exclusive level | Operators |", "| --- | ---: |",
    ])
    for level, count in readiness["highest_exclusive"].items():
        lines.append(f"| {level} | {count} |")
    lines.extend([
        "", f"Broad candidate coverage is not production readiness. Of {readiness['operator_revision_count']} UAT OperatorRevisions, {readiness['operator_revisions_without_any_mapped_direct_evidence']} have no mapped direct evidence in the frozen RAG corpus.", "",
        "## Integrity", "", f"Status: **{integrity['status']}**", f"Hard issues: **{integrity['hard_issue_count']}**", f"Declared warning records: **{integrity['warning_count']}**", "",
        "Warnings preserve evidence gaps rather than hiding them: deferred/reference layers contain referenced span IDs without a materialized span in that layer, and some materialized spans are not referenced by an assessment.", "",
        "## Current limitations", "",
        "- Counts span four frozen layers and therefore are physical coverage counts, not a canonical deduplicated KG size.",
        "- L0–L4 is recomputed only for the production UAT direct-evidence overlay.",
        "- Core legacy Source records and publication/repository references do not satisfy the strict SourceRevision ontology type.",
        "- Candidate claims have not undergone review or canonical promotion.", "",
        "## Exit report", "", "```text", "CHECKPOINT=1", f"STATUS={'PASS' if integrity['hard_issue_count'] == 0 else 'FAIL'}",
        "CHANGED_FILES=eval/scientific_kg_inventory_snapshot_v1.py; tests/test_scientific_kg_inventory_snapshot_v1.py; docs/status/SCIENTIFIC_KG_INVENTORY_SNAPSHOT_V1.md; data/evaluation/scientific_kg_inventory_snapshot_v1/*",
        "FOCUSED_TESTS=see manifest.json", "REGRESSION_TESTS=see manifest.json", "REAL_RUN=python -m eval.scientific_kg_inventory_snapshot_v1 --write",
        f"ARTIFACT_INTEGRITY={'PASS' if snapshot['artifact_integrity']['unchanged'] else 'FAIL'}",
        f"PRIMARY_RESULT=Scientific KG {scientific['nodes']} nodes/{scientific['edges']} edges physical; {governance['candidate_claims']} candidate claims; UAT L4={readiness['highest_exclusive']['L4']}/{readiness['operator_revision_count']}",
        "CURRENT_LIMITATION=no cross-layer identity merge; readiness limited to production UAT overlay",
        "NEXT_EARLIEST_DIVERGENCE=Checkpoint 2 scKG-Eval Specification v1 (not started)",
        "CORPUS_CHANGED=false", "KG_CONTENT_CHANGED=false", "PLANNER_CHANGED=false", "GOLD_CHANGED=false", "CANONICAL_PROMOTION=false",
        f"LOCAL_HEAD={snapshot['git_head']}", f"REMOTE_HEAD={snapshot['remote_head']}", "PUSH_STATUS=NOT_REQUESTED_FOR_CHECKPOINT_1", "STOPPED=true", "```", "",
    ])
    return "\n".join(lines)


def build_snapshot(before: dict[str, Any]) -> dict[str, Any]:
    graph = build_inventory()
    legacy, legacy_nodes, legacy_relations = legacy_inventory()
    scientific_nodes = graph["inventory"]["graph_node_counts_by_type"]
    scientific_relations = graph["inventory"]["graph_edge_counts_by_predicate"]
    layers = load_scientific_layers()
    semantic = semantic_counts(layers, graph)
    governance = governance_counts(layers, graph)
    readiness, readiness_detail = readiness_counts()
    integrity = integrity_issues(layers, graph, readiness)
    remote = subprocess.check_output(
        ["git", "ls-remote", "--heads", "origin", "feature/method-kg-expansion-v1"], cwd=ROOT, text=True
    ).strip().split()
    return {
        "schema_version": "sckg-scientific-kg-inventory-snapshot-v1",
        "checkpoint": 1,
        "git_head": git_head(),
        "remote_head": remote[0] if remote else "",
        "audit_mode": "read_only",
        "legacy_summary": legacy,
        "scientific_summary": {
            "substrate": "Scientific KG", "role": "ontology_backed_decision_knowledge",
            "nodes": len(graph["nodes"]), "edges": len(graph["edges"]),
            "entity_type_count": len(scientific_nodes), "relation_type_count": len(scientific_relations),
            "layer_count": len(layers), "identity_merge_performed": False,
        },
        "legacy_node_type_counts": legacy_nodes,
        "legacy_relation_type_counts": legacy_relations,
        "scientific_node_type_counts": scientific_nodes,
        "scientific_relation_type_counts": scientific_relations,
        "semantic_counts": semantic,
        "governance_counts": governance,
        "readiness_counts": readiness,
        "readiness_detail": readiness_detail,
        "evidence_coverage": {
            **graph["inventory"]["evidence"],
            "strict_source_revision_records": semantic["strict_source_revision_records"],
            "strict_source_revision_distinct_ids": semantic["strict_source_revision_distinct_ids"],
            **readiness["threshold_counts"],
        },
        "integrity_issues": integrity,
        "artifact_integrity": {"before": before},
    }


def write_outputs(snapshot: dict[str, Any]) -> dict[str, Any]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    payloads = {
        "node_type_counts.json": {"legacy_tool_kg": snapshot["legacy_node_type_counts"], "scientific_kg": snapshot["scientific_node_type_counts"]},
        "relation_type_counts.json": {"legacy_tool_kg": snapshot["legacy_relation_type_counts"], "scientific_kg": snapshot["scientific_relation_type_counts"]},
        "semantic_counts.json": snapshot["semantic_counts"],
        "governance_counts.json": snapshot["governance_counts"],
        "readiness_counts.json": {**snapshot["readiness_counts"], **snapshot["readiness_detail"]},
        "evidence_coverage.json": snapshot["evidence_coverage"],
        "integrity_issues.json": snapshot["integrity_issues"],
    }
    for name, payload in payloads.items():
        write_json(OUTPUT_DIR / name, payload)
    after = protected_identity()
    unchanged = snapshot["artifact_integrity"]["before"] == after
    snapshot["artifact_integrity"].update({"after": after, "unchanged": unchanged})
    if not unchanged:
        raise RuntimeError("protected artifact integrity changed during read-only audit")
    generated = {name: sha256(OUTPUT_DIR / name) for name in payloads}
    hashes = {
        "protected_before": snapshot["artifact_integrity"]["before"],
        "protected_after": after,
        "protected_unchanged": unchanged,
        "generated_artifact_sha256": generated,
    }
    write_json(OUTPUT_DIR / "hashes.json", hashes)
    manifest = {
        "schema_version": snapshot["schema_version"], "checkpoint": 1,
        "status": "PASS" if snapshot["integrity_issues"]["hard_issue_count"] == 0 else "FAIL",
        "git_head": snapshot["git_head"], "remote_head": snapshot["remote_head"],
        "audit_mode": "read_only", "legacy_and_scientific_separated": True,
        "broad_coverage_and_readiness_separated": True, "hard_coded_metrics": False,
        "kg_content_changed": False, "canonical_promotion": False,
        "artifact_integrity": "PASS" if unchanged else "FAIL",
        "artifacts": {**generated, "hashes.json": sha256(OUTPUT_DIR / "hashes.json")},
        "focused_tests": "pending runner verification",
        "regression_tests": "pending runner verification",
    }
    write_json(OUTPUT_DIR / "manifest.json", manifest)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(render_report(snapshot), encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true", help="write the checkpoint artifacts")
    args = parser.parse_args()
    before = protected_identity()
    snapshot = build_snapshot(before)
    if args.write:
        manifest = write_outputs(snapshot)
        print(json.dumps({"status": manifest["status"], "output": str(OUTPUT_DIR.relative_to(ROOT)), "report": str(REPORT_PATH.relative_to(ROOT))}, sort_keys=True))
    else:
        print(json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if snapshot["integrity_issues"]["hard_issue_count"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
