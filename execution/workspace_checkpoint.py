from __future__ import annotations

import hashlib
import json
from pathlib import Path

from core.research_workspace_models import (
    DataAssetProfile,
    NotebookShadowBundle,
    PreviewLineageSnapshot,
    PreviewResultIntegrity,
    PreviewRunResult,
    RepresentativePreviewManifest,
    WorkspaceCheckpointNode,
    WorkspaceCheckpointReport,
)
from core.tool_contract_registry import ToolContractRegistry
from execution.approval_service import ApprovalService
from execution.data_registry import DataRegistry
from execution.environment_registry import EnvironmentRegistry
from execution.notebook_shadow import scrublet_step_contract
from execution.research_workspace_service import ResearchWorkspaceService


_STAGES = ("source", "profile", "preview", "notebook", "approval", "result")
_ACTIONS = {
    "source": "Re-authorize the local artifact and rebuild its backed profile.",
    "profile": "Rebuild the backed DataProfile before creating another Preview.",
    "preview": "Build a new representative Preview from the current profile.",
    "notebook": "Recompile the governed Notebook and review its parameters.",
    "approval": "Create a new plan-specific approval for the current lineage.",
    "result": "Run the validated Preview again and inspect the new ValidationResult.",
}


class WorkspaceCheckpointService:
    """Derive freshness from persisted lineage without executing any workload."""

    def __init__(
        self,
        *,
        data_registry: DataRegistry,
        approval_service: ApprovalService,
        research_workspace: ResearchWorkspaceService,
        contract_registry: ToolContractRegistry,
        environment_registry: EnvironmentRegistry,
    ) -> None:
        self.data_registry = data_registry
        self.approval_service = approval_service
        self.research_workspace = research_workspace
        self.contract_registry = contract_registry
        self.environment_registry = environment_registry

    def capture_lineage(
        self,
        *,
        profile: DataAssetProfile,
        preview: RepresentativePreviewManifest,
        notebook: NotebookShadowBundle,
        approval_fingerprint: str,
    ) -> PreviewLineageSnapshot:
        contract = self.contract_registry.load("Scrublet", "0.2.3")
        environment = self.environment_registry.get(contract.environment_id)
        return PreviewLineageSnapshot(
            source_hash=profile.source_hash,
            profile_id=profile.profile_id,
            preview_id=preview.preview_id,
            preview_hash=preview.preview_hash,
            notebook_id=notebook.notebook_id,
            notebook_hash=notebook.notebook_hash,
            parameter_hash=notebook.parameter_hash,
            step_contract_id=notebook.step_contract_id,
            step_contract_version=notebook.step_contract_version,
            step_template_digest=notebook.step_template_digest,
            tool_contract_id=contract.contract_id,
            tool_contract_version=contract.contract_version,
            tool_contract_digest=_model_digest(contract),
            environment_id=environment.environment_id,
            environment_digest=_model_digest(environment),
            approval_fingerprint=approval_fingerprint,
        )

    def inspect_active(
        self,
        *,
        user_id: str,
        artifact_id: str,
        profile: DataAssetProfile | None = None,
        preview: RepresentativePreviewManifest | None = None,
        notebook: NotebookShadowBundle | None = None,
        approval_id: str | None = None,
        result: PreviewRunResult | None = None,
        result_integrity: PreviewResultIntegrity | None = None,
    ) -> WorkspaceCheckpointReport:
        expected_source = (
            profile.source_hash
            if profile is not None
            else (result.lineage.source_hash if result is not None else None)
        )
        nodes: list[WorkspaceCheckpointNode] = []
        source_node = self._source_node(user_id, artifact_id, expected_source)
        nodes.append(source_node)
        nodes.append(
            self._profile_node(profile, expected_source, source_node.status)
        )
        nodes.append(
            self._preview_node(
                user_id,
                artifact_id,
                preview,
                profile,
                nodes[-1].status,
            )
        )
        nodes.append(
            self._notebook_node(
                user_id,
                artifact_id,
                notebook,
                profile,
                preview,
                nodes[-1].status,
            )
        )
        nodes.append(
            self._approval_node(
                approval_id=approval_id,
                result=result,
                upstream_status=nodes[-1].status,
            )
        )
        nodes.append(
            self._result_node(
                result=result,
                integrity=result_integrity,
                active_notebook=notebook,
                upstream_status=nodes[-1].status,
            )
        )
        return _report(user_id, artifact_id, nodes)

    def inspect_result(
        self,
        *,
        result: PreviewRunResult,
        integrity: PreviewResultIntegrity,
    ) -> WorkspaceCheckpointReport:
        if result.lineage is None:
            nodes = [
                _node("source", "WAITING", ["legacy_result_lineage_missing"]),
                *[
                    _node(
                        stage,
                        "STALE",
                        ["legacy_result_lineage_missing"],
                        propagated=True,
                    )
                    for stage in _STAGES[1:]
                ],
            ]
            return WorkspaceCheckpointReport(
                user_id=result.user_id,
                artifact_id=result.artifact_id,
                overall_status="STALE",
                nodes=nodes,
                first_invalid_stage="source",
                rebuild_from="source",
                user_action=(
                    "This legacy Preview result lacks a complete lineage snapshot; "
                    "re-authorize the artifact and rebuild from DataProfile."
                ),
            )
        profile = self._load_profile(result.user_id, result.artifact_id, result.lineage)
        preview = self._load_preview(result.user_id, result.artifact_id, result.lineage)
        notebook = self._load_notebook(result.user_id, result.artifact_id, result.lineage)
        return self.inspect_active(
            user_id=result.user_id,
            artifact_id=result.artifact_id,
            profile=profile,
            preview=preview,
            notebook=notebook,
            approval_id=result.execution_run.approval_id,
            result=result,
            result_integrity=integrity,
        )

    def _source_node(
        self, user_id: str, artifact_id: str, expected_hash: str | None
    ) -> WorkspaceCheckpointNode:
        try:
            record = self.data_registry.get(artifact_id, user_id=user_id)
            current_hash = self.data_registry.current_hash(
                artifact_id, user_id=user_id
            )
        except (KeyError, FileNotFoundError) as exc:
            return _node("source", "FAILED", [str(exc)], recorded=expected_hash)
        if current_hash is None:
            return _node(
                "source",
                "WAITING",
                ["artifact_path_reauthorization_required"],
                recorded=expected_hash or record.sha256,
            )
        recorded = expected_hash or record.sha256
        if current_hash != record.sha256 or current_hash != recorded:
            return _node(
                "source",
                "STALE",
                ["registered_source_hash_changed"],
                recorded=recorded,
                current=current_hash,
            )
        return _node("source", "CURRENT", recorded=recorded, current=current_hash)

    def _profile_node(
        self,
        profile: DataAssetProfile | None,
        expected_source: str | None,
        upstream_status: str,
    ) -> WorkspaceCheckpointNode:
        propagated = _propagated("profile", upstream_status)
        if propagated:
            return propagated
        if profile is None:
            return _node("profile", "MISSING", ["data_profile_missing"])
        if expected_source and profile.source_hash != expected_source:
            return _node(
                "profile",
                "STALE",
                ["profile_source_hash_mismatch"],
                recorded=profile.source_hash,
                current=expected_source,
            )
        return _node("profile", "CURRENT", recorded=_model_digest(profile))

    def _preview_node(
        self,
        user_id: str,
        artifact_id: str,
        preview: RepresentativePreviewManifest | None,
        profile: DataAssetProfile | None,
        upstream_status: str,
    ) -> WorkspaceCheckpointNode:
        propagated = _propagated("preview", upstream_status)
        if propagated:
            return propagated
        if preview is None:
            return _node("preview", "MISSING", ["representative_preview_missing"])
        if profile is None or (
            preview.profile_id != profile.profile_id
            or preview.source_hash != profile.source_hash
        ):
            return _node("preview", "STALE", ["preview_profile_lineage_mismatch"])
        try:
            path = self.research_workspace.preview_path(
                user_id=user_id, artifact_id=artifact_id, preview=preview
            )
        except FileNotFoundError:
            return _node(
                "preview", "STALE", ["preview_artifact_missing_or_changed"]
            )
        return _node(
            "preview",
            "CURRENT",
            recorded=preview.preview_hash,
            current=_sha256(path),
        )

    def _notebook_node(
        self,
        user_id: str,
        artifact_id: str,
        notebook: NotebookShadowBundle | None,
        profile: DataAssetProfile | None,
        preview: RepresentativePreviewManifest | None,
        upstream_status: str,
    ) -> WorkspaceCheckpointNode:
        propagated = _propagated("notebook", upstream_status)
        if propagated:
            return propagated
        if notebook is None:
            return _node("notebook", "MISSING", ["notebook_shadow_missing"])
        if profile is None or preview is None or any(
            (
                notebook.profile_id != profile.profile_id,
                notebook.source_hash != profile.source_hash,
                notebook.preview_id != preview.preview_id,
                notebook.preview_hash != preview.preview_hash,
            )
        ):
            return _node("notebook", "STALE", ["notebook_upstream_lineage_mismatch"])
        current_step = scrublet_step_contract(self.contract_registry)
        reasons: list[str] = []
        if (
            notebook.step_contract_id != current_step.step_id
            or notebook.step_contract_version != current_step.step_version
            or notebook.tool_contract_version != current_step.tool_contract_version
            or notebook.step_template_digest != current_step.template_digest
        ):
            reasons.append("step_or_tool_contract_changed")
        try:
            trust = self.research_workspace.inspect_notebook_trust(
                user_id=user_id, artifact_id=artifact_id, bundle=notebook
            )
            if not trust.system_verified:
                reasons.extend(trust.issues)
            notebook_path = (
                self.research_workspace.notebook_path(
                    user_id=user_id, artifact_id=artifact_id, bundle=notebook
                )
                if trust.notebook_hash_matches
                else None
            )
            self.research_workspace.notebook_parameters(
                user_id=user_id, artifact_id=artifact_id, bundle=notebook
            )
        except (FileNotFoundError, ValueError):
            reasons.append("notebook_or_parameter_hash_changed")
            notebook_path = None
        if reasons:
            return _node("notebook", "STALE", sorted(set(reasons)))
        return _node(
            "notebook",
            "CURRENT",
            recorded=notebook.notebook_hash,
            current=_sha256(notebook_path) if notebook_path else None,
        )

    def _approval_node(
        self,
        *,
        approval_id: str | None,
        result: PreviewRunResult | None,
        upstream_status: str,
    ) -> WorkspaceCheckpointNode:
        propagated = _propagated("approval", upstream_status)
        if propagated:
            return propagated
        if result is not None and result.lineage is not None:
            try:
                contract = self.contract_registry.load("Scrublet", "0.2.3")
                environment = self.environment_registry.get(contract.environment_id)
            except (KeyError, ValueError):
                return _node(
                    "approval", "BLOCKED", ["contract_or_environment_unavailable"]
                )
            if (
                result.lineage.tool_contract_id != contract.contract_id
                or result.lineage.tool_contract_version != contract.contract_version
                or result.lineage.tool_contract_digest != _model_digest(contract)
            ):
                return _node("approval", "STALE", ["tool_contract_changed"])
            if (
                result.lineage.environment_id != environment.environment_id
                or result.lineage.environment_digest != _model_digest(environment)
            ):
                return _node("approval", "STALE", ["environment_fingerprint_changed"])
        if not approval_id:
            return _node("approval", "WAITING", ["execution_approval_missing"])
        try:
            approval = self.approval_service.get_execution_approval(approval_id)
        except KeyError:
            return _node("approval", "FAILED", ["execution_approval_not_found"])
        expected = result.lineage.approval_fingerprint if result is not None else None
        if expected and approval.request_fingerprint != expected:
            return _node("approval", "STALE", ["approval_fingerprint_changed"])
        if result is not None:
            if result.execution_run.request_id not in approval.consumed_request_ids:
                return _node("approval", "FAILED", ["approval_consumption_missing"])
            return _node(
                "approval", "CURRENT", recorded=approval.request_fingerprint
            )
        if approval.revoked_at is not None:
            return _node("approval", "STALE", ["execution_approval_revoked"])
        if approval.uses_consumed >= approval.max_uses:
            return _node("approval", "STALE", ["execution_approval_fully_consumed"])
        return _node("approval", "CURRENT", recorded=approval.request_fingerprint)

    def _result_node(
        self,
        *,
        result: PreviewRunResult | None,
        integrity: PreviewResultIntegrity | None,
        active_notebook: NotebookShadowBundle | None,
        upstream_status: str,
    ) -> WorkspaceCheckpointNode:
        propagated = _propagated("result", upstream_status)
        if propagated:
            return propagated
        if result is None:
            return _node("result", "MISSING", ["preview_result_missing"])
        if active_notebook is not None and any(
            (
                result.lineage.notebook_id != active_notebook.notebook_id,
                result.lineage.notebook_hash != active_notebook.notebook_hash,
                result.lineage.parameter_hash != active_notebook.parameter_hash,
            )
        ):
            return _node("result", "STALE", ["result_notebook_lineage_changed"])
        if integrity is None or not integrity.passed:
            return _node(
                "result",
                "FAILED",
                (integrity.issues if integrity is not None else ["result_integrity_unknown"]),
            )
        if result.status == "blocked":
            return _node("result", "BLOCKED", result.validation_result.failures)
        if result.status != "validated" or not result.validation_result.passed:
            return _node("result", "FAILED", result.validation_result.failures)
        return _node("result", "CURRENT", recorded=_model_digest(result))

    def _load_profile(
        self, user_id: str, artifact_id: str, lineage: PreviewLineageSnapshot
    ) -> DataAssetProfile | None:
        path = (
            self.research_workspace.workspace_root
            / user_id
            / "artifacts"
            / artifact_id
            / "profiles"
            / lineage.profile_id
            / "data_asset_profile.json"
        )
        return _load_model(path, DataAssetProfile)

    def _load_preview(
        self, user_id: str, artifact_id: str, lineage: PreviewLineageSnapshot
    ) -> RepresentativePreviewManifest | None:
        root = (
            self.research_workspace.workspace_root
            / user_id
            / "artifacts"
            / artifact_id
            / "previews"
        )
        return _find_model(root, "preview_manifest.json", "preview_id", lineage.preview_id, RepresentativePreviewManifest)

    def _load_notebook(
        self, user_id: str, artifact_id: str, lineage: PreviewLineageSnapshot
    ) -> NotebookShadowBundle | None:
        root = (
            self.research_workspace.workspace_root
            / user_id
            / "artifacts"
            / artifact_id
            / "notebooks"
        )
        return _find_model(root, "notebook_manifest.json", "notebook_id", lineage.notebook_id, NotebookShadowBundle)


def _node(
    stage: str,
    status: str,
    reasons: list[str] | None = None,
    *,
    recorded: str | None = None,
    current: str | None = None,
    propagated: bool = False,
) -> WorkspaceCheckpointNode:
    return WorkspaceCheckpointNode(
        stage=stage,
        status=status,
        reasons=reasons or [],
        rebuild_from=stage if status in {"STALE", "BLOCKED", "FAILED"} else None,
        user_action=_ACTIONS[stage],
        recorded_digest=recorded,
        current_digest=current,
        propagated=propagated,
    )


def _propagated(stage: str, upstream_status: str) -> WorkspaceCheckpointNode | None:
    if upstream_status in {"STALE", "BLOCKED", "FAILED"}:
        status = "STALE" if upstream_status == "STALE" else upstream_status
        return _node(
            stage,
            status,
            [f"upstream_{upstream_status.casefold()}"],
            propagated=True,
        )
    if upstream_status == "WAITING":
        return _node(
            stage,
            "WAITING",
            ["upstream_waiting"],
            propagated=True,
        )
    if upstream_status == "MISSING":
        return _node(
            stage,
            "MISSING",
            ["upstream_missing"],
            propagated=True,
        )
    return None


def _report(
    user_id: str, artifact_id: str, nodes: list[WorkspaceCheckpointNode]
) -> WorkspaceCheckpointReport:
    first = next((item for item in nodes if item.status != "CURRENT"), None)
    statuses = {item.status for item in nodes}
    if "FAILED" in statuses:
        overall = "FAILED"
    elif "BLOCKED" in statuses:
        overall = "BLOCKED"
    elif "STALE" in statuses:
        overall = "STALE"
    elif "WAITING" in statuses:
        overall = "WAITING"
    elif "MISSING" in statuses:
        overall = "INCOMPLETE"
    else:
        overall = "CURRENT"
    rebuild = first.stage if first and first.status in {"STALE", "BLOCKED", "FAILED"} else None
    action = first.user_action if first else "All recorded lineage checkpoints are current."
    return WorkspaceCheckpointReport(
        user_id=user_id,
        artifact_id=artifact_id,
        overall_status=overall,
        nodes=nodes,
        first_invalid_stage=first.stage if first else None,
        rebuild_from=rebuild,
        user_action=action,
    )


def _model_digest(model) -> str:
    return hashlib.sha256(
        json.dumps(
            model.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_model(path: Path, model_type):
    if not path.is_file():
        return None
    try:
        return model_type.model_validate_json(path.read_text(encoding="utf-8"))
    except ValueError:
        return None


def _find_model(root: Path, filename: str, field: str, value: str, model_type):
    if not root.is_dir():
        return None
    for path in root.glob(f"*/{filename}"):
        model = _load_model(path, model_type)
        if model is not None and getattr(model, field) == value:
            return model
    return None
