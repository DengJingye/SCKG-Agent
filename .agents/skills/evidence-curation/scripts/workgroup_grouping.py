#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import csv
import math
import re
from collections import defaultdict
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Dict, List, Sequence, Tuple


PREPRINT_VENUE_MARKERS = (
    "biorxiv",
    "bioRxiv",
    "openrxiv",
    "openRxiv",
    "medrxiv",
    "arxiv",
    "preprint",
)

PAPER_TYPE_PRIORITY = {
    "method_paper": 60,
    "protocol": 45,
    "application_paper": 40,
    "benchmark_paper": 35,
    "dataset_paper": 30,
    "review": 10,
    "unknown": 15,
    "": 15,
}


@dataclass
class GroupRecord:
    row: Dict[str, str]
    idx: int
    record_id: str
    record_type: str
    tool_name: str
    title_norm: str
    authors_norm: List[str]
    first_author_norm: str
    doi_norm: str
    pmid_norm: str
    arxiv_norm: str
    venue_norm: str
    paper_type_norm: str
    source_url_norm: str
    citation_count: int
    publication_year: int
    benchmark_name_norm: str


class UnionFind:
    def __init__(self, n: int) -> None:
        self.parent = list(range(n))
        self.rank = [0] * n

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra = self.find(a)
        rb = self.find(b)
        if ra == rb:
            return
        if self.rank[ra] < self.rank[rb]:
            self.parent[ra] = rb
        elif self.rank[ra] > self.rank[rb]:
            self.parent[rb] = ra
        else:
            self.parent[rb] = ra
            self.rank[ra] += 1


def read_tsv(path: Path) -> Tuple[List[Dict[str, str]], List[str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        rows = [dict(row) for row in reader]
        fieldnames = list(reader.fieldnames or [])
    return rows, fieldnames


def write_tsv(path: Path, fieldnames: Sequence[str], rows: Sequence[Dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(fieldnames), delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fieldnames})


def normalize_text(value: str) -> str:
    value = (value or "").strip().lower()
    value = re.sub(r"\s+", " ", value)
    return value


def normalize_title(value: str) -> str:
    value = normalize_text(value)
    value = value.replace("–", "-").replace("—", "-")
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def normalize_doi(value: str) -> str:
    value = normalize_text(value)
    if not value:
        return ""
    value = value.replace("https://doi.org/", "")
    value = value.replace("http://doi.org/", "")
    value = value.replace("doi:", "")
    return value.strip().rstrip(".")


def normalize_pmid(value: str) -> str:
    value = normalize_text(value)
    if not value:
        return ""
    digits = re.findall(r"\d+", value)
    return digits[0] if digits else ""


def normalize_arxiv(value: str) -> str:
    value = normalize_text(value)
    if not value:
        return ""
    value = value.replace("https://arxiv.org/abs/", "")
    value = value.replace("http://arxiv.org/abs/", "")
    value = value.replace("arxiv:", "")
    value = value.strip().rstrip("/")
    m = re.match(r"^([a-z\-]+/\d{7})(v\d+)?$", value)
    if m:
        return m.group(1)
    m = re.match(r"^(\d{4}\.\d{4,5})(v\d+)?$", value)
    if m:
        return m.group(1)
    return value


def normalize_author_token(value: str) -> str:
    value = normalize_text(value)
    value = re.sub(r"[.,]", "", value)
    return re.sub(r"\s+", " ", value).strip()


def split_authors(value: str) -> List[str]:
    value = (value or "").strip()
    if not value:
        return []
    parts = re.split(r"\s*;\s*|\s+and\s+|\s*&\s*|\s*\|\s*|\s*/\s*", value)
    return [normalize_author_token(p) for p in parts if normalize_author_token(p)]


def parse_int(value: str, default: int = 0) -> int:
    value = (value or "").strip()
    if not value:
        return default
    digits = re.findall(r"-?\d+", value.replace(",", ""))
    if not digits:
        return default
    try:
        return int(digits[0])
    except Exception:
        return default


def extract_year(value: str) -> int:
    m = re.search(r"(19|20)\d{2}", (value or "").strip())
    if not m:
        return 0
    try:
        return int(m.group(0))
    except Exception:
        return 0


def is_preprint_venue(venue: str, doi: str = "", source_url: str = "") -> bool:
    blob = " ".join([venue or "", doi or "", source_url or ""]).lower()
    return any(marker.lower() in blob for marker in PREPRINT_VENUE_MARKERS) or doi.startswith("10.1101")


def title_similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def author_overlap(a: Sequence[str], b: Sequence[str]) -> float:
    sa = set(a)
    sb = set(b)
    if not sa or not sb:
        return 0.0
    inter = len(sa & sb)
    denom = max(1, min(len(sa), len(sb)))
    return inter / denom


def paper_type_score(paper_type: str) -> int:
    return PAPER_TYPE_PRIORITY.get(normalize_text(paper_type), PAPER_TYPE_PRIORITY["unknown"])


def read_publication_records(path: Path) -> Tuple[List[GroupRecord], List[str]]:
    rows, fields = read_tsv(path)
    records: List[GroupRecord] = []
    for idx, row in enumerate(rows):
        authors_norm = split_authors(row.get("authors", ""))
        records.append(
            GroupRecord(
                row=row,
                idx=idx,
                record_id=row.get("publication_id", "").strip(),
                record_type="publication",
                tool_name=row.get("tool_name", "").strip(),
                title_norm=normalize_title(row.get("title", "")),
                authors_norm=authors_norm,
                first_author_norm=authors_norm[0] if authors_norm else "",
                doi_norm=normalize_doi(row.get("doi", "")),
                pmid_norm=normalize_pmid(row.get("pmid", "")),
                arxiv_norm=normalize_arxiv(row.get("arxiv_id", "")),
                venue_norm=normalize_text(row.get("venue", "")),
                paper_type_norm=normalize_text(row.get("paper_type", "")),
                source_url_norm=normalize_text(row.get("source_url", "")),
                citation_count=parse_int(row.get("citations", "")),
                publication_year=extract_year(row.get("publication_year", "")),
                benchmark_name_norm="",
            )
        )
    return records, fields


def read_benchmark_records(path: Path) -> Tuple[List[GroupRecord], List[str]]:
    rows, fields = read_tsv(path)
    records: List[GroupRecord] = []
    for idx, row in enumerate(rows):
        title_norm = normalize_title(row.get("paper_title", "") or row.get("benchmark_name", ""))
        authors_norm = split_authors(row.get("authors", ""))
        records.append(
            GroupRecord(
                row=row,
                idx=idx,
                record_id=row.get("benchmark_id", "").strip(),
                record_type="benchmark",
                tool_name=row.get("tool_name", "").strip(),
                title_norm=title_norm,
                authors_norm=authors_norm,
                first_author_norm=authors_norm[0] if authors_norm else "",
                doi_norm=normalize_doi(row.get("paper_doi", "")),
                pmid_norm=normalize_pmid(row.get("paper_pmid", "")),
                arxiv_norm="",
                venue_norm=normalize_text(row.get("venue", "")),
                paper_type_norm=normalize_text(row.get("benchmark_type", "")),
                source_url_norm=normalize_text(row.get("source_url", "")),
                citation_count=0,
                publication_year=extract_year(row.get("publication_year", "")),
                benchmark_name_norm=normalize_title(row.get("benchmark_name", "")),
            )
        )
    return records, fields


def group_records(records: List[GroupRecord]) -> List[List[int]]:
    if not records:
        return []

    uf = UnionFind(len(records))
    exact_map: Dict[str, List[int]] = defaultdict(list)

    for rec in records:
        tool_key = normalize_text(rec.tool_name) or f"row:{rec.idx}"
        if rec.doi_norm:
            exact_map[f"{tool_key}|doi:{rec.doi_norm}"].append(rec.idx)
        if rec.pmid_norm:
            exact_map[f"{tool_key}|pmid:{rec.pmid_norm}"].append(rec.idx)
        if rec.arxiv_norm:
            exact_map[f"{tool_key}|arxiv:{rec.arxiv_norm}"].append(rec.idx)
        if rec.source_url_norm:
            exact_map[f"{tool_key}|url:{rec.source_url_norm}"].append(rec.idx)

    for _, idxs in exact_map.items():
        if len(idxs) > 1:
            head = idxs[0]
            for idx in idxs[1:]:
                uf.union(head, idx)

    blocks: Dict[Tuple[str, str, str], List[int]] = defaultdict(list)
    for rec in records:
        title_block = rec.title_norm[:72] if rec.title_norm else rec.benchmark_name_norm[:72]
        block_key = (
            rec.tool_name.lower()[:32] if rec.tool_name else "",
            title_block,
            rec.first_author_norm[:32] if rec.first_author_norm else "",
        )
        blocks[block_key].append(rec.idx)

    for idxs in blocks.values():
        if len(idxs) < 2:
            continue
        for i in range(len(idxs)):
            for j in range(i + 1, len(idxs)):
                a = records[idxs[i]]
                b = records[idxs[j]]
                tsim = title_similarity(a.title_norm, b.title_norm)
                aover = author_overlap(a.authors_norm, b.authors_norm)
                same_tool = normalize_text(a.tool_name) == normalize_text(b.tool_name) if a.tool_name and b.tool_name else False
                if not same_tool:
                    continue

                should_union = False
                if a.doi_norm and a.doi_norm == b.doi_norm:
                    should_union = True
                elif a.pmid_norm and a.pmid_norm == b.pmid_norm:
                    should_union = True
                elif a.source_url_norm and a.source_url_norm == b.source_url_norm:
                    should_union = True
                elif same_tool and tsim >= 0.85:
                    should_union = True
                elif tsim >= 0.90 and aover >= 0.35:
                    should_union = True
                elif tsim >= 0.80 and aover >= 0.60:
                    should_union = True

                if should_union:
                    uf.union(a.idx, b.idx)

    groups_map: Dict[int, List[int]] = defaultdict(list)
    for rec in records:
        groups_map[uf.find(rec.idx)].append(rec.idx)
    return [sorted(v) for v in groups_map.values()]


def group_reason(members: List[GroupRecord]) -> str:
    reasons: List[str] = []
    dois = {m.doi_norm for m in members if m.doi_norm}
    pmids = {m.pmid_norm for m in members if m.pmid_norm}
    source_urls = {m.source_url_norm for m in members if m.source_url_norm}

    if len(dois) == 1 and len(members) > 1:
        reasons.append("shared DOI")
    elif len(dois) > 1:
        reasons.append("distinct DOIs")
    elif len(dois) == 1:
        reasons.append("has DOI")

    if len(pmids) == 1 and len(members) > 1:
        reasons.append("shared PMID")
    elif len(pmids) > 1:
        reasons.append("distinct PMIDs")
    elif len(pmids) == 1:
        reasons.append("has PMID")

    if len(source_urls) == 1 and len(members) > 1:
        reasons.append("shared source URL")
    elif len(source_urls) > 1:
        reasons.append("distinct source URLs")
    elif len(source_urls) == 1:
        reasons.append("has source URL")

    sims = []
    for i in range(len(members)):
        for j in range(i + 1, len(members)):
            sims.append(title_similarity(members[i].title_norm, members[j].title_norm))
    if sims:
        reasons.append(f"title similarity max={max(sims):.2f}")

    ovs = []
    for i in range(len(members)):
        for j in range(i + 1, len(members)):
            ovs.append(author_overlap(members[i].authors_norm, members[j].authors_norm))
    if ovs:
        reasons.append(f"author overlap max={max(ovs):.2f}")

    if any(is_preprint_venue(m.venue_norm, m.doi_norm, m.source_url_norm) for m in members):
        reasons.append("contains preprint version")
    if any(not is_preprint_venue(m.venue_norm, m.doi_norm, m.source_url_norm) for m in members):
        reasons.append("contains non-preprint version")

    return "; ".join(reasons) if reasons else "heuristic work group"


def canonical_score_publication(record: GroupRecord) -> float:
    score = 0.0
    if record.doi_norm:
        score += 6.0
    if record.pmid_norm:
        score += 6.0
    if record.arxiv_norm:
        score += 3.0
    if record.paper_type_norm:
        score += paper_type_score(record.paper_type_norm)
    if record.publication_year:
        score += min(max(record.publication_year, 1900), 2035) / 100.0
    if record.citation_count > 0:
        score += math.log1p(record.citation_count)
    if record.venue_norm and not is_preprint_venue(record.venue_norm, record.doi_norm, record.source_url_norm):
        score += 18.0
    if record.record_type == "publication":
        score += 2.0
    return score


def canonical_score_benchmark(record: GroupRecord) -> float:
    score = 0.0
    if record.doi_norm:
        score += 6.0
    if record.pmid_norm:
        score += 6.0
    if record.source_url_norm:
        score += 3.0
    if record.title_norm and len(record.title_norm) > 10:
        score += 4.0
    if record.tool_name:
        score += 3.0
    if record.benchmark_name_norm and not any(marker in record.benchmark_name_norm for marker in ("supplement", "appendix", "supporting")):
        score += 10.0
    if record.paper_type_norm and record.paper_type_norm != "unknown":
        score += paper_type_score(record.paper_type_norm)
    if record.publication_year:
        score += min(max(record.publication_year, 1900), 2035) / 100.0
    return score


def choose_canonical(records: List[GroupRecord]) -> GroupRecord:
    def key_pub(r: GroupRecord) -> Tuple[float, int, int, int, int]:
        return (
            canonical_score_publication(r),
            1 if (r.venue_norm and not is_preprint_venue(r.venue_norm, r.doi_norm, r.source_url_norm)) else 0,
            r.citation_count,
            r.publication_year,
            len(r.title_norm),
        )

    def key_bmk(r: GroupRecord) -> Tuple[float, int, int, int, int]:
        return (
            canonical_score_benchmark(r),
            1 if r.benchmark_name_norm and not any(marker in r.benchmark_name_norm for marker in ("supplement", "appendix", "supporting")) else 0,
            len(r.title_norm),
            r.publication_year,
            len(r.tool_name),
        )

    if records and records[0].record_type == "publication":
        return sorted(records, key=key_pub, reverse=True)[0]
    return sorted(records, key=key_bmk, reverse=True)[0]


def safe_work_group_suffix(record: GroupRecord) -> str:
    if record.record_id:
        suffix = re.sub(r"[^A-Za-z0-9_.-]+", "_", record.record_id.strip())
        suffix = suffix.strip("_")
        if suffix:
            return suffix
    return f"{record.idx:04d}"


def build_output_rows(records: List[GroupRecord], groups: List[List[int]]) -> Tuple[List[Dict[str, str]], List[Dict[str, str]]]:
    grouped_rows: List[Dict[str, str]] = []
    for idxs in groups:
        members = [records[i] for i in idxs]
        if not members:
            continue
        canonical = choose_canonical(members)
        wgid_prefix = "PUBWG" if members[0].record_type == "publication" else "BMKWG"
        work_group_id = f"{wgid_prefix}_{safe_work_group_suffix(canonical)}"
        reason = group_reason(members)
        canonical_row_id = canonical.record_id

        for m in members:
            out = dict(m.row)
            out["work_group_id"] = work_group_id
            out["canonical_flag"] = "true" if m.idx == canonical.idx else "false"
            out["duplicate_of"] = "" if m.idx == canonical.idx else canonical_row_id
            out["group_size"] = str(len(members))
            out["group_reason"] = reason
            out["canonical_score"] = f"{(canonical_score_publication(m) if m.record_type == 'publication' else canonical_score_benchmark(m)):.4f}"
            out["record_type"] = m.record_type
            grouped_rows.append(out)

    grouped_rows.sort(key=lambda r: (r.get("work_group_id", ""), r.get("canonical_flag", ""), r.get("record_id", ""), r.get("publication_id", ""), r.get("benchmark_id", "")))

    # Workgroup summary rows are useful for manual review
    summary_rows: List[Dict[str, str]] = []
    by_group: Dict[str, List[Dict[str, str]]] = defaultdict(list)
    for row in grouped_rows:
        by_group[row.get("work_group_id", "")].append(row)

    for wgid, rows in by_group.items():
        canonical_rows = [r for r in rows if r.get("canonical_flag") == "true"]
        canonical_id = canonical_rows[0].get("publication_id") or canonical_rows[0].get("benchmark_id") if canonical_rows else ""
        summary_rows.append(
            {
                "work_group_id": wgid,
                "record_type": rows[0].get("record_type", ""),
                "group_size": str(len(rows)),
                "canonical_id": canonical_id,
                "member_ids": ";".join(
                    [
                        r.get("publication_id", "") or r.get("benchmark_id", "")
                        for r in rows
                    ]
                ),
                "group_reason": rows[0].get("group_reason", ""),
            }
        )

    return grouped_rows, summary_rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Build workgroup views for publication and benchmark candidates.")
    parser.add_argument(
        "--publication-input",
        default="data/evidence_candidates/tool_publication_candidates.tsv",
        help="Input publication candidate TSV.",
    )
    parser.add_argument(
        "--benchmark-input",
        default="data/evidence_candidates/tool_benchmark_candidates.tsv",
        help="Input benchmark candidate TSV.",
    )
    parser.add_argument(
        "--publication-output",
        default="data/evidence_candidates/publication_work_groups.tsv",
        help="Output publication workgroup TSV.",
    )
    parser.add_argument(
        "--benchmark-output",
        default="data/evidence_candidates/benchmark_work_groups.tsv",
        help="Output benchmark workgroup TSV.",
    )
    parser.add_argument(
        "--publication-summary-output",
        default="data/evidence_candidates/publication_work_groups_summary.tsv",
        help="Output publication summary TSV.",
    )
    parser.add_argument(
        "--benchmark-summary-output",
        default="data/evidence_candidates/benchmark_work_groups_summary.tsv",
        help="Output benchmark summary TSV.",
    )
    args = parser.parse_args()

    pub_rows, pub_fields = read_tsv(Path(args.publication_input))
    bmk_rows, bmk_fields = read_tsv(Path(args.benchmark_input))

    pub_records, _ = read_publication_records(Path(args.publication_input))
    bmk_records, _ = read_benchmark_records(Path(args.benchmark_input))

    pub_groups = group_records(pub_records)
    bmk_groups = group_records(bmk_records)

    pub_grouped_rows, pub_summary_rows = build_output_rows(pub_records, pub_groups)
    bmk_grouped_rows, bmk_summary_rows = build_output_rows(bmk_records, bmk_groups)

    pub_out_fields = list(pub_fields) + [
        f for f in ["work_group_id", "canonical_flag", "duplicate_of", "group_size", "group_reason", "canonical_score", "record_type"]
        if f not in pub_fields
    ]
    bmk_out_fields = list(bmk_fields) + [
        f for f in ["work_group_id", "canonical_flag", "duplicate_of", "group_size", "group_reason", "canonical_score", "record_type"]
        if f not in bmk_fields
    ]

    summary_pub_fields = ["work_group_id", "record_type", "group_size", "canonical_id", "member_ids", "group_reason"]
    summary_bmk_fields = ["work_group_id", "record_type", "group_size", "canonical_id", "member_ids", "group_reason"]

    write_tsv(Path(args.publication_output), pub_out_fields, pub_grouped_rows)
    write_tsv(Path(args.benchmark_output), bmk_out_fields, bmk_grouped_rows)
    write_tsv(Path(args.publication_summary_output), summary_pub_fields, pub_summary_rows)
    write_tsv(Path(args.benchmark_summary_output), summary_bmk_fields, bmk_summary_rows)

    print(f"Publication groups: {len(pub_summary_rows)}")
    print(f"Benchmark groups: {len(bmk_summary_rows)}")
    print(f"Wrote: {args.publication_output}")
    print(f"Wrote: {args.benchmark_output}")
    print(f"Wrote: {args.publication_summary_output}")
    print(f"Wrote: {args.benchmark_summary_output}")


if __name__ == "__main__":
    main()
