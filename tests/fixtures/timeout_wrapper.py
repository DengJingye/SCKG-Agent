from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path


def main() -> int:
    artifacts = Path("artifacts")
    artifacts.mkdir(exist_ok=True)
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    (artifacts / "child_pid.txt").write_text(str(child.pid), encoding="utf-8")
    time.sleep(60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
