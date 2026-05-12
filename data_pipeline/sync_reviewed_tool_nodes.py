import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Dict, Iterable, List


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from connectors.graph_client import Neo4jClient
from core.evidence_schemas import APPROVED_REVIEW_STATUSES
from core.settings import get_settings
from core.task_ontology import tool_task_hints


DEFAULT_CATALOG = PROJECT_ROOT / "data" / "scrna_tools.tsv"
DEFAULT_PUBLICATIONS = PROJECT_ROOT / "data" / "tool_publications.tsv"
DEFAULT_BENCHMARKS = PROJECT_ROOT / "data" / "tool_benchmarks.tsv"
DEFAULT_PLAN_OUTPUT = PROJECT_ROOT / "eval" / "reviewed_tool_node_sync_plan.jsonl"


def load_tsv(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def normalize_name(value: str) -> str:
    return "".join(ch for ch in value.lower() if ch.isalnum())


def clean(value: str | None) -> str:
    return (value or "").strip()


def split_values(value: str | None) -> List[str]:
    raw = clean(value)
    if not raw:
        return []
    values = []
    for chunk in raw.replace("|", ";").split(";"):
        item = chunk.strip()
        if item and item.lower() not in {"unknown", "na", "none"}:
            values.append(item)
    return values


def approved(row: Dict[str, str]) -> bool:
    return clean(row.get("review_status")).lower() in APPROVED_REVIEW_STATUSES


def index_catalog(rows: Iterable[Dict[str, str]]) -> Dict[str, Dict[str, str]]:
    return {
        normalize_name(row.get("Tool", "")): row
        for row in rows
        if clean(row.get("Tool"))
    }


def values_from_evidence(tool_name: str, rows: Iterable[Dict[str, str]], field: str) -> List[str]:
    key = normalize_name(tool_name)
    values: List[str] = []
    seen = set()
    for row in rows:
        if normalize_name(row.get("tool_name", "")) != key:
            continue
        if not approved(row):
            continue
        for value in split_values(row.get(field)):
            normalized = value.lower()
            if normalized in seen:
                continue
            values.append(value)
            seen.add(normalized)
    return values


def build_plan(
    tool_names: List[str],
    catalog_rows: List[Dict[str, str]],
    publication_rows: List[Dict[str, str]],
    benchmark_rows: List[Dict[str, str]],
) -> List[Dict[str, object]]:
    catalog = index_catalog(catalog_rows)
    records = []
    for tool_name in tool_names:
        catalog_row = catalog.get(normalize_name(tool_name), {})
        if not catalog_row:
            raise ValueError(f"{tool_name} is missing from data/scrna_tools.tsv")
        tasks = values_from_evidence(tool_name, publication_rows, "task")
        tasks.extend(value for value in values_from_evidence(tool_name, benchmark_rows, "task") if value not in tasks)
        for value in tool_task_hints(tool_name):
            if value not in tasks:
                tasks.append(value)
        if normalize_name(tool_name) == "scib":
            tasks = ["Benchmark Protocol", "Data Integration Benchmark"]
        if normalize_name(tool_name) == "velociraptor":
            tasks = ["Wrapper Interface", "RNA Velocity"]
        modalities = values_from_evidence(tool_name, publication_rows, "modality")
        modalities.extend(value for value in values_from_evidence(tool_name, benchmark_rows, "modality") if value not in modalities)
        records.append(
            {
                "tool_name": clean(catalog_row.get("Tool")) or tool_name,
                "language": clean(catalog_row.get("Platform")) or "Unknown",
                "github_url": clean(catalog_row.get("Code")),
                "description": clean(catalog_row.get("Description")),
                "license": clean(catalog_row.get("License")) or "Unknown",
                "publish_year": (clean(catalog_row.get("Added")) or "Unknown")[:4],
                "tasks": tasks or ["General Analysis"],
                "modalities": modalities or ["Single-cell"],
                "kg_version": get_settings().kg_version,
            }
        )
    return records


def write_plan(path: Path, records: List[Dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def apply_records(records: List[Dict[str, object]]) -> None:
    client = Neo4jClient()
    if client.offline_store is not None:
        client.close()
        raise RuntimeError(
            "Refusing to sync reviewed Tool nodes into the offline graph store. "
            "Set OFFLINE_GRAPH_FALLBACK=false and ensure AuraDB is reachable."
        )
    try:
        for record in records:
            client.execute_query(
                """
                MERGE (tool:Tool {name: $tool_name})
                SET tool.description = $description,
                    tool.github_url = $github_url,
                    tool.license = $license,
                    tool.publish_year = $publish_year,
                    tool.source_url = $github_url,
                    tool.source_type = 'human_reviewed_catalog',
                    tool.extraction_method = 'data_pipeline/sync_reviewed_tool_nodes.py',
                    tool.confidence = 0.9,
                    tool.trust_level = 'source_based',
                    tool.graph_layer = 'trusted_core',
                    tool.use_for = ['retrieval', 'ranking', 'recommendation'],
                    tool.review_status = 'human_reviewed',
                    tool.kg_version = $kg_version

                MERGE (lang:Language {name: $language})
                MERGE (tool)-[:WRITTEN_IN]->(lang)

                WITH tool
                UNWIND $tasks AS task_name
                MERGE (task:Task {name: task_name})
                MERGE (tool)-[:PERFORMS_TASK]->(task)

                WITH tool
                UNWIND $modalities AS modality_name
                MERGE (modality:Modality {name: modality_name})
                MERGE (tool)-[:SUPPORTS_MODALITY]->(modality)
                """,
                record,
            )
    finally:
        client.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Sync human-reviewed Tool nodes from catalog and formal evidence, without LLM extraction."
    )
    parser.add_argument("--tool", action="append", required=True)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--publications", type=Path, default=DEFAULT_PUBLICATIONS)
    parser.add_argument("--benchmarks", type=Path, default=DEFAULT_BENCHMARKS)
    parser.add_argument("--plan-output", type=Path, default=DEFAULT_PLAN_OUTPUT)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    records = build_plan(
        tool_names=args.tool,
        catalog_rows=load_tsv(args.catalog),
        publication_rows=load_tsv(args.publications),
        benchmark_rows=load_tsv(args.benchmarks),
    )
    write_plan(args.plan_output, records)
    if args.apply:
        apply_records(records)
    print(
        json.dumps(
            {
                "plan_output": str(args.plan_output),
                "tools": [record["tool_name"] for record in records],
                "records": len(records),
                "applied": bool(args.apply),
            },
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
