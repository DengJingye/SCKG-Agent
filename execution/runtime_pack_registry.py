from __future__ import annotations

import hashlib
import json
import platform
from pathlib import Path
from urllib.parse import urlparse

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from core.runtime_pack_models import RuntimeLockFile, RuntimePackManifest
from core.settings import PROJECT_ROOT


DEFAULT_RUNTIME_PACK_ROOT = PROJECT_ROOT / "runtime_packs"
DEFAULT_MANIFEST_ROOT = DEFAULT_RUNTIME_PACK_ROOT / "manifests"
DEFAULT_PUBLIC_KEY = (
    DEFAULT_RUNTIME_PACK_ROOT / "trust" / "runtime-pack-maintainer-public.pem"
)
DEFAULT_SIGNATURE_ROOT = DEFAULT_RUNTIME_PACK_ROOT / "signatures"


class RuntimePackRegistry:
    """Load immutable task-family runtime manifests and verify their lock assets."""

    def __init__(
        self,
        *,
        manifest_root: Path = DEFAULT_MANIFEST_ROOT,
        asset_root: Path = DEFAULT_RUNTIME_PACK_ROOT,
        public_key_path: Path = DEFAULT_PUBLIC_KEY,
        signature_root: Path = DEFAULT_SIGNATURE_ROOT,
    ) -> None:
        self.manifest_root = Path(manifest_root).resolve()
        self.asset_root = Path(asset_root).resolve()
        self.public_key_path = Path(public_key_path).resolve()
        self.signature_root = Path(signature_root).resolve()

    def load_all(self) -> list[RuntimePackManifest]:
        if not self.manifest_root.exists():
            return []
        manifests = [self._load_signed_manifest(path) for path in sorted(self.manifest_root.glob("*.json"))]
        ids = [item.pack_id for item in manifests]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate runtime pack id")
        pairs = [
            (tool.tool_name.casefold(), tool.tool_version)
            for item in manifests
            for tool in item.supported_tools
        ]
        if len(set(pairs)) != len(pairs):
            raise ValueError("a tool version can belong to only one runtime pack")
        return manifests

    def get(self, pack_id: str) -> RuntimePackManifest:
        path = self.manifest_root / f"{pack_id}.json"
        if not path.is_file():
            raise KeyError(f"runtime pack is not registered: {pack_id}")
        manifest = self._load_signed_manifest(path)
        if manifest.pack_id != pack_id:
            raise ValueError("runtime pack file name and manifest id differ")
        return manifest

    def for_environment(self, environment_id: str) -> RuntimePackManifest:
        matches = [
            item for item in self.load_all() if item.environment_id == environment_id
        ]
        if not matches:
            raise KeyError(f"runtime pack missing for environment: {environment_id}")
        if len(matches) != 1:
            raise ValueError(f"multiple runtime packs map environment: {environment_id}")
        return matches[0]

    def for_tool(self, tool_name: str, tool_version: str) -> RuntimePackManifest:
        matches = [
            item
            for item in self.load_all()
            if any(
                tool.tool_name.casefold() == tool_name.casefold()
                and tool.tool_version == tool_version
                for tool in item.supported_tools
            )
        ]
        if not matches:
            raise KeyError(f"runtime pack missing for tool: {tool_name} {tool_version}")
        if len(matches) != 1:
            raise ValueError(f"multiple runtime packs map tool: {tool_name} {tool_version}")
        return matches[0]

    def lock_path(self, lock: RuntimeLockFile) -> Path:
        path = (self.asset_root / lock.path).resolve()
        try:
            path.relative_to(self.asset_root)
        except ValueError as exc:
            raise ValueError("runtime lock path escapes asset root") from exc
        return path

    def validate_assets(self, manifest: RuntimePackManifest) -> list[str]:
        reasons: list[str] = []
        for lock in manifest.lock_files:
            path = self.lock_path(lock)
            if not path.is_file():
                reasons.append(f"lock_file_missing:{lock.path}")
                continue
            actual = _sha256(path)
            if actual != lock.sha256:
                reasons.append(f"lock_digest_mismatch:{lock.path}")
                continue
            for host in _lock_hosts(path):
                if host not in manifest.allowed_install_hosts:
                    reasons.append(f"lock_host_not_allowlisted:{lock.path}:{host}")
        return sorted(reasons)

    def signature_path(self, pack_id: str) -> Path:
        path = (self.signature_root / f"{pack_id}.sig").resolve()
        try:
            path.relative_to(self.signature_root)
        except ValueError as exc:
            raise ValueError("runtime manifest signature escapes signature root") from exc
        return path

    def verify_signature(self, manifest_path: Path) -> bool:
        if not self.public_key_path.is_file():
            return False
        signature_path = self.signature_path(manifest_path.stem)
        if not signature_path.is_file():
            return False
        key = serialization.load_pem_public_key(self.public_key_path.read_bytes())
        if not isinstance(key, Ed25519PublicKey):
            raise ValueError("runtime manifest trust key must be Ed25519")
        try:
            key.verify(signature_path.read_bytes(), manifest_path.read_bytes())
        except InvalidSignature:
            return False
        return True

    def _load_signed_manifest(self, path: Path) -> RuntimePackManifest:
        if not self.verify_signature(path):
            raise ValueError(f"runtime manifest signature invalid: {path.name}")
        return RuntimePackManifest.model_validate_json(path.read_text(encoding="utf-8"))

    @staticmethod
    def current_platform_tag() -> str:
        system = platform.system().casefold()
        machine = platform.machine().casefold()
        if system == "darwin" and machine in {"arm64", "aarch64"}:
            return "osx-arm64"
        if system == "linux" and machine in {"x86_64", "amd64"}:
            return "linux-64"
        return f"{system}-{machine}"

    def inventory(self) -> dict:
        manifests = self.load_all()
        return {
            "schema_version": "1.0",
            "platform": self.current_platform_tag(),
            "pack_count": len(manifests),
            "packs": [
                {
                    "pack_id": item.pack_id,
                    "version": item.version,
                    "task_family": item.task_family,
                    "environment_id": item.environment_id,
                    "tools": [tool.model_dump(mode="json") for tool in item.supported_tools],
                    "manifest_digest": item.manifest_digest,
                    "signature_verified": self.verify_signature(
                        self.manifest_root / f"{item.pack_id}.json"
                    ),
                    "asset_issues": self.validate_assets(item),
                }
                for item in manifests
            ],
        }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _lock_hosts(path: Path) -> set[str]:
    hosts: set[str] = set()
    text = path.read_text(encoding="utf-8")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        payload = None
    if isinstance(payload, dict):
        for package in payload.get("packages") or []:
            if not isinstance(package, dict):
                continue
            value = str(package.get("url") or "")
            host = urlparse(value).hostname
            if host:
                hosts.add(host.casefold())
    for line in text.splitlines():
        stripped = line.strip()
        if "https://" not in stripped:
            continue
        for token in stripped.replace("\\", " ").split():
            if token.startswith("https://"):
                host = urlparse(token.split("#", 1)[0]).hostname
                if host:
                    hosts.add(host.casefold())
    return hosts
