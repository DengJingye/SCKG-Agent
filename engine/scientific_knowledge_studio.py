"""Preview-only one-PDF Scientific Knowledge Studio orchestration.

The service deliberately exposes no canonical mutation, promotion, review, RAG
indexing, or planner methods.  All writes are confined to one run directory.
"""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import re
import tempfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from core.scientific_knowledge_studio_models import (
    AtomicClaimProposal,
    CandidateDiff,
    DocumentSegment,
    EntityProposal,
    EvidenceSpanProposal,
    KnowledgeStudioRunManifest,
    LLMRunMetadata,
    ParseGap,
    ProposalGraph,
    ProposalGraphEdge,
    ProposalGraphNode,
    RelationProposal,
    RunStageRecord,
    ScopeDimensionProposal,
    ScopeProposal,
    SourceRevisionProposal,
)
from engine.scientific_kg_admin import ScientificKGAdminSnapshotService
from engine.knowledge_graph_view import GraphEdge, GraphNode, KnowledgeGraphView


PROMPT_VERSION = "scientific-knowledge-studio-semantic-v1"
SEMANTIC_SCHEMA_VERSION = "sckg-studio-semantic-response-v1"
PROPOSAL_ENTITY_TYPES = {
    "Method",
    "MethodVariant",
    "SoftwareProject",
    "Package",
    "PackageRelease",
    "Operator",
    "OperatorRevision",
    "RepresentationType",
    "RepresentationConstraint",
    "ApplicabilityScope",
}
CLAIM_TYPES = {
    "capability",
    "input_requirement",
    "output",
    "limitation",
    "parameter",
    "version",
    "workflow",
    "general",
}
STAGES = [
    "UPLOAD",
    "SOURCE_IDENTITY",
    "PARSE",
    "EVIDENCE_PROPOSAL",
    "SEMANTIC_EXTRACTION",
    "IDENTITY_RESOLUTION",
    "VALIDATION",
    "PREVIEW",
]


def _sha_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _stable_id(prefix: str, *parts: Any, length: int = 24) -> str:
    payload = "\0".join(str(part) for part in parts)
    return f"{prefix}{_sha_text(payload)[:length]}"


def _normalize_label(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value).casefold()).strip()


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(_canonical_json(row) + "\n" for row in rows), encoding="utf-8")


def _dump(item: BaseModel) -> dict[str, Any]:
    return item.model_dump(mode="json")


class PDFParseResult(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)
    metadata: dict[str, Any]
    page_count: int
    segments: list[DocumentSegment]
    gaps: list[ParseGap]
    parser_name: str
    parser_version: str


class PagePreservingPDFAdapter:
    """Narrow adapter over the same pypdf implementation used by the existing parser."""

    parser_name = "pypdf"

    def parser_version(self) -> str:
        try:
            return importlib.metadata.version("pypdf")
        except importlib.metadata.PackageNotFoundError:
            return "unavailable"

    def parse(self, pdf_path: Path, pdf_sha256: str) -> PDFParseResult:
        try:
            from pypdf import PdfReader
        except ModuleNotFoundError as exc:
            raise RuntimeError("page-preserving PDF parsing requires the declared pypdf dependency") from exc
        reader = PdfReader(str(pdf_path))
        metadata = {
            "title": str((reader.metadata or {}).get("/Title") or "").strip(),
            "author": str((reader.metadata or {}).get("/Author") or "").strip(),
            "subject": str((reader.metadata or {}).get("/Subject") or "").strip(),
        }
        pages: list[str | Exception] = []
        for page in reader.pages:
            try:
                pages.append(page.extract_text() or "")
            except Exception as exc:  # page-local failure becomes an explicit PARSE_GAP
                pages.append(exc)
        return self.parse_pages(
            pages,
            pdf_sha256=pdf_sha256,
            metadata=metadata,
            parser_version=self.parser_version(),
        )

    def parse_pages(
        self,
        pages: Sequence[str | Exception | None],
        *,
        pdf_sha256: str,
        metadata: dict[str, Any] | None = None,
        parser_version: str = "test-fixture",
    ) -> PDFParseResult:
        segments: list[DocumentSegment] = []
        gaps: list[ParseGap] = []
        for page_number, raw_page in enumerate(pages, 1):
            if isinstance(raw_page, Exception):
                gaps.append(ParseGap(page=page_number, reason=f"{type(raw_page).__name__}: {raw_page}", parser=self.parser_name))
                continue
            page_text = self._normalize_text(str(raw_page or ""))
            if not page_text:
                gaps.append(ParseGap(page=page_number, reason="empty_or_unextractable_page", parser=self.parser_name))
                continue
            blocks = self._bounded_blocks(page_text)
            if not blocks:
                gaps.append(ParseGap(page=page_number, reason="no_bounded_text_segments", parser=self.parser_name))
                continue
            section = "document"
            segment_index = 0
            for block in blocks:
                if self._looks_like_heading(block):
                    section = block[:120]
                    continue
                text_hash = _sha_text(block)
                segment_id = _stable_id(
                    "segment:", pdf_sha256, page_number, segment_index, text_hash, length=32
                )
                segments.append(
                    DocumentSegment(
                        segment_id=segment_id,
                        page_number=page_number,
                        segment_index=segment_index,
                        section=section,
                        exact_text=block,
                        text_sha256=text_hash,
                        source_pdf_sha256=pdf_sha256,
                        parser_name=self.parser_name,
                        parser_version=parser_version,
                    )
                )
                segment_index += 1
        return PDFParseResult(
            metadata=dict(metadata or {}),
            page_count=len(pages),
            segments=segments,
            gaps=gaps,
            parser_name=self.parser_name,
            parser_version=parser_version,
        )

    @staticmethod
    def _normalize_text(text: str) -> str:
        text = re.sub(r"\r\n?", "\n", text)
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    @classmethod
    def _bounded_blocks(cls, page_text: str, *, max_chars: int = 1800) -> list[str]:
        raw_blocks = [" ".join(item.split()) for item in re.split(r"\n\s*\n", page_text) if item.strip()]
        if len(raw_blocks) == 1:
            lines = [" ".join(line.split()) for line in page_text.splitlines() if line.strip()]
            raw_blocks = []
            buffer: list[str] = []
            for line in lines:
                if buffer and (cls._looks_like_heading(line) or len(" ".join(buffer + [line])) > max_chars):
                    raw_blocks.append(" ".join(buffer))
                    buffer = []
                buffer.append(line)
            if buffer:
                raw_blocks.append(" ".join(buffer))
        bounded: list[str] = []
        for block in raw_blocks:
            if len(block) <= max_chars:
                if len(block) >= 20:
                    bounded.append(block)
                continue
            sentences = re.split(r"(?<=[.!?])\s+", block)
            current = ""
            for sentence in sentences:
                sentence = sentence.strip()
                if not sentence:
                    continue
                if current and len(current) + 1 + len(sentence) > max_chars:
                    bounded.append(current)
                    current = ""
                if len(sentence) > max_chars:
                    for start in range(0, len(sentence), max_chars):
                        piece = sentence[start : start + max_chars].strip()
                        if len(piece) >= 20:
                            bounded.append(piece)
                else:
                    current = f"{current} {sentence}".strip()
            if current:
                bounded.append(current)
        return bounded

    @staticmethod
    def _looks_like_heading(value: str) -> bool:
        stripped = value.strip().strip(":")
        if not stripped or len(stripped) > 100:
            return False
        common = {"description", "arguments", "details", "value", "examples", "usage", "references", "author", "see also"}
        return stripped.casefold() in common or (stripped.isupper() and len(stripped.split()) <= 8)


class OntologyRegistry:
    """Read allowed types, predicates and observed endpoint pairs from the frozen graph."""

    def __init__(self, root: Path) -> None:
        snapshot = _json(root / "data/evaluation/scientific_kg_inventory_snapshot_v1/node_type_counts.json")
        relation_snapshot = _json(root / "data/evaluation/scientific_kg_inventory_snapshot_v1/relation_type_counts.json")
        graph = _json(root / "data/evidence_candidates/scientific_kg_v1_inventory/scientific_kg_v1_consolidated_graph.json")
        graph_types = set(snapshot["scientific_kg"])
        self.allowed_entity_types = PROPOSAL_ENTITY_TYPES & graph_types
        self.allowed_predicates = set(relation_snapshot["scientific_kg"])
        node_type = {row["graph_node_id"]: row["record_type"] for row in graph["nodes"]}
        self.endpoint_pairs: dict[str, set[tuple[str, str]]] = defaultdict(set)
        for edge in graph["edges"]:
            pair = (node_type.get(edge["source_graph_node_id"], ""), node_type.get(edge["target_graph_node_id"], ""))
            self.endpoint_pairs[edge["predicate"]].add(pair)

    def relation_valid(self, predicate: str, source_type: str, target_type: str) -> bool:
        return predicate in self.allowed_predicates and (source_type, target_type) in self.endpoint_pairs[predicate]


class ScientificIdentityResolver:
    def __init__(self, root: Path, allowed_types: set[str]) -> None:
        graph = _json(root / "data/evidence_candidates/scientific_kg_v1_inventory/scientific_kg_v1_consolidated_graph.json")
        self.records: dict[str, dict[str, Any]] = {}
        self.by_label: dict[tuple[str, str], set[str]] = defaultdict(set)
        self.by_api_path: dict[tuple[str, str], set[str]] = defaultdict(set)
        self.by_alias: dict[tuple[str, str], set[str]] = defaultdict(set)
        for node in graph["nodes"]:
            entity_type = str(node["record_type"])
            if entity_type not in allowed_types:
                continue
            canonical_id = str(node["record_id"])
            record = dict(node.get("record") or {})
            self.records.setdefault(canonical_id, {"canonical_id": canonical_id, "entity_type": entity_type, "label": str(node.get("label") or canonical_id), "record": record})
            label = _normalize_label(str(node.get("label") or ""))
            if label:
                self.by_label[(entity_type, label)].add(canonical_id)
            api_path = _normalize_label(str(record.get("api_path") or record.get("qualified_name") or ""))
            if api_path:
                self.by_api_path[(entity_type, api_path)].add(canonical_id)
            aliases = record.get("aliases") or record.get("governed_aliases") or []
            if isinstance(aliases, str):
                aliases = [aliases]
            for alias in aliases:
                normalized = _normalize_label(str(alias))
                if normalized:
                    self.by_alias[(entity_type, normalized)].add(canonical_id)

    def resolve(self, entity_type: str, raw_label: str, *, version: str | None = None) -> tuple[str, list[str], list[str]]:
        normalized = _normalize_label(raw_label)
        exact = set(self.by_label.get((entity_type, normalized), set()))
        api = set(self.by_api_path.get((entity_type, normalized), set()))
        aliases = set(self.by_alias.get((entity_type, normalized), set()))
        candidates = exact or api or aliases
        reasons = ["exact_normalized_label" if exact else "exact_api_path" if api else "governed_alias"] if candidates else []
        if version and candidates:
            matching = {
                candidate
                for candidate in candidates
                if version.casefold() in _canonical_json(self.records[candidate]["record"]).casefold()
                or version.casefold() in candidate.casefold()
            }
            if matching:
                candidates = matching
            else:
                return "POSSIBLE_EXISTING_IDENTITY", sorted(candidates), [*reasons, "version_conflict_retained"]
        if len(candidates) == 1:
            return "EXACT_EXISTING_IDENTITY", sorted(candidates), reasons
        if len(candidates) > 1:
            return "AMBIGUOUS", sorted(candidates), [*reasons, "multiple_exact_candidates"]
        return "NEW_CANDIDATE", [], ["no_exact_or_governed_alias_match", "fuzzy_merge_disabled"]


class EvidenceProposalBuilder:
    cues = (
        "require", "input", "output", "return", "produce", "method", "algorithm",
        "limitation", "difficult", "impossible", "recommended", "contamination",
        "single cell", "rna-seq", "matrix", "counts", "implements", "version",
    )

    def build(self, source: SourceRevisionProposal, segments: Sequence[DocumentSegment], *, limit: int = 16) -> list[EvidenceSpanProposal]:
        candidates: list[tuple[int, int, DocumentSegment, int, str]] = []
        for segment in segments:
            for start, end, sentence in self._sentences(segment.exact_text):
                lowered = sentence.casefold()
                cue_count = sum(cue in lowered for cue in self.cues)
                if cue_count == 0 or len(sentence) < 45 or len(sentence) > 850:
                    continue
                candidates.append((-cue_count, segment.page_number, segment, start, sentence))
        candidates.sort(key=lambda row: (row[0], row[1], row[2].segment_index, row[3]))
        output: list[EvidenceSpanProposal] = []
        seen: set[str] = set()
        for _score, _page, segment, start, sentence in candidates:
            digest = _sha_text(sentence)
            if digest in seen:
                continue
            seen.add(digest)
            end = start + len(sentence)
            output.append(
                EvidenceSpanProposal(
                    proposal_id=_stable_id("proposal:evidence-span:", source.proposal_id, segment.segment_id, start, end),
                    source_revision_proposal_id=source.proposal_id,
                    source_pdf_sha256=source.pdf_sha256,
                    page_number=segment.page_number,
                    segment_id=segment.segment_id,
                    start_offset=start,
                    end_offset=end,
                    exact_text=sentence,
                    text_sha256=digest,
                    extraction_method="deterministic_bounded_sentence_v1",
                    validation_status="VALID",
                )
            )
            if len(output) >= limit:
                break
        return output

    @staticmethod
    def _sentences(text: str) -> Iterable[tuple[int, int, str]]:
        pattern = re.compile(r"[^.!?\n]+(?:[.!?](?=\s|$)|$)")
        for match in pattern.finditer(text):
            raw = match.group(0)
            left = len(raw) - len(raw.lstrip())
            right = len(raw.rstrip())
            sentence = raw[left:right]
            if sentence:
                yield match.start() + left, match.start() + right, sentence


class RawEntity(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entity_type: str
    raw_label: str
    description: str = ""
    supporting_evidence_span_ids: list[str] = Field(min_length=1)
    version: str | None = None


class RawRelation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_label: str
    predicate: str
    target_label: str
    supporting_evidence_span_ids: list[str] = Field(min_length=1)
    origin: str


class RawScope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    local_id: str
    supporting_evidence_span_ids: list[str] = Field(min_length=1)
    dimensions: dict[str, dict[str, Any]]


class RawClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")
    claim_text: str
    claim_type: str
    subject_label: str
    object_or_requirement: str
    supporting_evidence_span_ids: list[str] = Field(min_length=1)
    scope_local_id: str
    version_conditions: list[str] = Field(default_factory=list)
    flavor_conditions: list[str] = Field(default_factory=list)


class SemanticResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: str
    entity_proposals: list[RawEntity]
    relation_proposals: list[RawRelation]
    atomic_claim_proposals: list[RawClaim]
    scope_proposals: list[RawScope]


class StructuredLLMProposalExtractor:
    """Strict, bounded adapter around an already-authorized callable/runtime."""

    def __init__(self, invoke: Callable[[str], str], *, max_retries: int = 2) -> None:
        self._invoke = invoke
        self.max_retries = max(0, min(int(max_retries), 2))

    def extract(self, prompt: str) -> tuple[SemanticResponse, str, int]:
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            raw = self._invoke(prompt)
            try:
                value = SemanticResponse.model_validate_json(raw)
                return value, raw, attempt
            except (ValidationError, json.JSONDecodeError) as exc:
                last_error = exc
        raise ValueError(f"structured LLM response invalid after bounded retry: {last_error}")


class LocalOntologyProposalExtractor:
    """Conservative deterministic fallback; it never claims to be an LLM."""

    def __init__(self, resolver: ScientificIdentityResolver) -> None:
        self.resolver = resolver

    def extract(
        self,
        source: SourceRevisionProposal,
        evidence: Sequence[EvidenceSpanProposal],
    ) -> SemanticResponse:
        entities: list[RawEntity] = []
        seen: set[tuple[str, str]] = set()
        version_match = re.search(r"\b(?:version\s*)?(\d+\.\d+(?:\.\d+)?)\b", " ".join(span.exact_text for span in evidence[:4]), re.I)
        version = version_match.group(1) if version_match else None
        title_lead = re.split(r"[:—-]", source.title, maxsplit=1)[0].strip()
        if title_lead and 1 <= len(title_lead.split()) <= 5:
            key = ("SoftwareProject", _normalize_label(title_lead))
            seen.add(key)
            support = next((span.proposal_id for span in evidence if title_lead.casefold() in span.exact_text.casefold()), evidence[0].proposal_id)
            entities.append(RawEntity(entity_type="SoftwareProject", raw_label=title_lead, description=f"Scientific software named by the source: {source.title}", supporting_evidence_span_ids=[support], version=version))

        # Exact label matching is conservative and uses only governed snapshot identities.
        for span in evidence:
            haystack = _normalize_label(span.exact_text)
            for canonical in self.resolver.records.values():
                entity_type = canonical["entity_type"]
                label = str(canonical["label"])
                normalized = _normalize_label(label)
                if len(normalized) < 4 or normalized not in haystack:
                    continue
                key = (entity_type, normalized)
                if key in seen:
                    continue
                seen.add(key)
                entities.append(RawEntity(entity_type=entity_type, raw_label=label, description="Exact governed Scientific KG label found in bounded PDF evidence.", supporting_evidence_span_ids=[span.proposal_id], version=version if entity_type in {"PackageRelease", "OperatorRevision"} else None))
                if len(entities) >= 12:
                    break
            if len(entities) >= 12:
                break

        primary_label = entities[0].raw_label if entities else title_lead or "document subject"
        scopes: list[RawScope] = []
        claims: list[RawClaim] = []
        for index, span in enumerate(evidence[:8]):
            lowered = span.exact_text.casefold()
            dimensions: dict[str, dict[str, Any]] = {
                "organism": {"value": None, "status": "UNSPECIFIED"},
                "study_design": {"value": None, "status": "UNSPECIFIED"},
                "evaluation_context": {"value": None, "status": "UNSPECIFIED"},
            }
            if "rna-seq" in lowered or "mrna" in lowered or "transcript" in lowered:
                dimensions["modality"] = {"value": "scRNA-seq", "status": "EXPLICIT"}
            else:
                dimensions["modality"] = {"value": None, "status": "UNSPECIFIED"}
            if version and version in span.exact_text:
                dimensions["method_operator_version"] = {"value": version, "status": "EXPLICIT"}
            else:
                dimensions["method_operator_version"] = {"value": None, "status": "UNSPECIFIED"}
            local_id = f"scope-{index}"
            scopes.append(RawScope(local_id=local_id, supporting_evidence_span_ids=[span.proposal_id], dimensions=dimensions))
            claim_type = self._claim_type(lowered)
            claims.append(
                RawClaim(
                    claim_text=span.exact_text,
                    claim_type=claim_type,
                    subject_label=primary_label,
                    object_or_requirement=self._object_text(span.exact_text),
                    supporting_evidence_span_ids=[span.proposal_id],
                    scope_local_id=local_id,
                    version_conditions=[version] if version and version in span.exact_text else [],
                )
            )
        return SemanticResponse(
            schema_version=SEMANTIC_SCHEMA_VERSION,
            entity_proposals=entities,
            relation_proposals=[],
            atomic_claim_proposals=claims,
            scope_proposals=scopes,
        )

    @staticmethod
    def _claim_type(lowered: str) -> str:
        if any(term in lowered for term in ("difficult", "impossible", "limitation", "without")):
            return "limitation"
        if any(term in lowered for term in ("require", "input", "depends")):
            return "input_requirement"
        if any(term in lowered for term in ("output", "return", "resulting matrix", "produce")):
            return "output"
        if "version" in lowered:
            return "version"
        if any(term in lowered for term in ("method", "implements", "remove", "estimate", "quantify")):
            return "capability"
        return "general"

    @staticmethod
    def _object_text(text: str) -> str:
        return text[:280]


class ScientificKnowledgeStudioService:
    """One-PDF preview orchestrator with no production write authority."""

    def __init__(self, repository_root: Path | None = None, *, parser: PagePreservingPDFAdapter | None = None) -> None:
        self.root = Path(repository_root or Path(__file__).resolve().parents[1])
        self.runtime_root = self.root / "data/runtime/scientific_knowledge_studio"
        self.parser = parser or PagePreservingPDFAdapter()
        self.ontology = OntologyRegistry(self.root)
        self.identity = ScientificIdentityResolver(self.root, self.ontology.allowed_entity_types)
        self.admin = ScientificKGAdminSnapshotService(self.root)

    def ontology_contract(self) -> dict[str, Any]:
        return {
            "entity_types": sorted(self.ontology.allowed_entity_types),
            "predicates": sorted(self.ontology.allowed_predicates),
            "claim_types": sorted(CLAIM_TYPES),
        }

    def run_pdf(
        self,
        pdf_path: Path,
        *,
        run_id: str | None = None,
        output_dir: Path | None = None,
        llm_extractor: StructuredLLMProposalExtractor | None = None,
        llm_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        path = Path(pdf_path)
        if path.suffix.casefold() != ".pdf":
            raise ValueError("Scientific Knowledge Studio v1 accepts exactly one PDF")
        original_bytes = path.read_bytes()
        return self._run(
            original_filename=path.name,
            original_bytes=original_bytes,
            parse=lambda digest: self.parser.parse(path, digest),
            run_id=run_id,
            output_dir=output_dir,
            llm_extractor=llm_extractor,
            llm_metadata=llm_metadata,
        )

    def run_pdf_bytes(
        self,
        original_filename: str,
        content: bytes,
        *,
        run_id: str | None = None,
        output_dir: Path | None = None,
    ) -> dict[str, Any]:
        if Path(original_filename).suffix.casefold() != ".pdf":
            raise ValueError("Scientific Knowledge Studio v1 accepts PDF only")
        with tempfile.NamedTemporaryFile(suffix=".pdf") as handle:
            handle.write(content)
            handle.flush()
            return self._run(
                original_filename=Path(original_filename).name,
                original_bytes=content,
                parse=lambda digest: self.parser.parse(Path(handle.name), digest),
                run_id=run_id,
                output_dir=output_dir,
                llm_extractor=None,
                llm_metadata=None,
            )

    def run_from_pages(
        self,
        *,
        original_filename: str,
        original_bytes: bytes,
        pages: Sequence[str | Exception | None],
        metadata: dict[str, Any] | None = None,
        run_id: str = "knowledge-studio:test-fixture",
        output_dir: Path,
        llm_extractor: StructuredLLMProposalExtractor | None = None,
        llm_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._run(
            original_filename=original_filename,
            original_bytes=original_bytes,
            parse=lambda digest: self.parser.parse_pages(pages, pdf_sha256=digest, metadata=metadata, parser_version="test-fixture"),
            run_id=run_id,
            output_dir=output_dir,
            llm_extractor=llm_extractor,
            llm_metadata=llm_metadata,
        )

    def _run(
        self,
        *,
        original_filename: str,
        original_bytes: bytes,
        parse: Callable[[str], PDFParseResult],
        run_id: str | None,
        output_dir: Path | None,
        llm_extractor: StructuredLLMProposalExtractor | None,
        llm_metadata: dict[str, Any] | None,
    ) -> dict[str, Any]:
        pdf_hash = _sha_bytes(original_bytes)
        run_id = run_id or f"knowledge-studio:{pdf_hash[:12]}:{_now().strftime('%Y%m%dT%H%M%SZ')}"
        if not run_id.startswith("knowledge-studio:"):
            raise ValueError("run_id must start with knowledge-studio:")
        run_dir = Path(output_dir or self.runtime_root / run_id.replace(":", "_"))
        if run_dir.exists() and any(run_dir.iterdir()):
            raise FileExistsError(f"Knowledge Studio run is write-once: {run_dir.name}")
        run_dir.mkdir(parents=True, exist_ok=True)
        stage_rows: list[RunStageRecord] = []

        def stage(name: str, status: str, inputs: list[str], outputs: list[str], reason: str) -> None:
            payload = {"stage": name, "status": status, "input_refs": inputs, "output_refs": outputs, "reason": reason}
            stage_rows.append(RunStageRecord(stage=name, timestamp=_now(), status=status, input_refs=inputs, output_refs=outputs, reason=reason, content_hash=_sha_text(_canonical_json(payload))))

        stage("UPLOAD", "DONE", [original_filename], [f"sha256:{pdf_hash}"], "one local PDF accepted; binary not copied into run artifacts")
        parsed = parse(pdf_hash)
        source = self._source_proposal(original_filename, original_bytes, pdf_hash, parsed, run_id)
        stage("SOURCE_IDENTITY", "DONE" if source.identity_status != "SOURCE_IDENTITY_AMBIGUOUS" else "WARNING", [f"sha256:{pdf_hash}"], [source.proposal_id], source.identity_status)
        stage("PARSE", "WARNING" if parsed.gaps else "DONE", [source.proposal_id], [row.segment_id for row in parsed.segments], f"{len(parsed.segments)} segments; {len(parsed.gaps)} PARSE_GAP")
        evidence = EvidenceProposalBuilder().build(source, parsed.segments)
        if not evidence:
            stage("EVIDENCE_PROPOSAL", "BLOCKED", [row.segment_id for row in parsed.segments], [], "no bounded evidence candidate")
            raise RuntimeError("no bounded EvidenceSpanProposal could be formed")
        evidence = self._validate_evidence(source, parsed.segments, evidence)
        stage("EVIDENCE_PROPOSAL", "DONE", [row.segment_id for row in parsed.segments], [row.proposal_id for row in evidence], f"{len(evidence)} bounded exact-text proposals")

        raw_response: str | None = None
        if llm_extractor:
            prompt = self._semantic_prompt(source, evidence)
            semantic, raw_response, retry_count = llm_extractor.extract(prompt)
            metadata = dict(llm_metadata or {})
            llm_run = LLMRunMetadata(
                status="COMPLETED",
                provider=str(metadata.get("provider") or "authorized_existing_runtime"),
                model=str(metadata.get("model") or "configured_model"),
                api_base_category=str(metadata.get("api_base_category") or "openai_compatible"),
                temperature=float(metadata.get("temperature", 0.1)),
                prompt_version=PROMPT_VERSION,
                schema_version=SEMANTIC_SCHEMA_VERSION,
                retry_count=retry_count,
                response_hash=_sha_text(raw_response),
            )
            method = "authorized_llm_strict_json"
        else:
            semantic = LocalOntologyProposalExtractor(self.identity).extract(source, evidence)
            llm_run = LLMRunMetadata(
                status="NOT_RUN",
                provider="none",
                model="none",
                api_base_category="none",
                temperature=0.0,
                prompt_version=PROMPT_VERSION,
                schema_version=SEMANTIC_SCHEMA_VERSION,
                retry_count=0,
                response_hash=None,
            )
            method = "local_deterministic_ontology_extractor_v1"
        stage("SEMANTIC_EXTRACTION", "DONE" if semantic.entity_proposals or semantic.atomic_claim_proposals else "WARNING", [row.proposal_id for row in evidence], [], method)

        entities = self._entity_proposals(semantic, evidence)
        scopes = self._scope_proposals(semantic, evidence)
        relations = self._relation_proposals(semantic, evidence, entities)
        claims = self._claim_proposals(semantic, evidence, entities, scopes)
        stage("IDENTITY_RESOLUTION", "WARNING" if any(row.identity_resolution_status == "AMBIGUOUS" for row in entities) else "DONE", [row.entity_proposal_id for row in entities], [candidate for row in entities for candidate in row.existing_candidate_ids], "exact/alias/package-constrained resolution only; fuzzy merge disabled")

        entities, relations, claims, scopes = self._validate_semantics(evidence, entities, relations, claims, scopes)
        validation_rows = [*evidence, *entities, *relations, *claims, *scopes]
        validation_counts = Counter(row.validation_status for row in validation_rows)
        stage("VALIDATION", "WARNING" if validation_counts["INVALID"] or validation_counts["NEEDS_REVIEW"] else "DONE", [getattr(row, "proposal_id", getattr(row, "entity_proposal_id", getattr(row, "relation_proposal_id", getattr(row, "claim_proposal_id", getattr(row, "scope_proposal_id", ""))))) for row in validation_rows], [], f"VALID={validation_counts['VALID']} NEEDS_REVIEW={validation_counts['NEEDS_REVIEW']} INVALID={validation_counts['INVALID']}")

        diff = self._candidate_diff(evidence, entities, relations, claims, validation_counts)
        graph = self._proposal_graph(source, evidence, entities, relations, claims, scopes)
        stage("PREVIEW", "DONE", [source.proposal_id], ["candidate_diff.json", "proposal_graph.json"], "preview only; Scientific KG unchanged")

        artifacts = {
            "source_proposal.json": _dump(source),
            "segments.jsonl": [_dump(row) for row in parsed.segments],
            "parse_gaps.json": [_dump(row) for row in parsed.gaps],
            "evidence_span_proposals.jsonl": [_dump(row) for row in evidence],
            "entity_proposals.jsonl": [_dump(row) for row in entities],
            "relation_proposals.jsonl": [_dump(row) for row in relations],
            "atomic_claim_proposals.jsonl": [_dump(row) for row in claims],
            "scope_proposals.jsonl": [_dump(row) for row in scopes],
            "candidate_diff.json": _dump(diff),
            "proposal_graph.json": _dump(graph),
            "validation_summary.json": {"counts": dict(sorted(validation_counts.items())), "validators": ["schema", "evidence", "identity", "governance"]},
            "run_trace.json": [_dump(row) for row in stage_rows],
            "ontology_contract.json": self.ontology_contract(),
        }
        if raw_response is not None:
            artifacts["raw_model_response.json"] = json.loads(raw_response)
        self._persist(run_dir, artifacts)
        artifact_hashes = {name: _sha_bytes((run_dir / name).read_bytes()) for name in artifacts}
        manifest = KnowledgeStudioRunManifest(
            run_id=run_id,
            created_at=_now(),
            original_filename=original_filename,
            pdf_sha256=pdf_hash,
            page_count=parsed.page_count,
            parsed_pages=len({row.page_number for row in parsed.segments}),
            parse_gap_count=len(parsed.gaps),
            stages=stage_rows,
            llm=llm_run,
            artifact_hashes=artifact_hashes,
        )
        _write_json(run_dir / "manifest.json", _dump(manifest))
        return {
            "run_dir": run_dir,
            "source": source,
            "segments": parsed.segments,
            "parse_gaps": parsed.gaps,
            "evidence": evidence,
            "entities": entities,
            "relations": relations,
            "claims": claims,
            "scopes": scopes,
            "candidate_diff": diff,
            "proposal_graph": graph,
            "manifest": manifest,
            "validation_counts": dict(validation_counts),
        }

    def _source_proposal(self, filename: str, content: bytes, digest: str, parsed: PDFParseResult, run_id: str) -> SourceRevisionProposal:
        title = str(parsed.metadata.get("title") or "").strip() or Path(filename).stem
        author_value = str(parsed.metadata.get("author") or "").strip()
        authors = [part.strip() for part in re.split(r"[;,]", author_value) if part.strip()]
        first_text = " ".join(row.exact_text for row in parsed.segments[:3])
        doi_match = re.search(r"(?:doi\s*:\s*|https?://doi\.org/)(10\.\d{4,9}/[-._;()/:A-Za-z0-9]+)", first_text, re.I)
        doi = doi_match.group(1).rstrip(".>,)") if doi_match else None
        source_matches = self._source_identity_matches(title, doi, digest)
        if len(source_matches) == 1:
            status = "SOURCE_IDENTITY_EXACT"
            work_id = source_matches[0]
        elif len(source_matches) > 1:
            status = "SOURCE_IDENTITY_AMBIGUOUS"
            work_id = _stable_id("source-work-candidate:", title, doi or "")
        else:
            status = "SOURCE_IDENTITY_NEW"
            work_id = _stable_id("source-work-candidate:", title, doi or "")
        return SourceRevisionProposal(
            proposal_id=_stable_id("proposal:source-revision:", digest, parsed.parser_name, parsed.parser_version, length=16),
            source_work_candidate_id=work_id,
            source_revision_candidate_id=_stable_id("source-revision-candidate:", work_id, digest),
            identity_status=status,
            title=title,
            authors=authors,
            doi=doi,
            original_filename=filename,
            file_size=len(content),
            pdf_sha256=digest,
            page_count=parsed.page_count,
            ingestion_run_id=run_id,
            parser_name=parsed.parser_name,
            parser_version=parsed.parser_version,
            created_at=_now(),
        )

    def _source_identity_matches(self, title: str, doi: str | None, digest: str) -> list[str]:
        matches: set[str] = set()
        paths = [
            self.root / "data/evidence_candidates/scientific_kg_v1_core/source_manifest.json",
            self.root / "data/evidence_candidates/scientific_kg_v1_uat_decision_rules/authoritative_source_manifest.json",
            self.root / "data/evidence_candidates/scientific_knowledge_scanpy_core_v1_1/authoritative_source_manifest.json",
            self.root / "data/evaluation/evidence_gap_acquisition_pilot_v1_repaired/source_registry.json",
        ]
        normalized_title = _normalize_label(title)
        for path in paths:
            if not path.is_file():
                continue
            payload = _json(path)
            rows = payload.get("sources", payload if isinstance(payload, list) else [payload])
            for row in rows:
                row_id = str(row.get("source_revision_id") or row.get("source_id") or row.get("source_work_id") or "")
                blob = _canonical_json(row).casefold()
                exact_hash = digest in blob
                exact_doi = bool(doi and doi.casefold() in blob)
                row_title = _normalize_label(str(row.get("title") or row.get("source_title") or ""))
                exact_title = bool(normalized_title and row_title and normalized_title == row_title)
                if row_id and (exact_hash or exact_doi or exact_title):
                    matches.add(row_id)
        return sorted(matches)

    def _validate_evidence(self, source: SourceRevisionProposal, segments: Sequence[DocumentSegment], evidence: Sequence[EvidenceSpanProposal]) -> list[EvidenceSpanProposal]:
        segment_map = {row.segment_id: row for row in segments}
        output = []
        for span in evidence:
            reasons: list[str] = []
            segment = segment_map.get(span.segment_id)
            if not segment:
                reasons.append("UNKNOWN_SEGMENT")
            else:
                if segment.page_number != span.page_number:
                    reasons.append("WRONG_PAGE_BINDING")
                if segment.source_pdf_sha256 != span.source_pdf_sha256 or span.source_pdf_sha256 != source.pdf_sha256:
                    reasons.append("WRONG_PDF_HASH")
                if segment.exact_text[span.start_offset : span.end_offset] != span.exact_text:
                    reasons.append("INVALID_EVIDENCE_BINDING")
                if _sha_text(span.exact_text) != span.text_sha256:
                    reasons.append("TEXT_HASH_MISMATCH")
                if span.exact_text == segment.exact_text:
                    reasons.append("UNBOUNDED_WHOLE_SEGMENT_EVIDENCE")
            output.append(span.model_copy(update={"validation_status": "INVALID" if reasons else "VALID", "validation_reasons": reasons}))
        return output

    def _entity_proposals(self, response: SemanticResponse, evidence: Sequence[EvidenceSpanProposal]) -> list[EntityProposal]:
        evidence_ids = {row.proposal_id for row in evidence}
        rows = []
        for raw in response.entity_proposals:
            normalized = _normalize_label(raw.raw_label)
            status, candidates, reasons = self.identity.resolve(raw.entity_type, raw.raw_label, version=raw.version)
            invalid_refs = sorted(set(raw.supporting_evidence_span_ids) - evidence_ids)
            if raw.entity_type not in self.ontology.allowed_entity_types:
                validation = "INVALID"
                reasons.append("UNKNOWN_ENTITY_TYPE")
            elif invalid_refs:
                validation = "INVALID"
                reasons.append("HALLUCINATED_EVIDENCE_ID")
            elif status in {"AMBIGUOUS", "POSSIBLE_EXISTING_IDENTITY", "UNRESOLVED"}:
                validation = "NEEDS_REVIEW"
            else:
                validation = "VALID"
            rows.append(EntityProposal(
                entity_proposal_id=_stable_id("proposal:entity:", raw.entity_type, normalized, raw.version or ""),
                entity_type=raw.entity_type,
                raw_label=raw.raw_label,
                normalized_label=normalized,
                description=raw.description,
                supporting_evidence_span_ids=raw.supporting_evidence_span_ids,
                identity_resolution_status=status,
                existing_candidate_ids=candidates,
                validation_status=validation,
                validation_reasons=sorted(set(reasons)),
                version=raw.version,
            ))
        return rows

    def _scope_proposals(self, response: SemanticResponse, evidence: Sequence[EvidenceSpanProposal]) -> list[ScopeProposal]:
        evidence_ids = {row.proposal_id for row in evidence}
        rows = []
        for raw in response.scope_proposals:
            reasons = []
            if set(raw.supporting_evidence_span_ids) - evidence_ids:
                reasons.append("HALLUCINATED_EVIDENCE_ID")
            dimensions = {}
            for key, value in raw.dimensions.items():
                try:
                    dimensions[key] = ScopeDimensionProposal.model_validate(value)
                except ValidationError:
                    reasons.append(f"INVALID_SCOPE_DIMENSION:{key}")
            try:
                row = ScopeProposal(
                    scope_proposal_id=_stable_id("proposal:scope:", raw.local_id, *raw.supporting_evidence_span_ids),
                    supporting_evidence_span_ids=raw.supporting_evidence_span_ids,
                    dimensions=dimensions,
                    validation_status="INVALID" if reasons else "VALID",
                    validation_reasons=reasons,
                )
            except ValidationError:
                row = ScopeProposal(
                    scope_proposal_id=_stable_id("proposal:scope:", raw.local_id, *raw.supporting_evidence_span_ids),
                    supporting_evidence_span_ids=raw.supporting_evidence_span_ids,
                    dimensions={"evaluation_context": ScopeDimensionProposal(value=None, status="UNSPECIFIED")},
                    validation_status="INVALID",
                    validation_reasons=[*reasons, "INVALID_SCOPE_SCHEMA"],
                )
            rows.append(row)
        return rows

    def _relation_proposals(self, response: SemanticResponse, evidence: Sequence[EvidenceSpanProposal], entities: Sequence[EntityProposal]) -> list[RelationProposal]:
        evidence_ids = {row.proposal_id for row in evidence}
        by_label = {_normalize_label(row.raw_label): row for row in entities}
        rows = []
        for raw in response.relation_proposals:
            source = by_label.get(_normalize_label(raw.source_label))
            target = by_label.get(_normalize_label(raw.target_label))
            reasons = []
            if not source or not target:
                reasons.append("UNKNOWN_RELATION_ENDPOINT")
            if raw.predicate not in self.ontology.allowed_predicates:
                reasons.append("UNSUPPORTED_RELATION_PROPOSAL")
            elif source and target and not self.ontology.relation_valid(raw.predicate, source.entity_type, target.entity_type):
                reasons.append("INVALID_RELATION_ENDPOINT_TYPES")
            if set(raw.supporting_evidence_span_ids) - evidence_ids:
                reasons.append("HALLUCINATED_EVIDENCE_ID")
            if raw.origin not in {"PDF_EXTRACTED", "INFERRED_FROM_EXISTING_KG"}:
                reasons.append("INVALID_RELATION_ORIGIN")
            rows.append(RelationProposal(
                relation_proposal_id=_stable_id("proposal:relation:", raw.source_label, raw.predicate, raw.target_label),
                source_entity_ref=source.entity_proposal_id if source else f"unresolved:{_normalize_label(raw.source_label)}",
                predicate=raw.predicate,
                target_entity_ref=target.entity_proposal_id if target else f"unresolved:{_normalize_label(raw.target_label)}",
                supporting_evidence_span_ids=raw.supporting_evidence_span_ids,
                origin=raw.origin if raw.origin in {"PDF_EXTRACTED", "INFERRED_FROM_EXISTING_KG"} else "PDF_EXTRACTED",
                validation_status="INVALID" if reasons else "VALID",
                validation_reasons=reasons,
            ))
        return rows

    def _claim_proposals(self, response: SemanticResponse, evidence: Sequence[EvidenceSpanProposal], entities: Sequence[EntityProposal], scopes: Sequence[ScopeProposal]) -> list[AtomicClaimProposal]:
        evidence_ids = {row.proposal_id for row in evidence}
        by_label = {_normalize_label(row.raw_label): row for row in entities}
        scope_by_local: dict[str, ScopeProposal] = {}
        for raw, scope in zip(response.scope_proposals, scopes):
            scope_by_local[raw.local_id] = scope
        rows = []
        for raw in response.atomic_claim_proposals:
            subject = by_label.get(_normalize_label(raw.subject_label))
            scope = scope_by_local.get(raw.scope_local_id)
            reasons = []
            if not raw.supporting_evidence_span_ids:
                reasons.append("CLAIM_EVIDENCE_REQUIRED")
            if set(raw.supporting_evidence_span_ids) - evidence_ids:
                reasons.append("HALLUCINATED_EVIDENCE_ID")
            if not subject:
                reasons.append("UNRESOLVED_CLAIM_SUBJECT")
            if not scope:
                reasons.append("UNKNOWN_SCOPE_PROPOSAL")
            if raw.claim_type not in CLAIM_TYPES:
                reasons.append("INVALID_CLAIM_TYPE")
            if len(re.split(r"\b(?:and|but|whereas|while)\b", raw.claim_text, flags=re.I)) > 3:
                reasons.append("NON_ATOMIC_CLAIM_NEEDS_REVIEW")
            validation = "INVALID" if any(reason in {"CLAIM_EVIDENCE_REQUIRED", "HALLUCINATED_EVIDENCE_ID", "UNKNOWN_SCOPE_PROPOSAL", "INVALID_CLAIM_TYPE"} for reason in reasons) else "NEEDS_REVIEW" if reasons else "VALID"
            rows.append(AtomicClaimProposal(
                claim_proposal_id=_stable_id("proposal:claim:", raw.claim_text, raw.subject_label, raw.scope_local_id),
                claim_text=raw.claim_text,
                claim_type=raw.claim_type,
                subject_ref=subject.entity_proposal_id if subject else f"unresolved:{_normalize_label(raw.subject_label)}",
                object_or_requirement=raw.object_or_requirement,
                supporting_evidence_span_ids=raw.supporting_evidence_span_ids,
                scope_proposal_id=scope.scope_proposal_id if scope else _stable_id("proposal:scope:", raw.scope_local_id),
                version_conditions=raw.version_conditions,
                flavor_conditions=raw.flavor_conditions,
                validation_status=validation,
                validation_reasons=reasons,
            ))
        return rows

    def _validate_semantics(self, evidence, entities, relations, claims, scopes):
        # Models already enforce schema and candidate-only governance. This pass
        # propagates invalid evidence and ambiguous identity into dependent items.
        invalid_evidence = {row.proposal_id for row in evidence if row.validation_status != "VALID"}
        entity_by_id = {row.entity_proposal_id: row for row in entities}
        scope_by_id = {row.scope_proposal_id: row for row in scopes}
        new_entities = []
        for row in entities:
            reasons = list(row.validation_reasons)
            if invalid_evidence & set(row.supporting_evidence_span_ids):
                reasons.append("INVALID_SUPPORTING_EVIDENCE")
            status = "INVALID" if "INVALID_SUPPORTING_EVIDENCE" in reasons or "UNKNOWN_ENTITY_TYPE" in reasons else row.validation_status
            new_entities.append(row.model_copy(update={"validation_status": status, "validation_reasons": sorted(set(reasons))}))
        new_relations = []
        for row in relations:
            reasons = list(row.validation_reasons)
            if invalid_evidence & set(row.supporting_evidence_span_ids):
                reasons.append("INVALID_SUPPORTING_EVIDENCE")
            if row.source_entity_ref not in entity_by_id or row.target_entity_ref not in entity_by_id:
                reasons.append("UNRESOLVED_RELATION_ENDPOINT")
            new_relations.append(row.model_copy(update={"validation_status": "INVALID" if reasons else "VALID", "validation_reasons": sorted(set(reasons))}))
        new_scopes = []
        for row in scopes:
            reasons = list(row.validation_reasons)
            if invalid_evidence & set(row.supporting_evidence_span_ids):
                reasons.append("INVALID_SUPPORTING_EVIDENCE")
            new_scopes.append(row.model_copy(update={"validation_status": "INVALID" if reasons else row.validation_status, "validation_reasons": sorted(set(reasons))}))
        new_claims = []
        for row in claims:
            reasons = list(row.validation_reasons)
            if invalid_evidence & set(row.supporting_evidence_span_ids):
                reasons.append("INVALID_SUPPORTING_EVIDENCE")
            if row.subject_ref not in entity_by_id:
                reasons.append("UNRESOLVED_CLAIM_SUBJECT")
            if row.scope_proposal_id not in scope_by_id:
                reasons.append("UNKNOWN_SCOPE_PROPOSAL")
            invalid = any(reason in {"INVALID_SUPPORTING_EVIDENCE", "HALLUCINATED_EVIDENCE_ID", "CLAIM_EVIDENCE_REQUIRED", "INVALID_CLAIM_TYPE", "UNKNOWN_SCOPE_PROPOSAL"} for reason in reasons)
            status = "INVALID" if invalid else "NEEDS_REVIEW" if reasons else "VALID"
            new_claims.append(row.model_copy(update={"validation_status": status, "validation_reasons": sorted(set(reasons))}))
        return new_entities, new_relations, new_claims, new_scopes

    def _candidate_diff(self, evidence, entities, relations, claims, validation_counts) -> CandidateDiff:
        summary = self.admin.summary()
        identity = Counter(row.identity_resolution_status for row in entities)
        return CandidateDiff(
            current_nodes=summary["scientific_kg_nodes"],
            current_edges=summary["scientific_kg_edges"],
            current_candidate_claims=summary["candidate_claims"],
            entity_proposals=len(entities),
            relation_proposals=len(relations),
            atomic_claim_proposals=len(claims),
            evidence_span_proposals=len(evidence),
            new_candidates=identity["NEW_CANDIDATE"],
            exact_existing_identity_matches=identity["EXACT_EXISTING_IDENTITY"],
            possible_matches=identity["POSSIBLE_EXISTING_IDENTITY"],
            ambiguous=identity["AMBIGUOUS"],
            unresolved=identity["UNRESOLVED"],
            valid=validation_counts["VALID"],
            needs_review=validation_counts["NEEDS_REVIEW"],
            invalid=validation_counts["INVALID"],
        )

    def _proposal_graph(self, source, evidence, entities, relations, claims, scopes) -> ProposalGraph:
        nodes = [ProposalGraphNode(node_id=source.proposal_id, label=source.title, node_type="SourceRevisionProposal", visual_class="SOURCE", detail=_dump(source))]
        edges: list[ProposalGraphEdge] = []
        for span in evidence:
            nodes.append(ProposalGraphNode(node_id=span.proposal_id, label=f"p.{span.page_number} · {span.exact_text[:70]}", node_type="EvidenceSpanProposal", visual_class="EVIDENCE_SPAN", detail=_dump(span)))
            edges.append(ProposalGraphEdge(source=source.proposal_id, target=span.proposal_id, relation="HAS_EVIDENCE_PROPOSAL", origin="PROPOSAL_BINDING"))
        for entity in entities:
            visual = "INVALID_PROPOSAL" if entity.validation_status == "INVALID" else "AMBIGUOUS_PROPOSAL" if entity.identity_resolution_status in {"AMBIGUOUS", "POSSIBLE_EXISTING_IDENTITY", "UNRESOLVED"} else "NEW_PROPOSAL"
            nodes.append(ProposalGraphNode(node_id=entity.entity_proposal_id, label=entity.raw_label, node_type=entity.entity_type, visual_class=visual, detail=_dump(entity)))
            for span_id in entity.supporting_evidence_span_ids:
                edges.append(ProposalGraphEdge(source=span_id, target=entity.entity_proposal_id, relation="SUPPORTS_PROPOSAL", origin="PROPOSAL_BINDING"))
            for existing_id in entity.existing_candidate_ids:
                existing_node_id = f"existing:{existing_id}"
                if all(row.node_id != existing_node_id for row in nodes):
                    nodes.append(ProposalGraphNode(node_id=existing_node_id, label=existing_id, node_type=entity.entity_type, visual_class="EXISTING_KG", detail={"canonical_id": existing_id}))
                edges.append(ProposalGraphEdge(source=entity.entity_proposal_id, target=existing_node_id, relation="IDENTITY_CANDIDATE", origin="INFERRED_FROM_EXISTING_KG"))
        for scope in scopes:
            nodes.append(ProposalGraphNode(node_id=scope.scope_proposal_id, label="Scope proposal", node_type="ApplicabilityScope", visual_class="INVALID_PROPOSAL" if scope.validation_status == "INVALID" else "NEW_PROPOSAL", detail=_dump(scope)))
        for claim in claims:
            nodes.append(ProposalGraphNode(node_id=claim.claim_proposal_id, label=claim.claim_text[:90], node_type="AtomicClaimProposal", visual_class="INVALID_PROPOSAL" if claim.validation_status == "INVALID" else "NEW_PROPOSAL", detail=_dump(claim)))
            if claim.subject_ref in {row.node_id for row in nodes}:
                edges.append(ProposalGraphEdge(source=claim.subject_ref, target=claim.claim_proposal_id, relation="SUBJECT_OF_PROPOSAL", origin="PROPOSAL_BINDING"))
            if claim.scope_proposal_id in {row.node_id for row in nodes}:
                edges.append(ProposalGraphEdge(source=claim.claim_proposal_id, target=claim.scope_proposal_id, relation="HAS_SCOPE_PROPOSAL", origin="PROPOSAL_BINDING"))
            for span_id in claim.supporting_evidence_span_ids:
                edges.append(ProposalGraphEdge(source=span_id, target=claim.claim_proposal_id, relation="SUPPORTS_PROPOSAL", origin="PROPOSAL_BINDING"))
        for relation in relations:
            if relation.source_entity_ref in {row.node_id for row in nodes} and relation.target_entity_ref in {row.node_id for row in nodes}:
                edges.append(ProposalGraphEdge(source=relation.source_entity_ref, target=relation.target_entity_ref, relation=relation.predicate, origin=relation.origin))
        return ProposalGraph(nodes=nodes, edges=edges)

    def _semantic_prompt(self, source: SourceRevisionProposal, evidence: Sequence[EvidenceSpanProposal]) -> str:
        contract = self.ontology_contract()
        payload = {
            "instruction": "Return strict JSON candidate proposals only. Every entity, relation, claim, and scope must cite one or more supplied EvidenceSpanProposal IDs. Never invent evidence text or ontology vocabulary.",
            "prompt_version": PROMPT_VERSION,
            "schema_version": SEMANTIC_SCHEMA_VERSION,
            "source": {"title": source.title, "doi": source.doi},
            "allowed_entity_types": contract["entity_types"],
            "allowed_predicates": contract["predicates"],
            "allowed_claim_types": contract["claim_types"],
            "evidence": [{"id": row.proposal_id, "page": row.page_number, "text": row.exact_text} for row in evidence],
            "required_top_level_keys": ["schema_version", "entity_proposals", "relation_proposals", "atomic_claim_proposals", "scope_proposals"],
        }
        return _canonical_json(payload)

    @staticmethod
    def _persist(run_dir: Path, artifacts: dict[str, Any]) -> None:
        for name, value in artifacts.items():
            path = run_dir / name
            if name.endswith(".jsonl"):
                _write_jsonl(path, value)
            else:
                _write_json(path, value)


def load_studio_run(run_dir: Path) -> dict[str, Any]:
    root = Path(run_dir)
    def jsonl(name: str) -> list[dict[str, Any]]:
        path = root / name
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()] if path.exists() else []
    return {
        "run_dir": root,
        "manifest": _json(root / "manifest.json"),
        "source": _json(root / "source_proposal.json"),
        "segments": jsonl("segments.jsonl"),
        "parse_gaps": _json(root / "parse_gaps.json"),
        "evidence": jsonl("evidence_span_proposals.jsonl"),
        "entities": jsonl("entity_proposals.jsonl"),
        "relations": jsonl("relation_proposals.jsonl"),
        "claims": jsonl("atomic_claim_proposals.jsonl"),
        "scopes": jsonl("scope_proposals.jsonl"),
        "candidate_diff": _json(root / "candidate_diff.json"),
        "proposal_graph": _json(root / "proposal_graph.json"),
        "validation": _json(root / "validation_summary.json"),
        "trace": _json(root / "run_trace.json"),
    }


def load_studio_evaluation_snapshot(snapshot_dir: Path) -> dict[str, Any]:
    root = Path(snapshot_dir)
    proposal = _json(root / "proposal_summary.json")
    evidence = _json(root / "evidence_summary.json")
    return {
        "run_dir": root,
        "manifest": _json(root / "manifest.json")["run_manifest"],
        "source": _json(root / "source_proposal.json"),
        "segments": evidence.get("segments", []),
        "parse_gaps": evidence.get("parse_gaps", []),
        "evidence": evidence.get("evidence_span_proposals", []),
        "entities": proposal.get("entity_proposals", []),
        "relations": proposal.get("relation_proposals", []),
        "claims": proposal.get("atomic_claim_proposals", []),
        "scopes": proposal.get("scope_proposals", []),
        "candidate_diff": _json(root / "candidate_diff.json"),
        "proposal_graph": _json(root / "proposal_graph.json"),
        "validation": _json(root / "validation_summary.json"),
        "trace": _json(root / "run_trace.json"),
    }


def candidate_demo_view(run: dict[str, Any]) -> dict[str, Any]:
    """Build a read-only presentation model from one persisted Studio run.

    Counts and bindings intentionally come from the supplied run artifacts.  This
    helper performs no extraction, validation repair, graph mutation, or
    production persistence, which keeps the demo UI deterministic and testable.
    """

    manifest = dict(run.get("manifest") or {})
    source = dict(run.get("source") or {})
    evidence_rows = [dict(row) for row in run.get("evidence") or []]
    entity_rows = [dict(row) for row in run.get("entities") or []]
    relation_rows = [dict(row) for row in run.get("relations") or []]
    claim_rows = [dict(row) for row in run.get("claims") or []]
    scope_rows = [dict(row) for row in run.get("scopes") or []]
    graph = dict(run.get("proposal_graph") or {})

    evidence_by_id = {str(row.get("proposal_id")): row for row in evidence_rows}
    entity_by_id = {str(row.get("entity_proposal_id")): row for row in entity_rows}
    scope_by_id = {str(row.get("scope_proposal_id")): row for row in scope_rows}

    statements: list[dict[str, Any]] = []
    for claim in claim_rows:
        subject_ref = str(claim.get("subject_ref") or "")
        subject = entity_by_id.get(subject_ref, {})
        scope = scope_by_id.get(str(claim.get("scope_proposal_id") or ""), {})
        bindings = [
            evidence_by_id[evidence_id]
            for evidence_id in claim.get("supporting_evidence_span_ids") or []
            if evidence_id in evidence_by_id
        ]
        statements.append(
            {
                **claim,
                "subject_label": subject.get("raw_label") or subject_ref or "NOT_MODELED",
                "predicate_label": claim.get("predicate") or claim.get("claim_type") or "NOT_MODELED",
                "polarity_label": claim.get("polarity") or "NOT_MODELED",
                "scope": scope,
                "evidence_bindings": bindings,
            }
        )

    validation_rows: list[dict[str, Any]] = []
    groups = (
        ("EvidenceSpan", evidence_rows, "proposal_id"),
        ("Entity", entity_rows, "entity_proposal_id"),
        ("Relation", relation_rows, "relation_proposal_id"),
        ("Candidate Statement", claim_rows, "claim_proposal_id"),
        ("ApplicabilityScope", scope_rows, "scope_proposal_id"),
    )
    for object_type, rows, id_field in groups:
        for row in rows:
            validation_rows.append(
                {
                    "object_type": object_type,
                    "object_id": row.get(id_field, ""),
                    "status": row.get("validation_status", "NEEDS_REVIEW"),
                    "reason_or_issue": "; ".join(row.get("validation_reasons") or [])
                    or "No validation issue recorded",
                }
            )

    page_count = int(manifest.get("page_count") or source.get("page_count") or 0)
    parsed_pages = int(manifest.get("parsed_pages") or 0)
    parse_gap_count = int(
        manifest.get("parse_gap_count")
        if manifest.get("parse_gap_count") is not None
        else len(run.get("parse_gaps") or [])
    )
    parse_status = "PARSED" if page_count and parsed_pages == page_count and parse_gap_count == 0 else "PARTIAL"
    counts = dict((run.get("validation") or {}).get("counts") or {})
    validation_counts = {
        "VALID": int(counts.get("VALID", 0)),
        "NEEDS_REVIEW": int(counts.get("NEEDS_REVIEW", 0)),
        "INVALID": int(counts.get("INVALID", 0)),
    }
    graph_nodes = len(graph.get("nodes") or [])
    graph_edges = len(graph.get("edges") or [])
    validate_state = "REVIEW" if validation_counts["INVALID"] or validation_counts["NEEDS_REVIEW"] else "DONE"

    return {
        "document": {
            "name": source.get("title") or source.get("original_filename") or manifest.get("original_filename") or "Unknown PDF",
            "file": source.get("original_filename") or manifest.get("original_filename") or "Unknown PDF",
            "source_type": source.get("source_type") or "local_scientific_pdf",
            "page_count": page_count,
            "parsed_pages": parsed_pages,
            "parse_gap_count": parse_gap_count,
            "parse_status": parse_status,
            "parser": " ".join(
                part for part in (str(source.get("parser_name") or ""), str(source.get("parser_version") or "")) if part
            ),
            "sha256": source.get("pdf_sha256") or manifest.get("pdf_sha256") or "",
        },
        "pipeline": [
            {"stage": "PDF", "value": "1 document", "status": "DONE"},
            {"stage": "Parse", "value": f"{parsed_pages} / {page_count} pages", "status": "DONE" if parse_status == "PARSED" else "WARNING"},
            {"stage": "Evidence", "value": f"{len(evidence_rows)} proposals", "status": "DONE" if evidence_rows else "BLOCKED"},
            {"stage": "Statement", "value": f"{len(claim_rows)} proposals", "status": "DONE" if claim_rows else "WARNING"},
            {"stage": "Scope", "value": f"{len(scope_rows)} proposals", "status": "DONE" if scope_rows else "WARNING"},
            {"stage": "Validate", "value": f"{validation_counts['VALID']} / {validation_counts['NEEDS_REVIEW']} / {validation_counts['INVALID']}", "status": validate_state},
            {"stage": "Candidate KG", "value": f"{graph_nodes} nodes · {graph_edges} edges", "status": "DONE" if graph.get("bounded_to_run") else "BLOCKED"},
        ],
        "statements": statements,
        "validation_counts": validation_counts,
        "validation_rows": validation_rows,
        "graph": {
            "node_count": graph_nodes,
            "edge_count": graph_edges,
            "bounded_to_run": bool(graph.get("bounded_to_run")),
        },
    }


def proposal_graph_view(payload: dict[str, Any]) -> KnowledgeGraphView:
    """Adapt persisted proposal artifacts to the reusable graph viewer.

    The adapter changes display labels only. Full artifact labels, excerpts,
    identifiers, hashes, validation results, and provenance stay in metadata.
    """

    rows = list(payload.get("nodes", []))
    by_id = {row["node_id"]: row for row in rows}
    entity_labels = {
        row["node_id"]: str((row.get("detail") or {}).get("raw_label") or row.get("label") or "Entity")
        for row in rows
        if row.get("node_type")
        not in {"SourceRevisionProposal", "EvidenceSpanProposal", "AtomicClaimProposal", "ApplicabilityScope"}
        and row.get("visual_class") != "EXISTING_KG"
    }
    subject_by_claim: dict[str, str] = {}
    existing_labels: dict[str, str] = {}
    for edge in payload.get("edges", []):
        if edge.get("relation") == "SUBJECT_OF_PROPOSAL":
            subject_by_claim[str(edge["target"])] = entity_labels.get(
                str(edge["source"]), str(edge["source"])
            )
        elif edge.get("relation") == "IDENTITY_CANDIDATE":
            existing_labels[str(edge["target"])] = entity_labels.get(
                str(edge["source"]), str(edge["target"])
            )

    evidence_ids = [
        row["node_id"]
        for row in sorted(
            (item for item in rows if item.get("node_type") == "EvidenceSpanProposal"),
            key=lambda item: (
                int((item.get("detail") or {}).get("page_number") or 0),
                item["node_id"],
            ),
        )
    ]
    claim_ids = [row["node_id"] for row in rows if row.get("node_type") == "AtomicClaimProposal"]
    scope_ids = [row["node_id"] for row in rows if row.get("node_type") == "ApplicabilityScope"]
    evidence_number = {node_id: index for index, node_id in enumerate(evidence_ids, 1)}
    claim_number = {node_id: index for index, node_id in enumerate(claim_ids, 1)}
    scope_number = {node_id: index for index, node_id in enumerate(scope_ids, 1)}

    def compact_text(value: Any, *, limit: int = 46) -> str:
        text = re.sub(r"\s+", " ", str(value or "")).strip()
        text = re.sub(r"^(?:\d+\s+Index\s+\d+\s+|Description\s+|Value\s+|Examples\s+)", "", text, flags=re.I)
        return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"

    def projection(row: dict[str, Any]) -> tuple[str, str, str]:
        node_id = row["node_id"]
        node_type = str(row.get("node_type") or "Unknown")
        detail = dict(row.get("detail") or {})
        if node_type == "EvidenceSpanProposal":
            return (
                f"E{evidence_number[node_id]} · p.{detail.get('page_number', '?')}",
                "evidence",
                "EvidenceSpan",
            )
        if node_type == "AtomicClaimProposal":
            subject = subject_by_claim.get(node_id, "Candidate")
            predicate = str(detail.get("claim_type") or "statement")
            obj = compact_text(
                detail.get("object_or_requirement") or row.get("label"), limit=24
            )
            return (
                f"S{claim_number[node_id]} · {compact_text(subject, limit=12)} → "
                f"{compact_text(predicate, limit=14)} → {obj}",
                "statement",
                "StatementRevision-compatible proposal",
            )
        if node_type == "ApplicabilityScope":
            dimensions = detail.get("dimensions") or {}
            explicit = [
                str(value.get("value"))
                for value in dimensions.values()
                if isinstance(value, dict)
                and value.get("status") == "EXPLICIT"
                and value.get("value")
            ]
            scope_text = " · ".join(explicit) if explicit else "unspecified"
            return (f"Scope {scope_number[node_id]} · {scope_text}", "scope", "ApplicabilityScope")
        if node_type == "SourceRevisionProposal":
            title = str(detail.get("title") or row.get("label") or "Source")
            return (f"{compact_text(title.split(':', 1)[0], limit=32)} source", "source", "SourceRevision")
        if row.get("visual_class") == "EXISTING_KG":
            return (existing_labels.get(node_id, compact_text(row.get("label"), limit=32)), "existing", node_type)
        return (
            compact_text(detail.get("raw_label") or row.get("label"), limit=36),
            "entity",
            node_type,
        )

    node_metadata: dict[str, dict[str, Any]] = {}
    for row in rows:
        display_label, viewer_group, ontology_type = projection(row)
        detail = dict(row.get("detail") or {})
        validation_status = str(detail.get("validation_status") or "CANDIDATE")
        node_metadata[row["node_id"]] = {
            "proposal_node_type": row["node_type"],
            "ontology_type": ontology_type,
            "viewer_group": viewer_group,
            "display_label": display_label,
            "full_label": row["label"],
            "candidate_state": (
                "INVALID"
                if validation_status == "INVALID"
                else "VALIDATED"
                if validation_status == "VALID"
                else "CANDIDATE"
            ),
            **detail,
        }
    nodes = {
        row["node_id"]: GraphNode(
            node_id=row["node_id"],
            label=row["label"],
            kind=row["visual_class"],
            metadata=node_metadata[row["node_id"]],
        )
        for row in rows
    }
    edges = []
    for row in payload.get("edges", []):
        source_state = node_metadata.get(row["source"], {}).get("candidate_state", "CANDIDATE")
        target_state = node_metadata.get(row["target"], {}).get("candidate_state", "CANDIDATE")
        validation_status = (
            "INVALID"
            if "INVALID" in {source_state, target_state}
            else "VALID"
            if source_state == target_state == "VALIDATED"
            else "CANDIDATE"
        )
        edges.append(
            GraphEdge(
                source=row["source"],
                target=row["target"],
                relation=row["relation"],
                metadata={
                    "origin": row["origin"],
                    "validation_status": validation_status,
                    "candidate_state": (
                        "INVALID"
                        if validation_status == "INVALID"
                        else "VALIDATED"
                        if validation_status == "VALID"
                        else "CANDIDATE"
                    ),
                    "provenance": ["proposal_graph.json", row["origin"]],
                    "reason": "real persisted proposal binding",
                },
            )
        )
    ids = list(nodes)
    return KnowledgeGraphView(
        nodes=nodes,
        edges=edges,
        visible_node_ids=ids,
        visible_edges=edges,
        inventory={"nodes": len(nodes), "edges": len(edges)},
        truncated=False,
    )
