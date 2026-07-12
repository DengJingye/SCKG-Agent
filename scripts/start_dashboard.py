from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DASHBOARD_APP = PROJECT_ROOT / "observability" / "dashboard" / "app.py"


def main() -> None:
    command = [sys.executable, "-m", "streamlit", "run", str(DASHBOARD_APP)]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(PROJECT_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    raise SystemExit(subprocess.call(command, cwd=PROJECT_ROOT, env=env))


if __name__ == "__main__":
    main()
