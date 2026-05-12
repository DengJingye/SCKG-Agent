import argparse
import csv
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Optional


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data_pipeline.evidence_backfill import evidence_safe_id, normalize_name


DEFAULT_CORE_TOOLS = PROJECT_ROOT / "data" / "evidence_candidates" / "core_50_tools.tsv"
DEFAULT_CANDIDATES = (
    PROJECT_ROOT / "data" / "evidence_candidates" / "core50_tool_publication_candidates_dedup.tsv"
)
DEFAULT_MANUAL_ANCHORS = (
    PROJECT_ROOT / "data" / "evidence_candidates" / "core50_publication_manual_anchors.tsv"
)
DEFAULT_REVIEW_ACTIONS = (
    PROJECT_ROOT / "data" / "evidence_candidates" / "core50_tool_publication_review_actions.tsv"
)
DEFAULT_MANUAL_OVERRIDES = (
    PROJECT_ROOT / "data" / "evidence_candidates" / "manual_audit_overrides.tsv"
)
DEFAULT_OUTPUT = (
    PROJECT_ROOT / "data" / "evidence_candidates" / "core50_publication_review_packet.tsv"
)

TARGET_TIERS = {"P0", "P1"}
TIER_ORDER = {"P0": 0, "P1": 1}
DECISION_ORDER = {
    "priority_review": 0,
    "needs_manual_lookup": 1,
    "keep_candidate": 2,
    "likely_duplicate": 3,
    "likely_noise": 4,
    "no_candidate_found": 5,
}
REQUIRED_FIELDS = ["title", "doi", "publication_year", "source_url", "authors"]
PUBLISHER_PREPRINT_SIGNALS = {"openrxiv", "biorxiv", "medrxiv"}
PREPRINT_DOI_PREFIXES = ("10.1101", "10.21203")
COMMON_NAME_TOOLS = {"harmony", "seurat", "mofa", "singleR".lower()}
HIGH_COLLISION_TOOLS = {"harmony", "seurat", "singleR".lower()}
BIOMED_CONTEXT_TERMS = {
    "single-cell",
    "single cell",
    "scrna",
    "rna-seq",
    "transcript",
    "genomics",
    "bioinformatics",
    "spatial",
    "multi-omics",
    "multiomics",
    "multi-omic",
    "cell type",
}
NOISE_TITLE_TERMS = {
    "conference",
    "supplemental information",
    "worldwide stem cell policy",
    "harmony in healing",
}
SECONDARY_TITLE_TERMS = {
    "abstract ",
    "faculty opinions recommendation",
    "supplemental information",
}

PACKET_FIELDS = [
    "priority_tier",
    "tool_name",
    "publication_id",
    "work_group_id",
    "canonical_flag",
    "duplicate_of",
    "title",
    "authors",
    "doi",
    "publication_year",
    "venue",
    "paper_type",
    "evidence_role",
    "confidence",
    "citations",
    "source_url",
    "review_action",
    "suggested_decision",
    "risk_notes",
    "missing_fields",
    "record_type",
    "review_status",
    "trust_level",
    "recommended_review_status",
    "recommended_trust_level",
    "validation_notes",
    "group_size",
    "group_reason",
    "source_type",
    "paper_url",
    "pmid",
    "arxiv_id",
]


def load_tsv(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(f"Missing required TSV: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def load_optional_tsv(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        return []
    return load_tsv(path)


def merge_candidate_rows(*row_groups: Iterable[Dict[str, str]]) -> List[Dict[str, str]]:
    merged: List[Dict[str, str]] = []
    seen = set()
    for rows in row_groups:
        for row in rows:
            publication_id = (row.get("publication_id") or "").strip()
            if not publication_id:
                continue
            if publication_id in seen:
                raise ValueError(f"Duplicate publication_id across candidate inputs: {publication_id}")
            merged.append(row)
            seen.add(publication_id)
    return merged


def write_tsv(rows: List[Dict[str, str]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=PACKET_FIELDS, delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: one_line(row.get(field, "")) for field in PACKET_FIELDS})


def one_line(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def target_tools(core_rows: Iterable[Dict[str, str]]) -> List[Dict[str, str]]:
    tools = []
    seen = set()
    for row in core_rows:
        tool_name = (row.get("tool_name") or "").strip()
        tier = (row.get("priority_tier") or "").strip()
        if not tool_name or tier not in TARGET_TIERS or tool_name in seen:
            continue
        tools.append({"tool_name": tool_name, "priority_tier": tier})
        seen.add(tool_name)
    return tools


def index_review_actions(rows: Iterable[Dict[str, str]]) -> Dict[str, Dict[str, str]]:
    return {
        row.get("publication_id", ""): row
        for row in rows
        if row.get("publication_id")
    }


def index_manual_overrides(rows: Iterable[Dict[str, str]]) -> Dict[tuple[str, str, str], Dict[str, str]]:
    index: Dict[tuple[str, str, str], Dict[str, str]] = {}
    for row in rows:
        tool_name = row.get("tool_name", "")
        title_match = row.get("title_match", "")
        if not tool_name or not title_match:
            continue
        canonical_flag = (row.get("canonical_flag") or "").strip().lower()
        index[(normalize_name(tool_name), override_title_key(title_match), canonical_flag)] = row
    return index


def override_title_key(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().lower())


def normalize_title(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def find_override(
    row: Dict[str, str],
    overrides: Dict[tuple[str, str, str], Dict[str, str]],
) -> Optional[Dict[str, str]]:
    base_key = (normalize_name(row.get("tool_name", "")), override_title_key(row.get("title", "")))
    canonical_flag = (row.get("canonical_flag") or "").strip().lower()
    return overrides.get((*base_key, canonical_flag)) or overrides.get((*base_key, ""))


def build_packet(
    core_tools: List[Dict[str, str]],
    candidates: List[Dict[str, str]],
    review_actions: Dict[str, Dict[str, str]],
    overrides: Dict[tuple[str, str, str], Dict[str, str]],
) -> List[Dict[str, str]]:
    tier_by_tool = {row["tool_name"]: row["priority_tier"] for row in core_tools}
    tool_position = {row["tool_name"]: index for index, row in enumerate(core_tools)}
    candidates_by_tool: Dict[str, List[Dict[str, str]]] = defaultdict(list)
    for row in candidates:
        tool_name = row.get("tool_name", "")
        if tool_name in tier_by_tool:
            candidates_by_tool[tool_name].append(row)

    packet_rows: List[Dict[str, str]] = []
    for tool in core_tools:
        tool_name = tool["tool_name"]
        tool_candidates = candidates_by_tool.get(tool_name, [])
        if not tool_candidates:
            packet_rows.append(no_candidate_row(tool))
            continue
        for candidate in tool_candidates:
            action = review_actions.get(candidate.get("publication_id", ""), {})
            override = find_override(candidate, overrides)
            packet_rows.append(packet_row(tool, candidate, action, override))

    packet_rows.sort(
        key=lambda row: (
            TIER_ORDER.get(row["priority_tier"], 9),
            tool_position.get(row["tool_name"], 999),
            DECISION_ORDER.get(row["suggested_decision"], 9),
            sort_number(row.get("citations")),
            row.get("publication_year", ""),
            row.get("title", ""),
        )
    )
    return packet_rows


def no_candidate_row(tool: Dict[str, str]) -> Dict[str, str]:
    tool_name = tool["tool_name"]
    return {
        "priority_tier": tool["priority_tier"],
        "tool_name": tool_name,
        "publication_id": f"NO_CAND_{evidence_safe_id(tool_name)}",
        "review_action": "manual_lookup_required",
        "suggested_decision": "no_candidate_found",
        "risk_notes": (
            "No publication candidate found in core50 candidate table; perform manual DOI/PMID/arXiv "
            "lookup before any promotion."
        ),
        "missing_fields": "publication_id;title;doi;source_url;publication_year;authors",
    }


def packet_row(
    tool: Dict[str, str],
    candidate: Dict[str, str],
    action: Dict[str, str],
    override: Optional[Dict[str, str]],
) -> Dict[str, str]:
    missing = merged_missing_fields(candidate, action)
    risk_notes = build_risk_notes(candidate, action, override, missing)
    review_action = review_action_value(action, override)
    decision = suggested_decision(candidate, action, override, missing, risk_notes)
    row = {field: one_line(candidate.get(field, "")) for field in PACKET_FIELDS}
    row.update(
        {
            "priority_tier": tool["priority_tier"],
            "review_action": review_action,
            "suggested_decision": decision,
            "risk_notes": "; ".join(risk_notes),
            "missing_fields": ";".join(missing),
            "recommended_review_status": action.get("recommended_review_status", ""),
            "recommended_trust_level": action.get("recommended_trust_level", ""),
            "validation_notes": action.get("validation_notes", ""),
        }
    )
    return row


def merged_missing_fields(candidate: Dict[str, str], action: Dict[str, str]) -> List[str]:
    missing = split_notes(action.get("missing_fields", ""))
    for field in REQUIRED_FIELDS:
        if not (candidate.get(field) or "").strip():
            missing.append(field)
    return sorted(set(missing), key=lambda item: REQUIRED_FIELDS.index(item) if item in REQUIRED_FIELDS else 99)


def split_notes(value: str) -> List[str]:
    return [
        part.strip()
        for part in re.split(r"[;,]", value or "")
        if part.strip()
    ]


def build_risk_notes(
    candidate: Dict[str, str],
    action: Dict[str, str],
    override: Optional[Dict[str, str]],
    missing: List[str],
) -> List[str]:
    notes = [
        "candidate_only",
        "requires_human_review_before_formal_ingest",
    ]
    notes.extend(split_notes(action.get("validation_notes", "")))
    notes.extend(split_notes(candidate.get("group_reason", "")))
    if action.get("reason"):
        notes.append(action["reason"])
    if candidate.get("canonical_flag") == "false" or candidate.get("duplicate_of"):
        notes.append("duplicate_or_noncanonical_candidate")
    if is_preprint_like(candidate):
        notes.append("preprint_or_preprint_like_source")
    if candidate.get("record_type") in {"application", "protocol", "supporting_evidence"}:
        notes.append(f"supporting_record_type:{candidate.get('record_type')}")
    if candidate.get("paper_type") in {"application_paper", "protocol", "review"}:
        notes.append(f"supporting_paper_type:{candidate.get('paper_type')}")
    if weak_title_tool_alignment(candidate):
        notes.append("weak_title_tool_alignment")
    if likely_noise_candidate(candidate):
        notes.append("likely_name_collision_or_non_method_record")
    if secondary_or_shell_candidate(candidate):
        notes.append("secondary_or_abstract_shell_not_primary_publication")
    if normalize_name(candidate.get("tool_name", "")) in COMMON_NAME_TOOLS:
        notes.append("generic_or_common_tool_name_requires_disambiguation")
    if missing:
        notes.append(f"missing_fields:{','.join(missing)}")
    if override:
        notes.append(f"manual_override:{override.get('audit_action', '')}")
        if override.get("reason"):
            notes.append(f"manual_override_reason:{override['reason']}")
    return dedupe_preserve_order(notes)


def review_action_value(action: Dict[str, str], override: Optional[Dict[str, str]]) -> str:
    if override and override.get("audit_action"):
        return override["audit_action"]
    if action.get("recommended_review_status"):
        trust = action.get("recommended_trust_level", "")
        return ":".join(part for part in [action["recommended_review_status"], trust] if part)
    return "manual_review"


def suggested_decision(
    candidate: Dict[str, str],
    action: Dict[str, str],
    override: Optional[Dict[str, str]],
    missing: List[str],
    risk_notes: List[str],
) -> str:
    if override:
        override_action = override.get("audit_action", "")
        if override_action == "prioritize_review":
            return "priority_review"
        if override_action == "mark_duplicate":
            return "likely_duplicate"
        if override_action == "keep_candidate":
            return "keep_candidate"
        if override_action == "move_to_benchmark":
            return "keep_candidate"

    if candidate.get("canonical_flag") == "false" or candidate.get("duplicate_of"):
        return "likely_duplicate"
    if "likely_name_collision_or_non_method_record" in risk_notes:
        return "likely_noise"
    if "weak_title_tool_alignment" in risk_notes and normalize_name(candidate.get("tool_name", "")) in HIGH_COLLISION_TOOLS:
        return "likely_noise"
    if missing or "secondary_or_abstract_shell_not_primary_publication" in risk_notes:
        return "needs_manual_lookup"
    if candidate.get("record_type") in {"application", "protocol", "supporting_evidence"}:
        return "keep_candidate"
    if candidate.get("paper_type") != "method_paper" or candidate.get("evidence_role") != "primary_method_reference":
        return "keep_candidate"
    if parse_float(candidate.get("confidence")) < 0.8:
        return "keep_candidate"
    if is_preprint_like(candidate) and not has_non_preprint_group_signal(candidate, action):
        return "keep_candidate"
    return "priority_review"


def is_preprint_like(candidate: Dict[str, str]) -> bool:
    doi = (candidate.get("doi") or "").lower()
    publisher = (candidate.get("publisher") or "").lower()
    venue = (candidate.get("venue") or "").lower()
    return (
        doi.startswith(PREPRINT_DOI_PREFIXES)
        or any(signal in publisher for signal in PUBLISHER_PREPRINT_SIGNALS)
        or any(signal in venue for signal in PUBLISHER_PREPRINT_SIGNALS)
    )


def has_non_preprint_group_signal(candidate: Dict[str, str], action: Dict[str, str]) -> bool:
    text = " ".join(
        [
            candidate.get("group_reason", ""),
            action.get("reason", ""),
            action.get("validation_notes", ""),
        ]
    ).lower()
    return "contains non-preprint version" in text


def weak_title_tool_alignment(candidate: Dict[str, str]) -> bool:
    title = normalize_title(candidate.get("title", ""))
    tool_name = normalize_name(candidate.get("tool_name", ""))
    aliases = [
        normalize_name(part)
        for part in (candidate.get("tool_alias", "") or candidate.get("tool_name", "")).split(";")
        if part.strip()
    ]
    return not any(alias and alias in title for alias in [tool_name, *aliases])


def likely_noise_candidate(candidate: Dict[str, str]) -> bool:
    title_raw = (candidate.get("title") or "").lower()
    title_norm = normalize_title(title_raw)
    tool_norm = normalize_name(candidate.get("tool_name", ""))
    context = " ".join(
        [
            candidate.get("title", ""),
            candidate.get("venue", ""),
            candidate.get("keywords", ""),
            candidate.get("task", ""),
            candidate.get("modality", ""),
        ]
    ).lower()
    if tool_norm == "harmony" and not any(term in context for term in ["integration", "single cell", "single-cell", "scrna"]):
        return True
    if any(term in title_raw for term in NOISE_TITLE_TERMS) and not any(
        term in context for term in BIOMED_CONTEXT_TERMS
    ):
        return True
    if tool_norm in HIGH_COLLISION_TOOLS and tool_norm in title_norm and not any(
        term in context for term in BIOMED_CONTEXT_TERMS
    ):
        return True
    if weak_title_tool_alignment(candidate) and not any(term in context for term in BIOMED_CONTEXT_TERMS):
        return True
    return False


def secondary_or_shell_candidate(candidate: Dict[str, str]) -> bool:
    title = (candidate.get("title") or "").lower()
    return any(term in title for term in SECONDARY_TITLE_TERMS)


def parse_float(value: str) -> float:
    try:
        return float(value or 0.0)
    except ValueError:
        return 0.0


def sort_number(value: Optional[str]) -> int:
    try:
        return -int(float(value or 0))
    except ValueError:
        return 0


def dedupe_preserve_order(values: Iterable[str]) -> List[str]:
    seen = set()
    deduped = []
    for value in values:
        cleaned = value.strip()
        if not cleaned or cleaned in seen:
            continue
        deduped.append(cleaned)
        seen.add(cleaned)
    return deduped


def summary(rows: List[Dict[str, str]]) -> Dict[str, object]:
    return {
        "rows": len(rows),
        "tiers": dict(Counter(row["priority_tier"] for row in rows)),
        "tools": len({row["tool_name"] for row in rows}),
        "suggested_decisions": dict(Counter(row["suggested_decision"] for row in rows)),
        "review_actions": dict(Counter(row["review_action"] for row in rows)),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a conservative P0/P1 publication review packet from candidate-only evidence."
    )
    parser.add_argument("--core-tools", type=Path, default=DEFAULT_CORE_TOOLS)
    parser.add_argument("--candidates", type=Path, default=DEFAULT_CANDIDATES)
    parser.add_argument(
        "--manual-anchors",
        type=Path,
        default=DEFAULT_MANUAL_ANCHORS,
        help="Candidate-only manual canonical anchor seed TSV.",
    )
    parser.add_argument("--review-actions", type=Path, default=DEFAULT_REVIEW_ACTIONS)
    parser.add_argument("--manual-overrides", type=Path, default=DEFAULT_MANUAL_OVERRIDES)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    core_tools = target_tools(load_tsv(args.core_tools))
    candidates = merge_candidate_rows(
        load_tsv(args.candidates),
        load_optional_tsv(args.manual_anchors),
    )
    review_actions = index_review_actions(load_tsv(args.review_actions))
    overrides = index_manual_overrides(load_tsv(args.manual_overrides))
    rows = build_packet(core_tools, candidates, review_actions, overrides)
    write_tsv(rows, args.output)
    print(json.dumps({"output": str(args.output), **summary(rows)}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
