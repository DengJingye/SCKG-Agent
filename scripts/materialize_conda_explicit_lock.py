from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Materialize a deterministic @EXPLICIT lock from a Conda dry-run JSON."
    )
    parser.add_argument("--dry-run-json", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--platform", default="osx-arm64")
    args = parser.parse_args()

    payload = json.loads(args.dry_run_json.read_text(encoding="utf-8"))
    actions = payload.get("actions") or {}
    fetch = {
        item.get("dist_name")
        or f"{item['name']}-{item['version']}-{item['build']}": item
        for item in actions.get("FETCH") or []
    }
    lines = [
        "# Generated from a clean-cache conda --dry-run solve.",
        f"# platform: {args.platform}",
        "@EXPLICIT",
    ]
    missing: list[str] = []
    for link in actions.get("LINK") or []:
        dist = str(link["dist_name"])
        package = fetch.get(dist)
        if package is None:
            missing.append(dist)
            continue
        url = str(package.get("url") or "")
        digest = str(package.get("md5") or "")
        if not url.startswith("https://") or len(digest) != 32:
            raise ValueError(f"package is missing an HTTPS URL or MD5: {dist}")
        lines.append(f"{url}#{digest}")
    if missing:
        raise ValueError(
            "dry-run did not include fetch metadata for: " + ", ".join(missing[:10])
        )
    if len(lines) <= 3:
        raise ValueError("dry-run contains no link actions")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "output": str(args.output),
                "package_count": len(lines) - 3,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
