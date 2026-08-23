from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request-json", required=True)
    args = parser.parse_args()
    if Path(args.request_json).name != "worker_request.json":
        raise ValueError("controlled request filename required")
    child = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        shell=False,
    )
    print(f"child_pid={child.pid}", flush=True)
    time.sleep(60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
