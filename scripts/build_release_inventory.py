from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ROOT = PROJECT_ROOT / "runtime_packs"
RELEASE_ROOT = PROJECT_ROOT / "release"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _conda_components(path: Path) -> list[dict]:
    components: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        value = line.strip()
        if not value.startswith("https://"):
            continue
        url = value.split("#", 1)[0]
        filename = Path(urlparse(url).path).name
        stem = re.sub(r"\.(conda|tar\.bz2)$", "", filename)
        parts = stem.rsplit("-", 2)
        if len(parts) != 3:
            continue
        name, version, build = parts
        components.append(
            {
                "type": "library",
                "name": name,
                "version": version,
                "source": "conda",
                "build": build,
                "download_host": urlparse(url).hostname,
                "lock_path": path.relative_to(PROJECT_ROOT).as_posix(),
            }
        )
    return components


def _pip_components(path: Path) -> list[dict]:
    components: list[dict] = []
    pattern = re.compile(r"^([A-Za-z0-9_.-]+)==([^\s\\]+)")
    for line in path.read_text(encoding="utf-8").splitlines():
        match = pattern.match(line.strip())
        if not match:
            continue
        components.append(
            {
                "type": "library",
                "name": match.group(1),
                "version": match.group(2),
                "source": "PyPI",
                "lock_path": path.relative_to(PROJECT_ROOT).as_posix(),
            }
        )
    return components


def build_inventory() -> tuple[dict, dict]:
    manifests = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted((RUNTIME_ROOT / "manifests").glob("*.json"))
    ]
    lock_paths = sorted((RUNTIME_ROOT / "locks").rglob("*")) + sorted(
        (RELEASE_ROOT / "locks").glob("*")
    )
    components: list[dict] = []
    for path in lock_paths:
        if not path.is_file():
            continue
        if "conda-explicit" in path.name:
            components.extend(_conda_components(path))
        elif "requirements" in path.name:
            components.extend(_pip_components(path))
    unique: dict[tuple[str, str, str], dict] = {}
    for component in components:
        key = (
            component["source"],
            component["name"].casefold(),
            component["version"],
        )
        unique.setdefault(key, component)

    generated_at = datetime.now(timezone.utc).isoformat()
    sbom = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "serialNumber": "urn:uuid:sckg-local-workbench-2026-07-rc1",
        "version": 1,
        "metadata": {
            "timestamp": generated_at,
            "component": {
                "type": "application",
                "name": "scKG Local Research Workbench",
                "version": "2026.07-rc1",
            },
        },
        "components": sorted(
            unique.values(),
            key=lambda item: (item["source"], item["name"].casefold(), item["version"]),
        ),
        "properties": [
            {"name": "sckg:datasets_bundled", "value": "false"},
            {"name": "sckg:runtime_packs_bundled", "value": "false"},
        ],
    }
    license_inventory = {
        "schema_version": "1.0",
        "generated_at": generated_at,
        "runtime_pack_declarations": [
            {
                "pack_id": manifest["pack_id"],
                "licenses": manifest["licenses"],
                "package_sources": manifest["package_sources"],
            }
            for manifest in manifests
        ],
        "component_count": len(unique),
        "transitive_license_status": "metadata_review_required_before_public_distribution",
        "notes": [
            "This inventory records reviewed top-level declarations and locked components.",
            "It is not a substitute for bundled upstream license texts or legal review.",
        ],
    }
    return sbom, license_inventory


def main() -> int:
    sbom, licenses = build_inventory()
    sbom_path = RELEASE_ROOT / "sbom.cdx.json"
    license_path = RELEASE_ROOT / "license-inventory.json"
    sbom_path.write_text(json.dumps(sbom, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    license_path.write_text(
        json.dumps(licenses, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "sbom": str(sbom_path.relative_to(PROJECT_ROOT)),
                "sbom_sha256": _sha256(sbom_path),
                "licenses": str(license_path.relative_to(PROJECT_ROOT)),
                "licenses_sha256": _sha256(license_path),
                "component_count": licenses["component_count"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
