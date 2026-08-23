from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from engine.canonical_knowledge_builder import CanonicalKnowledgeBuilder


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build source corpus v2 plus canonical catalog/decision graph projections."
    )
    parser.add_argument(
        "--reuse-corpus",
        action="store_true",
        help="Reuse the existing evidence index manifest instead of rebuilding chunks.",
    )
    args = parser.parse_args()
    snapshot = CanonicalKnowledgeBuilder(project_root=PROJECT_ROOT).build(
        write=True,
        rebuild_corpus=not args.reuse_corpus,
    )
    print(json.dumps(snapshot.model_dump(mode="json"), indent=2, ensure_ascii=False))
    if not snapshot.integrity_passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
