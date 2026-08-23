from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from eval.live_llm_runtime import resolve_live_llm_runtime
from eval.live_llm_smoke import REQUIRED_CONFIRMATION, run_live_llm_smoke


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the gated 5-turn live DeepSeek smoke.")
    parser.add_argument("--authorize-outbound", action="store_true")
    parser.add_argument("--confirmation-text", default="")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output = args.output or PROJECT_ROOT / ".sckg_exec/evaluations" / f"live-llm-smoke-{stamp}"
    runtime = resolve_live_llm_runtime()
    summary = run_live_llm_smoke(
        authorize_outbound=args.authorize_outbound,
        confirmation_text=args.confirmation_text,
        runtime_config=runtime.runtime_config if runtime.status == "ready" else None,
        safe_runtime_metadata=runtime.safe_metadata,
        output_dir=output,
    )
    if runtime.status != "ready" and summary.reason == "llm_credentials_not_configured":
        payload = {**asdict(summary), "runtime_blocker": runtime.reason, "output": str(output)}
    else:
        payload = {**asdict(summary), "output": str(output)}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if summary.status == "blocked":
        print(
            "Save and unlock the encrypted API config in Settings, then expose only "
            "SCKG_API_CONFIG_PASSPHRASE to this process."
        )
    print(f"Required confirmation: {REQUIRED_CONFIRMATION}")
    return 0 if summary.gate_passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
