from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from eval.live_llm_runtime import resolve_live_llm_runtime
from eval.open_world_evaluation import (
    HIDDEN_CONFIRMATION,
    REQUIRED_CONFIRMATION,
    run_open_world_ablation,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the governed open-world Research Chat ablation."
    )
    parser.add_argument("--authorize-outbound", action="store_true")
    parser.add_argument("--confirmation", default="")
    parser.add_argument("--passphrase", default=None)
    parser.add_argument(
        "--credential-source",
        choices=("auto", "encrypted", "environment"),
        default="auto",
        help=(
            "Select the already-configured local credential source explicitly. "
            "The default keeps encrypted-store precedence."
        ),
    )
    parser.add_argument("--call-budget", type=int, default=200)
    parser.add_argument("--include-hidden", action="store_true")
    parser.add_argument("--hidden-confirmation", default="")
    parser.add_argument("--output-dir", type=Path, default=None)
    args = parser.parse_args()

    runtime = (
        resolve_live_llm_runtime(
            passphrase=args.passphrase,
            credential_source=args.credential_source,
        )
        if args.authorize_outbound
        else None
    )
    output_dir = args.output_dir or (
        PROJECT_ROOT
        / ".sckg_exec/evaluations"
        / (
            "open-world-"
            + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        )
    )
    summary = run_open_world_ablation(
        output_dir=output_dir,
        runtime_config=(runtime.runtime_config if runtime else {}),
        safe_runtime_metadata=(runtime.safe_metadata if runtime else {}),
        authorize_outbound=bool(
            args.authorize_outbound and runtime and runtime.status == "ready"
        ),
        confirmation_text=args.confirmation,
        provider_call_budget=args.call_budget,
        include_hidden=args.include_hidden,
        hidden_confirmation=args.hidden_confirmation,
    )
    print(
        json.dumps(
            {
                "output_dir": str(output_dir),
                "hard_gate_passed": summary.hard_gate_passed,
                "completed_provider_calls": summary.completed_provider_calls,
                "gate_failures": summary.gate_failures,
                "required_confirmation": REQUIRED_CONFIRMATION,
                "hidden_confirmation": HIDDEN_CONFIRMATION,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if summary.hard_gate_passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
