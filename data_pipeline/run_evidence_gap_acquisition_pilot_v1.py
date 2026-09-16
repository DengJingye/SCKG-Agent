from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from core.trace_context import TraceCollector, TraceContext, TraceKind, TraceStage
from data_pipeline.download_evidence_pdfs import download_first_valid_pdf
from data_pipeline.ingest_evidence_pdfs import extract_pdf_text


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT_ROOT = (
    PROJECT_ROOT / "data" / "evaluation" / "evidence_gap_acquisition_pilot_v1"
)
CORE_GAPS = (
    PROJECT_ROOT
    / "data"
    / "evidence_candidates"
    / "scientific_kg_v1_core"
    / "evidence_gaps.json"
)
CORE_SOURCE_MANIFEST = (
    PROJECT_ROOT
    / "data"
    / "evidence_candidates"
    / "scientific_kg_v1_core"
    / "source_manifest.json"
)

PILOT_GAP_ID = "evidence-gap:v1-core:soupx:droplet-profile"
PILOT_ECOSYSTEM = "SoupX"
PILOT_VERSION = "1.6.2"
SCHEMA_VERSION = "sckg-evidence-gap-acquisition-pilot-v1"
SOURCE_WORK_ID = "source-work:soupx:official-manual"
SOURCE_REVISION_ID = "source-revision:soupx:official-manual:1.6.2"
EVIDENCE_SPAN_ID = "evidence-span:cp5:soupx:soupchannel-inputs:1.6.2"
SOURCE_TITLE = "SoupX package manual"
SPAN_PATTERN = re.compile(
    r"tod\s+Table of droplets\.\s+A matrix with columns being each droplet and rows each\s+"
    r"gene\.\s+toc\s+Table of counts\.\s+Just those columns of tod that contain cells\.",
    re.IGNORECASE,
)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def architecture_inventory() -> list[dict[str, str]]:
    return [
        {
            "component": "data_pipeline.evidence_candidate_crawler.CrossrefClient",
            "responsibility": "Crossref DOI and publication-metadata discovery",
            "status": "usable_as_is",
        },
        {
            "component": "data_pipeline.download_evidence_pdfs",
            "responsibility": "Open PDF discovery via direct URL, Crossref, DOI landing pages and optional Unpaywall",
            "status": "usable_as_is",
        },
        {
            "component": "data_pipeline.fetch_evidence_sources",
            "responsibility": "Official HTML/text and GitHub README acquisition",
            "status": "usable_as_is",
        },
        {
            "component": "data_pipeline.ingest_evidence_pdfs",
            "responsibility": "PDF text extraction with existing Poppler/pypdf fallbacks",
            "status": "usable_as_is",
        },
        {
            "component": "data_pipeline.build_source_registry",
            "responsibility": "Canonical source-key normalization, deduplication and validation status",
            "status": "usable_as_is",
        },
        {
            "component": "engine.source_corpus_v2 + data_pipeline.build_evidence_index",
            "responsibility": "Source-bound RAG corpus and evidence index construction",
            "status": "usable_as_is_not_invoked_in_cp5",
        },
        {
            "component": "Scientific KG v1.1 provenance contract",
            "responsibility": "SourceWork to SourceRevision to EvidenceSpan identity boundary",
            "status": "needs_thin_acquisition_adapter",
        },
        {
            "component": "core.trace_context",
            "responsibility": "Bounded request, retrieval, decision and validation audit trail",
            "status": "usable_as_is",
        },
    ]


def load_selected_gap(path: Path = CORE_GAPS) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = [row for row in payload.get("gaps", []) if row.get("gap_id") == PILOT_GAP_ID]
    if len(rows) != 1:
        raise ValueError("pilot_evidence_gap_not_unique")
    gap = rows[0]
    return {
        **gap,
        "search_intent": (
            "Resolve version-pinned SoupChannel droplet-table and filtered-count-table input semantics."
        ),
        "expected_evidence_type": "official versioned package manual",
    }


def discover_authoritative_source(path: Path = CORE_SOURCE_MANIFEST) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = [
        row
        for row in payload.get("sources", [])
        if row.get("ecosystem") == PILOT_ECOSYSTEM
        and row.get("authority") == "official"
        and row.get("version") == PILOT_VERSION
    ]
    if len(rows) != 1:
        raise ValueError("authoritative_source_not_unique")
    source = rows[0]
    if not str(source.get("source_uri", "")).lower().endswith(".pdf"):
        raise ValueError("authoritative_source_is_not_open_pdf")
    return source


def source_identity(source: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    work = {
        "record_type": "SourceWork",
        "source_work_id": SOURCE_WORK_ID,
        "canonical_title": SOURCE_TITLE,
        "ecosystem": PILOT_ECOSYSTEM,
        "authority": "official",
        "official_url": source["source_uri"],
    }
    revision = {
        "record_type": "SourceRevision",
        "source_revision_id": SOURCE_REVISION_ID,
        "source_work_id": SOURCE_WORK_ID,
        "version": PILOT_VERSION,
        "source_date": "2022-11-01",
        "official_url": source["source_uri"],
        "access": "open",
    }
    return work, revision


def extract_bounded_span(text: str) -> dict[str, Any]:
    match = SPAN_PATTERN.search(text)
    if match is None:
        raise ValueError("bounded_evidence_span_not_found")
    exact = " ".join(match.group(0).split())
    return {
        "record_type": "EvidenceSpan",
        "schema_version": SCHEMA_VERSION,
        "evidence_span_id": EVIDENCE_SPAN_ID,
        "source_revision_id": SOURCE_REVISION_ID,
        "locator": "PDF page 24; SoupChannel; Arguments: tod and toc",
        "text_offset_start": match.start(),
        "text_offset_end": match.end(),
        "exact_text": exact,
        "content_hash": sha256_bytes(exact.encode("utf-8")),
        "candidate_only": True,
        "review_status": "candidate_pending_review",
    }


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def record_stage(
    instrumentation: Any,
    audit: list[dict[str, Any]],
    *,
    stage: TraceStage,
    operation: str,
    input_ref: tuple[str, str] | None,
    output_ref: tuple[str, str],
    reused: bool = False,
) -> None:
    input_refs = []
    if input_ref:
        input_refs.append(
            {"record_type": input_ref[0], "record_id": input_ref[1], "relation": "input"}
        )
    with instrumentation.span(
        stage=stage,
        component="evidence_acquisition",
        operation=operation,
        input_refs=input_refs,
    ) as span:
        span.add_output_ref(
            record_type=output_ref[0], record_id=output_ref[1], relation="produced"
        )
        span.set_counter("reused", 1 if reused else 0)
    audit.append(
        {
            "stage": stage.value,
            "operation": operation,
            "status": "SUCCESS",
            "input_ref": list(input_ref) if input_ref else None,
            "output_ref": list(output_ref),
            "reused": reused,
        }
    )


def run_pilot(
    *,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    mode: str,
    session: requests.Session | None = None,
) -> dict[str, Any]:
    if mode not in {"acquire", "reuse"}:
        raise ValueError("unsupported_pilot_mode")
    output_root = output_root.resolve()
    registry_path = output_root / "source_registry.json"
    artifact_dir = output_root / "artifacts"
    text_dir = output_root / "extracted"
    run_dir = output_root / "runs" / mode
    if run_dir.exists():
        raise FileExistsError(f"pilot_run_already_exists:{mode}")
    if mode == "acquire" and registry_path.exists():
        raise FileExistsError("pilot_source_registry_already_exists")
    if mode == "reuse" and not registry_path.exists():
        raise FileNotFoundError("pilot_source_registry_missing")

    gap = load_selected_gap()
    source = discover_authoritative_source()
    work, revision = source_identity(source)
    audit: list[dict[str, Any]] = []
    trace_path = run_dir / "trace.jsonl"
    trace = TraceContext.new_request(
        trace_kind=TraceKind.RESEARCH,
        request_id=f"cp5-{mode}-soupx-gap",
        conversation_id="cp5-evidence-acquisition-pilot",
    )
    collector = TraceCollector(trace_path)
    instrumentation = trace.instrumentation()

    with collector.request_scope(trace):
        record_stage(
            instrumentation,
            audit,
            stage=TraceStage.STATE_INSPECTION,
            operation="detect_evidence_gap",
            input_ref=None,
            output_ref=("EvidenceGap", PILOT_GAP_ID),
        )
        record_stage(
            instrumentation,
            audit,
            stage=TraceStage.RETRIEVAL,
            operation="discover_authoritative_source",
            input_ref=("EvidenceGap", PILOT_GAP_ID),
            output_ref=("SourceWork", SOURCE_WORK_ID),
            reused=mode == "reuse",
        )
        record_stage(
            instrumentation,
            audit,
            stage=TraceStage.DECISION,
            operation="resolve_source_identity",
            input_ref=("SourceWork", SOURCE_WORK_ID),
            output_ref=("SourceRevision", SOURCE_REVISION_ID),
            reused=mode == "reuse",
        )

        if mode == "acquire":
            target = artifact_dir / "soupx-1.6.2-manual.pdf"
            candidates = [{"url": source["source_uri"], "source": "direct_pdf_url"}]
            active_session = session or requests.Session()
            active_session.headers.update(
                {"User-Agent": "scKG-Agent bounded evidence-gap acquisition pilot"}
            )
            downloaded = download_first_valid_pdf(
                candidates, target, session=active_session, timeout=30
            )
            if downloaded.get("status") != "downloaded":
                raise RuntimeError("authoritative_artifact_acquisition_failed")
            artifact_hash = sha256_file(target)
            artifact_id = f"source-artifact:sha256:{artifact_hash}"
            extracted = extract_pdf_text(target)
            if not extracted.get("ok"):
                raise RuntimeError("authoritative_artifact_parsing_failed")
            text = str(extracted["text"])
            text_path = text_dir / "soupx-1.6.2-manual.txt"
            text_path.parent.mkdir(parents=True, exist_ok=True)
            text_path.write_text(text, encoding="utf-8")
            artifact = {
                "record_type": "SourceArtifact",
                "source_artifact_id": artifact_id,
                "source_revision_id": SOURCE_REVISION_ID,
                "artifact_type": "application/pdf",
                "acquisition_url": source["source_uri"],
                "sha256": artifact_hash,
                "byte_size": target.stat().st_size,
                "acquired_at": datetime.now(timezone.utc).isoformat(),
                "local_path": str(target.relative_to(output_root)),
                "extracted_text_path": str(text_path.relative_to(output_root)),
                "extracted_text_sha256": sha256_file(text_path),
                "page_count": int(extracted.get("page_count") or 0),
                "extraction_method": str(extracted.get("extractor") or "unknown"),
            }
            registry = {
                "schema_version": SCHEMA_VERSION,
                "source_works": [work],
                "source_revisions": [revision],
                "source_artifacts": [artifact],
            }
            write_json(registry_path, registry)
        else:
            registry = read_json(registry_path)
            if len(registry.get("source_works", [])) != 1 or len(registry.get("source_revisions", [])) != 1:
                raise ValueError("source_identity_deduplication_failed")
            if registry["source_works"][0] != work or registry["source_revisions"][0] != revision:
                raise ValueError("source_identity_drift")
            if len(registry.get("source_artifacts", [])) != 1:
                raise ValueError("source_artifact_deduplication_failed")
            artifact = registry["source_artifacts"][0]
            target = output_root / artifact["local_path"]
            text_path = output_root / artifact["extracted_text_path"]
            if sha256_file(target) != artifact["sha256"]:
                raise ValueError("source_artifact_integrity_failed")
            if sha256_file(text_path) != artifact["extracted_text_sha256"]:
                raise ValueError("extracted_text_integrity_failed")
            text = text_path.read_text(encoding="utf-8")

        artifact_id = artifact["source_artifact_id"]
        record_stage(
            instrumentation,
            audit,
            stage=TraceStage.RETRIEVAL,
            operation="acquire_source_artifact",
            input_ref=("SourceRevision", SOURCE_REVISION_ID),
            output_ref=("SourceArtifact", artifact_id),
            reused=mode == "reuse",
        )
        record_stage(
            instrumentation,
            audit,
            stage=TraceStage.VALIDATION,
            operation="verify_artifact_integrity",
            input_ref=("SourceArtifact", artifact_id),
            output_ref=("SourceArtifact", artifact_id),
            reused=mode == "reuse",
        )
        span = extract_bounded_span(text)
        span["source_artifact_id"] = artifact_id
        record_stage(
            instrumentation,
            audit,
            stage=TraceStage.VALIDATION,
            operation="extract_evidence_span",
            input_ref=("SourceArtifact", artifact_id),
            output_ref=("EvidenceSpan", EVIDENCE_SPAN_ID),
            reused=mode == "reuse",
        )

    write_json(output_root / "architecture_inventory.json", architecture_inventory())
    write_json(output_root / "selected_evidence_gap.json", gap)
    write_json(output_root / "evidence_span.json", span)
    report = {
        "schema_version": SCHEMA_VERSION,
        "mode": mode,
        "status": "PASS",
        "gap_id": PILOT_GAP_ID,
        "source_work_id": SOURCE_WORK_ID,
        "source_revision_id": SOURCE_REVISION_ID,
        "source_artifact_id": artifact_id,
        "evidence_span_id": EVIDENCE_SPAN_ID,
        "artifact_sha256": artifact["sha256"],
        "evidence_span_sha256": span["content_hash"],
        "source_identity_reused": mode == "reuse",
        "artifact_reused": mode == "reuse",
        "canonical_claim_created": False,
        "canonical_kg_modified": False,
        "planner_modified": False,
        "audit_path": audit,
        "trace_path": str(trace_path.relative_to(output_root)),
    }
    write_json(run_dir / "report.json", report)
    write_json(
        output_root / "summary.json",
        {
            "schema_version": SCHEMA_VERSION,
            "pilot_status": "PASS",
            "gap_count": 1,
            "source_work_count": len(registry["source_works"]),
            "source_revision_count": len(registry["source_revisions"]),
            "source_artifact_count": len(registry["source_artifacts"]),
            "evidence_span_count": 1,
            "deduplication_verified": mode == "reuse",
            "promotion_performed": False,
            "latest_run": mode,
        },
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the bounded CP5 EvidenceGap acquisition pilot."
    )
    parser.add_argument("--mode", choices=("acquire", "reuse"), required=True)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    args = parser.parse_args()
    report = run_pilot(output_root=args.output_root, mode=args.mode)
    print(canonical_json(report))


if __name__ == "__main__":
    main()
