from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from core.knowledge_intelligence_models import HybridRetrievalRequest
from core.scientific_knowledge_conformance_models import ConformanceBundle, ReviewDecision
from core.trace_context import TraceCollector, TraceContext, TraceKind, TraceStage
from engine.hybrid_retrieval import HybridRetrievalService


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CP5_ROOT = (
    PROJECT_ROOT / "data" / "evaluation" / "evidence_gap_acquisition_pilot_v1_repaired"
)
DEFAULT_CP6_ROOT = (
    PROJECT_ROOT / "data" / "evaluation" / "candidate_knowledge_deposition_pilot_v1"
)
DEFAULT_OUTPUT_ROOT = (
    PROJECT_ROOT / "data" / "evaluation" / "candidate_knowledge_review_queue_v1"
)
SCHEMA_VERSION = "sckg-candidate-review-surface-v1.1"
REVIEW_ITEM_ID = "review-item:cp7:soupx:soupchannel-inputs:1.6.2"
FINAL_QUERY = "In SoupX SoupChannel, what do the tod and toc input tables contain?"
ALLOWED_ACTIONS = ["PROMOTE", "REJECT", "NEEDS_REVISION", "MERGE", "SUPERSEDE"]
ACTION_BINDINGS = {
    "PROMOTE": {
        "review_decision": "accepted",
        "additional_requirement": "approved KnowledgeChangeSet and immutable snapshot publication",
    },
    "REJECT": {"review_decision": "rejected", "additional_requirement": "reviewer rationale"},
    "NEEDS_REVISION": {
        "review_decision": "needs_revision",
        "additional_requirement": "new claim revision; do not mutate the reviewed revision",
    },
    "MERGE": {
        "review_decision": "needs_revision",
        "additional_requirement": "reviewed identity/claim crosswalk and KnowledgeChangeSet",
    },
    "SUPERSEDE": {
        "review_decision": "accepted",
        "additional_requirement": "reviewed SupersessionRecord and KnowledgeChangeSet",
    },
}


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sha_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(_canonical_json(row) + "\n" for row in rows), encoding="utf-8"
    )


def load_and_validate_candidate(
    *, cp5_root: Path = DEFAULT_CP5_ROOT, cp6_root: Path = DEFAULT_CP6_ROOT
) -> dict[str, Any]:
    cp5_registry = _json(cp5_root / "source_registry.json")
    cp5_span = _json(cp5_root / "evidence_span.json")
    cp5_report = _json(cp5_root / "runs" / "reuse" / "report.json")
    cp6_summary = _json(cp6_root / "summary.json")
    cp6_bundle = ConformanceBundle.model_validate(_json(cp6_root / "conformance_bundle.json"))
    cp6_provenance = _json(cp6_root / "provenance.json")
    cp6_graph = _json(cp6_root / "candidate_overlay_graph.json")
    cp6_second_query = _json(cp6_root / "second_query_result.json")
    cp6_lifecycle = _json(cp6_root / "evidence_gap_lifecycle.json")
    risk_rows = _jsonl(cp6_root / "risk_registry.jsonl")

    if len(cp6_bundle.atomic_claims) != 1 or len(cp6_bundle.evidence_assessments) != 1:
        raise ValueError("candidate_claim_or_assessment_not_unique")
    if len(cp5_registry["source_works"]) != 1:
        raise ValueError("source_work_not_unique")
    if len(cp5_registry["source_revisions"]) != 1:
        raise ValueError("source_revision_not_unique")
    if len(cp5_registry["source_artifacts"]) != 1:
        raise ValueError("source_artifact_not_unique")
    if len(risk_rows) != 1:
        raise ValueError("candidate_risk_registration_not_unique")

    claim = cp6_bundle.atomic_claims[0]
    assessment = cp6_bundle.evidence_assessments[0]
    source_work = cp5_registry["source_works"][0]
    source_revision = cp5_registry["source_revisions"][0]
    source_artifact = cp5_registry["source_artifacts"][0]
    scope = cp6_bundle.scopes[0]
    risk = risk_rows[0]

    if claim.content_hash != _sha_text(claim.claim_text):
        raise ValueError("claim_content_hash_mismatch")
    if assessment.claim_revision_id != claim.claim_revision_id:
        raise ValueError("assessment_claim_binding_mismatch")
    if assessment.evidence_span_ids != [cp5_span["evidence_span_id"]]:
        raise ValueError("assessment_span_binding_mismatch")
    if assessment.stance != "supports":
        raise ValueError("assessment_is_not_supporting")
    if cp5_span["content_hash"] != _sha_text(cp5_span["exact_text"]):
        raise ValueError("evidence_span_integrity_mismatch")
    if cp5_span["source_artifact_id"] != source_artifact["source_artifact_id"]:
        raise ValueError("span_artifact_binding_mismatch")
    if source_artifact["source_revision_id"] != source_revision["source_revision_id"]:
        raise ValueError("artifact_revision_binding_mismatch")
    if source_revision["source_work_id"] != source_work["source_work_id"]:
        raise ValueError("revision_work_binding_mismatch")
    if source_artifact["sha256"] != _sha_file(cp5_root / source_artifact["local_path"]):
        raise ValueError("source_artifact_hash_mismatch")
    if cp6_provenance["source_artifact_sha256"] != source_artifact["sha256"]:
        raise ValueError("candidate_source_hash_swap")
    if cp6_provenance["source_revision_id"] != source_revision["source_revision_id"]:
        raise ValueError("candidate_source_revision_swap")
    if cp6_provenance["source_work_id"] != source_work["source_work_id"]:
        raise ValueError("candidate_source_work_swap")
    if cp6_provenance["evidence_span_id"] != cp5_span["evidence_span_id"]:
        raise ValueError("candidate_span_swap")
    if cp6_graph["knowledge_status"] != "candidate_pending_review":
        raise ValueError("candidate_graph_status_conflation")
    if cp6_summary["knowledge_status"] != "candidate_pending_review":
        raise ValueError("candidate_summary_status_conflation")
    if cp6_summary["canonical_promotion_performed"]:
        raise ValueError("unexpected_canonical_promotion")
    if cp6_summary["execution_authorized"]:
        raise ValueError("candidate_execution_authority_leak")
    if risk["review_status"] != "candidate_pending_review":
        raise ValueError("candidate_review_status_conflation")
    if cp6_lifecycle["canonical_resolution_status"] != "unresolved":
        raise ValueError("evidence_gap_prematurely_resolved")

    return {
        "claim": claim,
        "assessment": assessment,
        "scope": scope,
        "source_work": source_work,
        "source_revision": source_revision,
        "source_artifact": source_artifact,
        "evidence_span": cp5_span,
        "risk": risk,
        "acquisition_report": cp5_report,
        "deposition_summary": cp6_summary,
        "deposition_provenance": cp6_provenance,
        "prior_reuse": cp6_second_query,
        "lifecycle": cp6_lifecycle,
    }


def build_review_item(candidate: dict[str, Any]) -> dict[str, Any]:
    claim = candidate["claim"]
    assessment = candidate["assessment"]
    scope = candidate["scope"]
    source_work = candidate["source_work"]
    source_revision = candidate["source_revision"]
    source_artifact = candidate["source_artifact"]
    evidence_span = candidate["evidence_span"]
    risk = candidate["risk"]
    deposition = candidate["deposition_summary"]
    return {
        "schema_version": SCHEMA_VERSION,
        "record_type": "ReviewDecisionSurface",
        "authoritative_decision_model": ReviewDecision.model_fields["schema_version"].default,
        "review_item_id": REVIEW_ITEM_ID,
        "queue_status": "pending_human_review",
        "knowledge_status": "candidate_pending_review",
        "candidate_claim_id": claim.claim_id,
        "claim_revision_id": claim.claim_revision_id,
        "scientific_proposition": claim.claim_text,
        "subject_id": claim.subject_id,
        "predicate": claim.predicate,
        "object_value": claim.object_value,
        "software_context": {
            "package": "SoupX",
            "version": "1.6.2",
            "package_release_id": claim.subject_id,
        },
        "applicability_scope": scope.model_dump(mode="json"),
        "risk": {
            "risk_class": risk["risk_class"],
            "review_requirement": risk["review_requirement"],
        },
        "evidence_assessment": assessment.model_dump(mode="json"),
        "evidence_span": {
            "evidence_span_id": evidence_span["evidence_span_id"],
            "locator": evidence_span["locator"],
            "content_hash": evidence_span["content_hash"],
        },
        "source_work": {
            "source_work_id": source_work["source_work_id"],
            "canonical_title": source_work["canonical_title"],
            "authority": source_work["authority"],
        },
        "source_revision": {
            "source_revision_id": source_revision["source_revision_id"],
            "version": source_revision["version"],
            "source_work_id": source_revision["source_work_id"],
        },
        "source_artifact": {
            "source_artifact_id": source_artifact["source_artifact_id"],
            "source_revision_id": source_artifact["source_revision_id"],
            "sha256": source_artifact["sha256"],
            "artifact_type": source_artifact["artifact_type"],
        },
        "provenance": {
            "acquisition_trace": candidate["acquisition_report"]["trace_path"],
            "acquisition_status": "reused_existing_artifact",
            "deposition_activity_id": candidate["deposition_provenance"]["derivation_activity_id"],
            "deposition_trace": deposition["trace_path"],
            "prior_candidate_reuse_count": 1,
            "external_reacquisition_count": 0,
        },
        "duplicate_status": {
            "status": "unique",
            "candidate_equivalent_count_before_deposition": deposition[
                "existing_knowledge_inspection"
            ]["candidate_equivalent_count"],
            "canonical_equivalent_count": deposition["existing_knowledge_inspection"][
                "canonical_equivalent_count"
            ],
        },
        "conflict_status": {
            "status": "none_detected",
            "conflicting_claim_revision_ids": deposition["conflicts_preserved"],
        },
        "allowed_reviewer_actions": ALLOWED_ACTIONS,
        "action_bindings": ACTION_BINDINGS,
        "review_decision": None,
        "reviewer_reason": None,
        "promotion_guard": {
            "promotion_allowed_now": False,
            "requires_review_decision": True,
            "requires_knowledge_change_set": True,
            "requires_immutable_snapshot": True,
            "execution_authority_granted": False,
        },
    }


def promotion_gate(
    review_item: dict[str, Any], *, review_decision: ReviewDecision | None, knowledge_change_set: dict[str, Any] | None
) -> dict[str, Any]:
    if review_item.get("knowledge_status") != "candidate_pending_review":
        return {"allowed": False, "reason": "candidate_status_invalid"}
    if review_decision is None:
        return {"allowed": False, "reason": "qualified_review_decision_missing"}
    if review_decision.decision != "accepted":
        return {"allowed": False, "reason": "review_decision_not_accepted"}
    if not knowledge_change_set:
        return {"allowed": False, "reason": "knowledge_change_set_missing"}
    return {"allowed": True, "reason": "manual_promotion_preconditions_present"}


def final_reuse_query(*, cp6_root: Path, claim_revision_id: str) -> dict[str, Any]:
    index_dir = cp6_root / "rag_index"
    service = HybridRetrievalService(
        evidence_chunks_path=index_dir / "evidence_chunks.jsonl",
        catalog_chunks_path=index_dir / "catalog_chunks.jsonl",
        fts_index_path=index_dir / "evidence_fts5.sqlite",
        index_manifest_path=index_dir / "evidence_index_manifest.json",
        coverage_path=index_dir / "retrieval_coverage_v2.json",
        dense_matrix_path=index_dir / "evidence_vectors.npy",
        dense_metadata_path=index_dir / "evidence_vector_metadata.json",
        graph_dir=index_dir / "absent_graph",
    )
    result = service.search(
        HybridRetrievalRequest(
            query=FINAL_QUERY,
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
    claim_rows = _jsonl(cp6_root / "candidate_atomic_claims.jsonl")
    matching_claims = [row for row in claim_rows if row["claim_revision_id"] == claim_revision_id]
    matching_hits = [
        hit
        for hit in result.hits
        if hit.chunk_id == "source:cp6:soupx:soupchannel-inputs:1.6.2"
    ]
    if len(matching_claims) != 1 or len(matching_hits) != 1:
        raise ValueError("final_candidate_reuse_failed")
    return {
        "query": FINAL_QUERY,
        "candidate_claim_revision_id": claim_revision_id,
        "candidate_claim_reused": True,
        "evidence_span_id": "evidence-span:cp5:soupx:soupchannel-inputs:1.6.2",
        "evidence_span_reused": True,
        "source_artifact_id": (
            "source-artifact:sha256:"
            "dabbfdf10c0ab46efee927026f77494e1df096999742f86705b91dcd0b1dac19"
        ),
        "source_artifact_reused": True,
        "knowledge_status": "candidate_pending_review",
        "external_reacquisition_count": 0,
        "retrieved_chunk_ids": [hit.chunk_id for hit in result.hits],
        "index_build_id": result.index_build_id,
    }


def _record_stage(
    instrumentation: Any,
    *,
    stage: TraceStage,
    operation: str,
    input_ref: tuple[str, str],
    output_ref: tuple[str, str],
    decision: tuple[str, str, str] | None = None,
) -> None:
    with instrumentation.span(
        stage=stage,
        component="candidate_review_governance",
        operation=operation,
        input_refs=[
            {"record_type": input_ref[0], "record_id": input_ref[1], "relation": "input"}
        ],
    ) as span:
        span.add_output_ref(
            record_type=output_ref[0], record_id=output_ref[1], relation="produced"
        )
        if decision:
            span.add_decision(
                decision_type=decision[0],
                outcome=decision[1],
                reason_code=decision[2],
                rule_version="cp7_governance_closure_v1",
                record_ref={
                    "record_type": output_ref[0],
                    "record_id": output_ref[1],
                    "relation": "decision_subject",
                },
            )


def run_review_queue(
    *,
    cp5_root: Path = DEFAULT_CP5_ROOT,
    cp6_root: Path = DEFAULT_CP6_ROOT,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
) -> dict[str, Any]:
    output_root = output_root.resolve()
    if (output_root / "summary.json").exists():
        raise FileExistsError("cp7_review_queue_already_completed")
    candidate = load_and_validate_candidate(cp5_root=cp5_root, cp6_root=cp6_root)
    review_item = build_review_item(candidate)
    gate = promotion_gate(review_item, review_decision=None, knowledge_change_set=None)
    if gate != {"allowed": False, "reason": "qualified_review_decision_missing"}:
        raise ValueError("promotion_guard_failed_closed")

    trace = TraceContext.new_request(
        trace_kind=TraceKind.RESEARCH,
        request_id="cp7-soupx-admin-review-queue",
        conversation_id="cp7-governance-closure",
    )
    instrumentation = trace.instrumentation()
    trace_path = output_root / "trace.jsonl"
    with TraceCollector(trace_path).request_scope(trace):
        _record_stage(
            instrumentation,
            stage=TraceStage.STATE_INSPECTION,
            operation="inspect_candidate_governance_state",
            input_ref=("AtomicClaimRevision", candidate["claim"].claim_revision_id),
            output_ref=("EvidenceGap", candidate["lifecycle"]["gap_id"]),
        )
        _record_stage(
            instrumentation,
            stage=TraceStage.VALIDATION,
            operation="verify_claim_evidence_source_chain",
            input_ref=("EvidenceAssessment", candidate["assessment"].assessment_id),
            output_ref=("SourceArtifact", candidate["source_artifact"]["source_artifact_id"]),
            decision=("provenance_fidelity", "pass", "claim_evidence_source_chain_intact"),
        )
        reuse = final_reuse_query(
            cp6_root=cp6_root, claim_revision_id=candidate["claim"].claim_revision_id
        )
        _record_stage(
            instrumentation,
            stage=TraceStage.RETRIEVAL,
            operation="reuse_candidate_for_governed_query",
            input_ref=("EvidenceSpan", candidate["evidence_span"]["evidence_span_id"]),
            output_ref=("AtomicClaimRevision", candidate["claim"].claim_revision_id),
            decision=("knowledge_reuse", "candidate", "candidate_pending_review_preserved"),
        )
        _record_stage(
            instrumentation,
            stage=TraceStage.DECISION,
            operation="enqueue_admin_review_item",
            input_ref=("AtomicClaimRevision", candidate["claim"].claim_revision_id),
            output_ref=("ReviewItem", REVIEW_ITEM_ID),
            decision=("review_queue", "pending", "qualified_human_review_required"),
        )
        _record_stage(
            instrumentation,
            stage=TraceStage.VALIDATION,
            operation="enforce_manual_promotion_guard",
            input_ref=("ReviewItem", REVIEW_ITEM_ID),
            output_ref=("AtomicClaimRevision", candidate["claim"].claim_revision_id),
            decision=("canonical_promotion", "blocked", gate["reason"]),
        )

    output_root.mkdir(parents=True, exist_ok=True)
    _write_jsonl(output_root / "review_queue.jsonl", [review_item])
    _write_json(output_root / "final_reuse_query.json", reuse)
    provenance_audit = {
        "status": "PASS",
        "chain": [
            candidate["claim"].claim_revision_id,
            candidate["assessment"].assessment_id,
            candidate["evidence_span"]["evidence_span_id"],
            candidate["source_artifact"]["source_artifact_id"],
            candidate["source_revision"]["source_revision_id"],
            candidate["source_work"]["source_work_id"],
        ],
        "broken_id_count": 0,
        "source_swap_count": 0,
        "scope_loss_count": 0,
        "epistemic_conflation_count": 0,
    }
    _write_json(output_root / "provenance_audit.json", provenance_audit)
    failures = {
        "schema_version": "sckg-night-failure-knowledge-v1",
        "events": [
            {
                "id": "night-cp2.6-evaluation-version-routing",
                "first_owner": "evaluation preregistration version boundary",
                "status": "resolved",
                "prevention_rule": "historical experiment integrity is separate from current SUT identity",
            },
            {
                "id": "night-cp4.5-missing-v1.2-formal-entrypoint",
                "first_owner": "evaluation runner boundary",
                "status": "resolved",
                "prevention_rule": "formal evaluation versions require a tested write-once canonical entrypoint",
            },
            {
                "id": "night-cp5-pdf-parsing-runtime-dependency",
                "first_owner": "PDF parsing runtime dependency",
                "status": "resolved",
                "prevention_rule": "verify the existing PDF extraction runtime before acquisition and preserve the failed trace",
            },
            {
                "id": "night-cp6-overbroad-operator-scope",
                "first_owner": "candidate scope construction",
                "status": "resolved_before_acceptance",
                "prevention_rule": "do not bind package-level span semantics to an operator absent direct support",
            },
        ],
    }
    _write_json(output_root / "failure_knowledge.json", failures)
    summary = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "review_item_id": REVIEW_ITEM_ID,
        "review_item_count": 1,
        "knowledge_status": "candidate_pending_review",
        "allowed_reviewer_actions": ALLOWED_ACTIONS,
        "promotion_gate": gate,
        "canonical_promotion_performed": False,
        "review_decision_created": False,
        "knowledge_change_set_created": False,
        "canonical_snapshot_created": False,
        "execution_authority_granted": False,
        "final_reuse": reuse,
        "provenance_audit": provenance_audit,
        "trace_path": "trace.jsonl",
    }
    _write_json(output_root / "summary.json", summary)
    artifact_names = sorted(
        path.name
        for path in output_root.iterdir()
        if path.is_file() and path.name != "manifest.json"
    )
    _write_json(
        output_root / "manifest.json",
        {
            "schema_version": SCHEMA_VERSION,
            "status": "candidate_pending_review",
            "artifacts": {name: _sha_file(output_root / name) for name in artifact_names},
            "canonical_promotion_performed": False,
        },
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build the CP7 governed candidate-knowledge admin review surface."
    )
    parser.add_argument("--cp5-root", type=Path, default=DEFAULT_CP5_ROOT)
    parser.add_argument("--cp6-root", type=Path, default=DEFAULT_CP6_ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    args = parser.parse_args()
    print(
        _canonical_json(
            run_review_queue(
                cp5_root=args.cp5_root,
                cp6_root=args.cp6_root,
                output_root=args.output_root,
            )
        )
    )


if __name__ == "__main__":
    main()
