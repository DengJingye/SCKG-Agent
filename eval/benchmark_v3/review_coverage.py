#!/usr/bin/env python3
"""Validate human review sidecars and derive coverage; never modify input reviews.

python -m eval.benchmark_v3.review_coverage --scenarios PATH --reviews PATH
Optional --output PATH creates a NEW report (refuses overwrite).
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path

from eval.benchmark_v3 import run_lane_alignment_audit as lanes
from eval.benchmark_v3.coverage_review import SOURCES, audit_scenario


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenarios", type=Path, required=True)
    parser.add_argument("--reviews", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    scenarios = lanes.read_jsonl(args.scenarios)
    cells = lanes.read_jsonl(args.reviews)
    ids = [r["scenario_id"] for r in scenarios]
    if len(ids) != len(set(ids)) or any(c["scenario_id"] not in ids for c in cells):
        raise ValueError("duplicate scenarios or orphan coverage cells")
    source = lanes.load_and_verify_sources()
    snapshots = lanes.coverage_snapshot(lanes.lane_manifest(source))["sources"]
    inventories, _, _ = lanes.source_records(source)
    records = {s: {r["id"]: r for r in inventories[s]} for s in SOURCES}
    reports = []
    for scenario in scenarios:
        own = [c for c in cells if c["scenario_id"] == scenario["scenario_id"]]
        reports.append(
            {
                "scenario_id": scenario["scenario_id"],
                "coverage": audit_scenario(scenario, own, snapshots, records),
                "review_cells": own,
            }
        )
    if args.output:
        with args.output.open("x", encoding="utf-8") as stream:
            json.dump(reports, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
    print(
        json.dumps(
            {
                "scenarios": len(reports),
                "cells": len(cells),
                "signature_counts": dict(
                    Counter(
                        r["coverage"]["exact_signature"]
                        or r["coverage"]["audit_status"]
                        for r in reports
                    )
                ),
                "gold_created": False,
                "lane_runs": 0,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
