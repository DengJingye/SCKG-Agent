#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from ingestion.scientific_documents import ScientificDocumentIngestionService
from ingestion.scientific_documents.reporting import summary_payload, write_regression_artifacts


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one hash-gated scientific PDF regression ingestion.")
    parser.add_argument("--pdf", required=True, type=Path)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()

    result = ScientificDocumentIngestionService(REPOSITORY_ROOT).run_pdf(
        args.pdf,
        expected_sha256=args.expected_sha256,
    )
    write_regression_artifacts(result, args.output_dir)
    summary = summary_payload(result)
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2))
    return 0 if summary["checks"]["soupx_regression"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
