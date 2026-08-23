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

from eval.portfolio_acceptance import PortfolioAcceptanceRunner


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the complete scKG portfolio acceptance.")
    parser.add_argument("--output-root", type=Path, default=None)
    args = parser.parse_args()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_root = args.output_root or PROJECT_ROOT / ".sckg_exec" / "portfolio" / f"rc-2.7.2-{stamp}"
    result = PortfolioAcceptanceRunner().run(output_root=output_root)
    print(
        json.dumps(
            {
                "portfolio_status": result.portfolio_status,
                "hard_gate_passed": result.hard_gate_passed,
                "phase6_status": result.phase6_status,
                "execution_policy": result.execution_policy,
                "git_dirty": result.git_dirty,
                "worktree_digest": result.worktree_digest,
                "output_root": output_root.relative_to(PROJECT_ROOT).as_posix(),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if result.hard_gate_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
