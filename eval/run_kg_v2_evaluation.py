from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from eval.kg_v2_evaluation import evaluate_kg_v2, write_evaluation_artifacts


def main() -> None:
    cases, summary = evaluate_kg_v2(data_dir=PROJECT_ROOT / "data")
    write_evaluation_artifacts(output_dir=PROJECT_ROOT / "eval" / "kg_v2", cases=cases, summary=summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if summary["status"] != "passed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
