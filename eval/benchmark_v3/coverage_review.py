"""Offline review sidecars; retrieval scores never assign coverage labels.

No production imports, provider calls, or Gold promotion. Reviewer identity and
scientific entailment require the human process documented in scoring_protocol.md.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

SOURCES = ("scientific_kg_v2", "legacy_kg", "ordinary_rag")
COARSE = {
    "111": "shared",
    "110": "shared",
    "101": "shared",
    "011": "shared",
    "100": "v2-only",
    "010": "legacy-only",
    "001": "rag-only",
    "000": "out-of-knowledge",
}
ALLOWED_KINDS = {
    "scientific_kg_v2": {"approved_statement"},
    "legacy_kg": {"legacy_candidate_claim", "rag_chunk", "catalog_metadata"},
    "ordinary_rag": {"rag_chunk", "catalog_metadata"},
}


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()


def make_cell(
    scenario_id: str, fact: dict, source: str, snapshot: dict, search: dict
) -> dict:
    if source not in SOURCES:
        raise ValueError("unknown coverage source")
    return {
        "scenario_id": scenario_id,
        "fact_id": fact["fact_id"],
        "fact_digest": digest(fact),
        "source": source,
        "snapshot_id": snapshot["snapshot_id"],
        "snapshot_digest": snapshot["digest"],
        "search_evidence": search,
        "reviews": [],
        "resolution": None,
        "status": "unknown",
        "gold_status": "none",
    }


def _validate_decision(decision: dict, cell: dict, registry: dict[str, dict]) -> None:
    for key in ("reviewer_id", "reviewed_at", "rationale"):
        if not isinstance(decision.get(key), str) or not decision[key].strip():
            raise ValueError(f"review needs {key}")
    status = decision.get("status")
    if status not in {"present", "absent", "unknown"}:
        raise ValueError("invalid reviewer coverage status")
    if status == "present":
        supports = decision.get("supports", [])
        if not supports:
            raise ValueError("present needs supporting IDs, excerpts and scope")
        for support in supports:
            record = registry.get(support.get("record_id"))
            if (
                not record
                or not record.get("consumer_eligible")
                or record.get("kind") not in ALLOWED_KINDS[cell["source"]]
            ):
                raise ValueError("support is not permitted consumer-visible knowledge")
            excerpt = support.get("excerpt", "")
            evidence = record.get("evidence", {}).get(support.get("evidence_id"), "")
            if not excerpt.strip() or excerpt not in evidence:
                raise ValueError("excerpt/evidence ID not bound to frozen record")
            for key in (
                "scope_and_version",
                "applicability_reason",
                "entailment_reason",
            ):
                if not support.get(key):
                    raise ValueError(f"support needs {key}")
            if (
                record["kind"] == "catalog_metadata"
                and support.get("assertion_class") != "catalog_discovery_metadata"
            ):
                raise ValueError(
                    "catalog metadata cannot support scientific recommendations or execution"
                )
    if status == "absent":
        procedure = decision.get("negative_search", {})
        for key in (
            "search_scope",
            "query_variants",
            "record_inventory_digest",
            "related_results",
            "insufficiency_reason",
        ):
            # related_results may explicitly be [] when nothing was relevant.
            if key not in procedure or (
                key != "related_results" and not procedure[key]
            ):
                raise ValueError(f"absent needs negative-search {key}")
        if procedure["record_inventory_digest"] != digest(registry):
            raise ValueError("negative search refers to another inventory")
        if (
            not isinstance(procedure["query_variants"], list)
            or len(procedure["query_variants"]) < 2
        ):
            raise ValueError("negative search requires at least two query variants")
        for result in procedure["related_results"]:
            if result.get("record_id") not in registry or not result.get(
                "insufficiency_reason"
            ):
                raise ValueError("invalid related-result negative evidence")


def resolve_cell(
    cell: dict, fact: dict, snapshot: dict, registry: dict[str, dict]
) -> str:
    """Two independent reviews, or two reviews plus a separate 00 resolution.

    Stored status is never authoritative. Frozen fact/source digests prevent
    reuse of a review after changing the question requirements or corpus.
    """
    if cell["fact_id"] != fact["fact_id"] or cell["fact_digest"] != digest(fact):
        raise ValueError("stale fact review")
    if (
        cell["snapshot_digest"] != snapshot["digest"]
        or cell["snapshot_id"] != snapshot["snapshot_id"]
    ):
        raise ValueError("stale snapshot review")
    reviews = cell["reviews"]
    identities = [r.get("reviewer_id") for r in reviews]
    if len(set(identities)) != len(identities) or len(reviews) > 2:
        raise ValueError("exactly two distinct reviewer identities required")
    for review in reviews:
        _validate_decision(review, cell, registry)
    if len(reviews) < 2:
        return "unknown"
    statuses = {r["status"] for r in reviews}
    if len(statuses) == 1:
        return reviews[0]["status"]
    resolution = cell.get("resolution")
    if not resolution:
        return "unknown"
    if (
        resolution.get("role") != "00-adjudicator"
        or resolution.get("reviewer_id") in identities
    ):
        raise ValueError("disagreement needs an independent 00 adjudicator")
    _validate_decision(resolution, cell, registry)
    return resolution["status"]


def aggregate(
    facts: list[dict],
    statuses: dict[tuple[str, str], str],
    *,
    requirements_reviewed: bool,
    scientific_applicability: str = "applicable",
) -> dict:
    unknown = {source: "unknown" for source in SOURCES}
    if not requirements_reviewed:
        return dict(
            unknown,
            exact_signature=None,
            coarse_label=None,
            audit_status="needs_adjudication",
        )
    if scientific_applicability == "not_applicable":
        if facts:
            raise ValueError("runtime-only coverage cannot contain scientific facts")
        return {
            **{s: "not_applicable" for s in SOURCES},
            "exact_signature": None,
            "coarse_label": None,
            "audit_status": "not_applicable",
        }
    if (
        scientific_applicability != "applicable"
        or not facts
        or not any(f["critical"] for f in facts)
    ):
        raise ValueError("applicable coverage needs critical scientific requirements")
    ids = [f["fact_id"] for f in facts]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate fact IDs")
    vector = {}
    for source in SOURCES:
        cells = [
            statuses.get((f["fact_id"], source), "unknown")
            for f in facts
            if f["critical"]
        ]
        if any(c not in {"present", "absent", "unknown"} for c in cells):
            raise ValueError("invalid cell status")
        # Conservatively require all critical cells reviewed even if one is absent.
        vector[source] = (
            "unknown"
            if "unknown" in cells
            else "absent" if "absent" in cells else "present"
        )
    signature = (
        None
        if "unknown" in vector.values()
        else "".join("1" if vector[s] == "present" else "0" for s in SOURCES)
    )
    return dict(
        vector,
        exact_signature=signature,
        coarse_label=COARSE.get(signature),
        audit_status="audited" if signature else "needs_adjudication",
    )


def audit_scenario(
    scenario: dict, cells: list[dict], snapshots: dict, records: dict
) -> dict:
    facts = {f["fact_id"]: f for f in scenario["required_scientific_facts"]}
    if len(facts) != len(scenario["required_scientific_facts"]):
        raise ValueError("duplicate fact IDs")
    statuses = {}
    for cell in cells:
        key = (cell["fact_id"], cell["source"])
        if (
            cell["scenario_id"] != scenario["scenario_id"]
            or key in statuses
            or key[0] not in facts
            or key[1] not in SOURCES
        ):
            raise ValueError("unexpected or duplicate coverage cell")
        if cell.get("scenario_input_digest") != digest(scenario["input"]):
            raise ValueError("stale scenario input review")
        statuses[key] = resolve_cell(
            cell, facts[key[0]], snapshots[key[1]], records[key[1]]
        )
    summary = aggregate(
        list(facts.values()),
        statuses,
        requirements_reviewed=scenario["requirements_review_status"] == "adjudicated",
        scientific_applicability=scenario["scientific_applicability"],
    )
    return dict(
        summary,
        fact_statuses=[
            {
                "fact_id": fact_id,
                "source": source,
                "resolved_status": statuses.get((fact_id, source), "unknown"),
            }
            for fact_id in facts
            for source in SOURCES
        ],
    )
