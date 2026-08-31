from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from core.knowledge_intelligence_models import RetrievalEvalCase
from engine.evidence_discovery_index import EvidenceChunk, load_chunks
from eval.retrieval_evaluation import read_gold_cases


CITATION_ADJUDICATION_SCHEMA_VERSION = "sckg-citation-adjudication-v1"
CITATION_EVALUATOR_VERSION = "architecture-citation-v2"
CITATION_HARD_FAILURE_TYPES = frozenset(
    {
        "fabricated_or_unknown_citation",
        "citation_source_metadata_conflict",
        "unsupported_wrong_source_evidence",
        "invalid_citation_mapping",
        "unsupported_or_conflicting_scientific_claim",
    }
)


class CitationAdjudicationError(ValueError):
    """Raised when curated citation evidence is inconsistent with its corpus."""


@dataclass(frozen=True)
class AcceptedEvidence:
    evidence_id: str
    source_id: str
    rationale: str


@dataclass(frozen=True)
class CitationCaseAdjudication:
    case_id: str
    expected_claim: str
    category: str
    historical_exact_chunk_ids: tuple[str, ...]
    accepted_evidence: tuple[AcceptedEvidence, ...]
    relevant_source_ids: tuple[str, ...]
    historical_review: str

    @property
    def accepted_evidence_ids(self) -> frozenset[str]:
        return frozenset(item.evidence_id for item in self.accepted_evidence)


@dataclass(frozen=True)
class CitationReference:
    evidence_id: str
    declared_source_id: str = ""


@dataclass(frozen=True)
class CitationCaseEvaluation:
    exact_chunk_match: bool
    relevant_source_match: bool
    supported_evidence_match: bool
    supported_precision: float
    cited_evidence_ids: tuple[str, ...]
    adjudicable_evidence_ids: tuple[str, ...]
    supported_evidence_ids: tuple[str, ...]
    unknown_evidence_ids: tuple[str, ...]
    wrong_source_evidence_ids: tuple[str, ...]
    source_metadata_conflicts: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "evaluator_version": CITATION_EVALUATOR_VERSION,
            "exact_chunk_match": self.exact_chunk_match,
            "relevant_source_match": self.relevant_source_match,
            "supported_evidence_match": self.supported_evidence_match,
            "supported_precision": self.supported_precision,
            "cited_evidence_ids": list(self.cited_evidence_ids),
            "adjudicable_evidence_ids": list(self.adjudicable_evidence_ids),
            "supported_evidence_ids": list(self.supported_evidence_ids),
            "unknown_evidence_ids": list(self.unknown_evidence_ids),
            "wrong_source_evidence_ids": list(self.wrong_source_evidence_ids),
            "source_metadata_conflicts": list(self.source_metadata_conflicts),
        }


@dataclass(frozen=True)
class CitationAdjudicationContract:
    schema_version: str
    evaluator_version: str
    base_gold_sha256: str
    adjudication_sha256: str
    evidence_corpus_sha256: str
    evidence_index_build_id: str
    cases: Mapping[str, CitationCaseAdjudication]
    evidence_by_id: Mapping[str, EvidenceChunk]

    def case(self, case_id: str) -> CitationCaseAdjudication | None:
        source_case_id = case_id.removeprefix("architecture.")
        return self.cases.get(source_case_id)

    def evaluate(
        self,
        case_id: str,
        references: Sequence[CitationReference],
    ) -> CitationCaseEvaluation:
        adjudication = self.case(case_id)
        if adjudication is None:
            raise CitationAdjudicationError(
                f"citation adjudication missing for case: {case_id}"
            )

        cited = _deduplicate_references(references)
        relevant_sources = set(adjudication.relevant_source_ids)
        accepted_ids = adjudication.accepted_evidence_ids
        historical_ids = set(adjudication.historical_exact_chunk_ids)
        adjudicable: list[str] = []
        supported: list[str] = []
        unknown: list[str] = []
        wrong_source: list[str] = []
        conflicts: list[str] = []

        for reference in cited:
            evidence = self.evidence_by_id.get(reference.evidence_id)
            if (
                evidence is None
                or not evidence.source_bound
                or evidence.retrieval_status == "catalog_only"
            ):
                unknown.append(reference.evidence_id)
                continue
            adjudicable.append(reference.evidence_id)
            authoritative_source = evidence_source_id(evidence)
            if (
                reference.declared_source_id
                and reference.declared_source_id != authoritative_source
            ):
                conflicts.append(reference.evidence_id)
                continue
            if authoritative_source not in relevant_sources:
                wrong_source.append(reference.evidence_id)
                continue
            if reference.evidence_id in accepted_ids:
                supported.append(reference.evidence_id)

        precision = len(supported) / len(adjudicable) if adjudicable else 0.0
        cited_ids = tuple(item.evidence_id for item in cited)
        return CitationCaseEvaluation(
            exact_chunk_match=bool(set(cited_ids).intersection(historical_ids)),
            relevant_source_match=any(
                evidence_source_id(self.evidence_by_id[evidence_id])
                in relevant_sources
                for evidence_id in adjudicable
            ),
            supported_evidence_match=bool(supported),
            supported_precision=round(precision, 6),
            cited_evidence_ids=cited_ids,
            adjudicable_evidence_ids=tuple(adjudicable),
            supported_evidence_ids=tuple(supported),
            unknown_evidence_ids=tuple(unknown),
            wrong_source_evidence_ids=tuple(wrong_source),
            source_metadata_conflicts=tuple(conflicts),
        )


def load_citation_adjudication(
    *,
    base_gold_path: Path,
    adjudication_path: Path,
    evidence_chunks_path: Path,
    evidence_manifest_path: Path,
) -> CitationAdjudicationContract:
    """Load and validate claim-first citation adjudication against immutable inputs."""

    base_gold_path = Path(base_gold_path)
    adjudication_path = Path(adjudication_path)
    evidence_chunks_path = Path(evidence_chunks_path)
    evidence_manifest_path = Path(evidence_manifest_path)
    raw = json.loads(adjudication_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise CitationAdjudicationError("adjudication root must be an object")
    if raw.get("schema_version") != CITATION_ADJUDICATION_SCHEMA_VERSION:
        raise CitationAdjudicationError("unsupported citation adjudication schema")

    base_digest = file_sha256(base_gold_path)
    corpus_digest = file_sha256(evidence_chunks_path)
    if raw.get("base_gold_sha256") != base_digest:
        raise CitationAdjudicationError("base gold digest mismatch")
    if raw.get("evidence_corpus_sha256") != corpus_digest:
        raise CitationAdjudicationError("evidence corpus digest mismatch")

    manifest = json.loads(evidence_manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or not manifest.get("build_id"):
        raise CitationAdjudicationError("evidence manifest build_id is required")
    if raw.get("evidence_index_build_id") != manifest.get("build_id"):
        raise CitationAdjudicationError("evidence index build mismatch")

    source_cases = {
        item.case_id: item
        for item in read_gold_cases(base_gold_path)
        if item.split == "evaluation" and item.relevant_chunk_ids
    }
    chunks = load_chunks(evidence_chunks_path)
    evidence_by_id = {item.chunk_id: item for item in chunks}
    raw_cases = raw.get("cases")
    if not isinstance(raw_cases, list):
        raise CitationAdjudicationError("adjudication cases must be a list")
    if any(not isinstance(item, dict) for item in raw_cases):
        raise CitationAdjudicationError("each adjudication case must be an object")
    rows_by_id = {str(item.get("case_id") or ""): item for item in raw_cases}
    if set(rows_by_id) != set(source_cases):
        missing = sorted(set(source_cases) - set(rows_by_id))
        extra = sorted(set(rows_by_id) - set(source_cases))
        raise CitationAdjudicationError(
            f"positive case coverage mismatch; missing={missing}; extra={extra}"
        )

    cases: dict[str, CitationCaseAdjudication] = {}
    for case_id, source_case in source_cases.items():
        cases[case_id] = _validate_case(
            rows_by_id[case_id],
            source_case=source_case,
            evidence_by_id=evidence_by_id,
        )

    return CitationAdjudicationContract(
        schema_version=CITATION_ADJUDICATION_SCHEMA_VERSION,
        evaluator_version=CITATION_EVALUATOR_VERSION,
        base_gold_sha256=base_digest,
        adjudication_sha256=file_sha256(adjudication_path),
        evidence_corpus_sha256=corpus_digest,
        evidence_index_build_id=str(manifest["build_id"]),
        cases=cases,
        evidence_by_id=evidence_by_id,
    )


def evidence_source_id(evidence: EvidenceChunk) -> str:
    return str(evidence.source_document_id or evidence.source_id or "")


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _validate_case(
    row: dict[str, Any],
    *,
    source_case: RetrievalEvalCase,
    evidence_by_id: Mapping[str, EvidenceChunk],
) -> CitationCaseAdjudication:
    case_id = _required_text(row, "case_id")
    category = _required_text(row, "category")
    expected_claim = _required_text(row, "expected_claim")
    historical_review = _required_text(row, "historical_review")
    if category != source_case.category:
        raise CitationAdjudicationError(f"category mismatch for {case_id}")
    if len(expected_claim) < 12 or len(historical_review) < 20:
        raise CitationAdjudicationError(
            f"claim and historical review must be substantive for {case_id}"
        )

    relevant_sources = _unique_text_list(row, "relevant_source_ids")
    accepted_rows = row.get("accepted_evidence")
    if not isinstance(accepted_rows, list) or not accepted_rows:
        raise CitationAdjudicationError(
            f"at least one accepted evidence item is required for {case_id}"
        )
    accepted: list[AcceptedEvidence] = []
    for accepted_row in accepted_rows:
        if not isinstance(accepted_row, dict):
            raise CitationAdjudicationError(
                f"accepted evidence row must be an object for {case_id}"
            )
        evidence_id = _required_text(accepted_row, "evidence_id")
        declared_source = _required_text(accepted_row, "source_id")
        rationale = _required_text(accepted_row, "rationale")
        if len(rationale) < 24:
            raise CitationAdjudicationError(
                f"claim-level rationale is too short for {case_id}:{evidence_id}"
            )
        evidence = evidence_by_id.get(evidence_id)
        if evidence is None:
            raise CitationAdjudicationError(
                f"accepted evidence is absent from corpus: {case_id}:{evidence_id}"
            )
        if not evidence.source_bound or evidence.retrieval_status == "catalog_only":
            raise CitationAdjudicationError(
                f"accepted evidence is not governed source-bound: {case_id}:{evidence_id}"
            )
        authoritative_source = evidence_source_id(evidence)
        if declared_source != authoritative_source:
            raise CitationAdjudicationError(
                f"accepted evidence source mismatch: {case_id}:{evidence_id}"
            )
        if authoritative_source not in relevant_sources:
            raise CitationAdjudicationError(
                f"accepted evidence source is not relevant: {case_id}:{evidence_id}"
            )
        accepted.append(
            AcceptedEvidence(
                evidence_id=evidence_id,
                source_id=authoritative_source,
                rationale=rationale,
            )
        )
    accepted_ids = [item.evidence_id for item in accepted]
    if len(accepted_ids) != len(set(accepted_ids)):
        raise CitationAdjudicationError(f"duplicate accepted evidence for {case_id}")

    base_sources = set(source_case.relevant_source_ids)
    for added_source in set(relevant_sources) - base_sources:
        if not any(item.source_id == added_source for item in accepted):
            raise CitationAdjudicationError(
                f"expanded source lacks accepted claim evidence: {case_id}:{added_source}"
            )

    return CitationCaseAdjudication(
        case_id=case_id,
        expected_claim=expected_claim,
        category=category,
        historical_exact_chunk_ids=tuple(source_case.relevant_chunk_ids),
        accepted_evidence=tuple(accepted),
        relevant_source_ids=tuple(relevant_sources),
        historical_review=historical_review,
    )


def _deduplicate_references(
    references: Iterable[CitationReference],
) -> tuple[CitationReference, ...]:
    values: list[CitationReference] = []
    seen: set[str] = set()
    for reference in references:
        evidence_id = str(reference.evidence_id or "").strip()
        if not evidence_id or evidence_id in seen:
            continue
        seen.add(evidence_id)
        values.append(
            CitationReference(
                evidence_id=evidence_id,
                declared_source_id=str(reference.declared_source_id or "").strip(),
            )
        )
    return tuple(values)


def _required_text(row: Mapping[str, Any], field: str) -> str:
    value = row.get(field)
    if not isinstance(value, str) or not value.strip():
        raise CitationAdjudicationError(f"{field} must be a non-empty string")
    return value.strip()


def _unique_text_list(row: Mapping[str, Any], field: str) -> tuple[str, ...]:
    value = row.get(field)
    if not isinstance(value, list) or not value:
        raise CitationAdjudicationError(f"{field} must be a non-empty list")
    values = tuple(str(item).strip() for item in value if str(item).strip())
    if len(values) != len(value) or len(values) != len(set(values)):
        raise CitationAdjudicationError(f"{field} must contain unique non-empty strings")
    return values
