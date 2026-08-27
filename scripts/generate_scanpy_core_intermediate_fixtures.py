from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from execution.scanpy_synthetic_fixture import (  # noqa: E402
    derive_scanpy_core_intermediate_fixtures,
    load_scanpy_synthetic_manifest,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--fixture-manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    manifest_path, manifest = derive_scanpy_core_intermediate_fixtures(
        args.fixture,
        load_scanpy_synthetic_manifest(args.fixture_manifest),
        args.output_dir,
        overwrite=args.overwrite,
    )
    print(
        json.dumps(
            {
                "manifest_path": str(manifest_path),
                "source_hash": manifest.source_h5ad_sha256,
                "states": [item.model_dump(mode="json") for item in manifest.states],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
