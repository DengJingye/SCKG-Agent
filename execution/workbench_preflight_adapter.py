"""Explicit, observation-only bridge from the isolated workbench to legacy execution.

Importing this adapter does not import the old execution stack. Its observation
functions are called only by an explicit readiness request, never app startup.
No executor, provisioning manager, permission service or analysis is instantiated.
Explicit runtime observation uses the existing manager's no-write discovery mode.
"""
from __future__ import annotations

import importlib


def control_plane_observation() -> dict:
    try:
        importlib.import_module("execution.local_controlled_executor")
        importlib.import_module("execution.preview_execution_service")
        return {"status": "passed", "detail": "Existing executor and preview service import; no execution attempted."}
    except Exception as exc:
        return {"status": "blocked", "detail": f"{type(exc).__name__}: {exc}",
                "blocker": "control_plane_import_failed"}


def runtime_observation(*, pack_id="doublet-python", home=None, registry=None,
                        allow_legacy_environments=True) -> dict:
    """Observe signed installed state only; never import the runtime or install it."""
    import os
    from execution.runtime_pack_resolver import RuntimePackResolver
    resolver = RuntimePackResolver.for_read_only_discovery(home=home, registry=registry,
        allow_legacy_environments=allow_legacy_environments)
    probe = resolver.manager.probe(pack_id)
    return {
        "schema_version": "workbench-runtime-discovery-v1", "pack_id": pack_id,
        "state": probe.state, "source": probe.source,
        "manifest_digest": probe.manifest_digest, "environment_id": probe.environment_id,
        "resolved_runtime_executable": probe.executable_paths.get("python") if probe.ready else None,
        "warnings": probe.warnings,
        "home_source": "explicit_server_home" if home is not None else "SCKG_HOME" if os.environ.get("SCKG_HOME") else "default_user_home",
        "read_only": True, "directories_created": False, "approvals_created": False,
        "runtime_imports_verified": False, "execution_attempted": False,
        "discovery_is_execution_readiness": False,
    }


def legacy_observation() -> dict:
    """Retain contract/legacy fields and add managed-first read-only discovery."""
    from core.tool_contract_registry import ToolContractRegistry
    from execution.environment_registry import EnvironmentRegistry
    from execution.execution_policy import ExecutionPolicy
    from execution.runtime_pack_registry import RuntimePackRegistry

    environments = EnvironmentRegistry()
    contracts = ToolContractRegistry(environment_registry=environments)
    contract = contracts.load("Scrublet", "0.2.3")
    gate = contracts.execution_gate(contract)
    registry = RuntimePackRegistry()
    manifest = registry.get("doublet-python")
    manifest_warnings = registry.validate_assets(manifest)
    discovery = runtime_observation(pack_id=manifest.pack_id, registry=registry)
    executable = discovery["resolved_runtime_executable"]
    return {"policy_mode": ExecutionPolicy().mode.value,
            "contract_id": contract.contract_id, "contract_version": contract.contract_version,
            "contract_gate_passed": gate.allowed, "contract_gate_reasons": gate.reasons,
            "wrapper_id": contract.wrapper_id, "environment_id": contract.environment_id,
            "runtime_pack_id": manifest.pack_id, "runtime_manifest_digest": manifest.manifest_digest,
            "runtime_manifest_warnings": manifest_warnings,
            "legacy_runtime_executable": executable if discovery["source"] == "legacy_conda_environment" else None,
            "resolved_runtime_executable": executable,
            "runtime_source": discovery["source"], "runtime_discovery": discovery,
            "runtime_imports_verified": False,
            "managed_runtime_resolution": "observed_ready" if discovery["source"] == "managed_pack" else "not_selected_or_unavailable",
            "runtime_existence_is_execution_readiness": False}

