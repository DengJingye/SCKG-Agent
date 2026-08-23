from __future__ import annotations

import hashlib
from pathlib import Path

from core.execution_models import AnnotationReferenceManifest
from core.settings import PROJECT_ROOT


DEFAULT_REFERENCE_MANIFEST_ROOT = PROJECT_ROOT / "reference_packs" / "manifests"


class AnnotationReferenceRegistry:
    """Read-only registry for versioned local annotation model/reference assets."""

    def __init__(self, root: Path = DEFAULT_REFERENCE_MANIFEST_ROOT) -> None:
        self.root = Path(root)

    def get(
        self,
        reference_id: str,
        *,
        expected_tool: str | None = None,
    ) -> AnnotationReferenceManifest:
        path = self.root / f"{reference_id}.json"
        if not path.is_file():
            raise KeyError(f"annotation reference is not registered: {reference_id}")
        manifest = AnnotationReferenceManifest.model_validate_json(
            path.read_text(encoding="utf-8")
        )
        if manifest.reference_id != reference_id:
            raise ValueError("annotation reference id and filename differ")
        if (
            expected_tool is not None
            and manifest.tool_name.casefold() != expected_tool.casefold()
        ):
            raise ValueError("annotation reference tool mismatch")
        return manifest

    def for_tool(self, tool_name: str) -> list[AnnotationReferenceManifest]:
        if not self.root.is_dir():
            return []
        return [
            manifest
            for manifest in (
                AnnotationReferenceManifest.model_validate_json(
                    path.read_text(encoding="utf-8")
                )
                for path in sorted(self.root.glob("*.json"))
            )
            if manifest.tool_name.casefold() == tool_name.casefold()
        ]

    def validate_assets(self, manifest: AnnotationReferenceManifest) -> list[str]:
        issues: list[str] = []
        for path_text, expected, label in (
            (manifest.local_path, manifest.sha256, "reference"),
            (
                manifest.gene_list_path,
                manifest.gene_list_sha256,
                "reference_gene_list",
            ),
        ):
            path = Path(path_text).expanduser()
            if not path.is_file():
                issues.append(f"{label}_missing")
            elif _sha256(path) != expected:
                issues.append(f"{label}_digest_mismatch")
        if manifest.runtime_network_allowed:
            issues.append("runtime_network_must_be_disabled")
        return issues

    def manifest_path(self, reference_id: str) -> Path:
        return (self.root / f"{reference_id}.json").resolve()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
