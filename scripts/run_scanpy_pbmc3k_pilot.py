#!/usr/bin/env python
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from execution.scanpy_pbmc3k_pilot import run_pbmc3k_pilot


def main() -> int:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    pilot_id = f"scanpy-pbmc3k-{stamp}"
    summary = run_pbmc3k_pilot(
        input_root=(
            PROJECT_ROOT
            / ".sckg_exec/approved-inputs/pbmc3k-scanpy-official/1.0.0"
        ),
        output_root=PROJECT_ROOT / ".sckg_exec/scanpy-pbmc3k-pilot" / pilot_id,
        package_root=PROJECT_ROOT / ".sckg_exec/packages",
        pilot_id=pilot_id,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
