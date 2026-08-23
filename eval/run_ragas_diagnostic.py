from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.settings import PROJECT_ROOT


OUTPUT = PROJECT_ROOT / "data" / "evaluation" / "ragas_diagnostic_v2.json"
REQUIRED_CONFIRMATION = "I AUTHORIZE RAGAS EVALUATOR CALLS"


def diagnostic_status(*, authorize_outbound: bool, confirmation_text: str) -> dict:
    ragas_available = importlib.util.find_spec("ragas") is not None
    if not authorize_outbound or confirmation_text != REQUIRED_CONFIRMATION:
        return {
            "schema_version": "ragas-diagnostic-v2.0",
            "evaluated_at": datetime.now(timezone.utc).isoformat(),
            "status": "not_run",
            "reason": "explicit_evaluator_consent_missing",
            "ragas_available": ragas_available,
            "metrics": [
                "context_precision",
                "context_recall",
                "faithfulness",
                "response_relevancy",
            ],
            "authority": "secondary_diagnostic_only",
        }
    if not ragas_available:
        return {
            "schema_version": "ragas-diagnostic-v2.0",
            "evaluated_at": datetime.now(timezone.utc).isoformat(),
            "status": "not_run",
            "reason": "ragas_eval_environment_unavailable",
            "ragas_available": False,
            "metrics": [],
            "authority": "secondary_diagnostic_only",
        }
    return {
        "schema_version": "ragas-diagnostic-v2.0",
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "status": "not_run",
        "reason": "evaluator_provider_not_configured_for_this_run",
        "ragas_available": True,
        "metrics": [],
        "authority": "secondary_diagnostic_only",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Optional governed RAGAS diagnostic.")
    parser.add_argument("--authorize-outbound", action="store_true")
    parser.add_argument("--confirmation-text", default="")
    args = parser.parse_args()
    payload = diagnostic_status(
        authorize_outbound=args.authorize_outbound,
        confirmation_text=args.confirmation_text,
    )
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
