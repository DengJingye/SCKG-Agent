from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from engine.evidence_discovery_index import load_chunks
from engine.hybrid_retrieval import HybridRetrievalService
from eval.retrieval_evaluation import (
    PROFILES,
    build_annotation_gold_cases,
    evaluate_profile,
    read_gold_cases,
    write_gold_cases,
)


DEFAULT_GOLD = PROJECT_ROOT / "eval" / "fixtures" / "annotation_retrieval_gold_v2.json"
DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "evaluation" / "annotation_retrieval_v2"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evaluate planning-only CellTypist and SingleR source admission."
    )
    parser.add_argument("--gold", type=Path, default=DEFAULT_GOLD)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--rebuild-gold", action="store_true")
    args = parser.parse_args()

    chunks = load_chunks(PROJECT_ROOT / "data" / "indexes" / "evidence_chunks.jsonl")
    if args.rebuild_gold or not args.gold.is_file():
        write_gold_cases(args.gold, build_annotation_gold_cases(chunks))
    cases = read_gold_cases(args.gold)
    service = HybridRetrievalService()
    worker_status = service.wait_for_dense_ready(timeout=60.0)
    args.output.mkdir(parents=True, exist_ok=True)
    profiles = {}
    for profile in PROFILES:
        summary, rows = evaluate_profile(service, cases, profile)
        profiles[profile.profile_id] = summary.model_dump(mode="json")
        (args.output / f"cases_{profile.profile_id}.jsonl").write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
            encoding="utf-8",
        )
    report = {
        "schema_version": "annotation-retrieval-admission-v2",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "case_count": len(cases),
        "tools": ["CellTypist", "SingleR"],
        "execution_status": "implemented_unqualified",
        "source_quarantine_enforced": True,
        "embedding_worker": worker_status.model_dump(mode="json"),
        "profiles": profiles,
    }
    (args.output / "summary.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
