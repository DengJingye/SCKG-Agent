from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from engine.algorithm_representation_v2 import (
    DEFAULT_AUDIT_TSV,
    DEFAULT_LEGACY_AUDIT_PATH,
    DEFAULT_PROFILE_PATH,
    DEFAULT_REPRESENTATIONS_PATH,
    DEFAULT_SUMMARY_JSON,
    DEFAULT_TOOL_CATALOG,
    build_representations,
    build_summary,
    load_chunks_if_exists,
    load_vectors_if_exists,
    read_tsv,
    write_representation_audit,
    write_representations,
)
from engine.evidence_discovery_index import CHUNKS_PATH, VECTORS_PATH, source_manifest_chunks


DEFAULT_SOURCE_MANIFEST = PROJECT_ROOT / "data" / "evidence_candidates" / "evidence_pdf_source_manifest_full.tsv"


def main() -> None:
    parser = argparse.ArgumentParser(description="Build source-bound Algorithm Representation v2 JSONL.")
    parser.add_argument("--tool-catalog", type=Path, default=DEFAULT_TOOL_CATALOG)
    parser.add_argument("--profile-tsv", type=Path, default=DEFAULT_PROFILE_PATH)
    parser.add_argument("--legacy-audit-tsv", type=Path, default=DEFAULT_LEGACY_AUDIT_PATH)
    parser.add_argument("--chunks-path", type=Path, default=CHUNKS_PATH)
    parser.add_argument("--vectors-path", type=Path, default=VECTORS_PATH)
    parser.add_argument(
        "--source-manifest",
        action="append",
        type=Path,
        default=None,
        help=(
            "Optional source manifest; source chunks are added to the representation build if present. "
            "May be passed multiple times. Defaults to the PDF source manifest when omitted."
        ),
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_REPRESENTATIONS_PATH)
    parser.add_argument("--audit-tsv", type=Path, default=DEFAULT_AUDIT_TSV)
    parser.add_argument("--summary-json", type=Path, default=DEFAULT_SUMMARY_JSON)
    args = parser.parse_args()

    chunks = load_chunks_if_exists(args.chunks_path)
    source_manifests = args.source_manifest or [DEFAULT_SOURCE_MANIFEST]
    source_manifest_summaries = []
    for source_manifest in source_manifests:
        if not source_manifest:
            continue
        chunks_for_manifest = []
        by_id = {chunk.chunk_id: chunk for chunk in chunks}
        for chunk in source_manifest_chunks(source_manifest):
            by_id[chunk.chunk_id] = chunk
            chunks_for_manifest.append(chunk)
        chunks = list(by_id.values())
        source_manifest_summaries.append(
            {
                "path": str(source_manifest),
                "chunks": len(chunks_for_manifest),
                "exists": source_manifest.exists(),
            }
        )
    representations = build_representations(
        catalog_rows=read_tsv(args.tool_catalog),
        chunks=chunks,
        vector_by_chunk=load_vectors_if_exists(args.vectors_path),
        profile_rows=read_tsv(args.profile_tsv),
        legacy_audit_rows=read_tsv(args.legacy_audit_tsv),
    )
    write_representations(representations, args.output)
    write_representation_audit(representations, args.audit_tsv)
    summary = build_summary(
        representations,
        output_path=args.output,
        audit_path=args.audit_tsv,
        chunks_path=args.chunks_path,
        vectors_path=args.vectors_path,
    )
    summary["source_manifests"] = source_manifest_summaries
    args.summary_json.parent.mkdir(parents=True, exist_ok=True)
    args.summary_json.write_text(json.dumps(summary, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
