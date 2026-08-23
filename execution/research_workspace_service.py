from __future__ import annotations

import re
import io
import uuid
import zipfile
from pathlib import Path

from core.research_workspace_models import (
    DataAssetProfile,
    NotebookTrustReport,
    NotebookShadowBundle,
    RepresentativePreviewManifest,
)
from engine.data_intelligence import AnnDataBackedAdapter
from execution.data_registry import DataRegistry
from execution.approval_service import ApprovalService
from execution.notebook_shadow import NotebookShadowCompiler
from execution.representative_preview import RepresentativePreviewBuilder
from core.settings import PROJECT_ROOT


class ResearchWorkspaceService:
    """Thin shadow facade over existing registration and new preview artifacts."""

    def __init__(
        self,
        *,
        data_registry: DataRegistry,
        approval_service: ApprovalService,
        workspace_root: Path,
        adapter: AnnDataBackedAdapter | None = None,
        preview_builder: RepresentativePreviewBuilder | None = None,
        notebook_compiler: NotebookShadowCompiler | None = None,
    ) -> None:
        self.data_registry = data_registry
        self.approval_service = approval_service
        self.workspace_root = Path(workspace_root).resolve()
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        self.adapter = adapter or AnnDataBackedAdapter()
        self.preview_builder = preview_builder or RepresentativePreviewBuilder()
        self.notebook_compiler = notebook_compiler or NotebookShadowCompiler()

    def profile(
        self, *, user_id: str, artifact_id: str, data_grant_id: str
    ) -> DataAssetProfile:
        self._require_data_access(user_id, artifact_id, data_grant_id)
        record = self.data_registry.get(artifact_id, user_id=user_id)
        path = self.data_registry.resolve_path(artifact_id, user_id=user_id)
        profile = self.adapter.profile(
            path=path,
            artifact_id=artifact_id,
            owner_user_id=user_id,
            source_hash=record.sha256,
        )
        profile_dir = self._artifact_root(user_id, artifact_id) / "profiles" / profile.profile_id
        profile_dir.mkdir(parents=True, exist_ok=True)
        (profile_dir / "data_asset_profile.json").write_text(
            profile.model_dump_json(indent=2) + "\n", encoding="utf-8"
        )
        return profile

    def build_preview(
        self,
        *,
        user_id: str,
        artifact_id: str,
        profile: DataAssetProfile,
        data_grant_id: str,
        max_cells: int = 500,
        random_seed: int = 20260812,
        stratify_key: str | None = None,
    ) -> RepresentativePreviewManifest:
        self._require_data_access(user_id, artifact_id, data_grant_id)
        self._check_profile_owner(user_id, artifact_id, profile)
        source_path = self.data_registry.resolve_path(artifact_id, user_id=user_id)
        preview_dir = (
            self._artifact_root(user_id, artifact_id)
            / "previews"
            / f"preview-{uuid.uuid4().hex[:12]}"
        )
        return self.preview_builder.build(
            source_path=source_path,
            profile=profile,
            output_dir=preview_dir,
            allowed_output_root=self._artifact_root(user_id, artifact_id),
            max_cells=max_cells,
            random_seed=random_seed,
            stratify_key=stratify_key,
        )

    def compile_notebook(
        self,
        *,
        user_id: str,
        artifact_id: str,
        profile: DataAssetProfile,
        preview: RepresentativePreviewManifest,
        data_grant_id: str,
        parameters: dict | None = None,
        task_context: dict[str, str | None] | None = None,
    ) -> NotebookShadowBundle:
        self._require_data_access(user_id, artifact_id, data_grant_id)
        self._check_profile_owner(user_id, artifact_id, profile)
        if preview.owner_user_id != user_id or preview.artifact_id != artifact_id:
            raise PermissionError("cross-user preview access is forbidden")
        preview_path = self._find_preview_path(user_id, artifact_id, preview)
        notebook_dir = (
            self._artifact_root(user_id, artifact_id)
            / "notebooks"
            / f"notebook-{uuid.uuid4().hex[:12]}"
        )
        return self.notebook_compiler.compile_scrublet(
            profile=profile,
            preview=preview,
            preview_path=preview_path,
            output_dir=notebook_dir,
            allowed_output_root=self._artifact_root(user_id, artifact_id),
            parameters=parameters,
            task_context=task_context,
        )

    def notebook_path(
        self, *, user_id: str, artifact_id: str, bundle: NotebookShadowBundle
    ) -> Path:
        if bundle.owner_user_id != user_id or bundle.artifact_id != artifact_id:
            raise PermissionError("cross-user notebook access is forbidden")
        for path in self._artifact_root(user_id, artifact_id).glob(
            "notebooks/*/analysis_preview.ipynb"
        ):
            if _sha256(path) == bundle.notebook_hash:
                return path
        raise FileNotFoundError("owned notebook artifact is missing")

    def preview_path(
        self,
        *,
        user_id: str,
        artifact_id: str,
        preview: RepresentativePreviewManifest,
    ) -> Path:
        if preview.owner_user_id != user_id or preview.artifact_id != artifact_id:
            raise PermissionError("cross-user preview access is forbidden")
        return self._find_preview_path(user_id, artifact_id, preview)

    def notebook_parameters(
        self, *, user_id: str, artifact_id: str, bundle: NotebookShadowBundle
    ) -> dict:
        import json
        from execution.approval_service import parameter_hash

        notebook_path = self.notebook_path(
            user_id=user_id, artifact_id=artifact_id, bundle=bundle
        )
        parameters_path = notebook_path.parent / "parameters.json"
        if not parameters_path.is_file():
            raise FileNotFoundError("owned notebook parameters are missing")
        parameters = json.loads(parameters_path.read_text(encoding="utf-8"))
        if parameter_hash(parameters) != bundle.parameter_hash:
            raise ValueError("notebook parameter hash changed")
        return parameters

    def notebook_bundle_bytes(
        self, *, user_id: str, artifact_id: str, bundle: NotebookShadowBundle
    ) -> bytes:
        notebook_path = self.notebook_path(
            user_id=user_id, artifact_id=artifact_id, bundle=bundle
        )
        allowed_names = (
            "analysis_preview.ipynb",
            "representative_preview.h5ad",
            "parameters.json",
            "step_contract.json",
            "notebook_manifest.json",
        )
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name in allowed_names:
                source = notebook_path.parent / name
                if source.is_file() and not source.is_symlink():
                    archive.write(source, arcname=name)
            archive.writestr(
                "README.txt",
                "scKG interactive Preview bundle\n\n"
                "Keep every file in this directory. Open analysis_preview.ipynb "
                "with the scKG Doublet Python kernel. The notebook never installs "
                "dependencies and does not run automatically. Preview results are "
                "engineering checks, not full-data scientific conclusions.\n",
            )
        return buffer.getvalue()

    def inspect_notebook_trust(
        self, *, user_id: str, artifact_id: str, bundle: NotebookShadowBundle
    ) -> NotebookTrustReport:
        if bundle.owner_user_id != user_id or bundle.artifact_id != artifact_id:
            raise PermissionError("cross-user notebook access is forbidden")
        notebook_path = None
        for manifest_path in self._artifact_root(user_id, artifact_id).glob(
            "notebooks/*/notebook_manifest.json"
        ):
            try:
                stored = NotebookShadowBundle.model_validate_json(
                    manifest_path.read_text(encoding="utf-8")
                )
            except (ValueError, OSError):
                continue
            if stored.notebook_id == bundle.notebook_id:
                candidate = manifest_path.parent / "analysis_preview.ipynb"
                if candidate.is_file() and not candidate.is_symlink():
                    notebook_path = candidate
                    break
        if notebook_path is None:
            raise FileNotFoundError("owned notebook artifact is missing")
        return self.notebook_compiler.inspect_trust(
            notebook_path=notebook_path, bundle=bundle
        )

    def artifact_workspace_root(self, *, user_id: str, artifact_id: str) -> Path:
        return self._artifact_root(user_id, artifact_id)

    def _find_preview_path(
        self, user_id: str, artifact_id: str, preview: RepresentativePreviewManifest
    ) -> Path:
        for path in self._artifact_root(user_id, artifact_id).glob(
            "previews/*/representative_preview.h5ad"
        ):
            if _sha256(path) == preview.preview_hash:
                return path
        raise FileNotFoundError("owned preview artifact is missing")

    def _check_profile_owner(
        self, user_id: str, artifact_id: str, profile: DataAssetProfile
    ) -> None:
        self.data_registry.get(artifact_id, user_id=user_id)
        if profile.owner_user_id != user_id or profile.artifact_id != artifact_id:
            raise PermissionError("cross-user profile access is forbidden")

    def _require_data_access(
        self, user_id: str, artifact_id: str, data_grant_id: str
    ) -> None:
        validation = self.approval_service.validate_data_access(
            data_grant_id, user_id=user_id, artifact_id=artifact_id
        )
        if not validation.allowed:
            raise PermissionError(";".join(validation.reasons))

    def _artifact_root(self, user_id: str, artifact_id: str) -> Path:
        if not _SAFE_ID.fullmatch(user_id) or not _SAFE_ID.fullmatch(artifact_id):
            raise ValueError("unsafe research workspace identifier")
        safe = self.workspace_root / user_id / "artifacts" / artifact_id
        safe.mkdir(parents=True, exist_ok=True)
        return safe


def _sha256(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def build_research_workspace_service(
    *, data_registry: DataRegistry, approval_service: ApprovalService
) -> ResearchWorkspaceService:
    return ResearchWorkspaceService(
        data_registry=data_registry,
        approval_service=approval_service,
        workspace_root=PROJECT_ROOT / ".sckg_exec" / "research-workspace",
    )


_SAFE_ID = re.compile(r"^[A-Za-z0-9_.-]+$")
