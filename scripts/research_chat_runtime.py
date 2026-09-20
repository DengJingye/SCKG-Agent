"""Explicit, secret-free launcher for the Research Chat worktree."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--enable-external", action="store_true",
                        help="Authorize sanitized Research Chat questions/context for this local server")
    parser.add_argument("--port", type=int, default=8501)
    args = parser.parse_args()
    config = args.env_file.expanduser().resolve(strict=True)
    stat = config.stat()
    if stat.st_size and getattr(stat, "st_blocks", 1) == 0:
        parser.error("Configuration is an unmaterialized placeholder; restore it locally first.")
    root = Path(__file__).resolve().parents[1]
    os.environ["SCKG_ENV_FILE"] = str(config)
    os.environ["SCKG_RESEARCH_CHAT_ENABLED"] = "true" if args.enable_external else "false"
    os.chdir(root)
    os.execv(sys.executable, [sys.executable, "-m", "streamlit", "run", "app.py",
        "--server.address", "127.0.0.1", "--server.port", str(args.port), "--server.headless", "true"])


if __name__ == "__main__":
    main()
