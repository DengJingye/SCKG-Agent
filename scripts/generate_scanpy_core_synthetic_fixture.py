#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from execution.scanpy_synthetic_fixture import (
    SCANPY_SYNTHETIC_FIXTURE_SEED,
    SCANPY_SYNTHETIC_FIXTURE_VERSION,
    generate_scanpy_core_synthetic_fixture,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate the versioned Scanpy Core structured synthetic fixture."
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=(
            PROJECT_ROOT
            / ".sckg_exec"
            / "fixtures"
            / "scanpy-core"
            / SCANPY_SYNTHETIC_FIXTURE_VERSION
        ),
    )
    parser.add_argument("--seed", type=int, default=SCANPY_SYNTHETIC_FIXTURE_SEED)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    h5ad_path, manifest_path, manifest = generate_scanpy_core_synthetic_fixture(
        args.output_dir,
        seed=args.seed,
        overwrite=args.overwrite,
    )
    print(
        json.dumps(
            {
                "fixture_path": str(h5ad_path),
                "manifest_path": str(manifest_path),
                "shape": manifest.shape,
                "seed": manifest.seed,
                "sha256": manifest.h5ad_sha256,
                "scientific_claim_allowed": manifest.scientific_claim_allowed,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
