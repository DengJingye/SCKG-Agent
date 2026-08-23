#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from eval.mainline_quality_gate import MainlineQualityGate


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the unified scKG mainline gate.")
    parser.add_argument("--output-root", type=Path, default=None)
    args = parser.parse_args()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    root = args.output_root or PROJECT_ROOT / ".sckg_exec" / "evaluations" / f"mainline-{stamp}"
    summary = MainlineQualityGate().run(output_root=root)
    print(
        json.dumps(
            {**summary.model_dump(mode="json"), "output_root": str(root)},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if summary.hard_gate_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
