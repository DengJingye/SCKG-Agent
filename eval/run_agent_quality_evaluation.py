from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from eval.agent_quality_evaluation import (
    DEFAULT_CASES,
    DEFAULT_OUTPUT,
    AgentQualityEvaluator,
    compare_with_baseline,
    load_cases,
    write_artifacts,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run deterministic scKG Agent quality evaluation.")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--repetitions", type=int, default=3)
    args = parser.parse_args()

    cases = load_cases(args.cases)
    runs, summary = AgentQualityEvaluator().evaluate(
        cases,
        repetitions=args.repetitions,
    )
    regression = compare_with_baseline(summary, args.baseline)
    write_artifacts(args.output, runs, summary, regression)
    print(
        json.dumps(
            {
                "summary": asdict(summary),
                "regression": asdict(regression),
                "output": str(args.output),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if summary.release_gate_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
