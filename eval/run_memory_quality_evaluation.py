from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from eval.memory_quality_evaluation import (
    DEFAULT_OUTPUT,
    MemoryQualityEvaluator,
    build_default_memory_cases,
    write_memory_artifacts,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run deterministic scKG Memory evaluation.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    results, summary = MemoryQualityEvaluator().evaluate(build_default_memory_cases())
    write_memory_artifacts(args.output, results, summary)
    print(
        json.dumps(
            {"summary": asdict(summary), "output": str(args.output)},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if summary.release_gate_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
