from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from execution.runtime_pack_registry import RuntimePackRegistry


def build_test_registry(tmp_path: Path) -> RuntimePackRegistry:
    asset_root = tmp_path / "assets"
    manifest_root = asset_root / "manifests"
    lock_root = asset_root / "locks" / "osx-arm64"
    manifest_root.mkdir(parents=True)
    lock_root.mkdir(parents=True)
    lock = lock_root / "test-pack.conda-explicit.txt"
    lock.write_text("@EXPLICIT\n", encoding="utf-8")
    digest = hashlib.sha256(lock.read_bytes()).hexdigest()
    manifest = {
        "schema_version": "1.0",
        "pack_id": "test-pack",
        "version": "1.0.0",
        "task_family": "doublet_detection",
        "display_name": "Test Pack",
        "platform": "osx-arm64",
        "architecture": "arm64",
        "supported_tools": [
            {
                "tool_name": "TestTool",
                "tool_version": "1.0.0",
                "environment_id": "test-environment",
                "wrapper_id": "test_wrapper"
            }
        ],
        "lock_files": [
            {
                "path": "locks/osx-arm64/test-pack.conda-explicit.txt",
                "kind": "conda_explicit",
                "sha256": digest
            }
        ],
        "package_sources": ["conda-forge"],
        "licenses": ["test-only"],
        "allowed_install_hosts": ["conda.anaconda.org"],
        "estimated_download_size_bytes": 1024,
        "estimated_installed_size_bytes": 4096,
        "network_required_for_install": True,
        "runtime_network_policy": "network_not_os_isolated",
        "qualification_status": "manifest_only",
        "removable": True,
        "legacy_environment_name": None,
        "python_entrypoint": "bin/python",
        "rscript_entrypoint": None,
        "import_smoke_modules": ["json"],
        "r_smoke_packages": [],
        "notes": ["test-only pack"]
    }
    manifest_root.joinpath("test-pack.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    trust_root = asset_root / "trust"
    signature_root = asset_root / "signatures"
    trust_root.mkdir()
    signature_root.mkdir()
    private = Ed25519PrivateKey.generate()
    public_key_path = trust_root / "runtime-pack-maintainer-public.pem"
    public_key_path.write_bytes(
        private.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    manifest_path = manifest_root / "test-pack.json"
    signature_root.joinpath("test-pack.sig").write_bytes(
        private.sign(manifest_path.read_bytes())
    )
    return RuntimePackRegistry(
        manifest_root=manifest_root,
        asset_root=asset_root,
        public_key_path=public_key_path,
        signature_root=signature_root,
    )


class FakePackCommandRunner:
    def __init__(self) -> None:
        self.commands: list[list[str]] = []

    def __call__(self, command, **kwargs):
        argv = [str(item) for item in command]
        self.commands.append(argv)
        if "create" in argv and "--prefix" in argv:
            prefix = Path(argv[argv.index("--prefix") + 1])
            executable = prefix / "bin" / "python"
            executable.parent.mkdir(parents=True, exist_ok=True)
            executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            executable.chmod(0o755)
        return subprocess.CompletedProcess(argv, 0, stdout="ok", stderr="")
