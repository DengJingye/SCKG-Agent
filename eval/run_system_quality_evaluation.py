from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from eval.system_quality_evaluation import (
    DEFAULT_STABLE_OUTPUT,
    SystemQualityEvaluator,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the unified local scKG Agent system quality gate."
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--stable-output", type=Path, default=DEFAULT_STABLE_OUTPUT)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Reuse passed command artifacts in --output and rerun only failed/missing commands.",
    )
    args = parser.parse_args()
    token = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output = args.output or (
        PROJECT_ROOT / ".sckg_exec" / "evaluations" / f"system-quality-{token}"
    )
    report = SystemQualityEvaluator(
        output_root=output,
        stable_output=args.stable_output,
        baseline_path=args.baseline,
        resume=args.resume,
    ).run()
    print(
        json.dumps(
            {
                "evaluation_id": report.evaluation_id,
                "recommended_status": report.recommended_status,
                "engineering_gate_passed": report.engineering_gate_passed,
                "phase6_complete_eligible": report.phase6_complete_eligible,
                "dimension_status": {
                    item.dimension: item.status for item in report.dimensions
                },
                "scenario_pass_count": sum(item.passed for item in report.scenarios),
                "scenario_count": len(report.scenarios),
                "blockers": report.blockers,
                "output": str(output.resolve().relative_to(PROJECT_ROOT)),
                "stable_output": str(
                    args.stable_output.resolve().relative_to(PROJECT_ROOT)
                ),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if report.engineering_gate_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
