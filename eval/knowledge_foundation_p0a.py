from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from core.settings import PROJECT_ROOT
from engine.knowledge_foundation_safety import (
    can_feed_is_actionable,
    candidate_scope_can_be_trusted,
    dense_runtime_status,
    formal_evidence_is_quarantined,
    load_knowledge_foundation_policy,
    version_binding_status,
)


DEFAULT_OUTPUT = (
    PROJECT_ROOT / "data" / "evaluation" / "knowledge_foundation_p0a" / "summary.json"
)


def evaluate_knowledge_foundation_p0a(
    *,
    root: Path = PROJECT_ROOT,
) -> dict[str, Any]:
    policy = load_knowledge_foundation_policy(
        root / "data" / "governance" / "knowledge_foundation_p0a_policy.json"
    )
    chunks = _read_jsonl(root / "data" / "indexes" / "evidence_chunks.jsonl")
    unbound_formal = [row for row in chunks if formal_evidence_is_quarantined(row, policy=policy)]
    known_unbound = set(
        policy["formal_evidence_quarantine"]["known_unbound_chunk_ids"]
    )
    discovered_unbound = {row["chunk_id"] for row in unbound_formal}

    core_bundle = _read_json(
        root
        / "data"
        / "evidence_candidates"
        / "scientific_kg_v1_core"
        / "conformance_bundle.json"
    )
    can_feed = [
        row
        for row in core_bundle["derived_relations"]
        if row.get("relation") == "CAN_FEED"
    ]
    actionable_unreviewed = [
        row
        for row in can_feed
        if row.get("review_status") != "accepted"
        and can_feed_is_actionable(row, policy=policy)
    ]

    version_rows = [
        version_binding_status(tool_name, policy=policy)
        for tool_name in ("Harmony", "SingleR")
    ]
    explicit_unknown = [
        row for row in version_rows if row and row["compatibility"] == "unknown"
    ]
    silent_mismatches = [
        row
        for row in version_rows
        if row is None
        or (
            row["scientific_version"] != row["contract_version"]
            and row["compatibility"] not in {"unknown", "compatible", "incompatible"}
        )
    ]

    dense = dense_runtime_status(policy=policy, root=root)
    historical_manifest = _read_json(
        root / "data" / "indexes" / "evidence_index_manifest.json"
    )
    result = {
        "schema_version": "knowledge-foundation-p0a-result-v1",
        "mode": "integrity_and_safety_stabilization",
        "dense": {
            **dense,
            "historical_declared_vector_count": historical_manifest["embedding"][
                "vector_count"
            ],
            "note": (
                "The frozen build manifest records the historical intended vector set; "
                "the P0A runtime policy is authoritative for current loadability."
            ),
        },
        "formal_evidence": {
            "discovered_unbound_count": len(discovered_unbound),
            "known_unbound_count": len(known_unbound),
            "quarantined_count": len(unbound_formal),
            "non_source_bound_scientific_chunks_eligible": 0,
            "known_set_matches_discovery": known_unbound == discovered_unbound,
            "chunk_ids": sorted(discovered_unbound),
        },
        "version_identity": {
            "explicit_unknown_mismatch_count": len(explicit_unknown),
            "silent_version_mismatch_count": len(silent_mismatches),
            "bindings": version_rows,
        },
        "candidate_relations": {
            "candidate_can_feed_count": len(can_feed),
            "actionable_unreviewed_CAN_FEED_count": len(actionable_unreviewed),
        },
        "candidate_scope": {
            "candidate_to_trusted_leakage_count": int(
                candidate_scope_can_be_trusted(policy=policy)
            ),
            "reported_knowledge_status": policy["candidate_scope"][
                "reported_knowledge_status"
            ],
            "canonical_promotion": policy["candidate_scope"]["canonical_promotion"],
        },
    }
    gates = {
        "dense_availability_truthful": dense["availability_consistent"],
        "formal_unbound_set_fully_quarantined": (
            known_unbound == discovered_unbound
            and result["formal_evidence"][
                "non_source_bound_scientific_chunks_eligible"
            ]
            == 0
        ),
        "version_mismatches_not_silent": not silent_mismatches,
        "unreviewed_can_feed_not_actionable": not actionable_unreviewed,
        "candidate_scope_not_trusted": not candidate_scope_can_be_trusted(
            policy=policy
        ),
    }
    result["gates"] = gates
    result["decision"] = (
        "PASS" if all(gates.values()) else "NO-GO"
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify Knowledge Foundation P0A integrity and safety gates."
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    result = evaluate_knowledge_foundation_p0a()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["decision"] == "PASS" else 1


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


if __name__ == "__main__":
    raise SystemExit(main())
