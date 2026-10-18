"""Bounded source parsers. Locations cite immutable parsed text, never invented OCR."""
from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree as ET

PARSER_VERSION = "workbench-ir-1"
MAX_XML_BYTES = 25 * 1024 * 1024
MAX_DOCX_UNCOMPRESSED = 100 * 1024 * 1024
SUPPORTED_EXTENSIONS = {".txt", ".md", ".markdown", ".pdf", ".docx", ".html", ".htm", ".xml"}


def _xml(data: bytes) -> ET.Element:
    if len(data) > MAX_XML_BYTES:
        raise ValueError("XML exceeds the parsing size limit")
    # ElementTree does not fetch external entities. Reject internal expansion too.
    decoded = data.decode("utf-8-sig")
    if "\0" in decoded or re.search(r"<!\s*(?:DOCTYPE|ENTITY)\b", decoded, flags=re.I):
        raise ValueError("XML DTD/entity declarations are not accepted")
    return ET.fromstring(data)


def _tag(node: ET.Element) -> str:
    return node.tag.rsplit("}", 1)[-1]


def _docx_text(node: ET.Element) -> str:
    parts = []
    for child in node.iter():
        name = _tag(child)
        if name == "t":
            parts.append(child.text or "")
        elif name == "tab":
            parts.append("\t")
        elif name in {"br", "cr"}:
            parts.append("\n")
    return "".join(parts)


def _docx(data: bytes) -> list[tuple[str, dict]]:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        infos = archive.infolist()
        if len(infos) > 10000 or sum(i.file_size for i in infos) > MAX_DOCX_UNCOMPRESSED:
            raise ValueError("DOCX archive exceeds expansion limits")
        if len({i.filename for i in infos}) != len(infos):
            raise ValueError("DOCX contains duplicate archive members")
        for info in infos:
            if info.flag_bits & 1:
                raise ValueError("Encrypted DOCX members are not supported")
            if info.file_size > MAX_XML_BYTES or info.file_size > max(info.compress_size, 1) * 1000:
                raise ValueError("DOCX member exceeds expansion limits")
        root = _xml(archive.read("word/document.xml"))
    body = next((n for n in root.iter() if _tag(n) == "body"), None)
    if body is None:
        raise ValueError("DOCX document body is missing")
    result = []
    paragraph = table = 0
    for node in body:
        if _tag(node) == "p":
            paragraph += 1
            result.append((_docx_text(node), {"kind": "docx_paragraph", "part": "word/document.xml", "paragraph": paragraph}))
        elif _tag(node) == "tbl":
            table += 1
            rows, cells, cursor = [], [], 0
            for r, row in enumerate((n for n in node if _tag(n) == "tr"), 1):
                values = []
                for c, cell in enumerate((n for n in row if _tag(n) == "tc"), 1):
                    value = "\n".join(_docx_text(p) for p in cell if _tag(p) == "p")
                    if values:
                        cursor += 1
                    cells.append({"row": r, "column": c, "start": cursor, "end": cursor + len(value)})
                    cursor += len(value)
                    values.append(value)
                rows.append("\t".join(values))
                cursor += 1
            result.append(("\n".join(rows), {"kind": "docx_table", "part": "word/document.xml", "table": table, "cells": cells}))
    return result


class _HTMLBlocks(HTMLParser):
    """Capture visible text; keep each table together to retain row context."""
    boundaries = {"p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "pre", "blockquote", "div", "section", "article"}
    ignored = {"script", "style", "noscript", "template"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocks = []
        self.parts = []
        self.ignore_depth = 0
        self.table_depth = 0
        self.kind = "html_text"
        self.ordinal = 0

    def flush(self):
        text = "".join(self.parts).strip()
        self.parts = []
        if text:
            self.ordinal += 1
            self.blocks.append((text, {"kind": self.kind, "element_ordinal": self.ordinal}))

    def handle_starttag(self, tag, attrs):
        if tag in self.ignored:
            self.ignore_depth += 1
        if self.ignore_depth:
            return
        if tag == "table":
            if not self.table_depth:
                self.flush()
                self.kind = "html_table"
            self.table_depth += 1
        elif tag == "br":
            self.parts.append("\n")
        elif tag in self.boundaries and not self.table_depth:
            self.flush()
            self.kind = "html_" + tag

    def handle_endtag(self, tag):
        if tag in self.ignored:
            self.ignore_depth = max(0, self.ignore_depth - 1)
            return
        if self.ignore_depth:
            return
        if tag == "table" and self.table_depth:
            self.table_depth -= 1
            if not self.table_depth:
                self.flush()
                self.kind = "html_text"
        elif self.table_depth and tag in {"td", "th"}:
            self.parts.append("\t")
        elif self.table_depth and tag == "tr":
            self.parts.append("\n")
        elif tag in self.boundaries and not self.table_depth:
            self.flush()

    def handle_data(self, data):
        if not self.ignore_depth:
            self.parts.append(data)


def _xml_blocks(data: bytes) -> list[tuple[str, dict]]:
    root = _xml(data)
    result = []

    def visit(node, path):
        name = _tag(node)
        # Do not recursively duplicate paragraphs or table contents.
        if name in {"table", "table-wrap"}:
            rows = ["\t".join("".join(cell.itertext()).strip() for cell in row if _tag(cell) in {"td", "th", "entry"}) for row in node.iter() if _tag(row) in {"tr", "row"}]
            caption = "\n".join("".join(child.itertext()).strip() for child in node if _tag(child) in {"label", "caption"})
            value = "\n".join(part for part in [caption, *rows] if part)
            if not value:
                value = "".join(node.itertext()).strip()
            if value:
                result.append((value, {"kind": "xml_" + name, "path": path}))
            return
        if name in {"p", "title", "article-title", "abstract", "caption"} or not len(node):
            value = "".join(node.itertext()).strip()
            if value:
                result.append((value, {"kind": "xml_" + name, "path": path}))
            return
        counts = {}
        for child in node:
            tag = _tag(child)
            counts[tag] = counts.get(tag, 0) + 1
            visit(child, f"{path}/{tag}[{counts[tag]}]")

    visit(root, "/" + _tag(root) + "[1]")
    return result


def parse_document(data: bytes, filename: str, *, source_id: str, source_revision_id: str,
                   max_pages: int = 200, max_chars: int = 1_000_000, max_blocks: int = 20000) -> dict:
    """Return immutable IR with exact block-relative and document-relative offsets.

    exact_text refers to the parser output, not byte offsets into PDF/HTML/DOCX.
    The source revision remains necessary to resolve a citation back to original bytes.
    """
    if any(not isinstance(value, int) or isinstance(value, bool) or value < 1 for value in (max_pages, max_chars, max_blocks)):
        raise ValueError("Parsing limits must be positive integers")
    limits = {"max_pages": max_pages, "max_chars": max_chars, "max_blocks": max_blocks}
    key = json.dumps([source_revision_id, PARSER_VERSION, limits], sort_keys=True)
    ir_id = "ir_" + hashlib.sha256(key.encode()).hexdigest()[:24]
    extension = Path(filename).suffix.lower()
    rows, gaps, total_pages, processed_pages = [], [], None, None
    format_notes = []
    try:
        if extension == ".pdf":
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(data))
            if reader.is_encrypted:
                raise ValueError("Encrypted PDF requires an unlocked source")
            total_pages = len(reader.pages)
            processed_pages = min(total_pages, max_pages)
            char_count = 0
            for i in range(processed_pages):
                try:
                    text = reader.pages[i].extract_text() or ""
                except Exception as exc:
                    gaps.append({"code": "pdf_page_error", "page": i + 1, "detail": str(exc)[:300]})
                    continue
                if not text.strip():
                    gaps.append({"code": "no_text_layer", "page": i + 1, "detail": "No usable text layer; OCR is not configured"})
                else:
                    rows.append((text, {"kind": "pdf_page", "page": i + 1}))
                    char_count += len(text)
                if char_count >= max_chars:
                    processed_pages = i + 1
                    if processed_pages < total_pages:
                        gaps.append({"code": "character_limit", "detail": "Remaining PDF pages were not parsed"})
                    break
            if processed_pages < total_pages and not any(g["code"] == "character_limit" for g in gaps):
                gaps.append({"code": "page_limit", "detail": "Remaining PDF pages were not parsed"})
            format_notes.append("PDF text order follows pypdf extraction; table layout and image-only content are not reconstructed")
        elif extension == ".docx":
            rows = _docx(data)
            format_notes.append("Body paragraphs and tables only; headers, footnotes, images and tracked-change semantics are not interpreted")
        elif extension in {".html", ".htm"}:
            parser = _HTMLBlocks()
            parser.feed(data.decode("utf-8-sig"))
            parser.close()
            parser.flush()
            rows = parser.blocks
            format_notes.append("Static HTML visible text only; JavaScript, images and CSS layout are not rendered")
        elif extension == ".xml":
            rows = _xml_blocks(data)
            format_notes.append("XML element text only; graphics and embedded binary objects are not interpreted")
        elif extension in {".txt", ".md", ".markdown"}:
            text = data.decode("utf-8-sig")
            # Paragraph splitting preserves exact source text inside every block.
            start = 0
            for match in re.finditer(r"\r?\n[ \t]*\r?\n", text):
                if text[start:match.start()].strip():
                    rows.append((text[start:match.start()], {"kind": "text_paragraph", "source_char_start": start, "source_char_end": match.start()}))
                start = match.end()
            if text[start:].strip():
                rows.append((text[start:], {"kind": "text_paragraph", "source_char_start": start, "source_char_end": len(text)}))
        else:
            gaps.append({"code": "unsupported_format", "detail": f"Unsupported source extension: {extension or '(none)'}"})
    except Exception as exc:
        gaps.append({"code": "parser_error", "detail": f"{type(exc).__name__}: {str(exc)[:400]}"})

    blocks, document_parts, used = [], [], 0
    for text, locator in rows:
        if not text.strip():
            continue
        if len(blocks) >= max_blocks or used >= max_chars:
            gaps.append({"code": "block_or_character_limit", "detail": "Some parsed text was omitted by configured limits"})
            break
        original_length = len(text)
        text = text[:max_chars - used]
        if len(text) < original_length:
            gaps.append({"code": "character_limit", "detail": "Final block was truncated"})
            locator = {**locator, "truncated": True}
            if "source_char_start" in locator:
                locator["source_char_end"] = locator["source_char_start"] + len(text)
        # Document offsets include the single separator between retained blocks.
        start = used + len(blocks)
        block_id = f"{ir_id}:b{len(blocks) + 1}"
        blocks.append({"id": block_id, "exact_text": text, "locator": {**locator, "block_start": 0, "block_end": len(text), "document_start": start, "document_end": start + len(text)}})
        document_parts.append(text)
        used += len(text)
    if not blocks and not gaps:
        gaps.append({"code": "empty_document", "detail": "No usable text was extracted"})
    return {
        "id": ir_id, "source_id": source_id, "source_revision_id": source_revision_id,
        "parser_version": PARSER_VERSION, "status": "parse_gap" if not blocks else ("partial" if gaps else "complete"),
        "blocks": blocks, "document_text": "\n".join(document_parts), "gaps": gaps,
        "coverage": {"total_pages": total_pages, "processed_pages": processed_pages, "retained_blocks": len(blocks), "retained_chars": used, "limits": limits, "text_extraction_complete": not gaps, "visual_content_verified": False, "format_notes": format_notes},
    }
