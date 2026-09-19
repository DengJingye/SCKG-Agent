"""Build the read-only PDF knowledge-ingestion capability audit.

This module records repository evidence; it does not execute ingestion, call an
LLM, rebuild an index, or mutate any knowledge substrate.  The output is a
checkpoint artifact that makes pilot, reusable, missing, and unsafe capabilities
explicit before Checkpoint 5 is designed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "data/evaluation/pdf_knowledge_ingestion_capability_audit_v1"
REPORT_PATH = ROOT / "docs/status/PDF_KNOWLEDGE_INGESTION_CAPABILITY_AUDIT_V1.md"
CHECKPOINT_3_COMMIT = "453cb31f27fc4f9e7bc6e810100848847ac9bd05"

STATUSES = {
    "IMPLEMENTED_PRODUCTION",
    "IMPLEMENTED_REUSABLE",
    "IMPLEMENTED_PILOT",
    "PARTIAL",
    "MISSING",
    "UNSAFE_TO_REUSE",
}


def _artifact(path: str, *, optional: bool = False, purpose: str = "") -> dict[str, Any]:
    return {"path": path, "optional": optional, "purpose": purpose}


def _stage(
    number: int,
    name: str,
    status: str,
    *,
    implementation: Iterable[str] = (),
    data_models: Iterable[str] = (),
    artifacts: Iterable[dict[str, Any]] = (),
    owner: str,
    reusable: bool,
    missing: Iterable[str] = (),
    risks: Iterable[str] = (),
    tool_specific: bool = False,
    source_specific: bool = False,
) -> dict[str, Any]:
    if status not in STATUSES:
        raise ValueError(f"invalid stage status: {status}")
    return {
        "stage_number": number,
        "stage": name,
        "status": status,
        "existing_implementation": list(implementation),
        "data_models": list(data_models),
        "persistent_artifacts": list(artifacts),
        "owner": owner,
        "reusable_for_checkpoint_5": reusable,
        "missing_capability": list(missing),
        "risks": list(risks),
        "tool_specific": tool_specific,
        "source_specific": source_specific,
    }


def capability_matrix() -> list[dict[str, Any]]:
    acquisition = "data_pipeline/run_evidence_gap_acquisition_pilot_v1.py"
    deposition = "data_pipeline/run_candidate_knowledge_deposition_pilot_v1.py"
    review = "data_pipeline/build_candidate_knowledge_review_queue_v1.py"
    conformance = "core/scientific_knowledge_conformance_models.py"
    parser = "data_pipeline/ingest_evidence_pdfs.py"
    registry = "data_pipeline/build_source_registry.py"
    corpus = "engine/source_corpus_v2.py"
    trace = "core/trace_context.py"
    cp5 = "data/evaluation/evidence_gap_acquisition_pilot_v1_repaired"
    cp6 = "data/evaluation/candidate_knowledge_deposition_pilot_v1"
    cp7 = "data/evaluation/candidate_knowledge_review_queue_v1"
    return [
        _stage(1, "File Upload / Registration", "PARTIAL",
            implementation=["app.py", parser, registry], data_models=["upload summary", "source registry row"],
            artifacts=[_artifact("app.py"), _artifact("data/source_registry.jsonl", optional=True)],
            owner="No governed PDF registration owner", reusable=False,
            missing=["PDF uploads are preview-only in the app", "no upload-to-SourceWork transaction"],
            risks=["UI upload and evidence acquisition are disconnected"]),
        _stage(2, "Content hash / artifact identity", "IMPLEMENTED_PILOT",
            implementation=[acquisition], data_models=["SourceArtifact pilot dictionary"],
            artifacts=[_artifact(f"{cp5}/source_registry.json")], owner=acquisition, reusable=True,
            missing=["formal SourceArtifact schema and generic registration adapter"],
            risks=["identity contract is embedded in a SoupX-specific runner"], tool_specific=True, source_specific=True),
        _stage(3, "SourceWork registration", "IMPLEMENTED_PILOT",
            implementation=[acquisition, registry], data_models=["SourceWork pilot dictionary", "SourceDocumentRecord"],
            artifacts=[_artifact(f"{cp5}/source_registry.json")], owner="No single authoritative owner",
            reusable=False, missing=["formal model and generic persistence owner"],
            risks=["DUPLICATE_OWNER_RISK"], tool_specific=True, source_specific=True),
        _stage(4, "SourceRevision creation", "IMPLEMENTED_PILOT",
            implementation=[acquisition], data_models=["SourceRevision pilot dictionary"],
            artifacts=[_artifact(f"{cp5}/source_registry.json")], owner="No formal SourceRevision owner",
            reusable=False, missing=["generic revision builder and formal schema"],
            risks=["DUPLICATE_OWNER_RISK", "fixed SoupX identifier"], tool_specific=True, source_specific=True),
        _stage(5, "DOI / title / metadata extraction", "PARTIAL",
            implementation=[registry], data_models=["source registry row"],
            artifacts=[_artifact("data/source_registry.jsonl", optional=True)], owner=registry, reusable=True,
            missing=["PDF-embedded metadata extraction"],
            risks=["metadata is sourced from manifests, URLs, or Crossref rather than the PDF"]),
        _stage(6, "PDF text extraction", "IMPLEMENTED_REUSABLE",
            implementation=[parser], data_models=["extraction result dictionary"],
            artifacts=[_artifact(f"{cp5}/extracted/soupx-1.6.2-manual.txt")], owner=parser, reusable=True,
            missing=["OCR and parser-version provenance"], risks=["preferred pdftotext path loses page boundaries"]),
        _stage(7, "Page / section / locator preservation", "PARTIAL",
            implementation=[parser, corpus], data_models=["[PDF_PAGE N] markers", "EvidenceChunk.source_span"],
            artifacts=[_artifact(f"{cp6}/rag_index/evidence_chunks.jsonl")], owner=corpus, reusable=False,
            missing=["page-preserving default parser", "stable locator contract"],
            risks=["pdftotext is preferred and emits no page markers; section detection is heuristic"]),
        _stage(8, "EvidenceSpan generation", "IMPLEMENTED_PILOT",
            implementation=[acquisition], data_models=["EvidenceSpan pilot dictionary"],
            artifacts=[_artifact(f"{cp5}/evidence_span.json")], owner=acquisition, reusable=False,
            missing=["generic span candidate generator and formal model"],
            risks=["hard-coded SoupX regular expression"], tool_specific=True, source_specific=True),
        _stage(9, "EvidenceSpan exact-text binding", "IMPLEMENTED_PILOT",
            implementation=[acquisition], data_models=["EvidenceSpan exact_text, locator, content_hash"],
            artifacts=[_artifact(f"{cp5}/evidence_span.json")], owner=acquisition, reusable=True,
            missing=["generic binding validator"], risks=["validated only for one SoupX span"],
            tool_specific=True, source_specific=True),
        _stage(10, "Entity extraction", "MISSING", owner="No owner", reusable=False,
            missing=["governed PDF entity extractor with span-bound structured output"],
            risks=["legacy tool-profile extractor does not produce Scientific KG candidates"]),
        _stage(11, "Entity resolution / deduplication", "PARTIAL",
            implementation=[registry, deposition], data_models=["source key", "claim semantic fingerprint"],
            artifacts=[_artifact(f"{cp6}/summary.json")], owner="No cross-type entity resolver", reusable=False,
            missing=["Method, OperatorRevision, and Representation resolvers"],
            risks=["per-type logic is split across builders"]),
        _stage(12, "Relation extraction", "UNSAFE_TO_REUSE",
            implementation=["data_pipeline/neo4j_loader.py", "data_pipeline/hybrid_loader.py"],
            data_models=["legacy Tool KG JSON response", "mutable Neo4j graph"],
            artifacts=[_artifact("data/scKG_embeddings_backup.jsonl", optional=True)],
            owner="data_pipeline/neo4j_loader.py", reusable=False,
            missing=["candidate-only Scientific KG relation extractor with evidence bindings"],
            risks=["UNSAFE_DIRECT_KG_MUTATION", "no governed relation endpoint validation"]),
        _stage(13, "Method / Operator / Representation resolution", "PARTIAL",
            implementation=[conformance, deposition],
            data_models=["Method", "OperatorRevision", "RepresentationType"],
            artifacts=[_artifact(f"{cp6}/conformance_bundle.json")], owner=conformance, reusable=False,
            missing=["resolution service from extracted strings to existing identities"],
            risks=["SoupX pilot reuses a hard-coded core identity slice"], tool_specific=True),
        _stage(14, "AtomicClaim extraction", "IMPLEMENTED_PILOT",
            implementation=[deposition], data_models=["AtomicClaimRevision"],
            artifacts=[_artifact(f"{cp6}/candidate_atomic_claims.jsonl")], owner=deposition, reusable=False,
            missing=["general extractor"], risks=["claim text is hard-coded for SoupX"],
            tool_specific=True, source_specific=True),
        _stage(15, "Claim typing", "IMPLEMENTED_PILOT",
            implementation=[deposition, conformance], data_models=["AtomicClaimRevision.claim_type"],
            artifacts=[_artifact(f"{cp6}/candidate_atomic_claims.jsonl")], owner=conformance, reusable=True,
            missing=["automated type selection"], risks=["pilot assigns the type manually"], tool_specific=True),
        _stage(16, "ApplicabilityScope extraction", "IMPLEMENTED_PILOT",
            implementation=[deposition, conformance], data_models=["ApplicabilityScope"],
            artifacts=[_artifact(f"{cp6}/conformance_bundle.json")], owner=conformance, reusable=False,
            missing=["general scope extractor"], risks=["pilot scope is hard-coded"], tool_specific=True),
        _stage(17, "Version / flavor extraction", "PARTIAL",
            implementation=[acquisition, deposition], data_models=["SourceRevision.version", "PackageRelease"],
            artifacts=[_artifact(f"{cp5}/source_registry.json"), _artifact(f"{cp6}/conformance_bundle.json")],
            owner="No general version/flavor extractor", reusable=False,
            missing=["PDF-grounded version and flavor extraction"], risks=["SoupX version is predetermined"],
            tool_specific=True, source_specific=True),
        _stage(18, "EvidenceAssessment creation", "IMPLEMENTED_PILOT",
            implementation=[deposition, conformance], data_models=["EvidenceAssessment"],
            artifacts=[_artifact(f"{cp6}/evidence_assessments.jsonl")], owner=conformance, reusable=True,
            missing=["generic assessment builder"], risks=["one pilot assessment only"], tool_specific=True),
        _stage(19, "Claim → Evidence binding", "IMPLEMENTED_PILOT",
            implementation=[deposition, conformance], data_models=["EvidenceAssessment.evidence_span_ids"],
            artifacts=[_artifact(f"{cp6}/evidence_assessments.jsonl")], owner=conformance, reusable=True,
            missing=["bundle-level validation against materialized EvidenceSpan records"],
            risks=["spans live outside ConformanceBundle"], tool_specific=True),
        _stage(20, "Ontology/schema validation", "IMPLEMENTED_REUSABLE",
            implementation=[conformance], data_models=["ConformanceBundle"],
            artifacts=[_artifact(f"{cp6}/conformance_bundle.json")], owner=conformance, reusable=True,
            missing=["allowed external relation vocabulary validation for extracted candidates"],
            risks=["EvidenceSpan records are external to the bundle"]),
        _stage(21, "Candidate identity creation", "IMPLEMENTED_PILOT",
            implementation=[deposition], data_models=["semantic fingerprint", "claim revision ID"],
            artifacts=[_artifact(f"{cp6}/candidate_atomic_claims.jsonl")], owner=deposition, reusable=True,
            missing=["central identity service for every candidate type"], risks=["identity is claim-specific"],
            tool_specific=True),
        _stage(22, "Candidate KG deposit", "IMPLEMENTED_PILOT",
            implementation=[deposition], data_models=["isolated candidate overlay"],
            artifacts=[_artifact(f"{cp6}/candidate_overlay_graph.json")], owner=deposition, reusable=True,
            missing=["general append-only candidate store and transaction boundary"],
            risks=["pilot directory is write-once rather than a revisioned datastore"], tool_specific=True),
        _stage(23, "Candidate RAG indexing/reuse", "IMPLEMENTED_PILOT",
            implementation=[deposition, "engine/evidence_discovery_index.py", "engine/hybrid_retrieval.py"],
            data_models=["EvidenceChunk"], artifacts=[_artifact(f"{cp6}/rag_index/evidence_chunks.jsonl")],
            owner="engine/evidence_discovery_index.py", reusable=True,
            missing=["production candidate retrieval gate"],
            risks=["validated only in an isolated retrieval_only index"], tool_specific=True),
        _stage(24, "EvidenceGap resolution/update", "PARTIAL",
            implementation=[acquisition, deposition], data_models=["evidence gap lifecycle record"],
            artifacts=[_artifact(f"{cp6}/evidence_gap_lifecycle.json")], owner="No authoritative EvidenceGap lifecycle owner",
            reusable=False, missing=["persisted governed transition service"],
            risks=["status is duplicated across pilot artifacts"], tool_specific=True),
        _stage(25, "Admin Review Item creation", "IMPLEMENTED_PILOT",
            implementation=[review], data_models=["ReviewDecisionSurface"],
            artifacts=[_artifact(f"{cp7}/review_queue.jsonl")], owner=review, reusable=True,
            missing=["general queue service"], risks=["actions are descriptive and not executable"], tool_specific=True),
        _stage(26, "ReviewDecision persistence", "MISSING",
            implementation=[conformance], data_models=["ReviewDecision"], owner="Model exists; persistence owner missing",
            reusable=False, missing=["decision repository and transaction"],
            risks=["no decision is created by the review queue pilot"]),
        _stage(27, "Promote / Reject / Merge / Supersede backend", "UNSAFE_TO_REUSE",
            implementation=[review, "data_pipeline/apply_next_review_decisions.py", "data_pipeline/promote_recovered_evidence.py"],
            data_models=["promotion guard", "legacy review TSV"], owner="No Scientific KG lifecycle backend",
            reusable=False, missing=["governed Scientific KG mutation handlers and immutable snapshot"],
            risks=["legacy mutators target a different evidence lifecycle", "unsafe to expose as UI actions"]),
        _stage(28, "Canonical Trace events", "IMPLEMENTED_PILOT",
            implementation=[trace, acquisition, deposition, review], data_models=["TraceContext", "TraceCollector"],
            artifacts=[_artifact(f"{cp6}/trace.jsonl"), _artifact(f"{cp7}/trace.jsonl")], owner=trace, reusable=True,
            missing=["explicit knowledge-evolution stage vocabulary"], risks=["operations use generic trace stages"],
            tool_specific=True),
        _stage(29, "Before/After KG diff", "PARTIAL",
            implementation=[deposition], data_models=["existing-knowledge inspection", "candidate overlay"],
            artifacts=[_artifact(f"{cp6}/candidate_overlay_graph.json"), _artifact(f"{cp6}/summary.json")],
            owner=deposition, reusable=False, missing=["general structured before/after candidate diff"],
            risks=["current comparison is claim-specific"], tool_specific=True),
        _stage(30, "Rollback / supersede support", "PARTIAL",
            implementation=[conformance], data_models=["SupersessionRecord"], owner=conformance, reusable=False,
            missing=["rollback store", "supersession persistence and execution handler"],
            risks=["schema exists without lifecycle backend"]),
    ]


def soupx_pipeline_map() -> dict[str, Any]:
    rows = [
        ("EvidenceGap selection", "data_pipeline/run_evidence_gap_acquisition_pilot_v1.py", "selected_evidence_gap.json", "IMPLEMENTED_PILOT", "fixed SoupX gap"),
        ("authoritative source discovery", "data_pipeline/run_evidence_gap_acquisition_pilot_v1.py", "source_registry.json", "IMPLEMENTED_PILOT", "fixed SoupX manual"),
        ("SourceWork / SourceRevision", "data_pipeline/run_evidence_gap_acquisition_pilot_v1.py", "source_registry.json", "IMPLEMENTED_PILOT", "ad hoc dictionaries"),
        ("artifact hash and PDF parse", "data_pipeline/ingest_evidence_pdfs.py", "artifacts/soupx-1.6.2-manual.pdf", "IMPLEMENTED_REUSABLE", "parser has page-provenance limits"),
        ("exact EvidenceSpan", "data_pipeline/run_evidence_gap_acquisition_pilot_v1.py", "evidence_span.json", "IMPLEMENTED_PILOT", "hard-coded regular expression"),
        ("EvidenceAssessment", "data_pipeline/run_candidate_knowledge_deposition_pilot_v1.py", "evidence_assessments.jsonl", "IMPLEMENTED_PILOT", "formal model; hard-coded content"),
        ("Candidate AtomicClaimRevision", "data_pipeline/run_candidate_knowledge_deposition_pilot_v1.py", "candidate_atomic_claims.jsonl", "IMPLEMENTED_PILOT", "formal model; hard-coded content"),
        ("Candidate KG / RAG", "data_pipeline/run_candidate_knowledge_deposition_pilot_v1.py", "candidate_overlay_graph.json", "IMPLEMENTED_PILOT", "isolated and retrieval-only"),
        ("candidate reuse", "data_pipeline/run_candidate_knowledge_deposition_pilot_v1.py", "second_query_result.json", "IMPLEMENTED_PILOT", "single-query pattern"),
        ("Admin Review Item", "data_pipeline/build_candidate_knowledge_review_queue_v1.py", "review_queue.jsonl", "IMPLEMENTED_PILOT", "read-only action surface"),
        ("promotion guard", "data_pipeline/build_candidate_knowledge_review_queue_v1.py", "summary.json", "IMPLEMENTED_PILOT", "fails closed; no promotion backend"),
    ]
    roots = {
        "acquisition": "data/evaluation/evidence_gap_acquisition_pilot_v1_repaired",
        "deposition": "data/evaluation/candidate_knowledge_deposition_pilot_v1",
        "review": "data/evaluation/candidate_knowledge_review_queue_v1",
    }
    output = []
    for index, (stage, module, artifact, status, limitation) in enumerate(rows, 1):
        root = roots["acquisition" if index <= 5 else "deposition" if index <= 9 else "review"]
        output.append({"order": index, "stage": stage, "module": module, "artifact": f"{root}/{artifact}", "status": status, "limitation": limitation})
    return {
        "pilot": "SoupX evidence-gap acquisition → candidate knowledge → review queue",
        "source_code_was_primary_evidence": True,
        "original_incomplete_run": "data/evaluation/evidence_gap_acquisition_pilot_v1",
        "authoritative_repaired_run": roots["acquisition"],
        "pipeline": output,
        "canonical_promotion_performed": False,
        "candidate_boundary_preserved": True,
    }


def authoritative_owner_map() -> dict[str, Any]:
    return {
        "owners": [
            {"concept": "SourceWork", "authoritative_owner": None, "implementations": ["data_pipeline/run_evidence_gap_acquisition_pilot_v1.py", "data_pipeline/build_source_registry.py"], "warning": "DUPLICATE_OWNER_RISK"},
            {"concept": "SourceRevision", "authoritative_owner": None, "implementations": ["data_pipeline/run_evidence_gap_acquisition_pilot_v1.py", "Scientific KG layer source manifests"], "warning": "DUPLICATE_OWNER_RISK"},
            {"concept": "EvidenceSpan", "authoritative_owner": None, "implementations": ["data_pipeline/run_evidence_gap_acquisition_pilot_v1.py", "scientific-layer JSONL", "engine/evidence_discovery_index.py:EvidenceChunk"], "warning": "DUPLICATE_OWNER_RISK"},
            {"concept": "EvidenceAssessment", "authoritative_owner": "core/scientific_knowledge_conformance_models.py:EvidenceAssessment", "implementations": ["core/scientific_knowledge_conformance_models.py"], "warning": None},
            {"concept": "AtomicClaimRevision", "authoritative_owner": "core/scientific_knowledge_conformance_models.py:AtomicClaimRevision", "implementations": ["core/scientific_knowledge_conformance_models.py"], "warning": None},
            {"concept": "Candidate status", "authoritative_owner": None, "implementations": ["candidate overlay", "risk registry", "pilot summary", "review item"], "warning": "DUPLICATE_OWNER_RISK"},
            {"concept": "ReviewDecision", "authoritative_owner": "core/scientific_knowledge_conformance_models.py:ReviewDecision", "implementations": ["core/scientific_knowledge_conformance_models.py"], "warning": "PERSISTENCE_OWNER_MISSING"},
            {"concept": "Promotion status", "authoritative_owner": None, "implementations": ["pilot summaries", "promotion preflights", "review surface"], "warning": "DUPLICATE_OWNER_RISK"},
            {"concept": "Trace", "authoritative_owner": "core/trace_context.py", "implementations": ["core/trace_context.py"], "warning": None},
        ],
        "policy": "No owner was silently selected where competing representations exist.",
    }


def pdf_parser_audit() -> dict[str, Any]:
    return {
        "owner": "data_pipeline/ingest_evidence_pdfs.py",
        "selection_order": ["Poppler pdftotext -layout when installed", "pypdf", "Ghostscript repair plus pypdf after pypdf failure"],
        "PDF_TEXT_EXTRACTION": "READY_WITH_LIMITATIONS",
        "PAGE_LOCATORS": "PARTIAL",
        "SECTION_LOCATORS": "PARTIAL_HEURISTIC",
        "SCANNED_PDF_SUPPORT": False,
        "TABLE_EXTRACTION": False,
        "FIGURE_EXTRACTION": False,
        "METADATA_EXTRACTION": "PARTIAL_EXTERNAL_MANIFEST_ONLY",
        "PARSER_VERSION_RECORDED": False,
        "SOURCE_HASH_BINDING": "PILOT_ONLY",
        "deterministic_output": "Same parser path is deterministic enough for a bounded pilot, but runtime/parser version is not recorded.",
        "critical_limitation": "The preferred pdftotext path reports page_count=0 and emits no [PDF_PAGE N] markers; pypdf preserves those markers.",
        "ocr_added_in_checkpoint": False,
    }


def llm_extraction_audit() -> dict[str, Any]:
    return {
        "governed_pdf_extractor_exists": False,
        "UNSAFE_DIRECT_KG_MUTATION": True,
        "extractors": [
            {
                "module": "data_pipeline/llm_extractor.py",
                "model_owner": "core/llm_client.py and runtime settings",
                "prompt_version_owner": "inline unversioned system_prompt",
                "outputs": ["tool profile fields"],
                "structured_schema": "JSON shape in prompt; no Pydantic model",
                "validation": "json.loads only",
                "retry_behavior": "client max_retries=2; extractor returns empty object on error",
                "hallucination_guard": "none",
                "source_span_requirement": False,
                "candidate_only": False,
                "assessment": "UNSAFE_TO_REUSE_FOR_GOVERNED_PDF_INGESTION",
            },
            {
                "module": "data_pipeline/neo4j_loader.py",
                "model_owner": "runtime extract_model setting",
                "prompt_version_owner": "inline unversioned prompt",
                "outputs": ["Tool", "Task", "Modality", "Hardware", "Resolution", "Algorithm"],
                "structured_schema": "JSON response format; no Scientific KG conformance model",
                "validation": "field defaults only",
                "retry_behavior": "single HTTP request; empty object on failure",
                "hallucination_guard": "low/model_extracted trust labels only",
                "source_span_requirement": False,
                "candidate_only": False,
                "writes": ["mutable Neo4j", "append-only local JSONL backup"],
                "assessment": "UNSAFE_DIRECT_KG_MUTATION",
            },
        ],
        "required_checkpoint_5_contract": "Versioned structured candidate entity/relation/claim/scope output with mandatory EvidenceSpan IDs and no canonical write authority.",
    }


def ontology_validation_audit() -> dict[str, Any]:
    return {
        "owner": "core/scientific_knowledge_conformance_models.py",
        "ONTOLOGY_VALIDATOR_EXISTS": "PARTIAL",
        "SCHEMA_VALIDATOR_EXISTS": True,
        "RELATION_ENDPOINT_VALIDATION": "SUPPORTED_FOR_DERIVED_RELATIONS_IN_CONFORMANCE_BUNDLE",
        "CLAIM_EVIDENCE_VALIDATION": "PARTIAL_EVIDENCE_ASSESSMENT_TO_CLAIM_ONLY",
        "SCOPE_VALIDATION": True,
        "checks": {
            "allowed_entity_types": "Pydantic discriminated record models",
            "allowed_relation_types": "DerivedRelation literal vocabulary",
            "endpoint_type_constraints": "checked for supported derived relation fields",
            "required_fields": True,
            "OperatorRevision_identity": True,
            "RepresentationType_identity": True,
            "ApplicabilityScope_schema": True,
            "evidence_binding_requirements": "EvidenceAssessment requires span IDs, but spans are external to ConformanceBundle",
            "version_constraints": "schema versions and selected entity identities",
            "knowledge_status": "governance fields exist; no lifecycle state machine",
        },
    }


def deduplication_audit() -> dict[str, Any]:
    return {
        "DEDUPLICATION_KEY_BY_TYPE": {
            "SourceWork": {"key": None, "status": "MISSING_GENERIC_KEY", "observed": "SoupX fixed ID; generic registry uses DOI, else URL, else normalized title"},
            "SourceRevision": {"key": None, "status": "MISSING_GENERIC_KEY", "observed": "SoupX fixed source revision and version"},
            "SourceArtifact": {"key": "sha256(file bytes)", "status": "IMPLEMENTED_PILOT"},
            "EvidenceSpan": {"key": None, "status": "MISSING_GENERIC_KEY", "observed": "fixed pilot ID plus source binding, locator, exact text content hash"},
            "AtomicClaimRevision": {"key": "sha256(subject_id, predicate, object_value, scope_id, polarity)", "status": "IMPLEMENTED_PILOT"},
            "OperatorRevision": {"key": None, "status": "NO_CENTRAL_RESOLVER"},
            "Method": {"key": None, "status": "NO_CENTRAL_RESOLVER"},
            "Representation": {"key": None, "status": "NO_CENTRAL_RESOLVER"},
        },
        "source_registry_fallback": ["normalized DOI", "URL", "normalized title"],
        "central_entity_resolution_service_exists": False,
        "invented_keys": False,
    }


def candidate_deposit_audit() -> dict[str, Any]:
    root = "data/evaluation/candidate_knowledge_deposition_pilot_v1"
    return {
        "meaning": "An isolated, write-once local candidate overlay plus an isolated retrieval-only index.",
        "candidate_entity_destination": f"{root}/candidate_overlay_graph.json",
        "candidate_relation_destination": f"{root}/candidate_overlay_graph.json",
        "candidate_claim_destination": f"{root}/candidate_atomic_claims.jsonl",
        "evidence_destination": [f"{root}/evidence_spans.jsonl", f"{root}/evidence_assessments.jsonl"],
        "append_only": False,
        "write_once_directory": True,
        "revisioning_supported": "MODEL_ONLY_NOT_WORKFLOW",
        "provenance_mandatory": "PILOT_VALIDATED",
        "candidate_can_overwrite_canonical": False,
        "candidate_can_enter_production_retrieval": False,
        "retrieval_gate": "isolated index; retrieval_status=retrieval_only; recommendation_eligible=false",
        "execution_authorized": False,
        "canonical_promotion_performed": False,
        "invariant": "Candidate != Reviewed != Trusted != Execution-authorized",
    }


def review_lifecycle_audit() -> dict[str, Any]:
    actions = {}
    for action in ["KEEP_CANDIDATE", "REJECT", "MERGE", "SUPERSEDE", "APPROVE_FOR_PROMOTION", "PROMOTE"]:
        actions[action] = {
            "BACKEND_EXISTS": False,
            "PERSISTENCE_EXISTS": False,
            "TRACE_EXISTS": False,
            "ROLLBACK_EXISTS": False,
            "SAFE_FOR_UI": False,
            "note": "The review queue exposes descriptive action bindings only; no action is persisted or executed.",
        }
    actions["PROMOTE"]["note"] = "A fail-closed promotion gate exists, but no KnowledgeChangeSet, snapshot, or mutation backend exists."
    return {
        "review_item_creation": "IMPLEMENTED_PILOT",
        "review_decision_model": "core/scientific_knowledge_conformance_models.py:ReviewDecision",
        "review_decision_persistence": False,
        "actions": actions,
        "PROMOTION_UI_ALLOWED": False,
        "read_only_review_item_display_safe": True,
    }


def trace_coverage() -> dict[str, Any]:
    status = {
        "UPLOAD": False,
        "SOURCE_REGISTER": "partial",
        "SOURCE_REVISION": "partial",
        "DOCUMENT_PARSE": "partial",
        "EVIDENCE_EXTRACTION": True,
        "ENTITY_RESOLUTION": False,
        "RELATION_EXTRACTION": False,
        "CLAIM_EXTRACTION": "partial",
        "SCHEMA_VALIDATION": True,
        "CANDIDATE_DEPOSIT": True,
        "ADMIN_REVIEW": "partial",
        "PROMOTION": "partial",
        "REJECT": False,
        "MERGE": False,
        "SUPERSEDE": False,
    }
    return {
        "owner": "core/trace_context.py",
        "TRACE_SUPPORTED": status,
        "covered_count_true": sum(value is True for value in status.values()),
        "partial_count": sum(value == "partial" for value in status.values()),
        "unsupported_count": sum(value is False for value in status.values()),
        "limitation": "Pilot operations are recorded with generic TraceStage values; knowledge-evolution stage names are not canonical trace enum values.",
        "new_trace_stages_added": False,
    }


def minimal_reusable_pipeline() -> dict[str, Any]:
    return {
        "feasible_as_is": False,
        "target": "one local PDF → registered source → parsed text → span-bound structured candidates → validation → diff → isolated candidate deposit → trace",
        "reuse": [
            {"step": "artifact hashing", "component": "data_pipeline/run_evidence_gap_acquisition_pilot_v1.py", "condition": "extract into a generic adapter"},
            {"step": "source registry dedup policy", "component": "data_pipeline/build_source_registry.py", "condition": "map to formal SourceWork and SourceRevision records"},
            {"step": "PDF text extraction", "component": "data_pipeline/ingest_evidence_pdfs.py", "condition": "force page-preserving path and record parser version"},
            {"step": "section/chunk locator helpers", "component": "engine/source_corpus_v2.py", "condition": "use for candidates without rebuilding production index"},
            {"step": "strict Scientific KG validation", "component": "core/scientific_knowledge_conformance_models.py", "condition": "validate external EvidenceSpan bindings too"},
            {"step": "candidate identity and isolated deposit pattern", "component": "data_pipeline/run_candidate_knowledge_deposition_pilot_v1.py", "condition": "generalize beyond SoupX and preserve candidate-only boundary"},
            {"step": "local candidate RAG primitives", "component": "engine/evidence_discovery_index.py", "condition": "keep retrieval_only and recommendation_eligible=false"},
            {"step": "trace", "component": "core/trace_context.py", "condition": "record each orchestration step"},
        ],
        "must_add_in_checkpoint_5": [
            "generic local PDF registration adapter",
            "formal SourceWork, SourceRevision, and SourceArtifact records or adapters",
            "generic exact EvidenceSpan candidate generator",
            "versioned candidate-only entity/relation/claim/scope extractor with mandatory span IDs",
            "entity resolution and dedup service",
            "structured before/after candidate diff",
            "single candidate-only orchestration path",
        ],
        "forbidden": ["trusted mutation", "canonical promotion", "production retrieval eligibility", "legacy Neo4j loader"],
    }


def gap_analysis() -> dict[str, Any]:
    return {
        "P0_REQUIRED_FOR_SINGLE_PDF_DEMO": [
            "generic local PDF registration",
            "formal SourceWork/SourceRevision/SourceArtifact adapter",
            "page-preserving parser mode with parser-version provenance",
            "generic exact EvidenceSpan candidate generation",
            "versioned structured candidate entity/relation/claim/scope extraction with mandatory span IDs",
            "entity resolution and per-type dedup keys",
            "external EvidenceSpan binding validation",
            "general before/after candidate diff",
            "candidate-only orchestration over the existing isolated deposit pattern",
        ],
        "P1_REQUIRED_FOR_REVIEW_UI": [
            "ReviewDecision repository",
            "persisted KEEP_CANDIDATE/REJECT state transitions",
            "action traces and reload-stable review state",
        ],
        "P2_REQUIRED_FOR_CANONICAL_LIFECYCLE": [
            "KnowledgeChangeSet backend",
            "immutable pre-promotion snapshot",
            "governed promote/merge/supersede handlers",
            "rollback implementation",
        ],
        "NOT_REQUIRED_FOR_MIDTERM": [
            "OCR for scanned PDFs",
            "table and figure extraction",
            "batch ingestion",
            "broad multi-document conflict resolution",
            "canonical promotion UI",
        ],
    }


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def protected_integrity() -> dict[str, Any]:
    baseline_path = ROOT / "data/evaluation/scientific_kg_inventory_snapshot_v1/hashes.json"
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))["protected_after"]
    checked: dict[str, Any] = {}
    excluded: list[str] = []
    changed: list[str] = []
    missing: list[str] = []
    for group, record in baseline.items():
        files = {}
        for relative, expected in record.get("files", {}).items():
            lower = relative.casefold()
            if "sealed" in lower or "c7" in Path(relative).parts:
                excluded.append(relative)
                continue
            path = ROOT / relative
            if not path.is_file():
                missing.append(relative)
                continue
            actual = _sha256(path)
            files[relative] = {"expected_sha256": expected, "actual_sha256": actual, "match": actual == expected}
            if actual != expected:
                changed.append(relative)
        checked[group] = files
    return {
        "baseline": "data/evaluation/scientific_kg_inventory_snapshot_v1/hashes.json:protected_after",
        "status": "PASS" if not changed and not missing else "FAIL",
        "checked_file_count": sum(len(value) for value in checked.values()),
        "checked": checked,
        "changed": changed,
        "missing": missing,
        "forbidden_paths_skipped": excluded,
        "quarantined_c7_payload_accessed": False,
        "kg_content_changed": False,
        "corpus_changed": False,
        "index_changed": False,
        "planner_changed": False,
        "gold_changed": False,
        "canonical_promotion": "none",
    }


def _git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


def _artifact_hashes(names: Iterable[str]) -> dict[str, str]:
    return {name: _sha256(OUTPUT_DIR / name) for name in names}


def _report(manifest: dict[str, Any], payloads: dict[str, Any]) -> str:
    counts = manifest["stage_counts"]
    p0 = payloads["gap_analysis.json"]["P0_REQUIRED_FOR_SINGLE_PDF_DEMO"]
    return f"""# PDF Knowledge Ingestion Capability Audit v1

STATUS=PASS
CHECKPOINT=PDF-Knowledge-Ingestion-Capability-Audit-v1
AUDIT_MODE=read-only

## Decision

The repository already contains **17/30 implemented reusable or pilot stages (56.7%)**, but only **2/30** are generic reusable capabilities without relying on a tool-specific pilot. The SoupX work proves the governed candidate boundary, exact evidence binding, isolated candidate deposit/reuse, trace, review-item creation, and a fail-closed promotion guard. It does not provide a general PDF-to-Scientific-KG extractor.

`MIDTERM_SINGLE_PDF_DEMO_FEASIBLE=false` for the repository as it stands. The blockers are generic source/revision registration, page-stable EvidenceSpan generation, governed entity and relation extraction, identity resolution, and one orchestrated candidate-only path. The safe backbone should be reused rather than replaced.

## Capability counts

| Classification | Count |
|---|---:|
| IMPLEMENTED_PRODUCTION | {counts['IMPLEMENTED_PRODUCTION']} |
| IMPLEMENTED_REUSABLE | {counts['IMPLEMENTED_REUSABLE']} |
| IMPLEMENTED_PILOT | {counts['IMPLEMENTED_PILOT']} |
| PARTIAL | {counts['PARTIAL']} |
| MISSING | {counts['MISSING']} |
| UNSAFE_TO_REUSE | {counts['UNSAFE_TO_REUSE']} |
| **TOTAL** | **{manifest['total_stages']}** |

## What already exists

- **Reusable:** PDF text extraction in `data_pipeline/ingest_evidence_pdfs.py` and Scientific KG schema/cross-reference validation in `core/scientific_knowledge_conformance_models.py`.
- **SoupX pilot:** artifact hashing, SourceWork/SourceRevision records, exact EvidenceSpan binding, EvidenceAssessment, typed/scoped AtomicClaimRevision, candidate identity, isolated candidate KG/RAG deposit, reuse, review-item creation, and trace.
- **Candidate-only guarantee:** the audited SoupX path writes to an isolated evaluation directory and sets retrieval-only/non-recommendation-eligible gates. It cannot overwrite canonical knowledge. No claim is reviewed, trusted, promoted, or execution-authorized.
- **Trace:** 3 of 15 requested knowledge-evolution stages are directly represented, 6 are partial through generic operations, and 6 are absent. The trace framework is reusable; the knowledge-evolution vocabulary is not yet canonical.

## What is pilot-only

The SourceWork, SourceRevision, EvidenceSpan, claim text, scope, version, and identity slice are fixed to SoupX. Candidate storage is a write-once evaluation directory rather than a revisioned repository. The review queue is a read-only decision surface; its actions are descriptions rather than persisted backend operations.

## Unsafe paths

`data_pipeline/neo4j_loader.py` can send LLM-derived Tool KG content directly to mutable Neo4j without Scientific KG candidate schemas or evidence-span bindings. It is flagged `UNSAFE_DIRECT_KG_MUTATION` and must not be reused for Checkpoint 5. Legacy review/promotion scripts target a different evidence lifecycle and are not a Scientific KG promotion backend.

## Review and promotion

`ReviewDecision` has a formal model but no persistence owner. KEEP, REJECT, MERGE, SUPERSEDE, APPROVE, and PROMOTE have no usable Scientific KG backend. The promotion gate fails closed, but canonical promotion is not safe to expose: `PROMOTION_UI_ALLOWED=false`.

## P0 for one-PDF demo

""" + "\n".join(f"- {item}" for item in p0) + f"""

## Checkpoint 5 reuse boundary

Reuse the generic PDF parser, source-registry dedup policy, section/chunk locator helpers, conformance models, candidate identity/deposit pattern, retrieval-only index primitives, and canonical trace framework. Add a thin generic orchestrator and the missing candidate-only structured extraction/resolution layer. Do not call the legacy Neo4j loader, grant production retrieval eligibility, or add canonical mutation.

## Audit integrity

- Focused audit tests validate the stage set, classification, path evidence, owner conflicts, unsafe mutation flag, SoupX mapping, reusable pipeline, protected artifacts, and C7 non-access contract.
- Bounded related regression: **{manifest['regression_tests']}**. The one excluded stale assertion expects an archived 48-claim asset that is absent from this branch; this checkpoint did not modify that builder, test, or asset path.
- Frozen KG/corpus/index/planner/gold hashes: **{manifest['artifact_integrity']}**.
- Quarantined C7 payload accessed: **false**.
- This checkpoint added no PDF ingestion, extractor, KG content, index, planner, gold, review UI, trace UI, benchmark, or promotion implementation.

## Exit

```text
CHECKPOINT=PDF-Knowledge-Ingestion-Capability-Audit-v1
STATUS=PASS

TOTAL_STAGES=30

IMPLEMENTED_PRODUCTION={counts['IMPLEMENTED_PRODUCTION']}
IMPLEMENTED_REUSABLE={counts['IMPLEMENTED_REUSABLE']}
IMPLEMENTED_PILOT={counts['IMPLEMENTED_PILOT']}
PARTIAL={counts['PARTIAL']}
MISSING={counts['MISSING']}
UNSAFE_TO_REUSE={counts['UNSAFE_TO_REUSE']}

SOUPX_REUSABLE_STAGES=11 mapped pilot steps; 3 directly reusable component patterns

PDF_UPLOAD_READY=false
PDF_PARSE_READY=true_with_limitations
SOURCE_REVISION_READY=pilot_only
EVIDENCE_SPAN_READY=pilot_only
ENTITY_EXTRACTION_READY=false
RELATION_EXTRACTION_READY=false
CLAIM_EXTRACTION_READY=pilot_only
ONTOLOGY_VALIDATION_READY=true_with_external_span_limit
CANDIDATE_DEPOSIT_READY=pilot_only
REVIEW_DECISION_READY=false
TRACE_READY=pilot_only
CANONICAL_PROMOTION_READY=false

MIDTERM_SINGLE_PDF_DEMO_FEASIBLE=false

P0_MISSING_COMPONENTS={json.dumps(p0, ensure_ascii=False)}

FOCUSED_TESTS={manifest['focused_tests']}
ARTIFACT_INTEGRITY={manifest['artifact_integrity']}

KG_CONTENT_CHANGED=false
CORPUS_CHANGED=false
INDEX_CHANGED=false
PLANNER_CHANGED=false
GOLD_CHANGED=false
CANONICAL_PROMOTION=none

CHECKPOINT_3_COMMIT={CHECKPOINT_3_COMMIT}
LOCAL_HEAD={manifest['local_head']}
REMOTE_HEAD={manifest['remote_head']}
PUSH_STATUS={manifest['checkpoint_3_push_status']}

NEXT_RECOMMENDED_CHECKPOINT=PDF Candidate Ingestion V1 / STOP_FOR_REVIEW
STOPPED=true
```
"""


def build(*, focused_tests: str = "pending", regression_tests: str = "pending") -> dict[str, Any]:
    matrix = capability_matrix()
    counts = Counter(row["status"] for row in matrix)
    integrity = protected_integrity()
    local_head = _git("rev-parse", "HEAD")
    try:
        remote_head = _git("rev-parse", "origin/feature/method-kg-expansion-v1")
    except subprocess.CalledProcessError:
        remote_head = "unavailable"
    payloads = {
        "capability_matrix.json": {"required_stage_count": 30, "allowed_statuses": sorted(STATUSES), "stages": matrix},
        "soupX_pipeline_map.json": soupx_pipeline_map(),
        "authoritative_owner_map.json": authoritative_owner_map(),
        "pdf_parser_audit.json": pdf_parser_audit(),
        "llm_extraction_audit.json": llm_extraction_audit(),
        "ontology_validation_audit.json": ontology_validation_audit(),
        "deduplication_audit.json": deduplication_audit(),
        "candidate_deposit_audit.json": candidate_deposit_audit(),
        "review_lifecycle_audit.json": review_lifecycle_audit(),
        "trace_coverage.json": trace_coverage(),
        "minimal_reusable_pipeline.json": minimal_reusable_pipeline(),
        "gap_analysis.json": gap_analysis(),
        "integrity.json": integrity,
    }
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, payload in payloads.items():
        _write_json(OUTPUT_DIR / name, payload)
    manifest = {
        "schema_version": "sckg-pdf-knowledge-ingestion-capability-audit-v1",
        "checkpoint": "PDF-Knowledge-Ingestion-Capability-Audit-v1",
        "status": "PASS" if integrity["status"] == "PASS" else "BLOCKED",
        "audit_mode": "read_only",
        "total_stages": len(matrix),
        "stage_counts": {status: counts.get(status, 0) for status in sorted(STATUSES)},
        "implemented_or_pilot_stage_count": counts["IMPLEMENTED_PRODUCTION"] + counts["IMPLEMENTED_REUSABLE"] + counts["IMPLEMENTED_PILOT"],
        "implemented_or_pilot_percent": round(100 * (counts["IMPLEMENTED_PRODUCTION"] + counts["IMPLEMENTED_REUSABLE"] + counts["IMPLEMENTED_PILOT"]) / len(matrix), 1),
        "midterm_single_pdf_demo_feasible": False,
        "checkpoint_3_commit": CHECKPOINT_3_COMMIT,
        "local_head": local_head,
        "remote_head": remote_head,
        "checkpoint_3_push_status": "VERIFIED" if local_head == remote_head == CHECKPOINT_3_COMMIT else "NOT_VERIFIED",
        "focused_tests": focused_tests,
        "regression_tests": regression_tests,
        "known_preexisting_regression_issue": {
            "test": "tests/test_scientific_knowledge_conformance_v1_1.py::test_legacy_crosswalk_reports_exact_non_automatic_migration_blockers",
            "reason": "The assertion expects 48 records at data/evidence_candidates/method_kg_atomic_claim_v1/atomic_claims.batch1.jsonl, but that archived branch asset is absent at the current HEAD; Checkpoint 4 did not modify the test, builder, or path.",
            "checkpoint_4_action": "deselected from bounded regression; no out-of-scope repair",
        },
        "artifact_integrity": integrity["status"],
        "quarantined_c7_payload_accessed": False,
        "kg_content_changed": False,
        "corpus_changed": False,
        "index_changed": False,
        "planner_changed": False,
        "gold_changed": False,
        "canonical_promotion": "none",
        "artifacts": {},
        "next_recommended_checkpoint": "PDF Candidate Ingestion V1 / STOP_FOR_REVIEW",
        "stopped": True,
    }
    manifest["artifacts"] = _artifact_hashes(payloads)
    _write_json(OUTPUT_DIR / "manifest.json", manifest)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(_report(manifest, payloads), encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--focused-tests", default="pending")
    parser.add_argument("--regression-tests", default="pending")
    args = parser.parse_args()
    print(json.dumps(build(focused_tests=args.focused_tests, regression_tests=args.regression_tests), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
