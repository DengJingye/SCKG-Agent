#!/usr/bin/env python
from __future__ import annotations

import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from core.tool_contract_registry import ToolContractRegistry
from execution.annotation_reference_registry import AnnotationReferenceRegistry
from execution.environment_registry import EnvironmentRegistry
from execution.runtime_pack_manager import RuntimePackManager
from execution.wrapper_registry import WrapperRegistry


TOOLS = (
    {
        "tool_name": "CellTypist",
        "tool_version": "1.7.1",
        "pack_id": "annotation-python",
        "environment_id": "annotation-python",
        "wrapper_id": "celltypist_v1_7_1",
        "reference_id": "celltypist-immune-all-low-v1",
    },
    {
        "tool_name": "SingleR",
        "tool_version": "2.14.0",
        "pack_id": "annotation-r",
        "environment_id": "annotation-r",
        "wrapper_id": "singler_v2_14_0",
        "reference_id": "singler-immune-reference-v1",
    },
)


def main() -> int:
    token = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report_root = PROJECT_ROOT / ".sckg_exec" / "reports" / f"annotation-{token}"
    report_root.mkdir(parents=True, exist_ok=False)
    manager = RuntimePackManager(
        home=report_root / "runtime-home",
        allow_legacy_environments=False,
    )
    environments = EnvironmentRegistry()
    contracts = ToolContractRegistry(environment_registry=environments)
    wrappers = WrapperRegistry()
    references = AnnotationReferenceRegistry()
    tool_results = []
    all_blockers: list[str] = []

    for spec in TOOLS:
        contract = contracts.load(spec["tool_name"], spec["tool_version"])
        environment = environments.get(spec["environment_id"])
        pack_probe = manager.probe(spec["pack_id"])
        install_plan = manager.create_plan(
            pack_id=spec["pack_id"],
            user_id="maintainer-readiness-check",
        )
        planning_gate = contracts.planning_gate(contract)
        execution_gate = contracts.execution_gate(contract)
        reference_status = "missing"
        reference_issues: list[str] = []
        try:
            reference = references.get(
                spec["reference_id"],
                expected_tool=spec["tool_name"],
            )
            reference_issues = references.validate_assets(reference)
            reference_status = "verified" if not reference_issues else "invalid"
        except (KeyError, ValueError) as exc:
            reference_issues = [f"{type(exc).__name__}:{exc}"]
        blockers = [
            *install_plan.blockers,
            *(["runtime_pack_not_ready"] if not pack_probe.ready else []),
            *(["reference_pack_not_ready"] if reference_status != "verified" else []),
            *execution_gate.reasons,
        ]
        all_blockers.extend(f"{spec['tool_name']}:{item}" for item in blockers)
        tool_results.append(
            {
                **spec,
                "contract_version": contract.contract_version,
                "planning_gate_allowed": planning_gate.allowed,
                "planning_gate_reasons": planning_gate.reasons,
                "execution_gate_allowed": execution_gate.allowed,
                "execution_gate_reasons": execution_gate.reasons,
                "contract_enabled_for_execution": contract.enabled_for_execution,
                "environment_status": environment.qualification_status,
                "environment_enabled_for_execution": environment.enabled_for_execution,
                "runtime_pack_state": pack_probe.state,
                "runtime_pack_manifest_digest": pack_probe.manifest_digest,
                "runtime_pack_install_blockers": install_plan.blockers,
                "projected_download_bytes": install_plan.estimated_download_size_bytes,
                "projected_install_bytes": install_plan.estimated_installed_size_bytes,
                "disk_free_bytes": install_plan.disk_free_bytes,
                "reference_status": reference_status,
                "reference_issues": reference_issues,
                "wrapper_runtime_ready": wrappers.get(
                    spec["wrapper_id"]
                ).is_runtime_ready(),
                "planned_configurations": 2,
                "planned_seeds_per_configuration": 3,
                "planned_initial_runs": 6,
                "actual_runs": 0,
            }
        )

    report = {
        "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "BLOCKED" if all_blockers else "READY_FOR_APPROVAL",
        "task": "cell_type_annotation",
        "disk": {
            "free_bytes": shutil.disk_usage(PROJECT_ROOT).free,
            "required_post_install_reserve_bytes": 6 * 1024**3,
            "cleanup_scope": "rebuildable_conda_cache_only",
        },
        "tools": tool_results,
        "planned_initial_runs": 12,
        "actual_runs": 0,
        "execution_request_count": 0,
        "user_data_used": False,
        "external_model_calls": 0,
        "blockers": sorted(set(all_blockers)),
        "safety_assertions": {
            "unapproved_install_started": False,
            "unapproved_execution_started": False,
            "network_download_during_execution": False,
            "enabled_for_execution_changed": False,
        },
    }
    report_path = report_root / "annotation_qualification_readiness.json"
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({**report, "report_path": str(report_path)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
