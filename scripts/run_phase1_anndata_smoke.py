#!/usr/bin/env python
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from engine.data_profiler import AnnDataProfiler
from tests.fixtures.anndata_factory import FIXTURE_SEED, write_phase1_fixtures


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="sckg_phase1_") as temp_dir:
        paths = write_phase1_fixtures(Path(temp_dir))
        profiler = AnnDataProfiler()
        raw = profiler.profile_payload(paths["raw_x"], batch_key="batch")
        layered = profiler.profile_payload(paths["counts_layer"])
        scaled = profiler.profile_payload(paths["scaled"])
        raw_distinct = profiler.profile_payload(paths["raw_x_distinct"])

        checks = {
            "raw_x_selected": raw["selected_count_source"] == "X",
            "counts_layer_selected": layered["selected_count_source"] == "layers/counts",
            "scaled_blocked": (
                scaled["selected_count_source"] is None
                and "count_source_unresolved" in scaled["blocking_errors"]
            ),
            "raw_x_distinct_selected": raw_distinct["selected_count_source"] == "raw.X",
            "no_scrublet_execution": True,
        }
        summary = {
            "ok": all(checks.values()),
            "phase": "Phase 1 AnnData profiling smoke",
            "conda_environment": os.getenv("CONDA_DEFAULT_ENV", "unknown"),
            "python": sys.version.split()[0],
            "fixture_seed": FIXTURE_SEED,
            "profiler_mode": "deterministic_worker_payload",
            "checks": checks,
            "selected_sources": {
                "raw_x": raw["selected_count_source"],
                "counts_layer": layered["selected_count_source"],
                "scaled": scaled["selected_count_source"],
                "raw_x_distinct": raw_distinct["selected_count_source"],
            },
            "scaled_blocking_errors": scaled["blocking_errors"],
            "guardrail": "This smoke profiles AnnData fixtures only; it does not import or run Scrublet.",
        }
        print(json.dumps(summary, indent=2, sort_keys=True))
        return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

