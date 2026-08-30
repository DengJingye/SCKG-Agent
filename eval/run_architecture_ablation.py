from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from eval.architecture_ablation import (
    load_fixed_research_cases,
    run_ledger_ablation,
    run_research_ablation,
)


DEFAULT_GOLD = PROJECT_ROOT / "eval" / "fixtures" / "retrieval_gold_v2.json"
DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / ".sckg_exec" / "evaluations"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run fixed, paired scKG architecture ablations."
    )
    parser.add_argument("--gold", type=Path, default=DEFAULT_GOLD)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    output = args.output or (
        DEFAULT_OUTPUT_ROOT
        / datetime.now(timezone.utc).strftime("architecture-%Y%m%dT%H%M%SZ")
    )
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    cases, case_digest = load_fixed_research_cases(args.gold, limit=args.limit)
    research = run_research_ablation(
        cases=cases,
        output_dir=output / "research",
    )
    ledger = run_ledger_ablation(output_dir=output / "ledger")
    summary = {
        "schema_version": "sckg-architecture-ablation-run-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "case_digest": case_digest,
        "case_count": len(cases),
        "research": research,
        "representation_ledger": ledger,
        "production_ablation_branch_added": False,
        "execution_policy": "disabled",
        "scientific_qualification": "not_run",
    }
    (output / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "output": str(output),
                "case_count": len(cases),
                "research_gates": {
                    mode: row["release_gate"]
                    for mode, row in research["modes"].items()
                },
                "ledger_aware_methods": ledger["ledger_aware"][
                    "planned_method_ids"
                ],
                "ledger_hidden_method_count": len(
                    ledger["ledger_hidden"]["planned_method_ids"]
                ),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
