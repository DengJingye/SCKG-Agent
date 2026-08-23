from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from connectors.graph_client import Neo4jClient
from engine.neo4j_kg_v2_importer import Neo4jKGv2Importer


def main() -> None:
    parser = argparse.ArgumentParser(description="Import KG v2 into an isolated Neo4j shadow namespace.")
    parser.add_argument("--confirm-shadow-import", action="store_true")
    args = parser.parse_args()
    if not args.confirm_shadow_import:
        raise SystemExit("Refusing to write Neo4j without --confirm-shadow-import")
    graph_dir = PROJECT_ROOT / "data" / "knowledge_graph_v2"
    client = Neo4jClient()
    if client.driver is None:
        raise SystemExit("Neo4j is unavailable; JSONL snapshot remains canonical")
    try:
        result = Neo4jKGv2Importer(client.execute_query, batch_size=1000).import_snapshot(graph_dir)
    finally:
        client.close()
    manifest_path = graph_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["neo4j_imported"] = result.passed
    manifest["neo4j_import_status"] = "shadow_import_verified" if result.passed else "count_mismatch"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({**result.__dict__, "passed": result.passed}, ensure_ascii=False, indent=2))
    if not result.passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
