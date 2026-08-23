from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.settings import PROJECT_ROOT
from engine.decision_graph_builder import DecisionGraphBuilder


def main() -> None:
    _, _, quality = DecisionGraphBuilder(data_dir=PROJECT_ROOT / "data").build(write=True)
    print(json.dumps(quality.model_dump(mode="json"), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
