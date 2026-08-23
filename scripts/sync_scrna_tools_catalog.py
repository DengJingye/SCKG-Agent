from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data_pipeline.scrna_tools_catalog import (
    CATALOG_URL,
    build_catalog_audit,
    fetch_catalog,
    load_catalog,
    write_catalog_snapshot,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Audit or synchronize the official scRNA-tools JSON catalog."
    )
    parser.add_argument("--source-json", type=Path, help="Use a downloaded tools.json file.")
    parser.add_argument("--source-url", default=CATALOG_URL)
    parser.add_argument("--apply", action="store_true", help="Write snapshot and compatibility TSV.")
    args = parser.parse_args()

    if args.source_json:
        rows, source_sha256 = load_catalog(args.source_json)
        source_label = str(args.source_json)
    else:
        rows, source_sha256 = fetch_catalog(args.source_url)
        source_label = args.source_url

    compatibility_tsv = PROJECT_ROOT / "data" / "scrna_tools.tsv"
    snapshot_path = PROJECT_ROOT / "data" / "catalog" / "scrna_tools_snapshot.json"
    audit_path = PROJECT_ROOT / "data" / "evidence_candidates" / "scrna_tools_catalog_audit.json"
    if args.apply:
        result = write_catalog_snapshot(
            rows,
            snapshot_path=snapshot_path,
            compatibility_tsv=compatibility_tsv,
            audit_path=audit_path,
            source_sha256=source_sha256,
            source_url=args.source_url,
        )
        result["snapshot_path"] = str(snapshot_path.relative_to(PROJECT_ROOT))
        result["compatibility_tsv"] = str(compatibility_tsv.relative_to(PROJECT_ROOT))
        result["audit_path"] = str(audit_path.relative_to(PROJECT_ROOT))
    else:
        result = build_catalog_audit(
            rows,
            current_tsv=compatibility_tsv,
            source_sha256=source_sha256,
            source_url=args.source_url,
        )
    result["source"] = source_label
    result["applied"] = args.apply
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
