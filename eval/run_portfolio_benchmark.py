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

from eval.portfolio_evaluation import PortfolioEvaluator


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Phase 6 portfolio benchmark.")
    parser.add_argument("--llm", action="store_true", help="Run the 16 x 3 LLM comparison.")
    parser.add_argument("--limit", type=int, default=None, help="Limit representative cases for a smoke.")
    parser.add_argument("--output-root", type=Path, default=None)
    parser.add_argument(
        "--resume-from",
        type=Path,
        default=None,
        help="Reuse existing per_case_results.jsonl rows and run only missing case/baseline pairs.",
    )
    parser.add_argument(
        "--replay-only",
        action="store_true",
        help="Re-adjudicate saved raw responses without creating model calls.",
    )
    parser.add_argument("--input-cost-per-million", type=float, default=None)
    parser.add_argument("--output-cost-per-million", type=float, default=None)
    args = parser.parse_args()
    token = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_root = args.output_root or PROJECT_ROOT / ".sckg_exec" / "evaluations" / f"portfolio-{token}"
    result = PortfolioEvaluator(
        output_root=output_root,
        input_cost_per_million=args.input_cost_per_million,
        output_cost_per_million=args.output_cost_per_million,
    ).run(
        use_llm=args.llm,
        limit=args.limit,
        resume_results_path=args.resume_from,
        replay_only=args.replay_only,
    )
    summary = result["summary"].model_dump(mode="json")
    print(json.dumps({**summary, "output_root": str(output_root)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
