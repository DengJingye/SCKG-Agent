import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List


DEFAULT_PREDICTIONS = Path(__file__).resolve().parent / "predictions.jsonl"
DEFAULT_OUTPUT = Path(__file__).resolve().parent / "review_queue.jsonl"


def load_jsonl(path: Path) -> List[Dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def build_review_queue(predictions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    tool_hits: Counter[str] = Counter()
    tool_missing: dict[str, Counter[str]] = defaultdict(Counter)
    tool_evidence_layers: dict[str, Counter[str]] = defaultdict(Counter)
    query_failures: List[Dict[str, Any]] = []

    for prediction in predictions:
        query_id = prediction["query_id"]
        if prediction.get("execution_status") != "ok":
            query_failures.append(
                {
                    "item_type": "query",
                    "query_id": query_id,
                    "priority": "high",
                    "reason": "prediction_not_ok",
                    "missing_components": prediction.get("missing_components", []),
                    "recommendation_type": prediction.get("recommendation_type"),
                    "clarification_state": prediction.get("parsed_constraints", {}).get("clarification_state"),
                }
            )

        for tool in prediction.get("candidate_tools", []) + prediction.get("scored_tools", []):
            tool_name = tool.get("tool_name")
            if not tool_name:
                continue
            tool_hits[tool_name] += 1
            evidence = tool.get("evidence", {})
            for missing in evidence.get("missing_evidence", []):
                tool_missing[tool_name][missing] += 1
            for item in evidence.get("items", []):
                layer = item.get("graph_layer", "unknown")
                trust = item.get("trust_level", "unknown")
                tool_evidence_layers[tool_name][f"{layer}:{trust}"] += 1

    queue: List[Dict[str, Any]] = []
    for tool_name, hits in tool_hits.most_common():
        missing = dict(tool_missing[tool_name])
        layers = dict(tool_evidence_layers[tool_name])
        experimental_count = sum(
            count for layer, count in layers.items()
            if layer.startswith("experimental:")
        )
        trusted_count = sum(
            count for layer, count in layers.items()
            if layer.startswith("trusted_core:") or ":source_based" in layer or ":verified" in layer
        )
        if missing or experimental_count > trusted_count:
            queue.append(
                {
                    "item_type": "tool",
                    "tool_name": tool_name,
                    "priority": _priority(hits, missing, experimental_count, trusted_count),
                    "hit_count": hits,
                    "missing_components": missing,
                    "evidence_layer_counts": layers,
                    "recommended_action": _recommended_action(missing, experimental_count, trusted_count),
                }
            )

    return query_failures + queue


def _priority(
    hits: int,
    missing: Dict[str, int],
    experimental_count: int,
    trusted_count: int,
) -> str:
    if hits >= 3 and ("trusted_recommendation_evidence" in missing or trusted_count == 0):
        return "critical"
    if hits >= 2 or experimental_count > trusted_count:
        return "high"
    return "medium"


def _recommended_action(
    missing: Dict[str, int],
    experimental_count: int,
    trusted_count: int,
) -> str:
    actions = []
    if "trusted_recommendation_evidence" in missing or trusted_count == 0:
        actions.append("verify official docs or paper evidence before recommendation")
    if "benchmark" in missing:
        actions.append("add benchmark evidence or keep ranking low-confidence")
    if "literature" in missing:
        actions.append("add paper/citation evidence")
    if "engineering" in missing:
        actions.append("refresh GitHub metadata")
    if experimental_count > trusted_count:
        actions.append("move LLM-extracted relations to review_needed or trusted_core after audit")
    return "; ".join(actions) if actions else "manual review"


def write_jsonl(records: List[Dict[str, Any]], path: Path) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build evidence governance review queue.")
    parser.add_argument("--predictions", type=Path, default=DEFAULT_PREDICTIONS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    predictions = load_jsonl(args.predictions)
    queue = build_review_queue(predictions)
    write_jsonl(queue, args.output)
    print(f"wrote {len(queue)} review items to {args.output}")


if __name__ == "__main__":
    main()
