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
from typing import Dict, Iterable, List, Optional, Sequence, Tuple


APPROVED_REVIEW_STATUSES = {"reviewed", "verified", "human_reviewed"}

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

SKIP_FIELDS_FOR_CANONICAL_SCORE = {
    "",
    "nan",
    "none",
    "unknown",
    "not specified",
}


@dataclass
class PublicationRecord:
    row: Dict[str, str]
    idx: int
    publication_id: str
    tool_name: str
    title_norm: str
    doi_norm: str
    pmid_norm: str
    arxiv_norm: str
    authors_norm: List[str]
    first_author_norm: str
    venue_norm: str
    paper_type_norm: str
    citation_count: int
    publication_year: int
    source_type_norm: str
    review_status_norm: str
    trust_level_norm: str


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
    value = re.sub(r"\s+", " ", value).strip()
    return value


def normalize_doi(value: str) -> str:
    value = normalize_text(value)
    if not value:
        return ""
    value = value.replace("https://doi.org/", "")
    value = value.replace("http://doi.org/", "")
    value = value.replace("doi:", "")
    value = value.strip().rstrip(".")
    return value


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


def normalize_tool_name(value: str) -> str:
    value = normalize_text(value)
    value = re.sub(r"[^a-z0-9]+", "", value)
    return value


def normalize_author_token(value: str) -> str:
    value = normalize_text(value)
    value = re.sub(r"[.,]", "", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def split_authors(value: str) -> List[str]:
    value = (value or "").strip()
    if not value:
        return []
    parts = re.split(r"\s*;\s*|\s+and\s+|\s*&\s*|\s*\|\s*|\s*/\s*", value)
    cleaned = [normalize_author_token(p) for p in parts if normalize_author_token(p)]
    return cleaned


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


def canonical_score(record: PublicationRecord) -> float:
    score = 0.0

    if record.doi_norm:
        score += 6.0
    if record.pmid_norm:
        score += 6.0
    if record.arxiv_norm:
        score += 3.0

    if record.review_status_norm in APPROVED_REVIEW_STATUSES:
        score += 10.0

    score += paper_type_score(record.paper_type_norm)

    if record.venue_norm and not is_preprint_venue(record.venue_norm, record.doi_norm):
        score += 18.0
    elif is_preprint_venue(record.venue_norm, record.doi_norm):
        score += 0.0

    if record.source_type_norm in {"manual", "pubmed", "crossref", "openalex", "semantic_scholar"}:
        score += 4.0

    if record.publication_year:
        score += min(max(record.publication_year, 1900), 2035) / 100.0

    if record.citation_count > 0:
        score += math.log1p(record.citation_count)

    if record.trust_level_norm == "trusted_core":
        score += 8.0

    if record.trust_level_norm == "review_needed":
        score += 2.0

    return score


def build_publication_record(row: Dict[str, str], idx: int) -> PublicationRecord:
    title = row.get("title", "")
    authors = row.get("authors", "")
    venue = row.get("venue", "")
    paper_type = row.get("paper_type", "")
    source_type = row.get("source_type", "")
    review_status = row.get("review_status", "")
    trust_level = row.get("trust_level", "")

    authors_norm = split_authors(authors)
    return PublicationRecord(
        row=row,
        idx=idx,
        publication_id=row.get("publication_id", "").strip(),
        tool_name=row.get("tool_name", "").strip(),
        title_norm=normalize_title(title),
        doi_norm=normalize_doi(row.get("doi", "")),
        pmid_norm=normalize_pmid(row.get("pmid", "")),
        arxiv_norm=normalize_arxiv(row.get("arxiv_id", "")),
        authors_norm=authors_norm,
        first_author_norm=authors_norm[0] if authors_norm else "",
        venue_norm=normalize_text(venue),
        paper_type_norm=normalize_text(paper_type),
        citation_count=parse_int(row.get("citations", "")),
        publication_year=extract_year(row.get("publication_year", "")),
        source_type_norm=normalize_text(source_type),
        review_status_norm=normalize_text(review_status),
        trust_level_norm=normalize_text(trust_level),
    )


def group_publications(records: List[PublicationRecord]) -> Tuple[List[List[int]], List[str]]:
    if not records:
        return [], []

    uf = UnionFind(len(records))
    exact_map: Dict[str, List[int]] = defaultdict(list)

    for rec in records:
        tool_key = normalize_tool_name(rec.tool_name) or f"row:{rec.idx}"
        if rec.doi_norm:
            exact_map[f"{tool_key}|doi:{rec.doi_norm}"].append(rec.idx)
        if rec.pmid_norm:
            exact_map[f"{tool_key}|pmid:{rec.pmid_norm}"].append(rec.idx)
        if rec.arxiv_norm:
            exact_map[f"{tool_key}|arxiv:{rec.arxiv_norm}"].append(rec.idx)

    for _, idxs in exact_map.items():
        if len(idxs) > 1:
            head = idxs[0]
            for idx in idxs[1:]:
                uf.union(head, idx)

    blocks: Dict[Tuple[str, str, str], List[int]] = defaultdict(list)
    for rec in records:
        block_key = (
            rec.tool_name.lower()[:32] if rec.tool_name else "",
            rec.title_norm[:64] if rec.title_norm else "",
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
                same_tool = normalize_tool_name(a.tool_name) == normalize_tool_name(b.tool_name) if a.tool_name and b.tool_name else False
                if not same_tool:
                    continue

                should_union = False
                if a.doi_norm and a.doi_norm == b.doi_norm:
                    should_union = True
                elif a.pmid_norm and a.pmid_norm == b.pmid_norm:
                    should_union = True
                elif a.arxiv_norm and a.arxiv_norm == b.arxiv_norm:
                    should_union = True
                elif same_tool and tsim >= 0.86:
                    should_union = True
                elif tsim >= 0.92 and aover >= 0.35:
                    should_union = True
                elif tsim >= 0.85 and aover >= 0.60:
                    should_union = True

                if should_union:
                    uf.union(a.idx, b.idx)

    groups_map: Dict[int, List[int]] = defaultdict(list)
    for rec in records:
        groups_map[uf.find(rec.idx)].append(rec.idx)

    groups = [sorted(v) for v in groups_map.values()]
    return groups, [f"n_groups={len(groups)}"]


def infer_group_reason(members: List[PublicationRecord]) -> str:
    reasons: List[str] = []
    dois = {m.doi_norm for m in members if m.doi_norm}
    pmids = {m.pmid_norm for m in members if m.pmid_norm}
    arxiv_ids = {m.arxiv_norm for m in members if m.arxiv_norm}

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

    if len(arxiv_ids) == 1 and len(members) > 1:
        reasons.append("shared arXiv ID")
    elif len(arxiv_ids) > 1:
        reasons.append("distinct arXiv IDs")
    elif len(arxiv_ids) == 1:
        reasons.append("has arXiv ID")

    title_sims = []
    for i in range(len(members)):
        for j in range(i + 1, len(members)):
            title_sims.append(title_similarity(members[i].title_norm, members[j].title_norm))
    if title_sims:
        reasons.append(f"title similarity max={max(title_sims):.2f}")

    author_ovs = []
    for i in range(len(members)):
        for j in range(i + 1, len(members)):
            author_ovs.append(author_overlap(members[i].authors_norm, members[j].authors_norm))
    if author_ovs:
        reasons.append(f"author overlap max={max(author_ovs):.2f}")

    if any(is_preprint_venue(m.venue_norm, m.doi_norm) for m in members):
        reasons.append("contains preprint version")
    if any(not is_preprint_venue(m.venue_norm, m.doi_norm) for m in members):
        reasons.append("contains non-preprint version")

    return "; ".join(reasons) if reasons else "heuristic publication grouping"


def choose_canonical(members: List[PublicationRecord]) -> PublicationRecord:
    scored = [(canonical_score(m), m) for m in members]
    scored.sort(
        key=lambda x: (
            x[0],
            1 if not is_preprint_venue(x[1].venue_norm, x[1].doi_norm) else 0,
            x[1].citation_count,
            x[1].publication_year,
            len(x[1].title_norm),
        ),
        reverse=True,
    )
    return scored[0][1]


def make_review_action_row(
    record: PublicationRecord,
    work_group_id: str,
    canonical_flag: bool,
    duplicate_of: str,
    group_reason: str,
    group_size: int,
) -> Dict[str, str]:
    missing_fields = get_missing_review_fields(record)
    validation_notes = get_validation_notes(record, canonical_flag, group_size)
    return {
        "publication_id": record.publication_id,
        "work_group_id": work_group_id,
        "canonical_flag": "true" if canonical_flag else "false",
        "duplicate_of": duplicate_of,
        "recommended_review_status": "review_needed" if canonical_flag else "review_needed",
        "recommended_trust_level": "review_needed" if canonical_flag else "retrieval_only",
        "reason": (
            f"{'canonical candidate' if canonical_flag else 'duplicate candidate'}; "
            f"group_size={group_size}; {group_reason}"
        ),
        "missing_fields": ";".join(missing_fields),
        "validation_notes": "; ".join(validation_notes),
    }


def get_missing_review_fields(record: PublicationRecord) -> List[str]:
    missing = []
    if not record.publication_id:
        missing.append("publication_id")
    if not record.tool_name:
        missing.append("tool_name")
    if not record.title_norm:
        missing.append("title")
    if not (record.doi_norm or record.pmid_norm or record.arxiv_norm):
        missing.append("doi_or_pmid_or_arxiv_id")
    if not record.authors_norm:
        missing.append("authors")
    if not record.paper_type_norm:
        missing.append("paper_type")
    if not normalize_text(record.row.get("evidence_role", "")):
        missing.append("evidence_role")
    if not normalize_text(record.row.get("source_url", "")):
        missing.append("source_url")
    return missing


def get_validation_notes(record: PublicationRecord, canonical_flag: bool, group_size: int) -> List[str]:
    notes = ["candidate_only"]
    if group_size > 1:
        notes.append("duplicate_group_requires_manual_review")
    if canonical_flag:
        notes.append("canonical_suggestion_not_verified")
    else:
        notes.append("duplicate_suggestion_not_verified")
    if is_preprint_venue(record.venue_norm, record.doi_norm, record.row.get("source_url", "")):
        notes.append("preprint_or_preprint_like_source")
    if record.paper_type_norm in {"protocol", "application_paper", "benchmark_paper"}:
        notes.append(f"supporting_record_type:{record.paper_type_norm}")
    return notes


def make_dedup_row(
    record: PublicationRecord,
    work_group_id: str,
    canonical_flag: bool,
    duplicate_of: str,
    canonical_score_value: float,
    group_size: int,
    group_reason: str,
) -> Dict[str, str]:
    out = dict(record.row)
    out["work_group_id"] = work_group_id
    out["canonical_flag"] = "true" if canonical_flag else "false"
    out["duplicate_of"] = duplicate_of
    out["group_size"] = str(group_size)
    out["group_reason"] = group_reason
    out["canonical_score"] = f"{canonical_score_value:.4f}"
    return out


def safe_work_group_suffix(record: PublicationRecord) -> str:
    if record.publication_id:
        suffix = re.sub(r"[^A-Za-z0-9_.-]+", "_", record.publication_id.strip())
        suffix = suffix.strip("_")
        if suffix:
            return suffix
    return f"{record.idx:04d}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Publication candidate canonical merge and review actions.")
    parser.add_argument(
        "--input",
        default="data/evidence_candidates/tool_publication_candidates.tsv",
        help="Input publication candidate TSV.",
    )
    parser.add_argument(
        "--dedup-output",
        default="data/evidence_candidates/tool_publication_candidates_dedup.tsv",
        help="Output deduplicated TSV.",
    )
    parser.add_argument(
        "--actions-output",
        default="data/evidence_candidates/tool_publication_review_actions.tsv",
        help="Output review actions TSV.",
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    dedup_path = Path(args.dedup_output)
    actions_path = Path(args.actions_output)

    rows, original_fields = read_tsv(input_path)
    records = [build_publication_record(row, idx) for idx, row in enumerate(rows)]

    groups, _ = group_publications(records)

    extra_dedup_fields = [
        "work_group_id",
        "canonical_flag",
        "duplicate_of",
        "group_size",
        "group_reason",
        "canonical_score",
    ]
    dedup_fieldnames = list(original_fields) + [f for f in extra_dedup_fields if f not in original_fields]

    review_fieldnames = [
        "publication_id",
        "work_group_id",
        "canonical_flag",
        "duplicate_of",
        "recommended_review_status",
        "recommended_trust_level",
        "reason",
        "missing_fields",
        "validation_notes",
    ]

    dedup_rows: List[Dict[str, str]] = []
    review_rows: List[Dict[str, str]] = []

    for idxs in groups:
        members = [records[i] for i in idxs]
        if not members:
            continue

        canonical = choose_canonical(members)
        group_reason = infer_group_reason(members)
        work_group_id = f"PUBWG_{safe_work_group_suffix(canonical)}"
        canonical_score_value = canonical_score(canonical)

        for member in members:
            is_canonical = member.idx == canonical.idx
            duplicate_of = "" if is_canonical else canonical.publication_id
            dedup_rows.append(
                make_dedup_row(
                    member,
                    work_group_id=work_group_id,
                    canonical_flag=is_canonical,
                    duplicate_of=duplicate_of,
                    canonical_score_value=canonical_score(member),
                    group_size=len(members),
                    group_reason=group_reason,
                )
            )
            review_rows.append(
                make_review_action_row(
                    member,
                    work_group_id=work_group_id,
                    canonical_flag=is_canonical,
                    duplicate_of=duplicate_of,
                    group_reason=group_reason,
                    group_size=len(members),
                )
            )

    dedup_rows.sort(key=lambda r: (r.get("work_group_id", ""), r.get("canonical_flag", ""), r.get("publication_id", "")))
    review_rows.sort(key=lambda r: (r.get("work_group_id", ""), r.get("publication_id", "")))

    write_tsv(dedup_path, dedup_fieldnames, dedup_rows)
    write_tsv(actions_path, review_fieldnames, review_rows)

    print(f"Input rows: {len(rows)}")
    print(f"Dedup rows: {len(dedup_rows)}")
    print(f"Review action rows: {len(review_rows)}")
    print(f"Wrote: {dedup_path}")
    print(f"Wrote: {actions_path}")


if __name__ == "__main__":
    main()
