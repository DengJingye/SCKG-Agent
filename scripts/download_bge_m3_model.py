from __future__ import annotations

import argparse
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Download a pinned BGE-M3 snapshot.")
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    from huggingface_hub import snapshot_download

    args.output.mkdir(parents=True, exist_ok=True)
    snapshot_download(
        repo_id=args.model_id,
        revision=args.revision,
        local_dir=args.output,
        local_dir_use_symlinks=False,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
