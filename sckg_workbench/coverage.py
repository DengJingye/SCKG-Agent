"""Auditable task coverage over an already governed, read-only release snapshot.

Keyword matches only suggest material to inspect. They never grant scientific
support. Scope and support require two named, release-bound human reviews.
"""
from __future__ import annotations

from collections import Counter

from .storage import content_hash, utcnow


_DOMAINS = {
    "scrna": ("单细胞 RNA", ("scrna", "scRNA-seq", "单细胞转录")),
    "rna_protein": ("RNA–蛋白", ("ADT", "CITE-seq", "totalVI", "RNA-蛋白", "RNA与蛋白")),
    "rna_atac": ("RNA–ATAC", ("RNA-ATAC", "RNA与ATAC", "MultiVI", "multiome", "多组学")),
    "pairing_missingness": ("配对、非配对与缺失模态", ("配对", "非配对", "unpaired", "paired", "missing modality", "缺失模态")),
    "spatial_basic": ("基础空间分析", ("空间", "spatial", "Stereo-seq", "Visium")),
}

_TASKS = {
    "input_qc": ("输入与质控", ("输入", "QC", "质控", "counts", "fragment")),
    "method_choice": ("方法选择", ("方法", "适用", "requires", "支持", "条件")),
    "interpretation": ("结果解释", ("解释", "输出", "潜空间", "图", "annotation")),
    "comparison": ("比较证据", ("比较", "benchmark", "指标", "基线", "重复")),
    "version": ("软件版本与依赖", ("版本", "version", "release", "依赖", "参数")),
    "failure": ("失败与限制", ("限制", "失败", "不适用", "缺失", "uncertainty")),
}


def _critical_conditions(domain: str, task: str) -> list[str]:
    checks = []
    if task in {"input_qc", "method_choice", "comparison", "failure"}:
        checks.append("input_representation")
    if domain in {"rna_protein", "rna_atac", "pairing_missingness"} and task in {
        "input_qc", "method_choice", "comparison", "failure"
    }:
        checks.append("pairing_and_missingness")
    if task in {"interpretation", "comparison"}:
        checks.append("statistical_unit")
    if domain == "spatial_basic" and task in {"input_qc", "method_choice", "interpretation", "comparison"}:
        checks.append("coordinate_frame_and_resolution")
    if task == "version":
        checks.append("software_version")
    return checks


def build_coverage_manifest() -> dict:
    """Draft task map. A cell is not in scope until both reviewers decide so."""
    cells = []
    for domain_id, (domain_title, domain_hints) in _DOMAINS.items():
        for task_id, (task_title, task_hints) in _TASKS.items():
            cells.append({
                "id": f"{domain_id}.{task_id}", "domain": domain_id, "task": task_id,
                "title": f"{domain_title} · {task_title}",
                "question": f"给定{domain_title}数据和研究目标，{task_title}应如何判断，哪些前提尚未确认？",
                "critical_conditions": _critical_conditions(domain_id, task_id),
                "search_hints": {"domain": list(domain_hints), "task": list(task_hints)},
                "scope_status": "proposed_for_two_reviewers",
            })
    manifest = {
        "schema_version": "sckg-task-coverage-v1", "target_use": "recommendation",
        "threshold": 0.9, "domains": {key: title for key, (title, _) in _DOMAINS.items()},
        "tasks": {key: title for key, (title, _) in _TASKS.items()}, "cells": cells,
    }
    manifest["manifest_hash"] = content_hash(manifest)
    return manifest


def _validate_manifest(manifest: dict) -> None:
    if manifest.get("schema_version") != "sckg-task-coverage-v1" or manifest.get("target_use") != "recommendation":
        raise ValueError("Unsupported coverage manifest")
    digest = manifest.get("manifest_hash")
    if digest != content_hash({k: v for k, v in manifest.items() if k != "manifest_hash"}):
        raise ValueError("Coverage manifest changed after freezing")
    cells = manifest.get("cells", [])
    if not cells or len({cell["id"] for cell in cells}) != len(cells):
        raise ValueError("Coverage cells must have unique identities")


def _discovery_clues(cell: dict, units: dict[str, dict]) -> tuple[list[str], list[str]]:
    """Literal leads only; a zero is not evidence of scientific absence."""
    found, sources = [], set()
    for cid, unit in units.items():
        claim = unit["claim"]
        text = " ".join(str(claim.get(key, "")) for key in (
            "proposition", "subject", "predicate", "object"
        )) + " " + " ".join(claim.get("conditions", []))
        text = text.casefold()
        hints = cell["search_hints"]
        if any(term.casefold() in text for term in hints["domain"]) and any(
            term.casefold() in text for term in hints["task"]
        ):
            found.append(cid)
            sources.update(e["source_id"] for e in unit["evidence"])
    return found, sorted(sources)


def _validated_reviews(reviews, manifest, snapshot, units):
    cells = {cell["id"]: cell for cell in manifest["cells"]}
    by_cell = {}
    seen = set()
    for review in reviews:
        cell_id = review.get("cell_id")
        reviewer = review.get("reviewer_id")
        if cell_id not in cells or not isinstance(reviewer, str) or not reviewer.strip():
            raise ValueError("Coverage review needs a known cell and named reviewer")
        if review.get("reviewer_role") != "domain_reviewer":
            raise ValueError("Coverage decisions require a declared domain reviewer")
        if (cell_id, reviewer) in seen:
            raise ValueError("One reviewer cannot vote twice on a cell")
        seen.add((cell_id, reviewer))
        if (review.get("manifest_hash") != manifest["manifest_hash"]
                or review.get("release_id") != snapshot["release_id"]
                or review.get("governance_version") != snapshot["governance_version"]
                or review.get("snapshot_hash") != snapshot["snapshot_hash"]):
            raise ValueError("Coverage review must bind the exact map, release and snapshot state")
        if not isinstance(review.get("reason"), str) or not review["reason"].strip():
            raise ValueError("Coverage review needs a reason")
        if review.get("scope") not in {"in", "out", "unsure"}:
            raise ValueError("Invalid coverage scope decision")
        ids = review.get("evidence_ids", [])
        critical = review.get("critical_evidence", {})
        if (not isinstance(ids, list) or len(ids) != len(set(ids)) or set(ids) - units.keys()
                or not isinstance(critical, dict)):
            raise ValueError("Coverage evidence must use distinct eligible IDs from the frozen release")
        if set(critical) - set(cells[cell_id]["critical_conditions"]):
            raise ValueError("Unknown critical condition")
        if any(not isinstance(v, list) or not v or set(v) - set(ids) for v in critical.values()):
            raise ValueError("Critical evidence must refer to reviewed release IDs")
        if review["scope"] == "in" and review.get("support") not in {"supported", "unsupported", "unknown"}:
            raise ValueError("In-scope review needs a support decision")
        if review["scope"] != "in" and (ids or critical or review.get("support") not in {None, "unknown"}):
            raise ValueError("Out-of-scope review cannot approve evidence")
        if (cells[cell_id]["task"] == "comparison" and review.get("support") == "supported"
                and (review.get("independent_comparison_verified") is not True
                     or not isinstance(review.get("independence_basis"), str)
                     or not review["independence_basis"].strip())):
            raise ValueError("Comparison support needs an explicit independence check and basis")
        by_cell.setdefault(cell_id, []).append(review)
    return by_cell


def build_coverage_report(snapshot: dict, reviews=(), manifest: dict | None = None) -> dict:
    """Calculate reviewed task coverage; never infer support from keyword hits.

    For a live UI, obtain ``snapshot`` using ``freeze_workbench_snapshot`` with
    purpose="recommendation". A review is invalidated by release, governance,
    or task-map changes. No write to the knowledge ledger occurs here.
    """
    manifest = manifest or build_coverage_manifest()
    _validate_manifest(manifest)
    if snapshot.get("schema_version") != "workbench-evaluation-snapshot-v1" or snapshot.get("split") != "development":
        raise ValueError("A governed development snapshot is required")
    if snapshot.get("purpose") != manifest["target_use"]:
        raise ValueError("Task coverage needs a recommendation-eligible snapshot")
    units = {unit["candidate_id"]: unit for unit in snapshot["units"]}
    if len(units) != len(snapshot["units"]):
        raise ValueError("Duplicate snapshot evidence ID")
    by_cell = _validated_reviews(reviews, manifest, snapshot, units)
    results = []
    for cell in manifest["cells"]:
        votes = by_cell.get(cell["id"], [])
        hints, source_hints = _discovery_clues(cell, units)
        result = {
            "id": cell["id"], "domain": cell["domain"], "task": cell["task"], "title": cell["title"],
            "critical_conditions": cell["critical_conditions"], "review_count": len(votes),
            "discovery_candidate_count": len(hints), "discovery_source_count": len(source_hints),
            "discovery_candidate_ids": hints, "discovery_only": True,
            "status": "scope_pending", "supporting_candidate_ids": [],
        }
        if len(votes) >= 2:
            scopes = {v["scope"] for v in votes}
            if "unsure" in scopes or len(scopes) > 1:
                result["status"] = "scope_disputed"
            elif scopes == {"out"}:
                result["status"] = "out_of_scope"
            else:
                decisions = {v["support"] for v in votes}
                if decisions == {"unsupported"}:
                    result["status"] = "unsupported"
                elif decisions == {"supported"}:
                    shared = set.intersection(*(set(v["evidence_ids"]) for v in votes))
                    shared = {cid for cid in shared if units[cid]["assessment"]["relation"] == "support"
                              and units[cid]["assessment"]["extent"] == "full"}
                    critical_ok = all(
                        bool(shared.intersection(*(set(v["critical_evidence"].get(condition, [])) for v in votes)))
                        for condition in cell["critical_conditions"]
                    )
                    if shared and critical_ok:
                        result["status"] = "supported"
                        result["supporting_candidate_ids"] = sorted(shared)
                    else:
                        result["status"] = "evidence_disputed_or_incomplete"
                else:
                    result["status"] = "support_disputed_or_unknown"
        results.append(result)
    domain_reports = {}
    for domain in manifest["domains"]:
        cells = [r for r in results if r["domain"] == domain]
        counts = Counter(r["status"] for r in cells)
        settled = all(r["status"] in {"supported", "unsupported", "out_of_scope"} for r in cells)
        denominator = counts["supported"] + counts["unsupported"]
        rate = counts["supported"] / denominator if settled and denominator else None
        domain_reports[domain] = {
            "cells": len(cells), "status_counts": dict(counts), "in_scope_denominator": denominator if settled else None,
            "coverage_rate": rate, "meets_threshold": rate >= manifest["threshold"] if rate is not None else None,
        }
    established = all(value["meets_threshold"] is not None for value in domain_reports.values())
    return {
        "schema_version": "sckg-task-coverage-report-v1", "manifest_hash": manifest["manifest_hash"],
        "snapshot_hash": snapshot["snapshot_hash"], "release_id": snapshot["release_id"],
        "governance_version": snapshot["governance_version"], "purpose": snapshot["purpose"],
        "eligible_unit_count": len(units), "eligible_source_count": len(snapshot["sources"]),
        "cells": results, "domains": domain_reports,
        "overall_status": ("meets_declared_threshold" if all(d["meets_threshold"] for d in domain_reports.values())
                           else "below_declared_threshold") if established else "not_established",
        "caution": "Literal discovery clues and published claim counts do not prove scientific coverage.",
    }


def _assert_live_snapshot(ledger, snapshot: dict) -> None:
    """Re-resolve the current eligible release before accepting a human decision."""
    from eval.workbench_snapshot import freeze_workbench_snapshot

    if snapshot.get("namespace") != ledger.workspace.namespace:
        raise ValueError("Coverage snapshot belongs to another workspace")
    actual = freeze_workbench_snapshot(ledger.workspace, purpose="recommendation")
    if snapshot.get("snapshot_hash") != actual["snapshot_hash"]:
        raise ValueError("Coverage snapshot is stale; review the current release")


def submit_coverage_review(ledger, snapshot: dict, review: dict, manifest: dict | None = None) -> dict:
    """Append one immutable domain-review decision to the isolated knowledge ledger.

    There is one vote per normalized reviewer, cell and exact snapshot. A later
    snapshot may receive a new vote; prior decisions remain immutable history.
    This records human judgment, but does not authenticate a real-world identity.
    """
    manifest = manifest or build_coverage_manifest()
    _validate_manifest(manifest)
    if not isinstance(review, dict):
        raise ValueError("Coverage review must be a record")
    reviewer = review.get("reviewer_id")
    if not isinstance(reviewer, str) or not reviewer.strip():
        raise ValueError("A named domain reviewer is required")
    normalized = {**review, "reviewer_id": reviewer.strip().casefold()}
    _validated_reviews([normalized], manifest, snapshot,
                       {unit["candidate_id"]: unit for unit in snapshot["units"]})
    cell = next(item for item in manifest["cells"] if item["id"] == normalized["cell_id"])
    if normalized.get("support") == "supported":
        ids = set(normalized.get("evidence_ids", []))
        if not ids or set(normalized.get("critical_evidence", {})) != set(cell["critical_conditions"]):
            raise ValueError("Supported coverage requires exact evidence for every critical condition")
        units = {unit["candidate_id"]: unit for unit in snapshot["units"]}
        if any(units[cid]["assessment"]["relation"] != "support" or
               units[cid]["assessment"]["extent"] != "full" for cid in ids):
            raise ValueError("Supported coverage needs fully supported released evidence")
    vote_key = [manifest["manifest_hash"], snapshot["snapshot_hash"],
                normalized["cell_id"], normalized["reviewer_id"]]
    record_id = "coverage-review-" + content_hash(vote_key)
    record = {**normalized, "id": record_id, "namespace": ledger.workspace.namespace,
              "created_at": utcnow(), "authority": "explicit_local_domain_review",
              "reviewer_identity_verification": "self_declared_local"}
    with ledger.transaction() as conn:
        # Writer lock protects both the live-state check and the unique vote.
        _assert_live_snapshot(ledger, snapshot)
        if ledger.get_record("coverage_review", record_id, conn=conn) is not None:
            raise ValueError("This reviewer already submitted a decision for this cell and snapshot")
        ledger.put_record("coverage_review", record_id, record, conn=conn)
        ledger.append_event("coverage_review_submitted", normalized["cell_id"], {
            "review_id": record_id, "reviewer_id": normalized["reviewer_id"],
            "scope": normalized["scope"], "support": normalized.get("support"),
            "snapshot_hash": snapshot["snapshot_hash"],
        }, conn=conn)
    return record


def list_coverage_review_history(ledger, *, cell_id: str | None = None) -> list[dict]:
    """All immutable decisions, including earlier releases and governance states."""
    records = ledger.list_records("coverage_review")
    return [record for record in records if cell_id is None or record["cell_id"] == cell_id]


def list_coverage_reviews(ledger, snapshot: dict, manifest: dict | None = None) -> list[dict]:
    """Only votes applicable to the present map and currently eligible snapshot."""
    manifest = manifest or build_coverage_manifest()
    _validate_manifest(manifest)
    _assert_live_snapshot(ledger, snapshot)
    reviews = [record for record in list_coverage_review_history(ledger)
               if record["namespace"] == ledger.workspace.namespace
               and record["manifest_hash"] == manifest["manifest_hash"]
               and record["release_id"] == snapshot["release_id"]
               and record["governance_version"] == snapshot["governance_version"]
               and record["snapshot_hash"] == snapshot["snapshot_hash"]]
    _validated_reviews(reviews, manifest, snapshot,
                       {unit["candidate_id"]: unit for unit in snapshot["units"]})
    return reviews
