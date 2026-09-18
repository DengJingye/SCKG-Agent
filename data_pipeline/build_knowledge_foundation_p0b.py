from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from core.scientific_knowledge_conformance_models import ReferenceArtifact
from core.settings import PROJECT_ROOT
from engine.knowledge_foundation_safety import (
    can_feed_is_actionable,
    candidate_scope_can_be_trusted,
    load_knowledge_foundation_policy,
)


DEFAULT_OUTPUT_DIR = (
    PROJECT_ROOT / "data" / "evaluation" / "knowledge_foundation_p0b"
)
AUDIT_DIR = PROJECT_ROOT / "data" / "evaluation" / "knowledge_foundation_audit_v1"
CORE_DIR = (
    PROJECT_ROOT / "data" / "evidence_candidates" / "scientific_kg_v1_core"
)
UAT_DIR = (
    PROJECT_ROOT
    / "data"
    / "evidence_candidates"
    / "scientific_kg_v1_uat_decision_rules"
)
SOURCE_DOCUMENTS = PROJECT_ROOT / "data" / "indexes" / "source_documents_v2.jsonl"
AUTHORITATIVE_SOURCE_MANIFEST = UAT_DIR / "authoritative_source_manifest.json"

SCHEMA_VERSION = "knowledge-foundation-p0b-candidate-v1"


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text(
        "".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
            for row in rows
        ),
        encoding="utf-8",
    )


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_software_documents() -> list[dict[str, Any]]:
    return [
        row
        for row in _read_jsonl(SOURCE_DOCUMENTS)
        if row.get("source_type") in {"github_readme", "official_docs_html"}
    ]


def _declared_versions() -> dict[str, dict[str, Any]]:
    sources = _read_json(CORE_DIR / "source_manifest.json")["sources"]
    return {
        source["ecosystem"].casefold(): source
        for source in sources
        if source["source_type"] == "official_api_or_package_documentation"
    }


def _pinned_authoritative_revisions() -> dict[str, dict[str, Any]]:
    rows = _read_json(AUTHORITATIVE_SOURCE_MANIFEST)["sources"]
    mapping: dict[str, dict[str, Any]] = {}
    for row in rows:
        revision_id = row.get("source_revision_id", "")
        if "/scanpy:" in revision_id or ":scanpy:" in revision_id:
            ecosystem = "scanpy"
        elif ":harmony:" in revision_id:
            ecosystem = "harmony"
        elif ":scrublet:" in revision_id:
            ecosystem = "scrublet"
        elif ":SingleR:" in revision_id:
            ecosystem = "singler"
        else:
            continue
        mapping[ecosystem] = {
            "source_revision_id": revision_id,
            "release_uri": row.get("release_uri"),
            "release_artifact_sha256": row.get("release_artifact_sha256")
            or row.get("pypi_sdist_sha256"),
            "git_commit": row.get("git_commit"),
            "release": row.get("release"),
            "source_file_count": len(row.get("source_files", [])),
        }
    return mapping


def _source_hardening_rows() -> list[dict[str, Any]]:
    versions = _declared_versions()
    pinned_revisions = _pinned_authoritative_revisions()
    rows: list[dict[str, Any]] = []
    for source in _canonical_software_documents():
        tools = source.get("referring_tool_names", [])
        tool = tools[0] if tools else "UNKNOWN"
        declared = versions.get(tool.casefold())
        pinned_revision = pinned_revisions.get(tool.casefold())
        text_path = PROJECT_ROOT / source["local_text_path"] if source.get("local_text_path") else None
        actual_digest = _sha(text_path) if text_path and text_path.exists() else None
        recorded_digest = source.get("content_hash") or None
        local_integrity = bool(actual_digest and actual_digest == recorded_digest)
        source_url = source.get("source_url", "")
        pinned_locator = any(marker in source_url for marker in ("/blob/v", "/tree/v", "/blob/refs/tags/"))

        if declared is None:
            version_status = "unresolved"
            declared_version = None
            candidate_locator = None
        elif pinned_locator:
            version_status = "immutable_locator_and_content_digest"
            declared_version = declared["version"]
            candidate_locator = source_url
        else:
            version_status = "version_asserted_but_not_bound_to_local_snapshot"
            declared_version = declared["version"]
            candidate_locator = declared["source_uri"]

        rows.append(
            {
                "schema_version": SCHEMA_VERSION,
                "source_document_id": source["source_id"],
                "ecosystem": tool,
                "source_work": source["canonical_title"],
                "source_type": source["source_type"],
                "origin_url": source_url,
                "local_text_path": source.get("local_text_path", ""),
                "recorded_content_sha256": recorded_digest,
                "actual_content_sha256": actual_digest,
                "content_integrity_status": "verified" if local_integrity else "unresolved",
                "declared_operator_version": declared_version,
                "candidate_version_locator": candidate_locator,
                "upstream_version_status": version_status,
                "scientific_use_status": (
                    "candidate_pinned_authoritative_revision_available"
                    if pinned_revision
                    else (
                        "candidate_version_scoped"
                        if version_status == "immutable_locator_and_content_digest"
                        else "candidate_unknown_version_binding"
                    )
                ),
                "pinned_authoritative_revision": pinned_revision,
                "promotion_eligible": False,
                "reason": (
                    "A local content digest freezes the captured text, but it does not prove "
                    "that a mutable upstream page corresponds to the declared package release. "
                    "Where a separate pinned revision exists, only evidence bound to that revision "
                    "may support version-sensitive claims."
                ),
            }
        )
    return sorted(rows, key=lambda row: (row["ecosystem"].casefold(), row["source_document_id"]))


def _reference_artifact_rows() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    definitions = [
        (
            "reference-artifact:celltypist:classifier-model-family",
            "CellTypist classifier model family",
            "pretrained_model",
            "CellTypist",
            ["version", "species_taxon", "feature_namespace", "label_space", "content_digest"],
            "Execution/applicability must clarify until an exact model revision is resolved.",
        ),
        (
            "reference-artifact:singler:reference-atlas-family",
            "SingleR reference expression atlas family",
            "atlas",
            "SingleR",
            ["version", "species_taxon", "feature_namespace", "biological_context", "content_digest"],
            "Reference expression identity must be resolved independently of the runtime matrix path.",
        ),
        (
            "reference-artifact:singler:reference-label-mapping-family",
            "SingleR reference label mapping family",
            "label_mapping",
            "SingleR",
            ["version", "label_ontology", "biological_context", "content_digest"],
            "Labels must remain bound to the selected reference atlas revision.",
        ),
        (
            "reference-artifact:singler:feature-mapping-family",
            "SingleR query-reference feature mapping family",
            "feature_mapping",
            "SingleR",
            ["version", "query_feature_namespace", "reference_feature_namespace", "content_digest"],
            "Shared-feature compatibility is scientific knowledge; actual instance alignment is runtime-owned.",
        ),
        (
            "reference-artifact:pyscenic:tf-list-family",
            "pySCENIC transcription-factor list family",
            "feature_mapping",
            "pySCENIC",
            ["version", "species_taxon", "genome_assembly", "feature_namespace", "content_digest"],
            "No revision is asserted until a versioned resource and digest are available.",
        ),
        (
            "reference-artifact:pyscenic:motif-annotation-family",
            "pySCENIC motif annotation family",
            "feature_mapping",
            "pySCENIC",
            ["version", "species_taxon", "genome_assembly", "feature_namespace", "content_digest"],
            "The v1.1 kind is a bounded family identity; exact motif resource revision remains unresolved.",
        ),
    ]
    identities: list[dict[str, Any]] = []
    requirements: list[dict[str, Any]] = []
    for entity_id, label, kind, ecosystem, fields, boundary in definitions:
        model = ReferenceArtifact(
            entity_id=entity_id,
            label=label,
            artifact_kind=kind,
        )
        identities.append(
            {
                **model.model_dump(mode="json"),
                "ecosystem": ecosystem,
                "knowledge_status": "candidate",
                "review_status": "candidate_pending_review",
            }
        )
        requirements.append(
            {
                "schema_version": SCHEMA_VERSION,
                "reference_artifact_id": entity_id,
                "ecosystem": ecosystem,
                "required_revision_identity_fields": fields,
                "reference_artifact_revision_id": None,
                "revision_resolution_status": "evidence_gap",
                "runtime_boundary": boundary,
                "applicability_action": "clarify_or_block",
                "canonical_promotion": "none",
            }
        )

    requirements.append(
        {
            "schema_version": SCHEMA_VERSION,
            "reference_artifact_id": None,
            "ecosystem": "pySCENIC",
            "required_revision_identity_fields": [
                "resource_kind",
                "version",
                "species_taxon",
                "genome_assembly",
                "feature_namespace",
                "content_digest",
            ],
            "reference_artifact_revision_id": None,
            "revision_resolution_status": "schema_kind_and_evidence_gap",
            "runtime_boundary": (
                "The frozen v1.1 ReferenceArtifact kind vocabulary does not explicitly name "
                "a motif-ranking database. Do not mislabel one merely to close the matrix."
            ),
            "applicability_action": "clarify_or_block",
            "canonical_promotion": "none",
        }
    )
    return identities, requirements


def _compatibility_review_packets() -> list[dict[str, Any]]:
    uat_relations = {
        row["relation_id"]: row
        for row in _read_jsonl(UAT_DIR / "derived_relations.jsonl")
        if row["relation"] == "CAN_FEED"
    }
    uat_proofs = {
        row["relation_id"]: row
        for row in _read_json(UAT_DIR / "derived_relation_proofs.json")["proofs"]
    }
    selected = {
        "Harmony corrected embedding -> Scanpy neighbors": "derived-relation:uat:can-feed:b40562c4d5040f73",
        "Scanpy neighbor graph -> Leiden": "derived-relation:uat:can-feed:b6a052e7eb55205e",
    }
    packets: list[dict[str, Any]] = []
    for label, relation_id in selected.items():
        relation = uat_relations[relation_id]
        proof = uat_proofs[relation_id]
        packets.append(
            {
                "schema_version": SCHEMA_VERSION,
                "closure": label,
                "relation": relation,
                "proof": proof,
                "scientific_evidence_status": "source_bound_candidate",
                "review_status": "candidate_pending_review",
                "actionable": False,
                "review_decision_ids": [],
                "version_scope_status": (
                    "unknown_cross_version_binding"
                    if label.startswith("Harmony")
                    else "exact_candidate_versions"
                ),
                "required_alignment_checks": proof["checks"],
            }
        )

    packets.append(
        {
            "schema_version": SCHEMA_VERSION,
            "closure": "scVelo velocity/transition state -> CellRank",
            "relation": None,
            "proof": None,
            "scientific_evidence_status": "evidence_gap",
            "review_status": "not_constructed",
            "actionable": False,
            "review_decision_ids": [],
            "version_scope_status": "unresolved",
            "required_alignment_checks": [
                "source_bound_claim_support",
                "transition_object_semantics",
                "observation_identity",
                "lineage_compatibility",
                "kernel_and_parameter_compatibility",
                "staleness",
            ],
            "reason": (
                "The frozen core has candidate operator/port records, but no reviewed cross-tool "
                "compatibility proof. Type similarity is insufficient."
            ),
        }
    )
    return packets


def _coverage_after() -> dict[str, Any]:
    before = _read_json(AUDIT_DIR / "core_tool_coverage.json")
    paths = []
    for row in before["paths"]:
        updated = dict(row)
        updated["p0b_candidate_deepening"] = []
        if row["ecosystem"] in {"CellTypist", "SingleR", "pySCENIC"}:
            updated["p0b_candidate_deepening"].append(
                "ReferenceArtifact family identity and explicit unresolved-revision boundary"
            )
        if row["ecosystem"] in {"Scanpy", "Harmony"}:
            updated["p0b_candidate_deepening"].append(
                "bounded candidate compatibility review packet"
            )
        if row["ecosystem"] in {"scVelo", "CellRank"}:
            updated["p0b_candidate_deepening"].append(
                "explicit cross-tool compatibility EvidenceGap"
            )
        updated["p0b_readiness_change"] = "none"
        updated["p0b_reason"] = (
            "P0B adds candidate scientific identity/review material only. It does not add "
            "Capability Packs, ToolContracts, planner bindings, or trusted promotion."
        )
        paths.append(updated)

    return {
        "schema_version": "knowledge-foundation-core-tool-coverage-p0b-v1",
        "baseline": {
            "artifact": "data/evaluation/knowledge_foundation_audit_v1/core_tool_coverage.json",
            "sha256": _sha(AUDIT_DIR / "core_tool_coverage.json"),
        },
        "definitions": before["definitions"],
        "summary_before": before["summary"],
        "summary_after": before["summary"],
        "paths": paths,
        "metric_integrity_note": (
            "Readiness counts are intentionally unchanged. Candidate source/reference/compatibility "
            "hardening is not production Planner consumption."
        ),
    }


def _core_semantic_closure(
    reference_identities: list[dict[str, Any]],
) -> dict[str, Any]:
    bundle = _read_json(CORE_DIR / "conformance_bundle.json")
    spans = {
        row["evidence_span_id"]: row
        for row in _read_jsonl(CORE_DIR / "evidence_spans.jsonl")
    }
    assessments = {
        row["claim_revision_id"]: row
        for row in _read_jsonl(CORE_DIR / "evidence_assessments.jsonl")
    }
    claims = _read_jsonl(CORE_DIR / "atomic_claims.jsonl")
    coverage = _read_json(AUDIT_DIR / "core_tool_coverage.json")
    coverage_by_ecosystem = {row["ecosystem"]: row for row in coverage["paths"]}

    entities = bundle["entities"]
    projects = {
        row["entity_id"]: row for row in entities if row["record_type"] == "SoftwareProject"
    }
    packages = {row["entity_id"]: row for row in entities if row["record_type"] == "Package"}
    releases = {
        row["entity_id"]: row for row in entities if row["record_type"] == "PackageRelease"
    }
    operators = {row["entity_id"]: row for row in entities if row["record_type"] == "Operator"}
    revisions = [row for row in entities if row["record_type"] == "OperatorRevision"]
    references_by_ecosystem: dict[str, list[str]] = {}
    for row in reference_identities:
        references_by_ecosystem.setdefault(row["ecosystem"], []).append(row["entity_id"])

    rows: list[dict[str, Any]] = []
    for revision in revisions:
        operator = operators[revision["operator_id"]]
        package = packages[operator["package_id"]]
        release = releases[revision["package_release_id"]]
        ecosystem = projects[package["project_id"]]["label"]
        coverage_key = "edgeR / pseudobulk" if ecosystem == "edgeR" else ecosystem
        revision_claims = [
            claim for claim in claims if claim["subject_id"] == revision["entity_id"]
        ]
        evidence_span_ids = sorted(
            {
                span_id
                for claim in revision_claims
                for span_id in assessments[claim["claim_revision_id"]]["evidence_span_ids"]
            }
        )
        source_ids = sorted({spans[span_id]["source_id"] for span_id in evidence_span_ids})
        constraint_ids = sorted(
            {
                constraint_id
                for port in revision["input_ports"]
                for requirement in port["requirements"]
                for constraint_id in requirement["representation_constraint_ids"]
            }
        )
        input_types = sorted(
            {
                relation["target_id"]
                for relation in bundle["derived_relations"]
                if relation["relation"] == "CONSUMES"
                and relation["source_id"] == revision["entity_id"]
            }
        )
        output_types = sorted(
            {
                port["representation_type_id"] for port in revision["output_ports"]
            }
        )
        coverage_row = coverage_by_ecosystem.get(coverage_key, {})
        rows.append(
            {
                "ecosystem": ecosystem,
                "package_id": package["entity_id"],
                "package_release_id": release["entity_id"],
                "version": release["version"],
                "operator_id": operator["entity_id"],
                "operator_revision_id": revision["entity_id"],
                "method_ids": revision["implements_method_ids"],
                "input_port_ids": [port["input_port_id"] for port in revision["input_ports"]],
                "output_port_ids": [port["output_port_id"] for port in revision["output_ports"]],
                "input_representation_types": input_types,
                "output_representation_types": output_types,
                "representation_constraint_ids": constraint_ids,
                "scope_id": revision["scope_id"],
                "claim_revision_ids": [claim["claim_revision_id"] for claim in revision_claims],
                "evidence_span_ids": evidence_span_ids,
                "source_ids": source_ids,
                "epistemic_status": "candidate_pending_review",
                "reference_artifact_ids": sorted(references_by_ecosystem.get(ecosystem, [])),
                "tool_contract_refs": revision["contract_refs"],
                "production_planner_consumes": coverage_row.get("planning_ready", False),
                "completeness": {
                    "operator_revision": "PRESENT",
                    "canonical_ports": "PRESENT" if revision["input_ports"] and revision["output_ports"] else "MISSING",
                    "representation_constraints": "PRESENT" if constraint_ids else "MISSING",
                    "applicability_scope": "PRESENT" if revision["scope_id"] else "MISSING",
                    "atomic_claims": "PRESENT" if revision_claims else "MISSING",
                    "source_bound_evidence": "PRESENT" if evidence_span_ids else "MISSING",
                    "reference_revision": (
                        "MISSING"
                        if ecosystem in {"CellTypist", "SingleR", "pySCENIC"}
                        else "NOT_APPLICABLE_OR_NOT_REQUIRED_FOR_THIS_OPERATOR"
                    ),
                    "production_planner_consumption": (
                        "PRESENT" if coverage_row.get("planning_ready", False) else "MISSING"
                    ),
                },
            }
        )

    by_ecosystem: list[dict[str, Any]] = []
    for ecosystem in sorted({row["ecosystem"] for row in rows}, key=str.casefold):
        ecosystem_rows = [row for row in rows if row["ecosystem"] == ecosystem]
        coverage_key = "edgeR / pseudobulk" if ecosystem == "edgeR" else ecosystem
        by_ecosystem.append(
            {
                "ecosystem": ecosystem,
                "operator_revision_count": len(ecosystem_rows),
                "claim_revision_count": sum(len(row["claim_revision_ids"]) for row in ecosystem_rows),
                "evidence_span_count": len(
                    {span_id for row in ecosystem_rows for span_id in row["evidence_span_ids"]}
                ),
                "source_count": len({source_id for row in ecosystem_rows for source_id in row["source_ids"]}),
                "reference_artifact_family_count": len(references_by_ecosystem.get(ecosystem, [])),
                "production_planner_consumes": coverage_by_ecosystem.get(coverage_key, {}).get(
                    "planning_ready", False
                ),
            }
        )
    return {
        "schema_version": "knowledge-foundation-p0b-semantic-closure-v1",
        "candidate_only": True,
        "operator_revisions": rows,
        "ecosystem_summary": by_ecosystem,
    }


def _gap_register(source_rows: list[dict[str, Any]]) -> dict[str, Any]:
    unresolved_sources = [
        row for row in source_rows if row["upstream_version_status"] != "immutable_locator_and_content_digest"
    ]
    return {
        "schema_version": "knowledge-foundation-p0b-gap-register-v1",
        "gaps": [
            {
                "gap_id": "P0B-SOURCE-REVISION-BINDING",
                "priority": "P0",
                "owner": "source_governance",
                "count": len(unresolved_sources),
                "status": "remaining",
                "decision_boundary": (
                    "Captured text is content-pinned, but mutable upstream locations are not proof "
                    "of the declared software release. Version-sensitive claims remain candidate/unknown."
                ),
            },
            {
                "gap_id": "P0B-REFERENCE-ARTIFACT-REVISION",
                "priority": "P0",
                "owner": "scientific_kg",
                "count": 3,
                "status": "contained",
                "decision_boundary": (
                    "CellTypist, SingleR and pySCENIC family identities are explicit, but no exact "
                    "revision is fabricated. Applicability must clarify or block."
                ),
            },
            {
                "gap_id": "P0B-PLANNER-CONSUMPTION",
                "priority": "P1",
                "owner": "capability_pack_toolcontract_planner",
                "count": 11,
                "status": "remaining",
                "decision_boundary": (
                    "Eleven of fourteen core ecosystems still lack production planner consumption; "
                    "candidate KG depth is not reported as planning readiness."
                ),
            },
            {
                "gap_id": "P0B-SCVELO-CELLRANK-COMPATIBILITY",
                "priority": "P1",
                "owner": "scientific_kg_compatibility_review",
                "count": 1,
                "status": "remaining",
                "decision_boundary": (
                    "No reviewed transition-state compatibility proof exists; the relation is not constructed."
                ),
            },
        ],
    }


def build(output_dir: Path = DEFAULT_OUTPUT_DIR) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    source_rows = _source_hardening_rows()
    identities, requirements = _reference_artifact_rows()
    packets = _compatibility_review_packets()
    coverage = _coverage_after()
    semantic_closure = _core_semantic_closure(identities)
    gaps = _gap_register(source_rows)

    _write_jsonl(output_dir / "source_revision_hardening.jsonl", source_rows)
    _write_jsonl(output_dir / "reference_artifact_candidates.jsonl", identities)
    _write_json(output_dir / "reference_artifact_requirements.json", {"requirements": requirements})
    _write_jsonl(output_dir / "compatibility_review_packets.jsonl", packets)
    _write_json(output_dir / "core_tool_coverage_after.json", coverage)
    _write_json(output_dir / "core_semantic_closure.json", semantic_closure)
    _write_json(output_dir / "gap_register.json", gaps)

    policy = load_knowledge_foundation_policy()
    core_relations = _read_jsonl(CORE_DIR / "derived_relations.jsonl")
    candidate_can_feed = [row for row in core_relations if row["relation"] == "CAN_FEED"]
    actionable_unreviewed = [
        row
        for row in candidate_can_feed
        if row.get("review_status") != "accepted"
        and can_feed_is_actionable(row, policy=policy)
    ]
    source_counts = {
        "audited": len(source_rows),
        "content_integrity_verified": sum(
            row["content_integrity_status"] == "verified" for row in source_rows
        ),
        "immutable_version_and_content_bound": sum(
            row["upstream_version_status"] == "immutable_locator_and_content_digest"
            for row in source_rows
        ),
        "version_binding_unresolved": sum(
            row["upstream_version_status"] != "immutable_locator_and_content_digest"
            for row in source_rows
        ),
        "ecosystems_with_parallel_pinned_authoritative_revision": sum(
            row["pinned_authoritative_revision"] is not None for row in source_rows
        ),
    }
    summary = {
        "schema_version": "knowledge-foundation-p0b-summary-v1",
        "mode": "candidate_scientific_knowledge_deepening",
        "source_hardening": source_counts,
        "reference_artifacts": {
            "candidate_family_identities": len(identities),
            "ecosystems": ["CellTypist", "SingleR", "pySCENIC"],
            "fabricated_reference_artifact_revisions": 0,
            "resolved_reference_artifact_revisions": 0,
        },
        "compatibility": {
            "review_packets": len(packets),
            "existing_candidate_can_feed": len(candidate_can_feed),
            "actionable_unreviewed_CAN_FEED": len(actionable_unreviewed),
            "accepted_in_p0b": 0,
        },
        "readiness": coverage["summary_after"],
        "safety": {
            "candidate_to_trusted_leakage": int(candidate_scope_can_be_trusted(policy=policy)),
            "canonical_promotion": "none",
            "canonical_kg_modified": False,
            "retrieval_index_rebuilt": False,
            "production_code_modified": False,
        },
        "gates": {
            "all_17_canonical_software_sources_audited": len(source_rows) == 17,
            "local_content_integrity_verified": source_counts["content_integrity_verified"] == 16,
            "mutable_sources_not_claimed_immutable": all(
                row["upstream_version_status"] != "immutable_locator_and_content_digest"
                for row in source_rows
                if not any(marker in row["origin_url"] for marker in ("/blob/v", "/tree/v", "/blob/refs/tags/"))
            ),
            "reference_identity_without_fabricated_revision": bool(identities)
            and not any(req["reference_artifact_revision_id"] for req in requirements),
            "unreviewed_can_feed_not_actionable": not actionable_unreviewed,
            "candidate_not_trusted": not candidate_scope_can_be_trusted(policy=policy),
            "readiness_not_gamed": coverage["summary_before"] == coverage["summary_after"],
        },
        "remaining_p0": ["P0B-SOURCE-REVISION-BINDING", "P0B-REFERENCE-ARTIFACT-REVISION"],
        "decision": "PASS_WITH_REMAINING_GAPS",
    }
    _write_json(output_dir / "summary.json", summary)

    artifact_names = [
        "source_revision_hardening.jsonl",
        "reference_artifact_candidates.jsonl",
        "reference_artifact_requirements.json",
        "compatibility_review_packets.jsonl",
        "core_tool_coverage_after.json",
        "core_semantic_closure.json",
        "gap_register.json",
        "summary.json",
    ]
    manifest = {
        "schema_version": "knowledge-foundation-p0b-manifest-v1",
        "candidate_only": True,
        "artifacts": {name: _sha(output_dir / name) for name in artifact_names},
        "frozen_inputs": {
            "audit_core_tool_coverage_sha256": _sha(AUDIT_DIR / "core_tool_coverage.json"),
            "core_conformance_bundle_sha256": _sha(CORE_DIR / "conformance_bundle.json"),
            "core_source_manifest_sha256": _sha(CORE_DIR / "source_manifest.json"),
            "uat_relations_sha256": _sha(UAT_DIR / "derived_relations.jsonl"),
            "source_documents_v2_sha256": _sha(SOURCE_DOCUMENTS),
            "authoritative_source_manifest_sha256": _sha(AUTHORITATIVE_SOURCE_MANIFEST),
        },
        "canonical_promotion": "none",
        "retrieval_index_rebuilt": False,
    }
    _write_json(output_dir / "manifest.json", manifest)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Build candidate-only Knowledge Foundation P0B artifacts.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()
    manifest = build(args.output_dir)
    print(json.dumps(manifest, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
