from __future__ import annotations

import hashlib
import importlib.metadata
import io
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

from .models import (
    BlockType,
    BoundedEvidenceSpanCandidate,
    CanonicalStatementCandidate,
    FinalDisposition,
    Governance,
    HumanReviewPacket,
    LayoutBlock,
    LinkedEntityCandidate,
    PropositionType,
    ProvenanceMapEntry,
    RawProposition,
    ReconstructedBlock,
    ResolvedScope,
    ScopeValue,
    ScopeValueStatus,
    SemanticBlock,
    SourceDocument,
    StageName,
    StageOutcome,
    ValidationReport,
)
from .ontology import ExactIdentityIndex, FrozenOntologyConformanceAdapter


SECTION_TYPES = {
    "description": BlockType.DESCRIPTION,
    "usage": BlockType.USAGE,
    "arguments": BlockType.ARGUMENTS,
    "details": BlockType.DETAILS,
    "value": BlockType.RETURN_VALUE,
    "examples": BlockType.EXAMPLES_CODE,
    "references": BlockType.REFERENCES,
    "author": BlockType.DOCUMENT_METADATA,
    "see also": BlockType.REFERENCES,
    "format": BlockType.DOCUMENT_METADATA,
}
TOC_ENTRY = re.compile(r"^([A-Za-z][\w.]*)\s+(?:\.\s*){3,}\d+\s*$")
PAGE_HEADER = re.compile(r"^(?:\d+\s+\S+|\S+\s+\d+)$")
PARAMETER_START = re.compile(r"^(\.\.\.|[A-Za-z][\w.]*)\s+")
TRUNCATED_END = re.compile(r"\b(?:and|or|with|to|of|the|a|an|this|that|using|under)\s*$", re.I)


def _sha_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _stable_id(prefix: str, *parts: object, length: int = 24) -> str:
    payload = "\0".join(str(part) for part in parts)
    return f"{prefix}{_sha_text(payload)[:length]}"


@dataclass(frozen=True)
class _Line:
    text: str
    start: int
    end: int


def _lines(page_text: str) -> list[_Line]:
    result: list[_Line] = []
    for match in re.finditer(r"[^\n]*(?:\n|$)", page_text):
        raw = match.group(0)
        if not raw:
            continue
        without_newline = raw[:-1] if raw.endswith("\n") else raw
        if without_newline.strip():
            leading = len(without_newline) - len(without_newline.lstrip())
            trailing = len(without_newline.rstrip())
            result.append(
                _Line(
                    text=without_newline[leading:trailing],
                    start=match.start() + leading,
                    end=match.start() + trailing,
                )
            )
    return result


def _reconstruct(raw_text: str) -> tuple[str, list[ProvenanceMapEntry], int]:
    def dehyphenation_end(position: int) -> int | None:
        if (
            raw_text[position] != "-"
            or position == 0
            or not raw_text[position - 1].isalpha()
            or position + 1 >= len(raw_text)
            or raw_text[position + 1] not in "\r\n"
        ):
            return None
        next_position = position + 1
        if raw_text[next_position] == "\r":
            next_position += 1
        if next_position < len(raw_text) and raw_text[next_position] == "\n":
            next_position += 1
        while next_position < len(raw_text) and raw_text[next_position] in " \t":
            next_position += 1
        left_match = re.search(r"[A-Za-z]+$", raw_text[:position])
        left_fragment = left_match.group(0) if left_match else ""
        if next_position < len(raw_text) and raw_text[next_position].isalpha():
            # Preserve short lexical compounds such as p-value and RNA-seq;
            # merge ordinary PDF line-wrap fragments, including nU- / MIs.
            if len(left_fragment) < 2:
                return None
            if left_fragment.isupper() and len(left_fragment) <= 5:
                return None
            return next_position
        return None

    output: list[str] = []
    provenance: list[ProvenanceMapEntry] = []
    dehyphenations = 0
    i = 0
    while i < len(raw_text):
        char = raw_text[i]
        dehyphenated_to = dehyphenation_end(i)
        if dehyphenated_to is not None:
            provenance.append(
                ProvenanceMapEntry(
                    normalized_start=len(output),
                    normalized_end=len(output),
                    raw_start=i,
                    raw_end=dehyphenated_to,
                    operation="DEHYPHENATED",
                )
            )
            dehyphenations += 1
            i = dehyphenated_to
            continue
        if char.isspace():
            j = i + 1
            while j < len(raw_text) and raw_text[j].isspace():
                j += 1
            if char in "\r\n" and output and output[-1] == "-" and j < len(raw_text) and raw_text[j].isalpha():
                left_match = re.search(r"[A-Za-z]+-$", "".join(output))
                left_fragment = left_match.group(0)[:-1] if left_match else ""
                if len(left_fragment) < 2 or (left_fragment.isupper() and len(left_fragment) <= 5):
                    provenance.append(
                        ProvenanceMapEntry(
                            normalized_start=len(output),
                            normalized_end=len(output),
                            raw_start=i,
                            raw_end=j,
                            operation="WHITESPACE_COLLAPSED",
                        )
                    )
                    i = j
                    continue
            if output and output[-1] != " ":
                start = len(output)
                output.append(" ")
                provenance.append(
                    ProvenanceMapEntry(
                        normalized_start=start,
                        normalized_end=start + 1,
                        raw_start=i,
                        raw_end=j,
                        operation="WHITESPACE_COLLAPSED",
                    )
                )
            i = j
            continue
        start_raw = i
        start_norm = len(output)
        while i < len(raw_text) and not raw_text[i].isspace() and dehyphenation_end(i) is None:
            output.append(raw_text[i])
            i += 1
        provenance.append(
            ProvenanceMapEntry(
                normalized_start=start_norm,
                normalized_end=len(output),
                raw_start=start_raw,
                raw_end=i,
                operation="COPY",
            )
        )
    normalized = "".join(output).strip()
    if output and output[0] == " ":
        for item in provenance:
            item.normalized_start = max(0, item.normalized_start - 1)
            item.normalized_end = max(0, item.normalized_end - 1)
    return normalized, provenance, dehyphenations


def _is_truncated(text: str, *, typed_block: bool) -> tuple[bool, list[str]]:
    value = text.strip()
    reasons: list[str] = []
    if not value:
        reasons.append("EMPTY_PROPOSITION")
    if value.count("(") != value.count(")") or value.count("[") != value.count("]"):
        reasons.append("UNBALANCED_DELIMITERS")
    if TRUNCATED_END.search(value):
        reasons.append("TRAILING_CONNECTIVE_FRAGMENT")
    if not typed_block and value and value[-1] not in ".!?'\")]:":
        reasons.append("NO_TERMINAL_BOUNDARY")
    return bool(reasons), reasons


class ScientificDocumentIngestionService:
    """Deterministic candidate-only ingestion for one text-extractable PDF."""

    def __init__(self, repository_root: Path) -> None:
        self.repository_root = repository_root.resolve()
        self.ontology = FrozenOntologyConformanceAdapter(self.repository_root)
        self.identities = ExactIdentityIndex(self.repository_root)

    @staticmethod
    def parser_version() -> str:
        try:
            return importlib.metadata.version("pypdf")
        except importlib.metadata.PackageNotFoundError:
            return "unavailable"

    def run_pdf(
        self,
        pdf_path: Path,
        *,
        expected_sha256: str | None = None,
    ) -> dict[str, object]:
        pdf_bytes = pdf_path.read_bytes()
        return self.run_pdf_bytes(
            pdf_path.name,
            pdf_bytes,
            expected_sha256=expected_sha256,
        )

    def run_pdf_bytes(
        self,
        filename: str,
        pdf_bytes: bytes,
        *,
        expected_sha256: str | None = None,
    ) -> dict[str, object]:
        digest = hashlib.sha256(pdf_bytes).hexdigest()
        if expected_sha256 is not None and digest != expected_sha256:
            raise ValueError(f"PDF_SHA256_MISMATCH expected={expected_sha256} actual={digest}")
        try:
            from pypdf import PdfReader
        except ModuleNotFoundError as exc:
            raise RuntimeError("pypdf is required for scientific PDF ingestion") from exc
        reader = PdfReader(io.BytesIO(pdf_bytes))
        pages = [str(page.extract_text() or "").replace("\r\n", "\n").replace("\r", "\n") for page in reader.pages]
        metadata = {str(key): str(value) for key, value in dict(reader.metadata or {}).items()}
        return self.run_pages(
            filename=filename,
            pdf_sha256=digest,
            pages=pages,
            metadata=metadata,
            parser_version=self.parser_version(),
        )

    def run_pages(
        self,
        *,
        filename: str,
        pdf_sha256: str,
        pages: Sequence[str],
        metadata: dict[str, str] | None = None,
        parser_version: str = "synthetic-fixture",
    ) -> dict[str, object]:
        if not pages or any(not isinstance(page, str) for page in pages):
            raise ValueError("one or more page text streams are required")
        source = self._source(filename, pdf_sha256, pages, metadata or {}, parser_version)
        layout_blocks = self._layout_blocks(pages, source)
        reconstructed = [self._reconstructed(block) for block in layout_blocks]
        semantic_blocks = self._semantic_blocks(layout_blocks, reconstructed)
        packets: list[HumanReviewPacket] = []
        layout_by_id = {block.block_id: block for block in layout_blocks}
        reconstructed_by_id = {block.block_id: block for block in reconstructed}
        for semantic in semantic_blocks:
            propositions = self._propositions(semantic, layout_by_id[semantic.layout_block_id])
            if not propositions:
                packets.append(
                    self._packet_without_proposition(
                        source,
                        semantic,
                        layout_by_id[semantic.layout_block_id],
                        reconstructed_by_id[semantic.layout_block_id],
                    )
                )
                continue
            for proposition in propositions:
                packets.append(
                    self._packet_for_proposition(
                        source,
                        semantic,
                        layout_by_id[semantic.layout_block_id],
                        reconstructed_by_id[semantic.layout_block_id],
                        proposition,
                    )
                )
        counts = Counter(packet.final_disposition.value for packet in packets)
        unbounded_ready = sum(
            1
            for packet in packets
            if packet.final_disposition == FinalDisposition.CANDIDATE_READY
            and (packet.evidence_span is None or not packet.evidence_span.bounded or packet.evidence_span.whole_segment)
        )
        return {
            "source": source,
            "page_streams": list(pages),
            "layout_blocks": layout_blocks,
            "reconstructed_blocks": reconstructed,
            "semantic_blocks": semantic_blocks,
            "packets": packets,
            "summary": {
                "pipeline": [
                    "LayoutBlock",
                    "ReconstructedBlock",
                    "SemanticBlock",
                    "RawProposition",
                    "BoundedEvidenceSpanCandidate",
                    "LinkedEntityCandidate",
                    "CanonicalStatementCandidate",
                    "ResolvedScope",
                    "ValidationReport",
                    "HumanReviewPacket",
                ],
                "counts": {status.value: counts.get(status.value, 0) for status in FinalDisposition},
                "layout_block_count": len(layout_blocks),
                "semantic_block_count": len(semantic_blocks),
                "dehyphenation_count": sum(block.dehyphenation_count for block in reconstructed),
                "unbounded_ready_candidates": unbounded_ready,
                "hallucinated_scope_count": sum(
                    packet.scope.hallucinated_value_count for packet in packets if packet.scope is not None
                ),
                "ontology_version": self.ontology.ontology_version,
                "governance": Governance().model_dump(mode="json"),
            },
        }

    def _source(
        self,
        filename: str,
        pdf_sha256: str,
        pages: Sequence[str],
        metadata: dict[str, str],
        parser_version: str,
    ) -> SourceDocument:
        first = pages[0] if pages else ""
        version_match = re.search(r"(?m)^Version\s+([^\s]+)\s*$", first)
        package_match = re.search(r"(?m)^Package\s+[‘'\"]?([^’'\"\n]+)", first)
        title_match = re.search(r"(?m)^Title\s+(.+)$", first)
        title = str(metadata.get("/Title") or (title_match.group(1).strip() if title_match else ""))
        software = package_match.group(1).strip() if package_match else None
        version = version_match.group(1).strip() if version_match else None
        return SourceDocument(
            source_artifact_id=f"source-artifact:sha256:{pdf_sha256}",
            source_revision_id=f"source-revision:sha256:{pdf_sha256}",
            filename=filename,
            sha256=pdf_sha256,
            page_count=len(pages),
            title=title,
            software_name=software,
            software_version=version,
            parser_name="pypdf",
            parser_version=parser_version,
        )

    def _layout_blocks(self, pages: Sequence[str], source: SourceDocument) -> list[LayoutBlock]:
        page_lines = [_lines(page) for page in pages]
        toc_names = {
            match.group(1)
            for lines in page_lines
            for line in lines
            if (match := TOC_ENTRY.match(line.text)) is not None
        }
        blocks: list[LayoutBlock] = []
        operator: str | None = None
        section: str | None = None
        in_toc = False
        after_index = False

        for page_number, (page_text, lines) in enumerate(zip(pages, page_lines), 1):
            buffer: list[_Line] = []
            hint = BlockType.UNKNOWN

            def flush() -> None:
                nonlocal buffer
                if not buffer:
                    return
                start, end = buffer[0].start, buffer[-1].end
                raw = page_text[start:end]
                blocks.append(
                    LayoutBlock(
                        block_id=_stable_id("layout-block:", source.sha256, page_number, start, end, raw),
                        page=page_number,
                        block_index=len([item for item in blocks if item.page == page_number]),
                        raw_text=raw,
                        page_start_offset=start,
                        page_end_offset=end,
                        section_label=section,
                        operator_name=operator,
                        document_version=source.software_version,
                        structural_hint=hint,
                    )
                )
                buffer = []

            def emit_line(line: _Line, line_hint: BlockType) -> None:
                nonlocal hint, buffer
                flush()
                hint = line_hint
                buffer = [line]
                flush()

            nonempty_positions = {id(line): index for index, line in enumerate(lines)}
            for line in lines:
                stripped = line.text.strip()
                line_index = nonempty_positions[id(line)]
                is_edge_line = line_index == 0 or line_index == len(lines) - 1
                if stripped.isdigit() or (is_edge_line and PAGE_HEADER.match(stripped)):
                    emit_line(line, BlockType.HEADER_FOOTER)
                    continue
                if stripped == "Contents":
                    flush()
                    in_toc = True
                    after_index = False
                    section = "Contents"
                    hint = BlockType.TOC
                    buffer = [line]
                    continue
                is_operator_heading = False
                operator_match = re.match(r"^([A-Za-z][\w.]*)\s+(.+)$", stripped)
                if operator_match and operator_match.group(1) in toc_names and not TOC_ENTRY.match(stripped):
                    is_operator_heading = True
                if in_toc and is_operator_heading and after_index:
                    flush()
                    in_toc = False
                    section = None
                if in_toc:
                    hint = BlockType.TOC
                    buffer.append(line)
                    if re.match(r"^Index\s+\d+\s*$", stripped):
                        after_index = True
                    continue
                if is_operator_heading:
                    flush()
                    operator = operator_match.group(1)
                    section = None
                    hint = BlockType.OPERATOR_HEADING
                    buffer = [line]
                    flush()
                    continue
                section_type = SECTION_TYPES.get(stripped.casefold())
                if section_type is not None:
                    flush()
                    section = stripped
                    hint = section_type
                    buffer = [line]
                    continue
                if not buffer:
                    if section is None and operator is None:
                        hint = BlockType.DOCUMENT_METADATA
                    else:
                        hint = SECTION_TYPES.get((section or "").casefold(), BlockType.UNKNOWN)
                buffer.append(line)
            flush()
        return blocks

    @staticmethod
    def _reconstructed(block: LayoutBlock) -> ReconstructedBlock:
        normalized, provenance, count = _reconstruct(block.raw_text)
        return ReconstructedBlock(
            block_id=block.block_id,
            raw_text=block.raw_text,
            normalized_text=normalized,
            provenance_map=provenance,
            dehyphenation_count=count,
            page=block.page,
            section_label=block.section_label,
            operator_name=block.operator_name,
            document_version=block.document_version,
        )

    def _semantic_blocks(
        self,
        layout_blocks: Sequence[LayoutBlock],
        reconstructed: Sequence[ReconstructedBlock],
    ) -> list[SemanticBlock]:
        recon_by_id = {block.block_id: block for block in reconstructed}
        parameters: dict[str, set[str]] = {}
        for layout in layout_blocks:
            if layout.structural_hint != BlockType.USAGE or not layout.operator_name:
                continue
            text = recon_by_id[layout.block_id].normalized_text
            call = re.search(rf"\b{re.escape(layout.operator_name)}\s*\((.*)\)", text)
            if not call:
                continue
            parameters[layout.operator_name] = set(
                re.findall(r"(?:^|,\s*)(\.\.\.|[A-Za-z][\w.]*)\s*(?==|,|\)|$)", call.group(1))
            )

        semantic: list[SemanticBlock] = []
        for layout in layout_blocks:
            recon = recon_by_id[layout.block_id]
            if layout.structural_hint == BlockType.ARGUMENTS:
                children = self._argument_semantic_blocks(layout, parameters.get(layout.operator_name or "", set()))
                if children:
                    semantic.extend(children)
                    continue
            content_start = self._content_start(layout)
            semantic.append(
                SemanticBlock(
                    semantic_block_id=_stable_id("semantic-block:", layout.block_id, layout.structural_hint.value),
                    layout_block_id=layout.block_id,
                    page=layout.page,
                    raw_text=layout.raw_text,
                    normalized_text=recon.normalized_text,
                    block_type=layout.structural_hint,
                    claim_eligible=layout.structural_hint
                    in {BlockType.DESCRIPTION, BlockType.DETAILS, BlockType.RETURN_VALUE},
                    content_raw_start=content_start,
                    content_raw_end=len(layout.raw_text),
                    operator_name=layout.operator_name,
                    document_version=layout.document_version,
                )
            )
        return semantic

    @staticmethod
    def _content_start(layout: LayoutBlock) -> int:
        if layout.structural_hint in set(SECTION_TYPES.values()):
            newline = layout.raw_text.find("\n")
            if newline >= 0:
                return newline + 1
        return 0

    def _argument_semantic_blocks(self, layout: LayoutBlock, known_parameters: set[str]) -> list[SemanticBlock]:
        lines = _lines(layout.raw_text)
        if lines and lines[0].text.casefold() == "arguments":
            lines = lines[1:]
        starts: list[tuple[int, str]] = []
        for index, line in enumerate(lines):
            match = PARAMETER_START.match(line.text)
            if match and (not known_parameters or match.group(1) in known_parameters):
                starts.append((index, match.group(1)))
        result: list[SemanticBlock] = []
        for position, (line_index, parameter) in enumerate(starts):
            end_line_index = starts[position + 1][0] if position + 1 < len(starts) else len(lines)
            selected = lines[line_index:end_line_index]
            start, end = selected[0].start, selected[-1].end
            raw = layout.raw_text[start:end]
            normalized, _, _ = _reconstruct(raw)
            result.append(
                SemanticBlock(
                    semantic_block_id=_stable_id("semantic-block:", layout.block_id, parameter, start, end),
                    layout_block_id=layout.block_id,
                    page=layout.page,
                    raw_text=raw,
                    normalized_text=normalized,
                    block_type=BlockType.PARAMETER_DESCRIPTION,
                    claim_eligible=True,
                    content_raw_start=start,
                    content_raw_end=end,
                    operator_name=layout.operator_name,
                    parameter_name=parameter,
                    document_version=layout.document_version,
                )
            )
        return result

    def _propositions(self, semantic: SemanticBlock, layout: LayoutBlock) -> list[RawProposition]:
        if not semantic.claim_eligible:
            return []
        if semantic.block_type == BlockType.PARAMETER_DESCRIPTION:
            normalized = semantic.normalized_text
            match = re.match(r"^(\.\.\.|[A-Za-z][\w.]*)\s+(.+)$", normalized)
            text = match.group(2).strip() if match else normalized
            truncated, reasons = _is_truncated(text, typed_block=True)
            return [
                RawProposition(
                    proposition_id=_stable_id("raw-proposition:", semantic.semantic_block_id, text),
                    semantic_block_id=semantic.semantic_block_id,
                    proposition_type=PropositionType.PARAMETER_DESCRIPTION,
                    text=text,
                    operator_name=semantic.operator_name,
                    parameter_name=semantic.parameter_name,
                    is_complete=not truncated,
                    abstention_reasons=reasons,
                    raw_start=semantic.content_raw_start,
                    raw_end=semantic.content_raw_end,
                )
            ]
        content_start = semantic.content_raw_start
        content_end = semantic.content_raw_end
        raw_content = layout.raw_text[content_start:content_end]
        typed = semantic.block_type == BlockType.RETURN_VALUE
        proposition_type = {
            BlockType.RETURN_VALUE: PropositionType.RETURN_VALUE,
            BlockType.DESCRIPTION: PropositionType.DESCRIPTION,
            BlockType.DETAILS: PropositionType.DETAIL,
        }[semantic.block_type]
        pieces: list[tuple[int, int, str]] = []
        if typed:
            leading = len(raw_content) - len(raw_content.lstrip())
            trailing = len(raw_content.rstrip())
            if trailing > leading:
                pieces.append((content_start + leading, content_start + trailing, raw_content[leading:trailing]))
        else:
            for match in re.finditer(r".*?(?:[.!?](?=\s|$)|$)", raw_content, flags=re.S):
                value = match.group(0)
                if not value.strip():
                    continue
                leading = len(value) - len(value.lstrip())
                trailing = len(value.rstrip())
                start = content_start + match.start() + leading
                end = content_start + match.start() + trailing
                pieces.append((start, end, layout.raw_text[start:end]))
        result: list[RawProposition] = []
        for start, end, raw in pieces:
            normalized, _, _ = _reconstruct(raw)
            if len(normalized) < 12:
                continue
            truncated, reasons = _is_truncated(normalized, typed_block=typed)
            result.append(
                RawProposition(
                    proposition_id=_stable_id("raw-proposition:", semantic.semantic_block_id, start, end, normalized),
                    semantic_block_id=semantic.semantic_block_id,
                    proposition_type=proposition_type,
                    text=normalized,
                    operator_name=semantic.operator_name,
                    is_complete=not truncated,
                    abstention_reasons=reasons,
                    raw_start=start,
                    raw_end=end,
                )
            )
        return result

    def _evidence(
        self,
        source: SourceDocument,
        layout: LayoutBlock,
        proposition: RawProposition,
    ) -> BoundedEvidenceSpanCandidate:
        exact = layout.raw_text[proposition.raw_start : proposition.raw_end]
        normalized, _, _ = _reconstruct(exact)
        whole_segment = proposition.raw_start == 0 and proposition.raw_end == len(layout.raw_text)
        return BoundedEvidenceSpanCandidate(
            evidence_span_id=_stable_id("evidence-span-candidate:", source.sha256, layout.page, layout.page_start_offset + proposition.raw_start, exact),
            source_revision_id=source.source_revision_id,
            source_artifact_id=source.source_artifact_id,
            exact_text=exact,
            normalized_text=normalized,
            content_hash=_sha_text(exact),
            locator=f"pdf_page:{layout.page}:unicode_text_stream:{layout.page_start_offset + proposition.raw_start}-{layout.page_start_offset + proposition.raw_end}",
            page=layout.page,
            section=layout.section_label,
            page_start_offset=layout.page_start_offset + proposition.raw_start,
            page_end_offset=layout.page_start_offset + proposition.raw_end,
            block_start_offset=proposition.raw_start,
            block_end_offset=proposition.raw_end,
            layout_block_id=layout.block_id,
            bounded=True,
            whole_segment=whole_segment,
            ontology_version=self.ontology.ontology_version,
        )

    def _link_entities(
        self,
        source: SourceDocument,
        proposition: RawProposition,
    ) -> list[LinkedEntityCandidate]:
        if not proposition.operator_name or not source.software_name or not source.software_version:
            return []
        operator = self.identities.operator_revision(
            source.software_name, proposition.operator_name, source.software_version
        )
        if operator is None:
            return [
                LinkedEntityCandidate(
                    mention=f"{source.software_name}::{proposition.operator_name}@{source.software_version}",
                    entity_type="OperatorRevision",
                    candidate_id=_stable_id("operator-revision-candidate:", source.software_name, proposition.operator_name, source.software_version),
                    resolution_status="NEW_CANDIDATE",
                    match_basis="SOURCE_CONTEXT",
                    context_role="operator",
                )
            ]
        links = [
            LinkedEntityCandidate(
                mention=f"{source.software_name}::{proposition.operator_name}@{source.software_version}",
                entity_type="OperatorRevision",
                candidate_id=operator["record_id"],
                resolution_status="EXACT_EXISTING_IDENTITY",
                match_basis="EXACT_ID",
                context_role="operator",
            )
        ]
        if proposition.proposition_type == PropositionType.PARAMETER_DESCRIPTION and proposition.parameter_name:
            links.append(
                LinkedEntityCandidate(
                    mention=proposition.parameter_name,
                    entity_type="ParameterDefinition",
                    candidate_id=(
                        f"parameter-definition-candidate:{source.software_name.casefold()}."
                        f"{proposition.operator_name.casefold()}.{proposition.parameter_name.casefold()}:"
                        f"{source.software_version}"
                    ),
                    resolution_status="NEW_CANDIDATE",
                    match_basis="SOURCE_CONTEXT",
                    context_role="parameter",
                )
            )
        if proposition.proposition_type == PropositionType.RETURN_VALUE:
            binding = self.identities.output_binding(operator["record_id"])
            if binding:
                output, representation = binding
                links.extend(
                    [
                        LinkedEntityCandidate(
                            mention=str(output["record"].get("role") or output["label"]),
                            entity_type="OutputPort",
                            candidate_id=output["record_id"],
                            resolution_status="EXACT_EXISTING_IDENTITY",
                            match_basis="EXACT_ID",
                            context_role="output",
                        ),
                        LinkedEntityCandidate(
                            mention=str(representation["record"].get("label") or representation["label"]),
                            entity_type="RepresentationType",
                            candidate_id=representation["record_id"],
                            resolution_status="EXACT_EXISTING_IDENTITY",
                            match_basis="EXACT_ID",
                            context_role="representation",
                        ),
                    ]
                )
        return links

    def _canonicalize(
        self,
        source: SourceDocument,
        proposition: RawProposition,
        entities: Sequence[LinkedEntityCandidate],
    ) -> CanonicalStatementCandidate | None:
        by_role = {entity.context_role: entity for entity in entities}
        operator = by_role.get("operator")
        if operator is None:
            return None
        qualifiers = {"software_version": f"=={source.software_version}"} if source.software_version else {}
        if proposition.proposition_type == PropositionType.PARAMETER_DESCRIPTION:
            parameter = by_role.get("parameter")
            if parameter is None:
                return None
            valid, reasons = self.ontology.validate_link(
                "has_parameter", "OperatorRevision", "ParameterDefinition", as_statement=True
            )
            return CanonicalStatementCandidate(
                canonical_candidate_id=_stable_id("canonical-statement-candidate:", operator.candidate_id, "has_parameter", parameter.candidate_id),
                canonical_kind="STATEMENT_REVISION",
                subject_id=operator.candidate_id,
                subject_type="OperatorRevision",
                predicate="has_parameter",
                object_id=parameter.candidate_id,
                object_type="ParameterDefinition",
                assertion_kind="definition",
                qualifiers=qualifiers,
                conditions=[],
                complete=valid,
                registry_conformant=valid,
                is_scientific_statement=True,
                conformance_reasons=reasons,
            )
        if proposition.proposition_type == PropositionType.RETURN_VALUE:
            output = by_role.get("output")
            representation = by_role.get("representation")
            if output is None or representation is None:
                return None
            valid, reasons = self.ontology.validate_link(
                "output_type", "OutputPort", "RepresentationType", as_statement=False
            )
            return CanonicalStatementCandidate(
                canonical_candidate_id=_stable_id("canonical-output-binding-candidate:", output.candidate_id, representation.candidate_id),
                canonical_kind="STRUCTURAL_OUTPUT_BINDING",
                subject_id=output.candidate_id,
                subject_type="OutputPort",
                predicate="output_type",
                object_id=representation.candidate_id,
                object_type="RepresentationType",
                qualifiers={},
                conditions=[],
                complete=valid,
                registry_conformant=valid,
                is_scientific_statement=False,
                conformance_reasons=reasons,
            )
        return None

    def _scope(
        self,
        source: SourceDocument,
        semantic: SemanticBlock,
        proposition: RawProposition,
        evidence: BoundedEvidenceSpanCandidate,
    ) -> ResolvedScope:
        values: list[ScopeValue] = []
        if source.software_version and semantic.operator_name:
            values.append(
                ScopeValue(
                    dimension="method_operator_version",
                    value=source.software_version,
                    status=ScopeValueStatus.SOURCE_CONTEXT,
                    provenance_kind="SOURCE_METADATA",
                    provenance_ref=source.source_revision_id,
                    rationale="Version inherited from the document's explicit Version field.",
                )
            )
            values.append(
                ScopeValue(
                    dimension="operator_context",
                    value=f"{source.software_name}::{semantic.operator_name}",
                    status=ScopeValueStatus.INHERITED,
                    provenance_kind="INHERITED_CONTEXT",
                    provenance_ref=semantic.semantic_block_id,
                    rationale="Operator inherited from the nearest operator heading.",
                )
            )
        else:
            values.append(
                ScopeValue(
                    dimension="method_operator_version",
                    status=ScopeValueStatus.UNKNOWN,
                    provenance_kind="NONE",
                    rationale="No explicit or inherited operator-version context is available.",
                )
            )
        if proposition.parameter_name:
            values.append(
                ScopeValue(
                    dimension="parameter_context",
                    value=proposition.parameter_name,
                    status=ScopeValueStatus.EXPLICIT,
                    provenance_kind="EVIDENCE_SPAN",
                    provenance_ref=evidence.evidence_span_id,
                    rationale="Parameter name occurs in the bounded evidence row.",
                )
            )
        for dimension in ("organism", "study_design"):
            values.append(
                ScopeValue(
                    dimension=dimension,
                    status=ScopeValueStatus.UNKNOWN,
                    provenance_kind="NONE",
                    rationale="No bounded evidence supplies this dimension; no model-common-sense fill is allowed.",
                )
            )
        known = [value for value in values if value.status not in {ScopeValueStatus.UNKNOWN, ScopeValueStatus.NOT_APPLICABLE}]
        unknown = [value for value in values if value.status == ScopeValueStatus.UNKNOWN]
        core_status = "partially_known" if known and unknown else ("explicit" if known else "unknown")
        return ResolvedScope(
            scope_id=_stable_id("resolved-scope:", proposition.proposition_id, *(f"{item.dimension}:{item.value}:{item.status}" for item in values)),
            core_scope_status=core_status,
            values=values,
            hallucinated_value_count=0,
        )

    def _packet_without_proposition(
        self,
        source: SourceDocument,
        semantic: SemanticBlock,
        layout: LayoutBlock,
        reconstructed: ReconstructedBlock,
    ) -> HumanReviewPacket:
        dropped_types = {
            BlockType.TOC,
            BlockType.HEADER_FOOTER,
            BlockType.EXAMPLES_CODE,
            BlockType.USAGE,
            BlockType.OPERATOR_HEADING,
            BlockType.DOCUMENT_METADATA,
            BlockType.REFERENCES,
        }
        disposition = FinalDisposition.DROPPED if semantic.block_type in dropped_types else FinalDisposition.ABSTAINED
        claim_stage = StageOutcome.DROPPED if disposition == FinalDisposition.DROPPED else StageOutcome.ABSTAINED
        stage_status = {stage: StageOutcome.NOT_APPLICABLE for stage in StageName}
        stage_status[StageName.TEXT_QUALITY] = StageOutcome.PASS
        stage_status[StageName.BLOCK_CLASSIFICATION] = StageOutcome.PASS
        stage_status[StageName.CLAIM_LIKENESS] = claim_stage
        reasons = {
            BlockType.TOC: "TOC_OR_INDEX_EXCLUDED",
            BlockType.HEADER_FOOTER: "HEADER_FOOTER_EXCLUDED",
            BlockType.EXAMPLES_CODE: "CODE_EXAMPLE_EXCLUDED_FROM_SCIENTIFIC_STATEMENTS",
            BlockType.USAGE: "USAGE_CODE_EXCLUDED_FROM_SCIENTIFIC_STATEMENTS",
            BlockType.OPERATOR_HEADING: "STRUCTURAL_OPERATOR_CONTEXT_ONLY",
            BlockType.DOCUMENT_METADATA: "DOCUMENT_METADATA_CONTEXT_ONLY",
            BlockType.REFERENCES: "REFERENCE_BLOCK_EXCLUDED",
        }
        warning = reasons.get(semantic.block_type, "NO_COMPLETE_PROPOSITION_DETECTED")
        validation = ValidationReport(
            stage_status=stage_status,
            warnings=[warning],
            ontology_registry_version=self.ontology.ontology_version,
            structurally_conformant=True,
            final_disposition=disposition,
        )
        return HumanReviewPacket(
            packet_id=_stable_id("human-review-packet:", semantic.semantic_block_id, disposition.value),
            source=source,
            raw_block=layout.raw_text,
            normalized_block=reconstructed.normalized_text,
            block_type=semantic.block_type,
            validation_report=validation,
            final_disposition=disposition,
        )

    def _packet_for_proposition(
        self,
        source: SourceDocument,
        semantic: SemanticBlock,
        layout: LayoutBlock,
        reconstructed: ReconstructedBlock,
        proposition: RawProposition,
    ) -> HumanReviewPacket:
        evidence = self._evidence(source, layout, proposition)
        entities = self._link_entities(source, proposition)
        canonical = self._canonicalize(source, proposition, entities) if proposition.is_complete else None
        scope = self._scope(source, semantic, proposition, evidence)
        errors: list[str] = []
        warnings: list[str] = []
        stage_status = {stage: StageOutcome.PASS for stage in StageName}

        if not proposition.is_complete:
            disposition = FinalDisposition.ABSTAINED
            stage_status[StageName.CLAIM_LIKENESS] = StageOutcome.ABSTAINED
            stage_status[StageName.ENTITY_LINKING] = StageOutcome.NOT_APPLICABLE
            stage_status[StageName.CANONICALIZATION] = StageOutcome.ABSTAINED
            stage_status[StageName.SEMANTIC_VALIDATION] = StageOutcome.ABSTAINED
            warnings.extend(proposition.abstention_reasons)
        elif not entities:
            disposition = FinalDisposition.EVIDENCE_ONLY
            stage_status[StageName.ENTITY_LINKING] = StageOutcome.ABSTAINED
            stage_status[StageName.CANONICALIZATION] = StageOutcome.ABSTAINED
            stage_status[StageName.SEMANTIC_VALIDATION] = StageOutcome.NOT_APPLICABLE
            warnings.append("NO_EXACT_OR_SOURCE_CONTEXT_ENTITY_LINK")
        elif canonical is None:
            disposition = FinalDisposition.EVIDENCE_ONLY
            stage_status[StageName.CANONICALIZATION] = StageOutcome.ABSTAINED
            stage_status[StageName.SEMANTIC_VALIDATION] = StageOutcome.NOT_APPLICABLE
            warnings.append("NO_ONTOLOGY_CONSTRAINED_CANONICAL_MAPPING")
        elif not canonical.registry_conformant:
            disposition = FinalDisposition.ABSTAINED
            stage_status[StageName.CANONICALIZATION] = StageOutcome.FAIL
            stage_status[StageName.SEMANTIC_VALIDATION] = StageOutcome.FAIL
            errors.extend(canonical.conformance_reasons)
        elif evidence.whole_segment:
            disposition = FinalDisposition.NEEDS_REVIEW
            stage_status[StageName.EVIDENCE_BINDING] = StageOutcome.NEEDS_REVIEW
            stage_status[StageName.SEMANTIC_VALIDATION] = StageOutcome.NEEDS_REVIEW
            warnings.append("WHOLE_SEGMENT_EVIDENCE_NOT_CANDIDATE_READY")
        elif any(entity.resolution_status != "EXACT_EXISTING_IDENTITY" for entity in entities):
            disposition = FinalDisposition.NEEDS_REVIEW
            stage_status[StageName.ENTITY_LINKING] = StageOutcome.NEEDS_REVIEW
            stage_status[StageName.SEMANTIC_VALIDATION] = StageOutcome.NEEDS_REVIEW
            warnings.append("NEW_ENTITY_IDENTITY_REQUIRES_HUMAN_REVIEW")
        else:
            disposition = FinalDisposition.CANDIDATE_READY

        validation = ValidationReport(
            stage_status=stage_status,
            errors=errors,
            warnings=warnings,
            ontology_registry_version=self.ontology.ontology_version,
            structurally_conformant=not errors,
            final_disposition=disposition,
        )
        return HumanReviewPacket(
            packet_id=_stable_id("human-review-packet:", proposition.proposition_id, disposition.value),
            source=source,
            raw_block=layout.raw_text,
            normalized_block=reconstructed.normalized_text,
            block_type=semantic.block_type,
            raw_proposition=proposition,
            linked_entities=list(entities),
            canonical_statement=canonical,
            scope=scope,
            evidence_span=evidence,
            validation_report=validation,
            final_disposition=disposition,
        )


def packets_as_dicts(packets: Iterable[HumanReviewPacket]) -> list[dict[str, object]]:
    return [packet.model_dump(mode="json") for packet in packets]
