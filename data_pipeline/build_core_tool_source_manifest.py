from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TOOL_CATALOG = PROJECT_ROOT / "data" / "scrna_tools.tsv"
DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "evidence_candidates" / "core_tool_source_manifest_v2.tsv"
DEFAULT_SUMMARY = PROJECT_ROOT / "data" / "evidence_candidates" / "core_tool_source_manifest_v2_summary.json"
DEFAULT_LOCAL_ROOT = "data/evidence_sources/text/core_docs"
DEFAULT_CORE_TOOLS = (
    "Seurat",
    "Scanpy",
    "Harmony",
    "scvi-tools",
    "CellTypist",
    "SingleR",
    "cell2location",
    "scVelo",
    "CellRank",
    "Scrublet",
    "DoubletFinder",
    "MIMOSCA",
    "tradeSeq",
    "MOFA2",
    "moscot",
    "wot",
)
DEFAULT_OFFICIAL_DOCS_URLS = {
    "mofa2": "https://biofam.github.io/MOFA2/",
    "wot": "https://broadinstitute.github.io/wot/",
}
MANIFEST_FIELDS = [
    "source_id",
    "evidence_kind",
    "tool_name",
    "record_id",
    "source_title",
    "source_url",
    "doi_or_pmid",
    "preferred_source_type",
    "local_text_path",
    "fetch_status",
    "fetch_priority",
    "notes",
]


def read_tsv(path: Path) -> List[Dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def write_tsv(path: Path, rows: Sequence[Dict[str, str]], fields: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def build_manifest_rows(
    catalog_rows: Sequence[Dict[str, str]],
    *,
    core_tools: Sequence[str] = DEFAULT_CORE_TOOLS,
    local_root: str = DEFAULT_LOCAL_ROOT,
) -> Tuple[List[Dict[str, str]], Dict[str, Any]]:
    catalog_by_tool: Dict[str, Dict[str, str]] = {}
    for row in catalog_rows:
        tool_name = clean(row.get("Tool"))
        if tool_name:
            catalog_by_tool.setdefault(norm(tool_name), row)

    manifest_rows: List[Dict[str, str]] = []
    missing_tools: List[str] = []
    skipped_no_github: List[str] = []
    for priority, requested_tool in enumerate(core_tools, start=1):
        catalog_row = catalog_by_tool.get(norm(requested_tool))
        if not catalog_row:
            missing_tools.append(requested_tool)
            continue
        tool_name = clean(catalog_row.get("Tool")) or requested_tool
        repo_url = clean(catalog_row.get("Code"))
        if "github.com/" not in repo_url.lower():
            skipped_no_github.append(tool_name)
            continue
        safe_tool = safe_slug(tool_name)
        record_id = f"CORE_DOCS_{safe_tool}_github_readme"
        manifest_rows.append(
            {
                "source_id": stable_source_id(tool_name, repo_url, "github_readme"),
                "evidence_kind": "docs",
                "tool_name": tool_name,
                "record_id": record_id,
                "source_title": f"{tool_name} official GitHub README",
                "source_url": repo_url,
                "doi_or_pmid": "",
                "preferred_source_type": "github_readme",
                "local_text_path": f"{local_root}/{safe_tool}_github_readme.txt",
                "fetch_status": "not_fetched",
                "fetch_priority": str(priority),
                "notes": (
                    "Source Coverage Sprint v2.1; retrieval-only source chunk; "
                    "does not promote formal evidence or recommendation support."
                ),
            }
        )
        docs_url = DEFAULT_OFFICIAL_DOCS_URLS.get(norm(tool_name))
        if docs_url:
            docs_record_id = f"CORE_DOCS_{safe_tool}_official_docs"
            manifest_rows.append(
                {
                    "source_id": stable_source_id(tool_name, docs_url, "official_docs_html"),
                    "evidence_kind": "docs",
                    "tool_name": tool_name,
                    "record_id": docs_record_id,
                    "source_title": f"{tool_name} official documentation homepage",
                    "source_url": docs_url,
                    "doi_or_pmid": "",
                    "preferred_source_type": "official_docs_html",
                    "local_text_path": f"{local_root}/{safe_tool}_official_docs.txt",
                    "fetch_status": "not_fetched",
                    "fetch_priority": str(priority),
                    "notes": (
                        "Source Coverage Sprint v2.1 official docs fallback; retrieval-only source chunk; "
                        "does not promote formal evidence or recommendation support."
                    ),
                }
            )

    summary = {
        "requested_core_tools": len(list(core_tools)),
        "manifest_rows": len(manifest_rows),
        "official_docs_fallback_rows": sum(
            1 for row in manifest_rows if row["preferred_source_type"] == "official_docs_html"
        ),
        "missing_tools": missing_tools,
        "skipped_no_github": skipped_no_github,
        "local_root": local_root,
        "policy": [
            "Core GitHub README text is source-bound evidence discovery material.",
            "README chunks cannot promote formal TSV evidence automatically.",
            "README chunks cannot change recommendation rank directly.",
        ],
    }
    return manifest_rows, summary


def stable_source_id(tool_name: str, url: str, source_type: str) -> str:
    digest = hashlib.sha1(f"{tool_name}|{url}|{source_type}".encode("utf-8")).hexdigest()[:12]
    return f"SRC_CORE_{digest}"


def safe_slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "_", clean(value)).strip("_")
    return slug or "unknown_tool"


def clean(value: object) -> str:
    return str(value or "").strip()


def norm(value: object) -> str:
    return clean(value).casefold()


def main() -> None:
    parser = argparse.ArgumentParser(description="Build source manifest rows for core tool README/docs coverage.")
    parser.add_argument("--tool-catalog", type=Path, default=DEFAULT_TOOL_CATALOG)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--summary-output", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument("--local-root", default=DEFAULT_LOCAL_ROOT)
    parser.add_argument("--core-tools", nargs="*", default=list(DEFAULT_CORE_TOOLS))
    args = parser.parse_args()

    rows, summary = build_manifest_rows(
        read_tsv(args.tool_catalog),
        core_tools=args.core_tools,
        local_root=args.local_root,
    )
    write_tsv(args.output, rows, MANIFEST_FIELDS)
    summary.update(
        {
            "tool_catalog": str(args.tool_catalog),
            "output": str(args.output),
            "summary_output": str(args.summary_output),
        }
    )
    args.summary_output.parent.mkdir(parents=True, exist_ok=True)
    args.summary_output.write_text(json.dumps(summary, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
