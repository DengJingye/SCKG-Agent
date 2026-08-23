from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from engine.evidence_discovery_index import (
    CATALOG_CHUNKS_PATH,
    CHUNKS_PATH,
    VECTORS_PATH,
    build_formal_tsv_chunks,
    catalog_tool_chunks,
    document_chunks,
    source_manifest_chunks,
    write_indexes,
    write_catalog_chunks,
)


def discover_documents(paths: list[Path]) -> list[Path]:
    discovered: list[Path] = []
    for path in paths:
        if path.is_file():
            discovered.append(path)
            continue
        if path.is_dir():
            for pattern in ("*.txt", "*.md"):
                discovered.extend(sorted(path.rglob(pattern)))
    return discovered


def main() -> None:
    parser = argparse.ArgumentParser(description="Build local EvidenceChunk JSONL indexes.")
    parser.add_argument("--chunks-output", type=Path, default=CHUNKS_PATH)
    parser.add_argument("--vectors-output", type=Path, default=VECTORS_PATH)
    parser.add_argument("--catalog-chunks-output", type=Path, default=CATALOG_CHUNKS_PATH)
    parser.add_argument(
        "--catalog-snapshot",
        type=Path,
        default=PROJECT_ROOT / "data" / "catalog" / "scrna_tools_snapshot.json",
    )
    parser.add_argument(
        "--documents",
        nargs="*",
        type=Path,
        default=[],
        help="Optional txt/md files or directories to index as retrieval-only document chunks.",
    )
    parser.add_argument(
        "--source-manifest",
        action="append",
        type=Path,
        default=[],
        help=(
            "Optional Evidence Recovery source manifest with local_text_path entries. "
            "May be passed multiple times."
        ),
    )
    parser.add_argument(
        "--with-embeddings",
        action="store_true",
        help="Call the configured embedding API and write dense vectors.",
    )
    args = parser.parse_args()

    chunks = build_formal_tsv_chunks()
    documents = discover_documents(args.documents)
    if documents:
        chunks.extend(document_chunks(documents))
    manifest_chunks = []
    source_manifest_summaries = []
    for manifest in args.source_manifest:
        chunks_for_manifest = source_manifest_chunks(manifest)
        manifest_chunks.extend(chunks_for_manifest)
        chunks.extend(chunks_for_manifest)
        source_manifest_summaries.append(
            {
                "path": str(manifest),
                "chunks": len(chunks_for_manifest),
                "exists": manifest.exists(),
            }
        )
    summary = write_indexes(
        chunks,
        chunks_path=args.chunks_output,
        vectors_path=args.vectors_output,
        with_embeddings=args.with_embeddings,
    )
    catalog_chunks = catalog_tool_chunks(args.catalog_snapshot)
    summary.update(write_catalog_chunks(catalog_chunks, args.catalog_chunks_output))
    summary["documents"] = len(documents)
    summary["source_manifest_chunks"] = len(manifest_chunks)
    summary["source_manifests"] = source_manifest_summaries
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
