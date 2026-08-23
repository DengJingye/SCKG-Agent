from __future__ import annotations

import argparse
import sys
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.runtime_pack_models import RuntimePackManifest
from execution.runtime_pack_registry import RuntimePackRegistry


DEFAULT_PRIVATE_KEY = (
    Path.home() / ".sckg" / "maintainer-keys" / "runtime-pack-ed25519.pem"
)


def sign_manifest(pack_id: str, private_key_path: Path) -> Path:
    registry = RuntimePackRegistry()
    manifest_path = registry.manifest_root / f"{pack_id}.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"runtime manifest missing: {pack_id}")
    manifest = RuntimePackManifest.model_validate_json(
        manifest_path.read_text(encoding="utf-8")
    )
    issues = registry.validate_assets(manifest)
    if issues:
        raise ValueError(f"runtime manifest assets invalid: {','.join(issues)}")

    private_key = serialization.load_pem_private_key(
        private_key_path.expanduser().read_bytes(), password=None
    )
    if not isinstance(private_key, Ed25519PrivateKey):
        raise ValueError("runtime manifest signing key must be Ed25519")
    expected_public = serialization.load_pem_public_key(
        registry.public_key_path.read_bytes()
    )
    actual_public_bytes = private_key.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )
    expected_public_bytes = expected_public.public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )
    if actual_public_bytes != expected_public_bytes:
        raise PermissionError("runtime signing key does not match release trust root")

    signature_path = registry.signature_path(pack_id)
    signature_path.write_bytes(private_key.sign(manifest_path.read_bytes()))
    if not registry.verify_signature(manifest_path):
        raise RuntimeError("runtime manifest signature verification failed after signing")
    return signature_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Sign one reviewed Runtime Pack manifest")
    parser.add_argument("pack_id")
    parser.add_argument("--private-key", type=Path, default=DEFAULT_PRIVATE_KEY)
    args = parser.parse_args()
    signature = sign_manifest(args.pack_id, args.private_key)
    print(f"signed: {signature.relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
