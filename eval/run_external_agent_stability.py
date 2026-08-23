from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from eval.agent_quality_evaluation import load_cases
from eval.external_agent_stability import (
    DEFAULT_OUTPUT,
    REQUIRED_CONFIRMATION,
    run_external_evaluation,
)
from eval.live_llm_runtime import resolve_live_llm_runtime


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Optional 20-case x 3-run external model stability diagnostic."
    )
    parser.add_argument("--authorize-outbound", action="store_true")
    parser.add_argument("--confirmation-text", default="")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--smoke-summary", type=Path)
    args = parser.parse_args()
    runtime = resolve_live_llm_runtime()
    summary = run_external_evaluation(
        load_cases(),
        authorize_outbound=args.authorize_outbound,
        confirmation_text=args.confirmation_text,
        runtime_config=runtime.runtime_config if runtime.status == "ready" else None,
        safe_runtime_metadata=runtime.safe_metadata,
        smoke_summary_path=args.smoke_summary,
        output_dir=args.output,
    )
    print(json.dumps(asdict(summary), ensure_ascii=False, indent=2))
    if summary.status == "not_run":
        print(f"To authorize: --authorize-outbound --confirmation-text '{REQUIRED_CONFIRMATION}'")
    return 0 if summary.gate_passed or summary.status == "not_run" else 2


if __name__ == "__main__":
    raise SystemExit(main())
