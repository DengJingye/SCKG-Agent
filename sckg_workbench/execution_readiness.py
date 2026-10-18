"""Fail-closed Scrublet readiness, without provisioning or executing anything.

The older executor remains the only supported execution route. This report does
not create its permissions, infer count provenance from numeric samples, or
convert a workbench dataset into a maintainer qualification fixture.
"""
from __future__ import annotations

import importlib

from .datasets import DatasetService, _fingerprint, _local_path, _open_local
from .storage import Workspace, utcnow


def _control_plane_observation() -> dict:
    try:
        adapter = importlib.import_module("execution.workbench_preflight_adapter")
        return adapter.control_plane_observation()
    except Exception as exc:
        return {"status": "blocked", "detail": f"{type(exc).__name__}: {exc}",
                "blocker": "control_plane_import_failed"}


def _legacy_observation() -> dict:
    adapter = importlib.import_module("execution.workbench_preflight_adapter")
    return adapter.legacy_observation()


class ScrubletReadinessService:
    def __init__(self, workspace: Workspace):
        self.datasets = DatasetService(workspace)

    def preflight(self, asset_id: str | None = None, *, profile_id: str | None = None) -> dict:
        checks = []

        def add(check_id, status, detail, blocker=None):
            checks.append({"check_id": check_id, "status": status, "detail": detail,
                           "blocker": blocker})

        control = _control_plane_observation()
        add("control_plane", control["status"], control["detail"], control.get("blocker"))
        legacy = {}
        try:
            legacy = _legacy_observation()
            add("legacy_contract", "passed" if legacy["contract_gate_passed"] else "blocked",
                "Legacy contract checks: " + (", ".join(legacy["contract_gate_reasons"]) or "passed"),
                None if legacy["contract_gate_passed"] else "legacy_contract_gate_failed")
            add("runtime_manifest", "passed" if not legacy["runtime_manifest_warnings"] else "blocked",
                "Signed runtime manifest and lock assets checked; this is not a fresh runtime qualification.",
                "runtime_manifest_invalid" if legacy["runtime_manifest_warnings"] else None)
            executable = legacy.get("resolved_runtime_executable", legacy.get("legacy_runtime_executable"))
            source = legacy.get("runtime_source") or ("legacy_conda_environment" if executable else "unavailable")
            add("runtime_entrypoint", "observed" if executable else "unknown",
                f"Existing {source} executable observed through read-only discovery; worker imports and execution not tested."
                if executable else "No compatible signed managed or permitted legacy entrypoint observed; no installation attempted.")
            add("policy", "blocked", "New workbench has no enabled, bound execution policy; existing default is " + legacy["policy_mode"],
                "execution_policy_disabled")
        except Exception as exc:
            add("legacy_registry", "blocked", f"{type(exc).__name__}: {exc}", "legacy_registry_unavailable")
            add("policy", "blocked", "No verified execution policy is bound.", "execution_policy_unverified")

        asset = self.datasets.get_asset(asset_id) if asset_id else None
        profile = None
        if asset is None:
            add("dataset", "blocked", "Select an existing workbench dataset asset.", "dataset_asset_missing")
        else:
            try:
                source = _local_path(asset["path"])
                with _open_local(source) as (handle, signature):
                    fingerprint = _fingerprint(handle, signature["size"])
                    if signature != asset["stat_signature"] or fingerprint != asset["bounded_fingerprint"]:
                        raise ValueError("dataset no longer matches its registered version")
                add("dataset", "passed", "Current stat and bounded fingerprint match registration; no whole-file scan.")
            except (OSError, ValueError) as exc:
                add("dataset", "blocked", str(exc), "dataset_changed_or_unreadable")
            if profile_id is not None:
                profile = self.datasets.get_profile(profile_id)
            else:
                profiles = self.datasets.list_profiles(asset["asset_id"])
                profile = profiles[-1] if profiles else None
            if profile and profile.get("asset_id") != asset["asset_id"]:
                profile = None
                add("profile_binding", "blocked", "Profile belongs to a different asset.", "dataset_profile_binding_mismatch")
            if profile:
                add("bounded_profile", "observed", "Bounded measurements are available; they do not authorize raw-count execution.")
                dimensions = profile["profile"]["dimensions"]
                if min(dimensions.get("n_obs", 0), dimensions.get("n_vars", 0)) <= 0:
                    add("nonempty_matrix", "blocked", "Execution requires a nonempty matrix.", "empty_dataset")
            else:
                add("bounded_profile", "blocked", "Create or select a profile for this dataset.", "dataset_profile_missing")

        add("raw_count_provenance", "blocked",
            "Count origin, matrix choice and required full/preview validation are not bound. Integer-valued prefixes, a counts layer name or .raw alone cannot establish untransformed counts.",
            "raw_count_provenance_unverified")
        add("data_access_grant", "blocked", "No old DataRegistry identity and validated data-access grant are bound to this asset.",
            "data_registry_and_access_grant_not_bound")
        add("preview_lineage", "blocked", "A bounded representative preview, exact parameters and notebook lineage have not been prepared through the governed service.",
            "preview_and_parameter_lineage_missing")
        add("execution_approval", "blocked", "No exact plan-specific approval and local-user allowance have been validated or consumed.",
            "execution_approval_and_allowlist_not_bound")
        add("workbench_adapter", "observed", "AnalysisService provides an explicitly authorized, small-data preview bridge to the existing executor. This independent read-only preflight has not bound its input declaration, task-specific identity or permissions.")
        return {"schema_version": "sckg-scrublet-readiness-v1", "checked_at": utcnow(),
                "capability_id": "scrublet_doublet_detection", "tool_version": "0.2.3",
                "status": "blocked", "ready": False,
                "asset_id": asset_id, "profile_id": profile["profile_id"] if profile else profile_id,
                "checks": checks, "blockers": sorted({c["blocker"] for c in checks if c["blocker"]}),
                "legacy": legacy, "execution_attempted": False, "raw_data_modified": False,
                "outbound_attempted": False, "approval_created": False,
                "scientific_claim_allowed": False,
                "next_steps": [
                    "Repair or select a verified control-plane environment without changing execution policy.",
                    "Re-run the existing temporary synthetic qualification through its existing router/executor and validator.",
                    "Select a small registered asset and explicitly supply X-count provenance and the expected doublet rate in the research workspace.",
                    "An authorized AnalysisService task binds the full source hash, preview, exact parameters and local-request permissions through the existing executor; retain logs, cancellation and output validation."]}
