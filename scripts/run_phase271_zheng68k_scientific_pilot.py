#!/usr/bin/env python
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from execution.annotation_reference_registry import AnnotationReferenceRegistry
from execution.runtime_pack_manager import RuntimePackManager


DATASET_ROOT = PROJECT_ROOT / ".sckg_exec" / "datasets" / "Zheng68K"
EXPECTED_ASSETS = {
    "dataset": DATASET_ROOT / "processed" / "zheng68k.h5ad",
    "dataset_manifest": DATASET_ROOT / "dataset_manifest.json",
    "label_mapping": DATASET_ROOT / "label_mapping.json",
    "split_manifest": DATASET_ROOT / "split_manifest.json",
}
REFERENCES = (
    ("CellTypist", "celltypist-immune-all-low-v1"),
    ("SingleR", "singler-immune-reference-v1"),
)


def main() -> int:
    token = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report_root = PROJECT_ROOT / ".sckg_exec" / "reports" / f"zheng68k-{token}"
    report_root.mkdir(parents=True, exist_ok=False)
    blockers = [
        f"missing_{name}:{path.name}"
        for name, path in EXPECTED_ASSETS.items()
        if not path.is_file()
    ]
    references = AnnotationReferenceRegistry()
    reference_state = {}
    for tool_name, reference_id in REFERENCES:
        try:
            manifest = references.get(reference_id, expected_tool=tool_name)
            issues = references.validate_assets(manifest)
        except (KeyError, ValueError) as exc:
            issues = [f"{type(exc).__name__}:{exc}"]
        reference_state[tool_name] = {
            "reference_id": reference_id,
            "issues": issues,
            "ready": not issues,
        }
        blockers.extend(f"{tool_name}:{issue}" for issue in issues)

    manager = RuntimePackManager(
        home=report_root / "runtime-home",
        allow_legacy_environments=False,
    )
    runtime_state = {
        pack_id: manager.probe(pack_id).model_dump(mode="json")
        for pack_id in ("annotation-python", "annotation-r")
    }
    for pack_id, state in runtime_state.items():
        if state["state"] != "ready":
            blockers.append(f"{pack_id}:runtime_pack_not_ready")

    report = {
        "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "BLOCKED" if blockers else "READY_FOR_MAINTAINER_APPROVAL",
        "dataset": "Zheng68K",
        "dataset_assets": {
            name: {"present": path.is_file(), "path_redacted": f".../{path.name}"}
            for name, path in EXPECTED_ASSETS.items()
        },
        "reference_state": reference_state,
        "runtime_state": runtime_state,
        "development_run_count": 0,
        "evaluation_run_count": 0,
        "execution_request_count": 0,
        "metric_authority": "scientific_pilot_metric",
        "bootstrap_iterations_planned": 500,
        "user_data_used": False,
        "evaluation_labels_modified": False,
        "enabled_for_execution_changed": False,
        "blockers": sorted(set(blockers)),
    }
    report_path = report_root / "zheng68k_scientific_pilot_readiness.json"
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({**report, "report_path": str(report_path)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
