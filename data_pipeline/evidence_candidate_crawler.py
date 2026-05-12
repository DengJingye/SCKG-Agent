import argparse
import csv
import hashlib
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import requests


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.evidence_schemas import BENCHMARK_FIELDS, PUBLICATION_FIELDS, empty_record
from core.settings import get_settings
from data_pipeline.evidence_backfill import (
    build_catalog_index,
    clean_optional,
    evidence_safe_id,
    get_catalog_row,
    load_jsonl,
    load_tsv,
    normalize_name,
    select_tools,
)


DEFAULT_QUEUE = PROJECT_ROOT / "eval" / "review_queue_organized.jsonl"
DEFAULT_CATALOG = PROJECT_ROOT / "data" / "scrna_tools.tsv"
DEFAULT_PUBLICATION_OUTPUT = PROJECT_ROOT / "data" / "evidence_candidates" / "tool_publication_candidates.tsv"
DEFAULT_BENCHMARK_OUTPUT = PROJECT_ROOT / "data" / "evidence_candidates" / "tool_benchmark_candidates.tsv"
DEFAULT_CORE_TOOLS = PROJECT_ROOT / "data" / "evidence_candidates" / "core_50_tools.tsv"

CORE_SEED_TOOLS = [
    "scvi-tools",
    "CellPLM",
    "SeuratExtend",
    "moscot",
    "nicheformer",
    "MAESTRO",
    "MIMOSCA",
    "MOFA",
    "MOFA2",
    "cell2location",
    "scIB",
    "SingleR",
    "scGPT",
    "CellRank",
    "tradeSeq",
    "velociraptor",
    "wot",
]

BENCHMARK_TERMS = {
    "benchmark",
    "benchmarking",
    "comparison",
    "comparative",
    "evaluation",
    "assessment",
}

TASK_TERMS = {
    "Data Integration": ["integration", "batch correction", "batch effect", "harmonization"],
    "Cell Type Annotation": ["annotation", "cell type", "label transfer"],
    "Trajectory Inference": ["trajectory", "pseudotime", "lineage", "rna velocity"],
    "Clustering": ["clustering", "cluster"],
    "DTU Analysis": ["dtu", "differential transcript", "isoform"],
    "QC": ["quality control", "doublet", "ambient"],
    "Spatial Mapping": ["spatial", "mapping"],
}

MODALITY_TERMS = {
    "scRNA-seq": ["scrna", "single-cell rna", "single cell rna", "single-cell transcript"],
    "scATAC-seq": ["scatac", "single-cell atac"],
    "single-cell Hi-C": ["single-cell hi-c", "single cell hi-c", "schic", "hi-c"],
    "spatial": ["spatial", "visium", "slide-seq", "merfish"],
    "multiome": ["multiome", "multi-omic", "multiomic", "cite-seq"],
    "long-read scRNA-seq": ["long-read", "pacbio", "nanopore", "isoform"],
}

BIOMED_CONTEXT_TERMS = {
    "single-cell",
    "single cell",
    "scrna",
    "rna-seq",
    "transcript",
    "genomics",
    "bioinformatics",
    "cell",
    "omics",
    "spatial",
}


class CrossrefClient:
    def __init__(self, mailto: Optional[str] = None, timeout: int = 20):
        self.mailto = mailto
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": (
                    "scKG-Agent evidence candidate crawler"
                    + (f" (mailto:{mailto})" if mailto else "")
                )
            }
        )

    def search(self, query: str, rows: int) -> List[Dict[str, Any]]:
        params = {
            "query.bibliographic": query,
            "rows": rows,
            "sort": "relevance",
            "order": "desc",
        }
        if self.mailto:
            params["mailto"] = self.mailto
        response = self.session.get(
            "https://api.crossref.org/works",
            params=params,
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        return payload.get("message", {}).get("items", [])


def select_candidate_tools(args: argparse.Namespace) -> List[str]:
    selected: List[str] = []
    if args.tools_file:
        selected.extend(load_tools_file(args.tools_file))
    if args.tools:
        selected.extend(split_tools(args.tools))
    if args.seed_core:
        selected.extend(CORE_SEED_TOOLS)
    if args.review_queue.exists():
        selected.extend(select_tools(load_jsonl(args.review_queue), args.max_tools))
    seen = set()
    unique = []
    for tool in selected:
        if tool not in seen:
            unique.append(tool)
            seen.add(tool)
        if len(unique) >= args.max_tools:
            break
    return unique


def load_tools_file(path: Path) -> List[str]:
    if not path.exists():
        raise FileNotFoundError(f"Tool manifest does not exist: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        sample = handle.read(4096)
        handle.seek(0)
        if "\t" in sample or "," in sample:
            dialect = csv.Sniffer().sniff(sample, delimiters="\t,")
            reader = csv.DictReader(handle, dialect=dialect)
            fields = reader.fieldnames or []
            key = "tool_name" if "tool_name" in fields else fields[0] if fields else ""
            return [(row.get(key) or "").strip() for row in reader if (row.get(key) or "").strip()]
        return [line.strip() for line in handle if line.strip() and not line.lstrip().startswith("#")]


def split_tools(raw: str) -> List[str]:
    return [item.strip() for item in re.split(r"[,;\n]+", raw) if item.strip()]


def crawl_candidates(args: argparse.Namespace) -> Dict[str, Any]:
    settings = get_settings()
    tools = select_candidate_tools(args)
    catalog_index = build_catalog_index(load_tsv(args.catalog))
    client = None if args.offline else CrossrefClient(mailto=args.mailto)
    now = datetime.now(timezone.utc).isoformat()
    publication_rows: List[Dict[str, str]] = []
    benchmark_rows: List[Dict[str, str]] = []
    errors: List[Dict[str, str]] = []
    seen_publications = set()

    for index, tool_name in enumerate(tools, start=1):
        catalog_row = get_catalog_row(tool_name, catalog_index)
        queries = build_queries(tool_name, catalog_row, args.query_variants)
        tool_items: List[Dict[str, Any]] = []
        for query in queries:
            if client is None:
                continue
            try:
                tool_items.extend(client.search(query, args.rows_per_query))
            except Exception as exc:
                errors.append({"tool_name": tool_name, "query": query, "error": str(exc)})
            if args.sleep > 0:
                time.sleep(args.sleep)

        candidate_rows: List[Dict[str, str]] = []
        candidate_benchmarks: List[Dict[str, str]] = []
        for item in dedupe_crossref_items(tool_items):
            confidence = relevance_score(tool_name, item)
            if confidence < args.min_confidence:
                continue
            key = publication_key(item)
            if (tool_name, key) in seen_publications:
                continue
            seen_publications.add((tool_name, key))
            pub_row = crossref_to_publication_row(
                tool_name=tool_name,
                item=item,
                catalog_row=catalog_row,
                confidence=confidence,
                now=now,
                kg_version=settings.kg_version,
                embedding_version=settings.embedding_version,
                include_abstract=args.include_abstract,
            )
            candidate_rows.append(pub_row)
            if pub_row["benchmark_included"] == "true":
                candidate_benchmarks.append(
                    publication_to_benchmark_candidate(
                        pub_row,
                        now=now,
                        kg_version=settings.kg_version,
                    )
                )
        candidate_rows = apply_work_group_governance(candidate_rows)
        candidate_benchmarks = apply_work_group_governance(candidate_benchmarks, id_field="benchmark_id")
        candidate_rows.sort(key=lambda row: float(row["confidence"]), reverse=True)
        candidate_benchmarks.sort(key=lambda row: float(row["confidence"]), reverse=True)
        publication_rows.extend(
            [
                row for row in candidate_rows
                if row.get("record_type") != "benchmark"
            ][: args.max_candidates_per_tool]
        )
        benchmark_rows.extend(candidate_benchmarks[: args.max_candidates_per_tool])
        print(f"[{index}/{len(tools)}] {tool_name}: {len(tool_items)} raw Crossref items")

    write_tsv(publication_rows, args.publication_output, PUBLICATION_FIELDS)
    write_tsv(benchmark_rows, args.benchmark_output, BENCHMARK_FIELDS)
    return {
        "tools": len(tools),
        "publication_candidates": len(publication_rows),
        "benchmark_candidates": len(benchmark_rows),
        "errors": len(errors),
        "publication_output": str(args.publication_output),
        "benchmark_output": str(args.benchmark_output),
        "error_examples": errors[:5],
    }


def build_queries(tool_name: str, catalog_row: Dict[str, str], variants: int) -> List[str]:
    description = clean_optional(catalog_row.get("Description")) or ""
    aliases = [
        alias.strip()
        for alias in tool_alias(tool_name).split(";")
        if alias.strip()
    ]
    terms = [tool_name, f"{tool_name} single-cell", f"{tool_name} scRNA-seq"]
    for alias in aliases:
        if alias != tool_name:
            terms.extend([alias, f"{alias} single-cell", f"{alias} scRNA-seq"])
    if description:
        terms.append(f"{tool_name} {description[:160]}")
        if aliases:
            terms.append(f"{aliases[0]} {description[:160]}")
    deduped = []
    seen = set()
    for term in terms:
        if term not in seen:
            deduped.append(term)
            seen.add(term)
    return deduped[:variants]


def dedupe_crossref_items(items: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    deduped: Dict[str, Dict[str, Any]] = {}
    for item in items:
        deduped.setdefault(publication_key(item), item)
    return list(deduped.values())


def publication_key(item: Dict[str, Any]) -> str:
    doi = clean_optional(item.get("DOI"))
    if doi:
        return normalize_name(doi)
    title = first_text(item.get("title"))
    return normalize_name(title) or stable_hash(json.dumps(item, sort_keys=True)[:500])


def crossref_to_publication_row(
    tool_name: str,
    item: Dict[str, Any],
    catalog_row: Dict[str, str],
    confidence: float,
    now: str,
    kg_version: str,
    embedding_version: str,
    include_abstract: bool,
) -> Dict[str, str]:
    row = empty_record(PUBLICATION_FIELDS)
    title = first_text(item.get("title"))
    doi = clean_optional(item.get("DOI")) or ""
    paper_url = clean_optional(item.get("URL")) or (f"https://doi.org/{doi}" if doi else "")
    abstract = strip_tags(item.get("abstract") or "") if include_abstract else ""
    authors, first_author = author_fields(item.get("author", []))
    subjects = ";".join(item.get("subject", []) or [])
    venue = first_text(item.get("container-title"))
    publisher = clean_optional(item.get("publisher")) or ""
    full_text = " ".join([title, abstract, subjects, venue, publisher]).lower()
    paper_type = infer_paper_type(full_text, tool_name)
    record_type = infer_record_type(paper_type, full_text)
    evidence_role = infer_evidence_role(paper_type, full_text, tool_name)
    confidence = cap_candidate_confidence(confidence, record_type, full_text)
    row.update(
        {
            "publication_id": f"CAND_PUB_{evidence_safe_id(tool_name)}_{stable_hash(doi or title)}",
            "work_group_id": work_group_id(tool_name, title),
            "canonical_flag": "unknown",
            "duplicate_of": "",
            "record_type": record_type,
            "source_record_id": doi or paper_url or title,
            "tool_name": tool_name,
            "tool_alias": tool_alias(tool_name),
            "title": title,
            "authors": authors,
            "first_author": first_author,
            "doi": doi,
            "paper_url": paper_url,
            "pdf_url": first_pdf_url(item),
            "publication_year": publication_year(item),
            "venue": venue,
            "publisher": publisher,
            "paper_type": paper_type,
            "evidence_role": evidence_role,
            "abstract": abstract,
            "keywords": subjects,
            "task": infer_terms(full_text, TASK_TERMS),
            "modality": infer_terms(full_text, MODALITY_TERMS),
            "benchmark_included": "true" if has_benchmark_signal(full_text) else "false",
            "github_url": clean_optional(catalog_row.get("Code")) or "",
            "license_reported": clean_optional(catalog_row.get("License")) or "",
            "citation_source": "Crossref",
            "citations": str(item.get("is-referenced-by-count", "")),
            "citation_count_source": "Crossref:is-referenced-by-count",
            "source_url": paper_url,
            "source_type": "crossref",
            "extraction_method": "crossref_api_candidate_search",
            "claim_text": "",
            "claim_span": title[:500],
            "confidence": f"{confidence:.3f}",
            "trust_level": "review_needed",
            "review_status": "pending",
            "kg_version": kg_version,
            "embedding_version": embedding_version,
            "created_at": now,
            "updated_at": now,
            "last_checked": now,
            "notes": "candidate_only; requires human review before ingest",
        }
    )
    return row


def publication_to_benchmark_candidate(
    pub_row: Dict[str, str],
    now: str,
    kg_version: str,
) -> Dict[str, str]:
    row = empty_record(BENCHMARK_FIELDS)
    row.update(
        {
            "benchmark_id": f"CAND_BMK_{evidence_safe_id(pub_row['tool_name'])}_{stable_hash(pub_row['publication_id'])}",
            "work_group_id": pub_row["work_group_id"],
            "canonical_flag": pub_row["canonical_flag"],
            "duplicate_of": pub_row["duplicate_of"],
            "record_type": "benchmark",
            "source_record_id": pub_row["publication_id"],
            "benchmark_name": pub_row["title"],
            "benchmark_type": first_semicolon_value(pub_row["task"]) or "unknown",
            "task": pub_row["task"],
            "modality": pub_row["modality"],
            "tool_name": pub_row["tool_name"],
            "tool_alias": pub_row["tool_alias"],
            "workflow_step": infer_workflow_step(pub_row["task"]),
            "paper_title": pub_row["title"],
            "paper_doi": pub_row["doi"],
            "paper_pmid": pub_row["pmid"],
            "source_url": pub_row["source_url"],
            "source_type": pub_row["source_type"],
            "claim_span": pub_row["claim_span"],
            "extraction_method": "crossref_api_candidate_search",
            "confidence": pub_row["confidence"],
            "trust_level": "review_needed",
            "review_status": "pending",
            "kg_version": kg_version,
            "created_at": now,
            "updated_at": now,
            "last_checked": now,
            "notes": "candidate benchmark shell; manually extract metric/rank/score/protocol before ingest",
        }
    )
    return row


def relevance_score(tool_name: str, item: Dict[str, Any]) -> float:
    title = first_text(item.get("title")).lower()
    abstract = strip_tags(item.get("abstract") or "").lower()
    subjects = " ".join(item.get("subject", []) or []).lower()
    haystack = " ".join([title, abstract, subjects])
    if not has_biomed_context(haystack):
        return 0.0
    norm_tool = normalize_name(tool_name)
    aliases = [normalize_name(alias) for alias in tool_alias(tool_name).split(";")]
    score = 0.1
    if norm_tool and norm_tool in normalize_name(title):
        score += 0.55
    elif norm_tool and norm_tool in normalize_name(haystack):
        score += 0.35
    elif any(alias and alias in normalize_name(title) for alias in aliases):
        score += 0.5
    elif any(alias and alias in normalize_name(haystack) for alias in aliases):
        score += 0.3
    if any(term in haystack for terms in MODALITY_TERMS.values() for term in terms):
        score += 0.15
    if has_benchmark_signal(haystack):
        score += 0.1
    if item.get("DOI"):
        score += 0.05
    return min(score, 0.95)


def has_biomed_context(text: str) -> bool:
    return any(term in text for term in BIOMED_CONTEXT_TERMS)


def infer_paper_type(text: str, tool_name: str) -> str:
    if has_benchmark_signal(text):
        return "benchmark_paper"
    if "nature protocols" in text or "protocol" in text:
        return "protocol"
    if normalize_name(tool_name) in normalize_name(text[:300]):
        return "method_paper"
    if "review" in text:
        return "review"
    return "application_paper"


def infer_evidence_role(paper_type: str, text: str, tool_name: str) -> str:
    if paper_type == "benchmark_paper":
        return "comparative_evaluation"
    if paper_type == "protocol":
        return "workflow_support"
    if normalize_name(tool_name) in normalize_name(text[:300]):
        return "primary_method_reference"
    return "application_evidence"


def infer_record_type(paper_type: str, text: str) -> str:
    if paper_type == "benchmark_paper":
        return "benchmark"
    if paper_type == "protocol":
        return "protocol"
    if paper_type == "application_paper":
        return "application"
    if "support" in text:
        return "supporting_evidence"
    return "publication"


def cap_candidate_confidence(confidence: float, record_type: str, text: str) -> float:
    capped = confidence
    if record_type == "application":
        capped = min(capped, 0.65)
    if "hi-c" in text or "hic" in text:
        capped = min(capped, 0.55)
    if record_type == "protocol":
        capped = min(capped, 0.7)
    if record_type == "benchmark":
        capped = min(capped, 0.4)
    return capped


def has_benchmark_signal(text: str) -> bool:
    return any(term in text for term in BENCHMARK_TERMS)


def infer_terms(text: str, mapping: Dict[str, List[str]]) -> str:
    matched = [
        label for label, terms in mapping.items()
        if any(term in text for term in terms)
    ]
    return ";".join(matched)


def infer_workflow_step(task: str) -> str:
    first = first_semicolon_value(task).lower()
    if "integration" in first:
        return "integration"
    if "annotation" in first:
        return "annotation"
    if "trajectory" in first:
        return "trajectory"
    if "clustering" in first:
        return "clustering"
    if "dtu" in first:
        return "DTU"
    return first or "unknown"


def tool_alias(tool_name: str) -> str:
    aliases = {
        "scvi-tools": "scVI;scvi;scvi-tools",
        "MOFA2": "MOFA;MOFA2",
        "CellRank": "cellrank;CellRank",
    }
    return aliases.get(tool_name, tool_name)


def apply_work_group_governance(
    rows: List[Dict[str, str]],
    id_field: str = "publication_id",
) -> List[Dict[str, str]]:
    groups: Dict[str, List[Dict[str, str]]] = {}
    for row in rows:
        groups.setdefault(row.get("work_group_id") or row[id_field], []).append(row)

    governed: List[Dict[str, str]] = []
    for group_rows in groups.values():
        canonical = max(group_rows, key=canonical_priority)
        canonical_id = canonical[id_field]
        for row in group_rows:
            if row[id_field] == canonical_id:
                row["canonical_flag"] = "true"
            else:
                row["canonical_flag"] = "false"
                row["duplicate_of"] = canonical_id
                row["notes"] = append_note(row.get("notes", ""), "duplicate_version; keep for provenance, exclude from ranking")
            governed.append(row)
    return governed


def canonical_priority(row: Dict[str, str]) -> tuple[int, int, int, int, float]:
    source_record = row.get("source_record_id", "").lower()
    doi = row.get("doi", "").lower() or row.get("paper_doi", "").lower()
    venue = row.get("venue", "")
    year = safe_int(row.get("publication_year", ""))
    preprint_penalty = int(
        any(prefix in doi for prefix in ["10.1101", "10.21203", "biorxiv", "medrxiv"])
        or "openrxiv" in row.get("publisher", "").lower()
        or "preprint" in row.get("notes", "").lower()
    )
    journal_bonus = int(bool(venue) and not preprint_penalty)
    protocol_penalty = int(row.get("record_type") == "protocol")
    confidence = float(row.get("confidence") or 0.0)
    return (
        journal_bonus,
        -preprint_penalty,
        -protocol_penalty,
        year,
        confidence,
    )


def work_group_id(tool_name: str, title: str) -> str:
    title_key = canonical_title_key(title)
    return f"WG_{evidence_safe_id(tool_name)}_{stable_hash(title_key)}"


def canonical_title_key(title: str) -> str:
    lowered = title.lower()
    lowered = lowered.replace("single-cell", "single cell")
    lowered = re.sub(r"\bpreprint\b|\bprotocol\b|\bversion\b", " ", lowered)
    return normalize_name(lowered)


def safe_int(value: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def append_note(existing: str, note: str) -> str:
    if not existing:
        return note
    if note in existing:
        return existing
    return f"{existing}; {note}"


def author_fields(authors: List[Dict[str, Any]]) -> tuple[str, str]:
    names = []
    for author in authors:
        name = " ".join(
            part for part in [
                clean_optional(author.get("given")),
                clean_optional(author.get("family")),
            ]
            if part
        )
        if name:
            names.append(name)
    return ";".join(names), names[0] if names else ""


def publication_year(item: Dict[str, Any]) -> str:
    for key in ["published-print", "published-online", "published", "issued", "created"]:
        date_parts = item.get(key, {}).get("date-parts", [])
        if date_parts and date_parts[0]:
            return str(date_parts[0][0])
    return ""


def first_pdf_url(item: Dict[str, Any]) -> str:
    for link in item.get("link", []) or []:
        url = clean_optional(link.get("URL"))
        content_type = (link.get("content-type") or "").lower()
        if url and ("pdf" in content_type or url.lower().endswith(".pdf")):
            return url
    return ""


def first_text(value: Any) -> str:
    if isinstance(value, list):
        return str(value[0]).strip() if value else ""
    return str(value).strip() if value is not None else ""


def first_semicolon_value(value: str) -> str:
    return value.split(";")[0].strip() if value else ""


def strip_tags(value: str) -> str:
    return re.sub(r"<[^>]+>", " ", value).replace("\n", " ").strip()


def stable_hash(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:12]


def write_tsv(rows: List[Dict[str, str]], path: Path, fields: List[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate publication/benchmark evidence candidates for human review."
    )
    parser.add_argument("--review-queue", type=Path, default=DEFAULT_QUEUE)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--publication-output", type=Path, default=DEFAULT_PUBLICATION_OUTPUT)
    parser.add_argument("--benchmark-output", type=Path, default=DEFAULT_BENCHMARK_OUTPUT)
    parser.add_argument(
        "--tools-file",
        type=Path,
        default=None,
        help=f"Optional newline/CSV/TSV tool manifest. Example: {DEFAULT_CORE_TOOLS}",
    )
    parser.add_argument("--tools", default="", help="Comma/semicolon/newline separated explicit tool list.")
    parser.add_argument("--max-tools", type=int, default=50)
    parser.add_argument("--rows-per-query", type=int, default=5)
    parser.add_argument("--query-variants", type=int, default=5)
    parser.add_argument("--max-candidates-per-tool", type=int, default=8)
    parser.add_argument("--min-confidence", type=float, default=0.35)
    parser.add_argument("--sleep", type=float, default=0.2)
    parser.add_argument("--mailto", default="", help="Optional email for Crossref polite pool.")
    parser.add_argument("--seed-core", action="store_true", help="Prioritize the built-in core tool seed list.")
    parser.add_argument("--offline", action="store_true", help="Only write TSV headers; do not call Crossref.")
    parser.add_argument(
        "--include-abstract",
        action="store_true",
        help="Store Crossref abstracts when available. Defaults off because abstracts may be copyrighted.",
    )
    args = parser.parse_args()

    summary = crawl_candidates(args)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
