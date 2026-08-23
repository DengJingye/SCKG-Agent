from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from eval.continuous_agent_evaluation import (
    DEFAULT_OUTPUT,
    ContinuousAgentEvaluator,
    freeze_baseline,
    write_report,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Aggregate scKG Agent effectiveness, efficiency, stability, and compliance."
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--baseline",
        type=Path,
        help="Previous continuous evaluation latest.json used for regression comparison.",
    )
    parser.add_argument("--history", type=Path)
    parser.add_argument(
        "--freeze-baseline",
        type=Path,
        help="Write this result as a new immutable candidate baseline; refuses overwrite.",
    )
    args = parser.parse_args()
    token = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report = ContinuousAgentEvaluator().evaluate(
        evaluation_id=f"continuous-agent-quality-{token}",
        baseline_path=args.baseline,
    )
    write_report(report, output_dir=args.output, history_path=args.history)
    if args.freeze_baseline:
        freeze_baseline(report, baseline_path=args.freeze_baseline)
    print(
        json.dumps(
            {
                "evaluation_id": report.evaluation_id,
                "release_signal": report.release_signal,
                "category_signals": {
                    row.category: row.signal for row in report.category_summaries
                },
                "measured_metrics": report.coverage.measured_metric_count,
                "total_metrics": report.coverage.total_metric_count,
                "release_gate_coverage": (
                    report.coverage.measured_release_metric_count
                    / max(1, report.coverage.release_metric_count)
                ),
                "zero_tolerance_violations": report.zero_tolerance_violation_count,
                "regression_status": report.regression_status,
                "regression_count": report.regression_count,
                "warnings": report.warnings,
                "output": str(args.output),
                "frozen_baseline": str(args.freeze_baseline)
                if args.freeze_baseline
                else None,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 1 if report.zero_tolerance_violation_count else 0


if __name__ == "__main__":
    raise SystemExit(main())
