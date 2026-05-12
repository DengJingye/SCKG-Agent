import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from connectors.graph_client import Neo4jClient
from core.settings import get_settings


NODE_QUERY = """
MATCH (n)
RETURN elementId(n) AS element_id, labels(n) AS labels, properties(n) AS properties
ORDER BY element_id
"""

RELATIONSHIP_QUERY = """
MATCH (a)-[r]->(b)
RETURN
  elementId(r) AS element_id,
  type(r) AS type,
  elementId(a) AS start_element_id,
  labels(a) AS start_labels,
  properties(a) AS start_properties,
  elementId(b) AS end_element_id,
  labels(b) AS end_labels,
  properties(b) AS end_properties,
  properties(r) AS properties
ORDER BY element_id
"""


def json_default(value: Any) -> Any:
    if isinstance(value, (datetime,)):
        return value.isoformat()
    if hasattr(value, "iso_format"):
        return value.iso_format()
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def stable_node_key(labels: list[str], properties: dict[str, Any], fallback: str) -> str:
    for key in ("name", "evidence_id", "id", "doi", "pmid"):
        value = properties.get(key)
        if value not in (None, ""):
            return f"{'+'.join(labels)}:{key}:{value}"
    return fallback


def export_snapshot(output_path: Path, include_relationships: bool = True) -> dict[str, Any]:
    settings = get_settings()
    exported_at = datetime.now(timezone.utc).isoformat()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    client = Neo4jClient()
    node_count = 0
    relationship_count = 0
    try:
        with output_path.open("w", encoding="utf-8") as handle:
            for row in client.execute_query(NODE_QUERY):
                labels = list(row.get("labels") or [])
                properties = dict(row.get("properties") or {})
                record = {
                    "record_type": "node",
                    "exported_at": exported_at,
                    "kg_version": settings.kg_version,
                    "element_id": row.get("element_id"),
                    "stable_key": stable_node_key(labels, properties, str(row.get("element_id"))),
                    "labels": labels,
                    "properties": properties,
                }
                handle.write(json.dumps(record, ensure_ascii=False, default=json_default) + "\n")
                node_count += 1

            if include_relationships:
                for row in client.execute_query(RELATIONSHIP_QUERY):
                    start_labels = list(row.get("start_labels") or [])
                    start_properties = dict(row.get("start_properties") or {})
                    end_labels = list(row.get("end_labels") or [])
                    end_properties = dict(row.get("end_properties") or {})
                    record = {
                        "record_type": "relationship",
                        "exported_at": exported_at,
                        "kg_version": settings.kg_version,
                        "element_id": row.get("element_id"),
                        "type": row.get("type"),
                        "start_element_id": row.get("start_element_id"),
                        "start_stable_key": stable_node_key(
                            start_labels,
                            start_properties,
                            str(row.get("start_element_id")),
                        ),
                        "start_labels": start_labels,
                        "end_element_id": row.get("end_element_id"),
                        "end_stable_key": stable_node_key(
                            end_labels,
                            end_properties,
                            str(row.get("end_element_id")),
                        ),
                        "end_labels": end_labels,
                        "properties": dict(row.get("properties") or {}),
                    }
                    handle.write(json.dumps(record, ensure_ascii=False, default=json_default) + "\n")
                    relationship_count += 1
    finally:
        client.close()

    return {
        "output_path": str(output_path),
        "node_count": node_count,
        "relationship_count": relationship_count,
        "include_relationships": include_relationships,
        "exported_at": exported_at,
        "kg_version": settings.kg_version,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Export a read-only Neo4j graph snapshot to JSONL.")
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "data" / "graph_snapshots" / "neo4j_snapshot.jsonl",
        help="Snapshot JSONL output path.",
    )
    parser.add_argument(
        "--nodes-only",
        action="store_true",
        help="Export nodes only, without relationships.",
    )
    args = parser.parse_args()
    summary = export_snapshot(args.output, include_relationships=not args.nodes_only)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
