from __future__ import annotations

import csv
import hashlib
import json
import re
from collections import Counter
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Sequence

from core.canonical_task_ontology import (
    canonical_task_for_text,
    canonical_task_ids_for_tool,
)
from core.knowledge_intelligence_models import (
    RetrievalCoverageReport,
    SourceDocumentRecord,
)
from core.settings import PROJECT_ROOT
from engine.evidence_discovery_index import (
    EvidenceChunk,
    build_formal_tsv_chunks,
    catalog_tool_chunks,
    chunk_to_dict,
    content_hash,
)


CORE_TOOLS = (
    "Scrublet",
    "scDblFinder",
    "Harmony",
    "Scanorama",
    "Seurat",
    "Scanpy",
    "scvi-tools",
    "CellTypist",
    "SingleR",
    "cell2location",
    "scVelo",
    "CellRank",
    "MOFA2",
    "moscot",
    "tradeSeq",
    "DoubletFinder",
)
QUALIFIED_TOOLS = ("Scrublet", "scDblFinder", "Harmony", "Scanorama")
DEFAULT_SOURCE_DOCUMENTS_PATH = PROJECT_ROOT / "data" / "indexes" / "source_documents_v2.jsonl"
DEFAULT_CHUNKS_PATH = PROJECT_ROOT / "data" / "indexes" / "evidence_chunks.jsonl"
DEFAULT_CATALOG_CHUNKS_PATH = PROJECT_ROOT / "data" / "indexes" / "scrna_tools_catalog_chunks.jsonl"
DEFAULT_MANIFEST_PATH = PROJECT_ROOT / "data" / "indexes" / "evidence_index_manifest.json"
DEFAULT_COVERAGE_PATH = PROJECT_ROOT / "data" / "indexes" / "retrieval_coverage_v2.json"
DEFAULT_SOURCE_QUARANTINE = (
    PROJECT_ROOT / "data" / "evidence_candidates" / "source_quarantine_v2.json"
)
DEFAULT_SOURCE_MANIFESTS = (
    PROJECT_ROOT / "data" / "evidence_candidates" / "source_registry.tsv",
    PROJECT_ROOT / "data" / "evidence_candidates" / "core_tool_source_manifest_v2.tsv",
    PROJECT_ROOT / "data" / "evidence_candidates" / "evidence_source_manifest_v1.tsv",
)

COMMON_HEADINGS = {
    "abstract",
    "summary",
    "introduction",
    "background",
    "results",
    "methods",
    "materials and methods",
    "discussion",
    "conclusion",
    "conclusions",
    "availability",
    "installation",
    "usage",
    "quick start",
    "best practices",
    "parameters",
    "arguments",
    "input",
    "inputs",
    "output",
    "outputs",
    "limitations",
    "references",
}


class SourceCorpusBuilder:
    def __init__(
        self,
        *,
        project_root: Path = PROJECT_ROOT,
        source_manifests: Optional[Sequence[Path]] = None,
        target_tokens: int = 500,
        max_tokens: int = 700,
        overlap_tokens: int = 80,
        source_quarantine_path: Optional[Path] = None,
    ) -> None:
        self.project_root = Path(project_root)
        self.source_manifests = tuple(
            Path(path)
            for path in (
                source_manifests
                or (
                    self.project_root / "data" / "evidence_candidates" / "source_registry.tsv",
                    self.project_root / "data" / "evidence_candidates" / "core_tool_source_manifest_v2.tsv",
                    self.project_root / "data" / "evidence_candidates" / "evidence_source_manifest_v1.tsv",
                )
            )
        )
        self.target_tokens = target_tokens
        self.max_tokens = max_tokens
        self.overlap_tokens = overlap_tokens
        self.source_quarantine_path = Path(
            source_quarantine_path
            or self.project_root
            / "data"
            / "evidence_candidates"
            / "source_quarantine_v2.json"
        )
        self._quarantined_dois, self._quarantined_record_ids = (
            self._load_source_quarantine()
        )
        if not 100 <= self.target_tokens <= self.max_tokens:
            raise ValueError("target_tokens must be between 100 and max_tokens")
        if not 0 <= self.overlap_tokens < self.target_tokens:
            raise ValueError("overlap_tokens must be smaller than target_tokens")

    def build(self, *, write: bool = True) -> Dict[str, Any]:
        source_documents = self.build_source_documents()
        source_chunks = self.build_source_chunks(source_documents)
        formal_chunks = [
            self._upgrade_formal_chunk(chunk)
            for chunk in build_formal_tsv_chunks(
                publications_path=self.project_root / "data" / "tool_publications.tsv",
                benchmarks_path=self.project_root / "data" / "tool_benchmarks.tsv",
            )
            if not self._is_quarantined_formal_chunk(chunk)
        ]
        chunks = self._dedupe_chunks([*formal_chunks, *source_chunks])
        catalog_path = self.project_root / "data" / "catalog" / "scrna_tools_snapshot.json"
        catalog_chunks = [self._upgrade_catalog_chunk(chunk) for chunk in catalog_tool_chunks(catalog_path)]
        build_id = self._build_id(source_documents, chunks, catalog_chunks)
        dense_metadata = self._matching_dense_metadata(build_id, chunks)
        coverage = self._coverage(
            build_id,
            source_documents,
            chunks,
            catalog_chunks,
            dense_metadata=dense_metadata,
        )
        manifest = {
            "schema_version": "evidence-index-manifest-v2",
            "build_id": build_id,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source_document_count": len(source_documents),
            "evidence_chunk_count": len(chunks),
            "catalog_chunk_count": len(catalog_chunks),
            "source_digest": self._records_digest(source_documents),
            "chunk_digest": self._chunks_digest(chunks),
            "catalog_digest": self._chunks_digest(catalog_chunks),
            "chunk_policy": {
                "target_tokens": self.target_tokens,
                "max_tokens": self.max_tokens,
                "overlap_tokens": self.overlap_tokens,
                "section_aware": True,
                "page_aware_when_markers_available": True,
            },
            "embedding": {
                "provider": "local_optional_model_pack",
                "model": "BAAI/bge-m3",
                "model_revision": dense_metadata.get("model_revision", ""),
                "snapshot_digest": dense_metadata.get("snapshot_digest", ""),
                "vector_count": len(dense_metadata.get("chunk_ids") or []),
                "dense_source_digest": dense_metadata.get("source_digest", ""),
                "fallback": "kg_plus_sqlite_fts5_bm25",
            },
            "evidence_boundary": "retrieval_only_no_automatic_promotion",
        }
        if write:
            self._write_outputs(source_documents, chunks, catalog_chunks, manifest, coverage)
        return {
            "source_documents": source_documents,
            "chunks": chunks,
            "catalog_chunks": catalog_chunks,
            "manifest": manifest,
            "coverage": coverage,
        }

    def build_source_documents(self) -> List[SourceDocumentRecord]:
        candidates = [
            candidate
            for manifest in self.source_manifests
            for candidate in self._manifest_candidates(manifest)
        ]
        grouped: Dict[str, List[Dict[str, Any]]] = {}
        for candidate in candidates:
            grouped.setdefault(self._dedupe_key(candidate), []).append(candidate)
        records: List[SourceDocumentRecord] = []
        for key, group in sorted(grouped.items()):
            records.append(self._merge_source_group(key, group))
        return records

    def build_source_chunks(
        self, source_documents: Sequence[SourceDocumentRecord]
    ) -> List[EvidenceChunk]:
        chunks: List[EvidenceChunk] = []
        for document in source_documents:
            if document.source_status != "source_text_available" or not document.local_text_path:
                continue
            path = self._resolve_path(document.local_text_path)
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            sections = list(_iter_sections(text))
            task_tags = sorted(
                {
                    task_id
                    for tool_name in document.referring_tool_names
                    for task_id in canonical_task_ids_for_tool(tool_name)
                }
            )
            primary_task = task_tags[0] if task_tags else ""
            for index, unit in enumerate(
                _chunk_sections(
                    sections,
                    target_tokens=self.target_tokens,
                    max_tokens=self.max_tokens,
                    overlap_tokens=self.overlap_tokens,
                ),
                start=1,
            ):
                chunk_text = unit["text"]
                if len(chunk_text) < 80:
                    continue
                section = unit["section"]
                inferred_task = canonical_task_for_text(f"{section} {chunk_text[:800]}")
                canonical_task = inferred_task.task_id if inferred_task else primary_task
                combined_tags = sorted(set(task_tags + ([canonical_task] if canonical_task else [])))
                source_span = _source_span(unit["page"], section, unit["paragraph_start"], unit["paragraph_end"])
                chunk_id = "sourcev2:" + hashlib.sha256(
                    f"{document.source_id}|{source_span}|{chunk_text}".encode("utf-8")
                ).hexdigest()[:20]
                chunks.append(
                    EvidenceChunk(
                        chunk_id=chunk_id,
                        evidence_id=(document.referring_record_ids[0] if document.referring_record_ids else document.source_id),
                        source_kind="source_document",
                        source_table="data/indexes/source_documents_v2.jsonl",
                        source_record_id=document.source_id,
                        source_id=document.source_id,
                        source_document_id=document.source_id,
                        source_type=document.source_type,
                        source_span=source_span,
                        tool_name=(document.referring_tool_names[0] if document.referring_tool_names else ""),
                        tool_names=document.referring_tool_names,
                        task=canonical_task,
                        canonical_task=canonical_task,
                        task_tags=combined_tags,
                        review_status="source_validated_retrieval_only",
                        trust_level="source_bound",
                        graph_layer="retrieval_only",
                        recommendation_eligible="false",
                        authority_tier="source_material",
                        evidence_category=";".join(document.evidence_kinds),
                        doi=document.doi,
                        source_url=document.source_url,
                        title=document.canonical_title,
                        chunk_text=chunk_text,
                        claim_type=_claim_type(section, chunk_text),
                        page=unit["page"],
                        section=section,
                        paragraph_index=unit["paragraph_start"],
                        token_count=_token_count(chunk_text),
                        content_hash=content_hash(chunk_text),
                        source_bound=True,
                        retrieval_status="retrieval_only",
                        claim_boundary=(
                            "Source-bound discovery chunk only; it cannot authorize execution, "
                            "change ranking, or promote formal evidence."
                        ),
                        embedding_version="BAAI/bge-m3-local-optional",
                    )
                )
        return chunks

    def _manifest_candidates(self, path: Path) -> Iterator[Dict[str, Any]]:
        if not path.is_file():
            return
        for row in _read_tsv(path):
            is_registry = "canonical_title" in row
            validation_status = _clean(row.get("validation_status"))
            source_status = _clean(row.get("source_status"))
            issue = _clean(row.get("validation_issue") or row.get("candidate_issue"))
            quarantined = (
                "mismatch" in validation_status.casefold()
                or "mismatch" in source_status.casefold()
                or bool(issue and "mismatch" in issue.casefold())
            )
            local_text_path = _clean(row.get("local_text_path"))
            text_path = self._resolve_path(local_text_path) if local_text_path else None
            text = (
                text_path.read_text(encoding="utf-8", errors="ignore")
                if text_path is not None and text_path.is_file()
                else ""
            )
            tools = _split_values(
                row.get("referring_tool_names") if is_registry else row.get("tool_name")
            )
            record_ids = _split_values(
                row.get("referring_record_ids") if is_registry else row.get("record_id")
            )
            kinds = _split_values(
                row.get("evidence_kinds") if is_registry else row.get("evidence_kind")
            )
            title = _clean(row.get("canonical_title") or row.get("source_title"))
            if not title:
                title = Path(local_text_path).stem if local_text_path else _clean(row.get("source_id"))
            normalized_doi = _normalize_doi(row.get("doi") or row.get("doi_or_pmid"))
            explicitly_quarantined = (
                normalized_doi in self._quarantined_dois
                or bool(set(record_ids) & self._quarantined_record_ids)
            )
            yield {
                "source_id": _clean(row.get("source_id")),
                "canonical_title": title or "Untitled source",
                "doi": normalized_doi,
                "source_url": _clean(row.get("source_url")),
                "source_type": _clean(
                    row.get("source_type")
                    or row.get("preferred_source_type")
                    or (kinds[0] if kinds else "document")
                ),
                "source_status": "quarantined"
                if quarantined or explicitly_quarantined
                else ("source_text_available" if text else "metadata_only"),
                "validation_status": validation_status,
                "validation_issue": issue,
                "local_text_path": local_text_path,
                "local_pdf_path": _clean(row.get("local_pdf_path") or row.get("pdf_path")),
                "content_hash": content_hash(text) if text else "",
                "text_chars": len(text),
                "tools": tools,
                "record_ids": record_ids,
                "kinds": kinds,
            }

    def _load_source_quarantine(self) -> tuple[set[str], set[str]]:
        if not self.source_quarantine_path.is_file():
            return set(), set()
        payload = json.loads(self.source_quarantine_path.read_text(encoding="utf-8"))
        records = payload.get("records") if isinstance(payload, dict) else []
        dois = {
            _normalize_doi(row.get("doi"))
            for row in records or []
            if isinstance(row, dict) and _normalize_doi(row.get("doi"))
        }
        record_ids = {
            str(record_id)
            for row in records or []
            if isinstance(row, dict)
            for record_id in row.get("record_ids") or []
            if str(record_id).strip()
        }
        return dois, record_ids

    def _is_quarantined_formal_chunk(self, chunk: EvidenceChunk) -> bool:
        return (
            _normalize_doi(chunk.doi) in self._quarantined_dois
            or chunk.source_record_id in self._quarantined_record_ids
            or chunk.evidence_id in self._quarantined_record_ids
        )

    def _dedupe_key(self, candidate: Dict[str, Any]) -> str:
        if candidate["doi"]:
            return f"doi:{candidate['doi']}"
        if candidate["content_hash"]:
            return f"content:{candidate['content_hash']}"
        normalized_title = re.sub(r"[^a-z0-9]+", "", candidate["canonical_title"].casefold())
        return f"title:{normalized_title}|{candidate['source_url'].casefold()}"

    def _merge_source_group(
        self, key: str, group: Sequence[Dict[str, Any]]
    ) -> SourceDocumentRecord:
        selected = max(group, key=lambda item: (item["text_chars"], bool(item["source_url"])))
        quarantined = any(item["source_status"] == "quarantined" for item in group)
        has_text = any(item["source_status"] == "source_text_available" for item in group)
        status = "quarantined" if quarantined else ("source_text_available" if has_text else "metadata_only")
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
        return SourceDocumentRecord(
            source_id=f"SRCV2_{digest}",
            canonical_title=selected["canonical_title"],
            doi=selected["doi"],
            source_url=selected["source_url"],
            source_type=selected["source_type"],
            source_status=status,
            validation_status=selected["validation_status"],
            validation_issue="; ".join(sorted({item["validation_issue"] for item in group if item["validation_issue"]})),
            local_text_path=selected["local_text_path"] if has_text else "",
            local_pdf_path=selected["local_pdf_path"],
            content_hash=selected["content_hash"] if has_text else "",
            text_chars=selected["text_chars"] if has_text else 0,
            referring_record_ids=sorted({value for item in group for value in item["record_ids"]}),
            referring_tool_names=sorted({value for item in group for value in item["tools"]}),
            evidence_kinds=sorted({value for item in group for value in item["kinds"]}),
            source_spans_available=has_text,
            retrieval_only=True,
        )

    def _upgrade_formal_chunk(self, chunk: EvidenceChunk) -> EvidenceChunk:
        task = canonical_task_for_text(chunk.task)
        return replace(
            chunk,
            canonical_task=task.task_id if task else "",
            task_tags=[task.task_id] if task else [],
            tool_names=[chunk.tool_name] if chunk.tool_name else [],
            claim_type=_claim_type(chunk.claim_span, chunk.chunk_text),
            token_count=_token_count(chunk.chunk_text),
            content_hash=content_hash(chunk.chunk_text),
            source_bound=bool(chunk.claim_span and chunk.doi),
            retrieval_status="formal_frozen_retrieval_only",
        )

    def _upgrade_catalog_chunk(self, chunk: EvidenceChunk) -> EvidenceChunk:
        task_tags = list(canonical_task_ids_for_tool(chunk.tool_name))
        return replace(
            chunk,
            canonical_task=task_tags[0] if task_tags else "",
            task_tags=task_tags,
            tool_names=[chunk.tool_name] if chunk.tool_name else [],
            claim_type="catalog_metadata",
            token_count=_token_count(chunk.chunk_text),
            content_hash=content_hash(chunk.chunk_text),
            source_bound=True,
            retrieval_status="catalog_only",
        )

    @staticmethod
    def _dedupe_chunks(chunks: Sequence[EvidenceChunk]) -> List[EvidenceChunk]:
        by_id: Dict[str, EvidenceChunk] = {}
        for chunk in chunks:
            by_id.setdefault(chunk.chunk_id, chunk)
        return [by_id[key] for key in sorted(by_id)]

    def _coverage(
        self,
        build_id: str,
        documents: Sequence[SourceDocumentRecord],
        chunks: Sequence[EvidenceChunk],
        catalog_chunks: Sequence[EvidenceChunk],
        *,
        dense_metadata: Dict[str, Any],
    ) -> RetrievalCoverageReport:
        source_tools = {
            tool.casefold()
            for document in documents
            if document.source_status == "source_text_available"
            for tool in document.referring_tool_names
        }
        missing_qualified = [tool for tool in QUALIFIED_TOOLS if tool.casefold() not in source_tools]
        missing_core = [tool for tool in CORE_TOOLS if tool.casefold() not in source_tools]
        return RetrievalCoverageReport(
            build_id=build_id,
            chunk_count=len(chunks),
            catalog_chunk_count=len(catalog_chunks),
            source_document_count=sum(document.source_status == "source_text_available" for document in documents),
            source_bound_tool_count=len(source_tools),
            qualified_tool_count=len(QUALIFIED_TOOLS),
            qualified_tool_source_coverage_rate=(len(QUALIFIED_TOOLS) - len(missing_qualified)) / len(QUALIFIED_TOOLS),
            core_tool_source_coverage_rate=(len(CORE_TOOLS) - len(missing_core)) / len(CORE_TOOLS),
            chunks_by_claim_type=dict(Counter(chunk.claim_type for chunk in chunks)),
            chunks_by_task=dict(Counter(chunk.canonical_task or "unmapped" for chunk in chunks)),
            missing_qualified_tools=missing_qualified,
            missing_core_tools=missing_core,
            embedding_model=(
                "BAAI/bge-m3"
                if dense_metadata
                else "BAAI/bge-m3-local-optional"
            ),
            dense_vector_count=len(dense_metadata.get("chunk_ids") or []),
            quality_flags=[
                flag
                for flag, condition in (
                    ("qualified_tool_source_gap", bool(missing_qualified)),
                    ("core_tool_source_gap", bool(missing_core)),
                    ("dense_model_pack_not_built", not dense_metadata),
                )
                if condition
            ],
        )

    def _matching_dense_metadata(
        self,
        build_id: str,
        chunks: Sequence[EvidenceChunk],
    ) -> Dict[str, Any]:
        path = self.project_root / "data" / "indexes" / "evidence_vector_metadata.json"
        try:
            metadata = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        expected_ids = [
            chunk.chunk_id
            for chunk in sorted(chunks, key=lambda item: item.chunk_id)
            if chunk.source_bound and chunk.retrieval_status != "catalog_only"
        ]
        if (
            metadata.get("build_id") != build_id
            or metadata.get("model") != "BAAI/bge-m3"
            or metadata.get("chunk_ids") != expected_ids
            or metadata.get("shape") != [len(expected_ids), 1024]
        ):
            return {}
        return metadata

    def _write_outputs(
        self,
        documents: Sequence[SourceDocumentRecord],
        chunks: Sequence[EvidenceChunk],
        catalog_chunks: Sequence[EvidenceChunk],
        manifest: Dict[str, Any],
        coverage: RetrievalCoverageReport,
    ) -> None:
        index_dir = self.project_root / "data" / "indexes"
        _write_jsonl_atomic(
            index_dir / "source_documents_v2.jsonl",
            (record.model_dump(mode="json") for record in documents),
        )
        _write_jsonl_atomic(
            index_dir / "evidence_chunks.jsonl",
            (chunk_to_dict(chunk) for chunk in chunks),
        )
        _write_jsonl_atomic(
            index_dir / "scrna_tools_catalog_chunks.jsonl",
            (chunk_to_dict(chunk) for chunk in catalog_chunks),
        )
        _write_json_atomic(index_dir / "evidence_index_manifest.json", manifest)
        _write_json_atomic(
            index_dir / "retrieval_coverage_v2.json",
            coverage.model_dump(mode="json"),
        )

    def _resolve_path(self, value: str) -> Path:
        path = Path(value)
        return path if path.is_absolute() else self.project_root / path

    @staticmethod
    def _records_digest(records: Sequence[SourceDocumentRecord]) -> str:
        payload = "\n".join(record.model_dump_json() for record in records)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @staticmethod
    def _chunks_digest(chunks: Sequence[EvidenceChunk]) -> str:
        payload = "\n".join(
            f"{chunk.chunk_id}:{chunk.content_hash or content_hash(chunk.chunk_text)}"
            for chunk in chunks
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _build_id(
        self,
        documents: Sequence[SourceDocumentRecord],
        chunks: Sequence[EvidenceChunk],
        catalog_chunks: Sequence[EvidenceChunk],
    ) -> str:
        digest = hashlib.sha256(
            (
                self._records_digest(documents)
                + self._chunks_digest(chunks)
                + self._chunks_digest(catalog_chunks)
            ).encode("utf-8")
        ).hexdigest()[:16]
        return f"evidence-v2-{digest}"


def _iter_sections(text: str) -> Iterator[Dict[str, Any]]:
    current_page: Optional[int] = None
    current_section = "document"
    paragraph_index = 0
    buffer: List[str] = []

    def flush() -> Optional[Dict[str, Any]]:
        nonlocal paragraph_index, buffer
        paragraph = " ".join(" ".join(buffer).split())
        buffer = []
        if len(paragraph) < 40:
            return None
        paragraph_index += 1
        return {
            "page": current_page,
            "section": current_section,
            "paragraph": paragraph,
            "paragraph_index": paragraph_index,
        }

    for raw_line in str(text or "").splitlines():
        line = " ".join(raw_line.split())
        page_match = re.fullmatch(r"\[PDF_PAGE\s+(\d+)\]", line)
        if page_match:
            item = flush()
            if item:
                yield item
            current_page = int(page_match.group(1))
            continue
        if not line:
            item = flush()
            if item:
                yield item
            continue
        heading = _heading(line)
        if heading:
            item = flush()
            if item:
                yield item
            current_section = heading
            continue
        buffer.append(line)
    item = flush()
    if item:
        yield item


def _chunk_sections(
    paragraphs: Sequence[Dict[str, Any]],
    *,
    target_tokens: int,
    max_tokens: int,
    overlap_tokens: int,
) -> Iterator[Dict[str, Any]]:
    index = 0
    while index < len(paragraphs):
        first = paragraphs[index]
        page = first["page"]
        section = first["section"]
        selected: List[Dict[str, Any]] = []
        total = 0
        cursor = index
        while cursor < len(paragraphs):
            item = paragraphs[cursor]
            count = _token_count(item["paragraph"])
            if selected and (item["section"] != section or item["page"] != page) and total >= target_tokens // 2:
                break
            if selected and total + count > max_tokens:
                break
            if not selected and count > max_tokens:
                sentences = _sentences(item["paragraph"])
                partial: List[str] = []
                partial_count = 0
                for sentence in sentences:
                    sentence_count = _token_count(sentence)
                    if partial and partial_count + sentence_count > max_tokens:
                        break
                    partial.append(sentence)
                    partial_count += sentence_count
                selected.append({**item, "paragraph": " ".join(partial)})
                total = partial_count
                cursor += 1
                break
            selected.append(item)
            total += count
            cursor += 1
            if total >= target_tokens:
                break
        if not selected:
            index += 1
            continue
        yield {
            "page": page,
            "section": section,
            "paragraph_start": selected[0]["paragraph_index"],
            "paragraph_end": selected[-1]["paragraph_index"],
            "text": "\n\n".join(item["paragraph"] for item in selected),
        }
        if cursor >= len(paragraphs):
            break
        overlap = 0
        rewind = cursor
        while rewind > index + 1 and overlap < overlap_tokens:
            rewind -= 1
            overlap += _token_count(paragraphs[rewind]["paragraph"])
        index = max(index + 1, rewind)


def _heading(line: str) -> str:
    stripped = line.strip().strip("#*: ")
    lowered = stripped.casefold()
    if not stripped or len(stripped) > 120:
        return ""
    if line.lstrip().startswith("#"):
        return stripped
    if lowered.rstrip(":") in COMMON_HEADINGS:
        return stripped.rstrip(":")
    if re.match(r"^(?:\d+(?:\.\d+)*|[ivx]+)[.)]?\s+[A-Z]", stripped):
        reference_like = (
            " et al" in lowered
            or "http" in lowered
            or len(stripped.split()) > 12
            or stripped.count(".") > 2
        )
        return "" if reference_like else stripped
    if stripped.isupper() and 2 <= len(stripped.split()) <= 10:
        return stripped.title()
    return ""


def _claim_type(section: str, text: str) -> str:
    haystack = f"{section} {text[:1000]}".casefold()
    rules = (
        ("failure_mode", ("failure", "limitation", "caveat", "error", "may perform poorly")),
        ("parameter", ("parameter", "argument", "threshold", "default", "n_neighbors", "theta=")),
        ("input_requirement", ("input", "raw count", "counts matrix", "requires", "anndata")),
        ("output", ("output", "returns", "predicted", "embedding", "score")),
        ("metric", ("benchmark", "auprc", "auroc", "f1", "silhouette", "accuracy")),
        ("workflow", ("workflow", "quick start", "installation", "usage", "pipeline")),
    )
    for claim_type, markers in rules:
        if any(marker in haystack for marker in markers):
            return claim_type
    return "general"


def _source_span(
    page: Optional[int], section: str, paragraph_start: int, paragraph_end: int
) -> str:
    parts = []
    if page is not None:
        parts.append(f"page:{page}")
    if section:
        parts.append(f"section:{section}")
    suffix = str(paragraph_start)
    if paragraph_end != paragraph_start:
        suffix += f"-{paragraph_end}"
    parts.append(f"paragraph:{suffix}")
    return ";".join(parts)


def _sentences(text: str) -> List[str]:
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+", text) if part.strip()]


def _token_count(text: str) -> int:
    words = re.findall(r"[A-Za-z0-9][A-Za-z0-9_.+-]*|[\u4e00-\u9fff]", text or "")
    return len(words)


def _normalize_doi(value: Any) -> str:
    text = _clean(value).casefold()
    text = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", text)
    return text.strip().rstrip(".")


def _split_values(value: Any) -> List[str]:
    if isinstance(value, list):
        values = value
    else:
        values = re.split(r"[;|]", _clean(value))
    return sorted({str(item).strip() for item in values if str(item).strip()})


def _read_tsv(path: Path) -> List[Dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _write_jsonl_atomic(path: Path, rows: Iterable[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    temporary.replace(path)


def _write_json_atomic(path: Path, value: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
