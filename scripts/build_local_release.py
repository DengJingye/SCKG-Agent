from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = PROJECT_ROOT / "release" / "release-manifest.json"
FORBIDDEN_SUFFIXES = {".h5ad", ".pdf"}
FORBIDDEN_NAMES = {".env", "scKG_embeddings_backup.jsonl"}
FORBIDDEN_CONTENT = (
    b"/Users/",
    b"/opt/anaconda3/",
    b"/Data/Omics/",
    b"BEGIN PRIVATE KEY",
)
TEXT_SUFFIXES = {".csv", ".json", ".jsonl", ".md", ".py", ".toml", ".tsv", ".txt", ".yaml", ".yml"}
EXECUTABLE_SUFFIXES = {".command"}


def load_release_manifest(path: Path = DEFAULT_MANIFEST) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def collect_release_files(manifest: dict) -> list[Path]:
    selected: set[Path] = set()
    for entry in manifest["include"]:
        path = (PROJECT_ROOT / entry).resolve()
        if not path.exists():
            continue
        if path.is_file():
            candidates = [path]
        else:
            candidates = [item for item in path.rglob("*") if item.is_file()]
        for candidate in candidates:
            relative = candidate.relative_to(PROJECT_ROOT)
            posix = relative.as_posix()
            if any(fnmatch.fnmatch(posix, pattern) for pattern in manifest["exclude_patterns"]):
                continue
            selected.add(relative)
    return sorted(selected, key=lambda item: item.as_posix())


def release_bytes(relative: Path) -> bytes:
    path = PROJECT_ROOT / relative
    data = path.read_bytes()
    if path.suffix.casefold() not in TEXT_SUFFIXES and path.name not in {".env.example"}:
        return data
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return data
    text = re.sub(r"/Users/[^\"'`\s,}\]]+", "[local-path-redacted]", text)
    text = re.sub(r"/opt/anaconda3/[^\"'`\s,}\]]+", "[legacy-conda-path-redacted]", text)
    text = re.sub(r"/Data/Omics/[^\"'`\s,}\]]+", "[local-path-redacted]", text)
    return text.encode("utf-8")


def validate_release(files: list[Path], manifest: dict) -> dict:
    issues: list[str] = []
    total = 0
    hashes: dict[str, str] = {}
    for relative in files:
        path = PROJECT_ROOT / relative
        data = release_bytes(relative)
        total += len(data)
        hashes[relative.as_posix()] = hashlib.sha256(data).hexdigest()
        if path.name in FORBIDDEN_NAMES or path.suffix.casefold() in FORBIDDEN_SUFFIXES:
            issues.append(f"forbidden_release_asset:{relative.as_posix()}")
        if any(fragment in data for fragment in FORBIDDEN_CONTENT):
            issues.append(f"local_path_or_secret_material:{relative.as_posix()}")
    if total > int(manifest["max_release_size_bytes"]):
        issues.append("release_size_limit_exceeded")
    return {
        "product": manifest["product"],
        "target": manifest["target"],
        "file_count": len(files),
        "total_size_bytes": total,
        "max_release_size_bytes": int(manifest["max_release_size_bytes"]),
        "issues": sorted(set(issues)),
        "file_hashes": hashes,
        "validated_at": datetime.now(timezone.utc).isoformat(),
    }


def build_release(output: Path, *, check_only: bool = False) -> dict:
    manifest = load_release_manifest()
    files = collect_release_files(manifest)
    report = validate_release(files, manifest)
    if report["issues"]:
        return report
    if check_only:
        return report
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for relative in files:
            info = zipfile.ZipInfo(relative.as_posix(), date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            mode = 0o755 if relative.suffix in EXECUTABLE_SUFFIXES else 0o644
            info.external_attr = mode << 16
            archive.writestr(info, release_bytes(relative))
        release_report = dict(report)
        release_report.pop("file_hashes", None)
        archive.writestr(
            "release-validation.json",
            json.dumps(release_report, indent=2, sort_keys=True) + "\n",
        )
    report["archive_path"] = str(output.resolve())
    report["archive_size_bytes"] = output.stat().st_size
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a data-free local scKG release")
    parser.add_argument("--check", action="store_true")
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "dist" / "sckg-local-workbench-mac-arm64-beta.zip",
    )
    args = parser.parse_args()
    report = build_release(args.output, check_only=args.check)
    print(json.dumps({key: value for key, value in report.items() if key != "file_hashes"}, indent=2, sort_keys=True))
    return 1 if report["issues"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
