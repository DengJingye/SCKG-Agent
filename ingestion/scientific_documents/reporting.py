from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from .models import BlockType, FinalDisposition, HumanReviewPacket, PropositionType, ScopeValueStatus


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _fence(value: str) -> str:
    return f"```text\n{value}\n```"


def regression_checks(result: dict[str, object]) -> dict[str, bool]:
    packets: list[HumanReviewPacket] = list(result["packets"])  # type: ignore[arg-type]
    reconstructed = list(result["reconstructed_blocks"])  # type: ignore[arg-type]

    index_rows = [packet for packet in packets if re.search(r"(?m)^Index\s+\d+\s*$", packet.raw_block)]
    example_rows = [packet for packet in packets if packet.block_type == BlockType.EXAMPLES_CODE]
    value_rows = [
        packet
        for packet in packets
        if packet.raw_proposition is not None
        and packet.raw_proposition.proposition_type == PropositionType.RETURN_VALUE
        and packet.raw_proposition.operator_name == "adjustCounts"
    ]
    method_rows = [
        packet
        for packet in packets
        if packet.raw_proposition is not None
        and packet.raw_proposition.proposition_type == PropositionType.PARAMETER_DESCRIPTION
        and packet.raw_proposition.operator_name == "adjustCounts"
        and packet.raw_proposition.parameter_name == "method"
    ]
    ready = [packet for packet in packets if packet.final_disposition == FinalDisposition.CANDIDATE_READY]
    ready_canonical = [packet.canonical_statement for packet in ready if packet.canonical_statement is not None]
    scoped = [packet for packet in packets if packet.scope is not None]
    condition_rows = [
        packet
        for packet in packets
        if packet.raw_proposition is not None
        and packet.raw_proposition.proposition_type == PropositionType.CONDITION
    ]

    checks = {
        "layout_blocks": int(result["summary"]["layout_block_count"]) > 0,  # type: ignore[index]
        "text_reconstruction": all("\n" not in block.normalized_text for block in reconstructed),
        "dehyphenation": any(
            "contamina-\ntion" in block.raw_text and "contamination" in block.normalized_text
            for block in reconstructed
        ),
        "index_toc_filter": bool(index_rows)
        and all(packet.block_type == BlockType.TOC and packet.final_disposition == FinalDisposition.DROPPED for packet in index_rows),
        "code_example_filter": bool(example_rows)
        and all(
            packet.raw_proposition is None
            and packet.canonical_statement is None
            and packet.final_disposition == FinalDisposition.DROPPED
            for packet in example_rows
        ),
        "truncation_filter": any(
            packet.final_disposition == FinalDisposition.ABSTAINED
            and packet.raw_proposition is not None
            and not packet.raw_proposition.is_complete
            for packet in packets
        ),
        "raw_claim_separated": all(
            packet.raw_proposition is None
            or packet.canonical_statement is None
            or packet.raw_proposition.proposition_id != packet.canonical_statement.canonical_candidate_id
            for packet in packets
        ),
        "entity_linking": any(
            entity.resolution_status == "EXACT_EXISTING_IDENTITY"
            and not entity.fuzzy_merge_used
            for packet in packets
            for entity in packet.linked_entities
        )
        and all(not entity.fuzzy_merge_used for packet in packets for entity in packet.linked_entities),
        "operator_context": bool(method_rows)
        and all(any(entity.context_role == "operator" for entity in packet.linked_entities) for packet in method_rows),
        "return_value_mapping": bool(value_rows)
        and any(
            packet.canonical_statement is not None
            and packet.canonical_statement.canonical_kind == "STRUCTURAL_OUTPUT_BINDING"
            and packet.canonical_statement.predicate == "output_type"
            and packet.canonical_statement.subject_type == "OutputPort"
            and packet.canonical_statement.object_type == "RepresentationType"
            and not packet.canonical_statement.is_scientific_statement
            for packet in value_rows
        ),
        "parameter_context": bool(method_rows)
        and all(
            packet.canonical_statement is not None
            and packet.canonical_statement.predicate == "has_parameter"
            and packet.raw_proposition is not None
            and packet.raw_proposition.parameter_name == "method"
            for packet in method_rows
        ),
        "parameter_semantics": bool(method_rows)
        and all(
            packet.canonical_statement is not None
            and packet.canonical_statement.object_record is not None
            and bool(packet.canonical_statement.object_record.get("value_domain", {}).get("allowed_values"))
            for packet in method_rows
        ),
        "operator_identity_recovery": any(
            item.predicate == "revision_of"
            and item.subject_id == "operator-revision:soupx.soupx__adjustcounts:1.6.2"
            and item.object_id == "operator:soupx.soupx__adjustcounts"
            for item in ready_canonical
        ),
        "capability_mapping": any(
            item.predicate == "implements_method"
            and item.object_id == "method:ambient_count_correction"
            for item in ready_canonical
        )
        and any(
            item.predicate == "supports_task"
            and item.object_id == "task:ambient_rna_removal"
            for item in ready_canonical
        ),
        "condition_handling": bool(condition_rows)
        and all(
            packet.canonical_statement is None
            and packet.final_disposition == FinalDisposition.EVIDENCE_ONLY
            and len(packet.evidence_gaps) == 1
            for packet in condition_rows
        )
        and any(
            item.predicate == "has_requirement"
            and item.object_id == "requirement:v1-core:soupx:soupx__adjustcounts:input2"
            for item in ready_canonical
        ),
        "bounded_evidence": all(
            packet.evidence_span is None
            or (
                packet.evidence_span.bounded
                and packet.evidence_span.page_end_offset > packet.evidence_span.page_start_offset
                and packet.evidence_span.content_hash
            )
            for packet in packets
        ),
        "source_context_scope": bool(scoped)
        and all(
            any(
                value.dimension == "method_operator_version"
                and value.status in {ScopeValueStatus.SOURCE_CONTEXT, ScopeValueStatus.INHERITED}
                and value.value == "1.6.2"
                for value in packet.scope.values
            )
            for packet in scoped
            if packet.raw_proposition and packet.raw_proposition.operator_name
        ),
        "scope_provenance": all(
            value.status in {ScopeValueStatus.UNKNOWN, ScopeValueStatus.NOT_APPLICABLE}
            or bool(value.provenance_ref)
            for packet in scoped
            for value in packet.scope.values
        ),
        "unknown_unsupported_scope": all(
            all(
                value.status == ScopeValueStatus.UNKNOWN
                for value in packet.scope.values
                if value.dimension in {"organism", "study_design"}
            )
            for packet in scoped
        ),
        "no_hallucinated_scope": sum(packet.scope.hallucinated_value_count for packet in scoped) == 0,
        "canonicalization": any(packet.canonical_statement is not None for packet in packets),
        "ready_has_no_whole_segment_evidence": all(
            packet.evidence_span is not None
            and packet.evidence_span.bounded
            and not packet.evidence_span.whole_segment
            for packet in ready
        ),
        "governance_defaults": all(
            packet.governance.human_review_status == "pending"
            and packet.governance.knowledge_status == "candidate"
            and packet.governance.trusted is False
            and packet.governance.production_retrieval_eligible is False
            and packet.governance.execution_authorized is False
            for packet in packets
        ),
        "candidate_recovery_minimum": len(ready_canonical) >= 4
        and len({(item.subject_id, item.predicate, item.object_id) for item in ready_canonical}) >= 4,
    }
    checks["soupx_regression"] = all(checks.values())
    return checks


def summary_payload(result: dict[str, object]) -> dict[str, object]:
    packets: list[HumanReviewPacket] = list(result["packets"])  # type: ignore[arg-type]
    checks = regression_checks(result)
    counts = Counter(packet.final_disposition.value for packet in packets)
    source = result["source"]
    ready_candidates = [
        {
            "subject": packet.canonical_statement.subject_id,
            "predicate": packet.canonical_statement.predicate,
            "object": packet.canonical_statement.object_id,
            "canonical_kind": packet.canonical_statement.canonical_kind,
            "evidence_span_id": packet.evidence_span.evidence_span_id if packet.evidence_span else None,
            "source_revision_id": packet.source.source_revision_id,
        }
        for packet in packets
        if packet.final_disposition == FinalDisposition.CANDIDATE_READY
        and packet.canonical_statement is not None
    ]
    ontology_gaps = [
        gap.model_dump(mode="json")
        for packet in packets
        for gap in packet.evidence_gaps
    ]
    return {
        "schema_version": "scientific-document-ingestion-regression-v1",
        "window": "09-Scientific-Document-Ingestion",
        "phase": "INGESTION-QUALITY-HARDENING",
        "source": source.model_dump(mode="json"),  # type: ignore[union-attr]
        "pipeline": result["summary"]["pipeline"],  # type: ignore[index]
        "ontology_version": result["summary"]["ontology_version"],  # type: ignore[index]
        "checks": checks,
        "counts": {status.value: counts.get(status.value, 0) for status in FinalDisposition},
        "ready_candidates": ready_candidates,
        "ontology_gaps": ontology_gaps,
        "unbounded_ready_candidates": result["summary"]["unbounded_ready_candidates"],  # type: ignore[index]
        "hallucinated_scope_count": result["summary"]["hallucinated_scope_count"],  # type: ignore[index]
        "governance": result["summary"]["governance"],  # type: ignore[index]
        "scientific_validity_assessed": False,
        "ontology_mutated": False,
        "approved_kg_mutated": False,
        "promotion_performed": False,
        "human_approval_performed": False,
    }


def render_before_after(result: dict[str, object]) -> str:
    source = result["source"]
    packets: list[HumanReviewPacket] = list(result["packets"])  # type: ignore[arg-type]
    summary = summary_payload(result)
    lines = [
        "# SoupX ingestion before / after",
        "",
        "> Candidate-only regression artifact. Structural conformance is not scientific validity, human approval, trust, or promotion.",
        "",
        "## Fixture",
        "",
        f"- File: `{source.filename}`",  # type: ignore[union-attr]
        f"- SHA256: `{source.sha256}`",  # type: ignore[union-attr]
        f"- Pages: `{source.page_count}`",  # type: ignore[union-attr]
        f"- Frozen ontology: `{result['summary']['ontology_version']}`",  # type: ignore[index]
        "- PDF binary: local-only, not committed",
        "",
        "## Before (audited legacy prototype)",
        "",
        "- Index/TOC and code examples could enter claim extraction.",
        "- Raw claims and canonical statements were conflated; objects could contain source paragraphs.",
        "- Evidence could be tagged `UNBOUNDED_WHOLE_SEGMENT_EVIDENCE`.",
        "- Operator/version inheritance and scope provenance were incomplete.",
        "- A single `VALID`/`INVALID` label could be read as scientific validity.",
        "",
        "## After (quality-hardened candidate pipeline)",
        "",
        f"- Dispositions: `{_json(summary['counts'])}`",
        f"- Regression checks: `{_json(summary['checks'])}`",
        f"- CANDIDATE_READY with whole-segment evidence: `{summary['unbounded_ready_candidates']}`",
        f"- Hallucinated scope values: `{summary['hallucinated_scope_count']}`",
        "- Statuses below are ingestion dispositions only; `scientific_validity_assessed=false`.",
        "",
        "## Human review packets",
        "",
    ]
    for index, packet in enumerate(packets, 1):
        proposition = packet.raw_proposition.model_dump(mode="json") if packet.raw_proposition else None
        entities = [item.model_dump(mode="json") for item in packet.linked_entities]
        canonical = packet.canonical_statement.model_dump(mode="json") if packet.canonical_statement else None
        scope = packet.scope.model_dump(mode="json") if packet.scope else None
        evidence = packet.evidence_span.model_dump(mode="json") if packet.evidence_span else None
        gaps = [item.model_dump(mode="json") for item in packet.evidence_gaps]
        lines.extend(
            [
                f"### {index}. {packet.block_type.value} → {packet.final_disposition.value}",
                "",
                "**raw block**",
                "",
                _fence(packet.raw_block),
                "",
                "**→ normalized block**",
                "",
                _fence(packet.normalized_block),
                "",
                f"**→ block type:** `{packet.block_type.value}`",
                "",
                f"**→ proposition:** `{_json(proposition)}`",
                "",
                f"**→ linked entities:** `{_json(entities)}`",
                "",
                f"**→ canonical statement / abstain:** `{_json(canonical)}`",
                "",
                f"**→ scope + provenance:** `{_json(scope)}`",
                "",
                f"**→ exact evidence:** `{_json(evidence)}`",
                "",
                f"**→ ontology gaps:** `{_json(gaps)}`",
                "",
                f"**→ stage status:** `{_json({key.value: value.value for key, value in packet.validation_report.stage_status.items()})}`",
                "",
                f"**→ final disposition:** `{packet.final_disposition.value}`",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def write_regression_artifacts(result: dict[str, object], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    summary = summary_payload(result)
    packets: list[HumanReviewPacket] = list(result["packets"])  # type: ignore[arg-type]
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    (output_dir / "human_review_packets.jsonl").write_text(
        "".join(
            json.dumps(packet.model_dump(mode="json"), ensure_ascii=False, sort_keys=True) + "\n"
            for packet in packets
        ),
        encoding="utf-8",
    )
    (output_dir / "soupx_before_after.md").write_text(render_before_after(result), encoding="utf-8")
