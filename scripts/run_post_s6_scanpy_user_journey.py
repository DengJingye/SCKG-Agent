#!/usr/bin/env python
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from execution.scanpy_synthetic_fixture import (
    SCANPY_SYNTHETIC_FIXTURE_VERSION,
    generate_scanpy_core_synthetic_fixture,
    load_scanpy_synthetic_manifest,
)
from execution.scanpy_user_journey import run_scanpy_synthetic_user_journey


def main() -> int:
    fixture_root = (
        PROJECT_ROOT
        / ".sckg_exec"
        / "fixtures"
        / "scanpy-core"
        / SCANPY_SYNTHETIC_FIXTURE_VERSION
    )
    fixture_path = fixture_root / "scanpy_core_synthetic_v1.h5ad"
    manifest_path = fixture_root / "fixture_manifest.json"
    if not fixture_path.is_file() or not manifest_path.is_file():
        fixture_path, manifest_path, _ = generate_scanpy_core_synthetic_fixture(
            fixture_root
        )
    manifest = load_scanpy_synthetic_manifest(manifest_path)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    journey_id = f"post-s6-scanpy-{stamp}"
    result = run_scanpy_synthetic_user_journey(
        journey_id=journey_id,
        fixture_path=fixture_path,
        fixture_manifest=manifest,
        work_root=(PROJECT_ROOT / ".sckg_exec" / "scanpy-user-journeys" / journey_id),
        package_root=(PROJECT_ROOT / ".sckg_exec" / "packages"),
    )
    summary_path = (
        PROJECT_ROOT
        / ".sckg_exec"
        / "scanpy-user-journeys"
        / journey_id
        / "summary.json"
    )
    summary_path.write_text(
        json.dumps(result.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result.model_dump(mode="json"), indent=2, sort_keys=True))
    checks = [
        result.source_unchanged,
        result.package_complete,
        result.package_hashes_valid,
        len(result.routes) == 2,
        all(route.validation_passed for route in result.routes),
        all(route.lineage_hashes_valid for route in result.routes),
        all(route.annotation_confirmation_required for route in result.routes),
        not any(route.final_annotation_present for route in result.routes),
    ]
    return 0 if all(checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
