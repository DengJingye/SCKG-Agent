from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

from core.knowledge_intelligence_models import HybridRetrievalRequest
from core.scientific_knowledge_conformance_models import (
    ApplicabilityScope,
    AtomicClaimRevision,
    ConformanceBundle,
    EvidenceAssessment,
    Package,
    PackageRelease,
    SoftwareProject,
)
from core.trace_context import TraceCollector, TraceContext, TraceKind, TraceStage
from engine.evidence_discovery_index import EvidenceChunk, write_indexes
from engine.hybrid_retrieval import HybridRetrievalService


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CP5_ROOT = (
    PROJECT_ROOT / "data" / "evaluation" / "evidence_gap_acquisition_pilot_v1_repaired"
)
DEFAULT_OUTPUT_ROOT = (
    PROJECT_ROOT / "data" / "evaluation" / "candidate_knowledge_deposition_pilot_v1"
)
CORE_BUNDLE = (
    PROJECT_ROOT
    / "data"
    / "evidence_candidates"
    / "scientific_kg_v1_core"
    / "conformance_bundle.json"
)
CORE_CANDIDATE_ROOT = PROJECT_ROOT / "data" / "evidence_candidates"

SCHEMA_VERSION = "sckg-candidate-knowledge-deposition-pilot-v1"
GAP_ID = "evidence-gap:v1-core:soupx:droplet-profile"
SOURCE_WORK_ID = "source-work:soupx:official-manual"
SOURCE_REVISION_ID = "source-revision:soupx:official-manual:1.6.2"
SOURCE_ARTIFACT_SHA256 = "dabbfdf10c0ab46efee927026f77494e1df096999742f86705b91dcd0b1dac19"
SOURCE_ARTIFACT_ID = f"source-artifact:sha256:{SOURCE_ARTIFACT_SHA256}"
EVIDENCE_SPAN_ID = "evidence-span:cp5:soupx:soupchannel-inputs:1.6.2"
EVIDENCE_SPAN_SHA256 = "d56762056291c5c96519ff9eec38ca5345e1ad88e5ed4bf823f79181b0a558df"
SUBJECT_ID = "package-release:soupx:1.6.2"
SCOPE_ID = "scope:cp6:soupx:soupchannel:1.6.2"
PREDICATE = "defines_input_table_semantics"
CLAIM_TEXT = (
    "In SoupX 1.6.2, SoupChannel defines tod as a genes-by-droplets droplet table "
    "and toc as the count table containing only tod columns corresponding to droplets with cells."
)
CLAIM_OBJECT = (
    "SoupChannel tod is a genes-by-droplets droplet table; toc contains the tod columns "
    "corresponding to droplets with cells."
)
SECOND_QUERY = "In SoupX SoupChannel, what do the tod and toc input tables contain?"
FORBIDDEN_BROADENING = (
    "universal raw-count",
    "capture compatibility",
    "preprocessing",
    "pipeline ordering",
    "quality-control threshold",
)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(_canonical_json(row) + "\n" for row in rows),
        encoding="utf-8",
    )


def architecture_inventory() -> list[dict[str, str]]:
    return [
        {
            "capability": "AtomicClaimRevision and EvidenceAssessment",
            "existing_implementation": "core.scientific_knowledge_conformance_models",
            "disposition": "reused_as_is",
        },
        {
            "capability": "candidate knowledge overlay",
            "existing_implementation": "Scientific KG v1.1 candidate JSONL/conformance bundle artifacts",
            "disposition": "thin_deposition_adapter",
        },
        {
            "capability": "evidence indexing and retrieval",
            "existing_implementation": "EvidenceChunk + HybridRetrievalService local FTS5 pipeline",
            "disposition": "reused_with_isolated_index_paths",
        },
        {
            "capability": "source identity and acquisition deduplication",
            "existing_implementation": "CP5 SourceWork/SourceRevision/SourceArtifact registry",
            "disposition": "read_only_reuse",
        },
        {
            "capability": "governed audit trail",
            "existing_implementation": "core.trace_context",
            "disposition": "reused_as_is",
        },
        {
            "capability": "automatic candidate promotion",
            "existing_implementation": "intentionally absent",
            "disposition": "not_allowed",
        },
    ]


def load_cp5_evidence(cp5_root: Path = DEFAULT_CP5_ROOT) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    registry = json.loads((cp5_root / "source_registry.json").read_text(encoding="utf-8"))
    span = json.loads((cp5_root / "evidence_span.json").read_text(encoding="utf-8"))
    works = registry.get("source_works", [])
    revisions = registry.get("source_revisions", [])
    artifacts = registry.get("source_artifacts", [])
    if [row.get("source_work_id") for row in works] != [SOURCE_WORK_ID]:
        raise ValueError("source_work_identity_drift")
    if [row.get("source_revision_id") for row in revisions] != [SOURCE_REVISION_ID]:
        raise ValueError("source_revision_identity_drift")
    if [row.get("source_artifact_id") for row in artifacts] != [SOURCE_ARTIFACT_ID]:
        raise ValueError("source_artifact_identity_drift")
    artifact = artifacts[0]
    if artifact.get("sha256") != SOURCE_ARTIFACT_SHA256:
        raise ValueError("source_artifact_hash_drift")
    artifact_path = cp5_root / artifact["local_path"]
    text_path = cp5_root / artifact["extracted_text_path"]
    if _sha_file(artifact_path) != SOURCE_ARTIFACT_SHA256:
        raise ValueError("source_artifact_integrity_failed")
    if _sha_file(text_path) != artifact.get("extracted_text_sha256"):
        raise ValueError("source_text_integrity_failed")
    if span.get("evidence_span_id") != EVIDENCE_SPAN_ID:
        raise ValueError("evidence_span_identity_drift")
    if span.get("content_hash") != EVIDENCE_SPAN_SHA256:
        raise ValueError("evidence_span_hash_drift")
    if _sha_text(span.get("exact_text", "")) != EVIDENCE_SPAN_SHA256:
        raise ValueError("evidence_span_integrity_failed")
    if span.get("source_artifact_id") != SOURCE_ARTIFACT_ID:
        raise ValueError("evidence_span_artifact_binding_drift")
    return registry, artifact, span


def _core_identity_slice() -> tuple[list[Any], ApplicabilityScope]:
    payload = json.loads(CORE_BUNDLE.read_text(encoding="utf-8"))
    by_entity = {row["entity_id"]: row for row in payload["entities"]}
    project = SoftwareProject.model_validate(by_entity["software-project:soupx"])
    package = Package.model_validate(by_entity["package:soupx"])
    release = PackageRelease.model_validate(by_entity[SUBJECT_ID])
    scope = ApplicabilityScope.model_validate(
        {
            "scope_id": SCOPE_ID,
            "version_constraints": [
                {"subject_id": SUBJECT_ID, "status": "exact", "expression": "1.6.2"}
            ],
            "scope_status": "explicit",
        }
    )
    return [project, package, release], scope


def build_candidate_records() -> tuple[AtomicClaimRevision, EvidenceAssessment]:
    fingerprint = _sha_text(
        _canonical_json(
            {
                "subject_id": SUBJECT_ID,
                "predicate": PREDICATE,
                "object_value": CLAIM_OBJECT,
                "scope_id": SCOPE_ID,
                "polarity": "positive",
            }
        )
    )
    suffix = fingerprint[:16]
    claim = AtomicClaimRevision(
        claim_id=f"claim:cp6:{suffix}",
        claim_revision_id=f"claim-revision:cp6:{suffix}:1",
        subject_id=SUBJECT_ID,
        predicate=PREDICATE,
        object_value=CLAIM_OBJECT,
        scope_id=SCOPE_ID,
        claim_text=CLAIM_TEXT,
        polarity="positive",
        assertion_kind="definition",
        semantic_fingerprint=fingerprint,
        content_hash=_sha_text(CLAIM_TEXT),
        created_by_activity_id="activity:cp6-candidate-knowledge-deposition-pilot-v1",
    )
    assessment = EvidenceAssessment(
        assessment_id=f"evidence-assessment:cp6:{suffix}",
        claim_revision_id=claim.claim_revision_id,
        evidence_span_ids=[EVIDENCE_SPAN_ID],
        stance="supports",
        subject_aligned=True,
        predicate_aligned=True,
        object_aligned=True,
        scope_alignment="aligned",
        rationale=(
            "The exact version-pinned SoupChannel argument span directly defines tod and toc; "
            "it does not support broader raw-count, preprocessing, or workflow-order claims."
        ),
    )
    return claim, assessment


def _all_existing_claim_rows(*, exclude: Path | None = None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(CORE_CANDIDATE_ROOT.glob("**/atomic_claims.jsonl")):
        if exclude is not None and path.resolve() == exclude.resolve():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
    return rows


def inspect_existing_knowledge(claim: AtomicClaimRevision, *, output_root: Path) -> dict[str, Any]:
    overlay_path = output_root / "candidate_atomic_claims.jsonl"
    candidate_rows = _all_existing_claim_rows(exclude=overlay_path)
    canonical_nodes = []
    canonical_path = PROJECT_ROOT / "data" / "knowledge_graph_v2" / "nodes.jsonl"
    if canonical_path.is_file():
        canonical_nodes = [
            json.loads(line)
            for line in canonical_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    equivalent = [
        row
        for row in candidate_rows
        if row.get("semantic_fingerprint") == claim.semantic_fingerprint
    ]
    conflicting = [
        row
        for row in candidate_rows
        if row.get("subject_id") == claim.subject_id
        and row.get("predicate") == claim.predicate
        and row.get("scope_id") == claim.scope_id
        and row.get("semantic_fingerprint") != claim.semantic_fingerprint
    ]
    canonical_equivalent = [
        row
        for row in canonical_nodes
        if row.get("semantic_fingerprint") == claim.semantic_fingerprint
        or row.get("claim_revision_id") == claim.claim_revision_id
    ]
    return {
        "candidate_equivalent_count": len(equivalent),
        "canonical_equivalent_count": len(canonical_equivalent),
        "conflicting_candidate_claim_revision_ids": [
            row.get("claim_revision_id") for row in conflicting
        ],
    }


def _candidate_graph(
    claim: AtomicClaimRevision,
    assessment: EvidenceAssessment,
    *,
    artifact: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "knowledge_status": "candidate_pending_review",
        "nodes": [
            {"id": claim.claim_revision_id, "type": "AtomicClaimRevision"},
            {"id": assessment.assessment_id, "type": "EvidenceAssessment"},
            {"id": SUBJECT_ID, "type": "PackageRelease"},
            {"id": EVIDENCE_SPAN_ID, "type": "EvidenceSpan"},
            {"id": SOURCE_ARTIFACT_ID, "type": "SourceArtifact", "sha256": artifact["sha256"]},
            {"id": SOURCE_REVISION_ID, "type": "SourceRevision"},
            {"id": SOURCE_WORK_ID, "type": "SourceWork"},
        ],
        "edges": [
            {"source": claim.claim_revision_id, "relation": "SUBJECT", "target": SUBJECT_ID},
            {"source": assessment.assessment_id, "relation": "ASSESSES", "target": claim.claim_revision_id},
            {"source": EVIDENCE_SPAN_ID, "relation": "SUPPORTS", "target": claim.claim_revision_id},
            {"source": EVIDENCE_SPAN_ID, "relation": "EXTRACTED_FROM", "target": SOURCE_ARTIFACT_ID},
            {"source": SOURCE_ARTIFACT_ID, "relation": "ARTIFACT_OF", "target": SOURCE_REVISION_ID},
            {"source": SOURCE_REVISION_ID, "relation": "REVISION_OF", "target": SOURCE_WORK_ID},
        ],
        "forbidden_derived_relations_created": [],
    }


def _build_rag_index(
    *, output_root: Path, claim: AtomicClaimRevision, span: dict[str, Any]
) -> tuple[HybridRetrievalService, dict[str, Any]]:
    index_dir = output_root / "rag_index"
    chunks_path = index_dir / "evidence_chunks.jsonl"
    vectors_path = index_dir / "evidence_vectors.jsonl"
    chunk = EvidenceChunk(
        chunk_id="source:cp6:soupx:soupchannel-inputs:1.6.2",
        evidence_id=EVIDENCE_SPAN_ID,
        source_id=SOURCE_REVISION_ID,
        source_document_id=SOURCE_REVISION_ID,
        source_type="official_package_manual",
        source_span="PDF page 24; SoupChannel; Arguments: tod and toc",
        source_kind="source_document",
        source_table="cp5_acquired_source",
        source_record_id=EVIDENCE_SPAN_ID,
        tool_name="SoupX",
        tool_names=["SoupX", "SoupChannel"],
        canonical_task="ambient_rna_removal",
        task="ambient_rna_removal",
        task_tags=["ambient_rna_removal"],
        title="SoupX 1.6.2 SoupChannel input tables",
        claim_text=claim.claim_text,
        claim_span=span["exact_text"],
        chunk_text=span["exact_text"],
        claim_type="input_requirement",
        content_hash=span["content_hash"],
        source_bound=True,
        review_status="candidate_pending_review",
        trust_level="source_bound_candidate",
        graph_layer="candidate",
        recommendation_eligible="false",
        authority_tier="official",
        retrieval_status="retrieval_only",
        claim_boundary="Candidate evidence retrieval only; cannot authorize execution or promote knowledge.",
        use_for=["retrieval", "candidate_evidence"],
        kg_version="v1.1-candidate",
    )
    index_report = write_indexes(
        [chunk], chunks_path=chunks_path, vectors_path=vectors_path, with_embeddings=False
    )
    service = HybridRetrievalService(
        evidence_chunks_path=chunks_path,
        catalog_chunks_path=index_dir / "catalog_chunks.jsonl",
        fts_index_path=index_dir / "evidence_fts5.sqlite",
        index_manifest_path=index_dir / "evidence_index_manifest.json",
        coverage_path=index_dir / "retrieval_coverage_v2.json",
        dense_matrix_path=index_dir / "evidence_vectors.npy",
        dense_metadata_path=index_dir / "evidence_vector_metadata.json",
        graph_dir=index_dir / "absent_graph",
    )
    return service, index_report


def _record_stage(
    instrumentation: Any,
    audit: list[dict[str, Any]],
    *,
    stage: TraceStage,
    operation: str,
    input_ref: tuple[str, str] | None,
    output_ref: tuple[str, str],
    decision: tuple[str, str, str] | None = None,
    reused: bool = False,
) -> None:
    refs = []
    if input_ref:
        refs.append({"record_type": input_ref[0], "record_id": input_ref[1], "relation": "input"})
    with instrumentation.span(
        stage=stage,
        component="candidate_knowledge_deposition",
        operation=operation,
        input_refs=refs,
    ) as span:
        span.add_output_ref(record_type=output_ref[0], record_id=output_ref[1], relation="produced")
        span.set_counter("reused", 1 if reused else 0)
        if decision:
            span.add_decision(
                decision_type=decision[0],
                outcome=decision[1],
                reason_code=decision[2],
                rule_version="cp6_candidate_deposition_v1",
                record_ref={
                    "record_type": output_ref[0],
                    "record_id": output_ref[1],
                    "relation": "decision_subject",
                },
            )
    audit.append(
        {
            "stage": stage.value,
            "operation": operation,
            "input_ref": list(input_ref) if input_ref else None,
            "output_ref": list(output_ref),
            "reused": reused,
        }
    )


def run_pilot(
    *, output_root: Path = DEFAULT_OUTPUT_ROOT, cp5_root: Path = DEFAULT_CP5_ROOT
) -> dict[str, Any]:
    output_root = output_root.resolve()
    if (output_root / "summary.json").exists():
        raise FileExistsError("candidate_deposition_pilot_already_completed")
    registry, artifact, span = load_cp5_evidence(cp5_root)
    claim, assessment = build_candidate_records()
    existing = inspect_existing_knowledge(claim, output_root=output_root)
    if existing["candidate_equivalent_count"] or existing["canonical_equivalent_count"]:
        raise ValueError("equivalent_knowledge_already_exists")

    entities, scope = _core_identity_slice()
    bundle = ConformanceBundle(
        fixture_id="conformance-fixture:cp6-candidate-knowledge-deposition",
        description="Candidate-only SoupX 1.6.2 SoupChannel input-table semantics overlay.",
        scopes=[scope],
        entities=entities,
        atomic_claims=[claim],
        evidence_assessments=[assessment],
        expected_semantics=[
            "The exact CP5 span supports only tod/toc table semantics.",
            "Candidate knowledge cannot authorize execution or imply canonical promotion.",
        ],
    )

    audit: list[dict[str, Any]] = []
    trace_path = output_root / "trace.jsonl"
    trace = TraceContext.new_request(
        trace_kind=TraceKind.RESEARCH,
        request_id="cp6-soupx-candidate-deposition",
        conversation_id="cp6-governed-self-deposition-pilot",
    )
    instrumentation = trace.instrumentation()
    with TraceCollector(trace_path).request_scope(trace):
        _record_stage(
            instrumentation,
            audit,
            stage=TraceStage.STATE_INSPECTION,
            operation="inspect_existing_candidate_knowledge",
            input_ref=("EvidenceGap", GAP_ID),
            output_ref=("EvidenceGap", GAP_ID),
        )
        _record_stage(
            instrumentation,
            audit,
            stage=TraceStage.RETRIEVAL,
            operation="reuse_acquired_evidence_span",
            input_ref=("SourceArtifact", SOURCE_ARTIFACT_ID),
            output_ref=("EvidenceSpan", EVIDENCE_SPAN_ID),
            reused=True,
        )
        _record_stage(
            instrumentation,
            audit,
            stage=TraceStage.DECISION,
            operation="assess_exact_span_support",
            input_ref=("EvidenceSpan", EVIDENCE_SPAN_ID),
            output_ref=("EvidenceAssessment", assessment.assessment_id),
            decision=("evidence_support", "supports", "exact_bounded_span_support"),
        )
        _record_stage(
            instrumentation,
            audit,
            stage=TraceStage.VALIDATION,
            operation="validate_atomic_claim_revision",
            input_ref=("EvidenceAssessment", assessment.assessment_id),
            output_ref=("AtomicClaimRevision", claim.claim_revision_id),
            decision=("candidate_validation", "allow", "schema_and_binding_valid"),
        )

        output_root.mkdir(parents=True, exist_ok=True)
        _write_json(output_root / "architecture_inventory.json", architecture_inventory())
        _write_json(output_root / "conformance_bundle.json", bundle.model_dump(mode="json"))
        _write_jsonl(output_root / "candidate_atomic_claims.jsonl", [claim.model_dump(mode="json")])
        _write_jsonl(output_root / "evidence_assessments.jsonl", [assessment.model_dump(mode="json")])
        _write_jsonl(output_root / "evidence_spans.jsonl", [span])
        _write_json(output_root / "candidate_overlay_graph.json", _candidate_graph(claim, assessment, artifact=artifact))
        _write_json(
            output_root / "provenance.json",
            {
                "schema_version": SCHEMA_VERSION,
                "claim_revision_id": claim.claim_revision_id,
                "software_context_id": SUBJECT_ID,
                "evidence_assessment_id": assessment.assessment_id,
                "evidence_span_id": EVIDENCE_SPAN_ID,
                "source_artifact_id": SOURCE_ARTIFACT_ID,
                "source_artifact_sha256": SOURCE_ARTIFACT_SHA256,
                "source_revision_id": SOURCE_REVISION_ID,
                "source_work_id": SOURCE_WORK_ID,
                "derivation_activity_id": claim.created_by_activity_id,
            },
        )
        _write_jsonl(
            output_root / "risk_registry.jsonl",
            [
                {
                    "record_id": claim.claim_revision_id,
                    "record_type": "AtomicClaimRevision",
                    "risk_class": "R3",
                    "review_requirement": "qualified_human",
                    "review_status": "candidate_pending_review",
                }
            ],
        )
        _write_json(
            output_root / "evidence_gap_lifecycle.json",
            {
                "gap_id": GAP_ID,
                "current_status": "pending_review",
                "canonical_resolution_status": "unresolved",
                "events": [
                    "unresolved",
                    "evidence_acquired",
                    "candidate_knowledge_created",
                    "pending_review",
                ],
                "candidate_claim_revision_id": claim.claim_revision_id,
            },
        )
        _record_stage(
            instrumentation,
            audit,
            stage=TraceStage.DECISION,
            operation="deposit_candidate_overlay",
            input_ref=("AtomicClaimRevision", claim.claim_revision_id),
            output_ref=("CandidateKnowledge", claim.claim_revision_id),
            decision=("knowledge_status", "candidate", "candidate_pending_review"),
        )

        service, index_report = _build_rag_index(output_root=output_root, claim=claim, span=span)
        _record_stage(
            instrumentation,
            audit,
            stage=TraceStage.RETRIEVAL,
            operation="index_candidate_evidence",
            input_ref=("EvidenceSpan", EVIDENCE_SPAN_ID),
            output_ref=("RAGIndex", service.index_build_id),
        )

        query_result = service.search(
            HybridRetrievalRequest(
                query=SECOND_QUERY,
                tool_names=["SoupX"],
                claim_types=["input_requirement"],
                top_k=3,
                enable_dense=False,
                use_kg=False,
                use_governance_rerank=True,
                use_contract_gate=False,
                include_catalog=False,
            )
        )
        matching_hits = [hit for hit in query_result.hits if hit.chunk_id == "source:cp6:soupx:soupchannel-inputs:1.6.2"]
        if len(matching_hits) != 1:
            raise ValueError("deposited_evidence_not_retrieved")
        deposited_rows = [
            json.loads(line)
            for line in (output_root / "candidate_atomic_claims.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        reused_claims = [row for row in deposited_rows if row.get("semantic_fingerprint") == claim.semantic_fingerprint]
        if len(reused_claims) != 1:
            raise ValueError("candidate_claim_reuse_failed")
        _record_stage(
            instrumentation,
            audit,
            stage=TraceStage.RETRIEVAL,
            operation="reuse_candidate_for_second_query",
            input_ref=("RAGIndex", service.index_build_id),
            output_ref=("AtomicClaimRevision", claim.claim_revision_id),
            decision=("knowledge_reuse", "candidate", "existing_candidate_reused"),
            reused=True,
        )
        _record_stage(
            instrumentation,
            audit,
            stage=TraceStage.VALIDATION,
            operation="verify_candidate_governance_boundary",
            input_ref=("AtomicClaimRevision", claim.claim_revision_id),
            output_ref=("EvidenceGap", GAP_ID),
            decision=("promotion_boundary", "blocked", "human_review_required"),
        )

    second_query = {
        "query": SECOND_QUERY,
        "candidate_claim_revision_id": claim.claim_revision_id,
        "candidate_claim_reused": True,
        "candidate_knowledge_status": "candidate_pending_review",
        "evidence_span_id": EVIDENCE_SPAN_ID,
        "evidence_span_reused": True,
        "source_artifact_id": SOURCE_ARTIFACT_ID,
        "source_artifact_reused": True,
        "retrieved_chunk_ids": [hit.chunk_id for hit in query_result.hits],
        "retrieved_source_ids": [hit.source_id for hit in query_result.hits],
        "external_reacquisition_count": 0,
        "answer_projection": {
            "claim_text": claim.claim_text,
            "knowledge_status": "candidate_pending_review",
            "evidence_span_ids": [EVIDENCE_SPAN_ID],
            "source_revision_id": SOURCE_REVISION_ID,
        },
    }
    _write_json(output_root / "second_query_result.json", second_query)
    source_counts = {
        "source_work_count": len(registry["source_works"]),
        "source_revision_count": len(registry["source_revisions"]),
        "source_artifact_count": len(registry["source_artifacts"]),
        "evidence_span_count": 1,
        "candidate_claim_count": 1,
        "evidence_assessment_count": 1,
    }
    summary = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "candidate_proposition": claim.claim_text,
        "claim_revision_id": claim.claim_revision_id,
        "evidence_assessment_id": assessment.assessment_id,
        "knowledge_status": "candidate_pending_review",
        "candidate_kg_deposited": True,
        "rag_deposited": True,
        "second_query_reused": True,
        "external_reacquisition_count": 0,
        "dedup_counts": source_counts,
        "existing_knowledge_inspection": existing,
        "conflicts_preserved": existing["conflicting_candidate_claim_revision_ids"],
        "derived_relation_count": 0,
        "review_decision_count": 0,
        "canonical_promotion_performed": False,
        "canonical_kg_modified": False,
        "planner_modified": False,
        "execution_authorized": False,
        "forbidden_broadening_present": any(term in claim.claim_text.casefold() for term in FORBIDDEN_BROADENING),
        "rag_index": {**index_report, "build_id": service.index_build_id},
        "trace_path": "trace.jsonl",
        "audit_path": audit,
    }
    _write_json(output_root / "summary.json", summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the bounded CP6 candidate-knowledge deposition pilot.")
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--cp5-root", type=Path, default=DEFAULT_CP5_ROOT)
    args = parser.parse_args()
    print(_canonical_json(run_pilot(output_root=args.output_root, cp5_root=args.cp5_root)))


if __name__ == "__main__":
    main()
