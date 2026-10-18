"""Frozen, honest B/R/K study records for the scientific value question.

This module registers tasks and validates receipts. It never calls a model,
creates gold answers, or equates engineering checks with scientific results.
"""
from __future__ import annotations

from collections import defaultdict
import random

from eval.confirmation_power import (
    DOMAINS, MIN_GROUPS_PER_DOMAIN, check_confirmation_power_plan,
)
from sckg_workbench.storage import content_hash


ARMS = {"B": "no_extra_knowledge", "R": "same_sources_raw_rag", "K": "governed_sckg"}
_PINNED_FIELDS = ("model_id", "model_revision", "prompt_hash", "tool_registry_hash",
                  "input_token_budget", "output_token_budget", "sampling_seed")


def build_development_study(snapshot: dict, case_specs: list[dict]) -> dict:
    """Adapt previously authored scenarios without promoting them to gold."""
    if snapshot.get("split") != "development" or snapshot.get("purpose") != "recommendation":
        raise ValueError("Development study requires a recommendation snapshot")
    cases = []
    for item in case_specs:
        if item.get("split") != "development":
            raise ValueError("Cannot silently convert sealed or unknown material into development tasks")
        cases.append({
            "case_id": item["case_id"], "question": item["question"],
            "profile": item["profile"], "split": "development",
            "dependency_group_id": item["dependency_group_id"],
            "source_work_ids": [], "dataset_ids": [],
            "gold_reviews": [], "adjudicated_gold": None,
            "prior_development_exposure": True,
        })
    source_corpus = sorted(({
        "source_id": source["id"], "source_revision_id": source["source_revision_id"],
        "blob_sha256": source["blob_sha256"],
    } for source in snapshot.get("sources", [])), key=lambda item: item["source_id"])
    study = {
        "schema_version": "sckg-scientific-value-v1",
        "study_id": "development-" + content_hash([snapshot["snapshot_hash"], [c["case_id"] for c in cases]])[:20],
        "knowledge_release_id": snapshot["release_id"],
        "knowledge_snapshot_hash": snapshot["snapshot_hash"],
        "source_corpus": source_corpus,
        "source_corpus_manifest_hash": content_hash(source_corpus),
        "arms": [{"id": key, "evidence_mode": value} for key, value in ARMS.items()],
        "fixed_configuration": {key: None for key in _PINNED_FIELDS},
        "replicates": 1, "bootstrap_seed": 20261008,
        "minimum_independent_confirmation_groups": None,
        "confirmation_power_plan": None,
        "development_pilot_receipt_hash": None,
        "cases": cases,
    }
    study["study_hash"] = content_hash(study)
    return study


def validate_study(study: dict) -> dict:
    """Return blockers; structural preparation never implies scientific success."""
    if study.get("schema_version") != "sckg-scientific-value-v1":
        raise ValueError("Unknown scientific value study schema")
    if study.get("study_hash") != content_hash({k: v for k, v in study.items() if k != "study_hash"}):
        raise ValueError("Scientific value study changed after freezing")
    if {arm.get("id"): arm.get("evidence_mode") for arm in study.get("arms", [])} != ARMS or len(study["arms"]) != 3:
        raise ValueError("B, R and K must be distinct fixed evidence arms")
    cases = study.get("cases", [])
    if not cases or len({c.get("case_id") for c in cases}) != len(cases):
        raise ValueError("Study requires distinct nonempty cases")
    if type(study.get("replicates")) is not int or study["replicates"] < 1:
        raise ValueError("Replicate count must be fixed before runs")
    config = study.get("fixed_configuration", {})
    blockers = []
    inferential_blockers = []
    if any(config.get(key) in (None, "") for key in _PINNED_FIELDS):
        blockers.append("Model, prompt, tools, budgets and seed must be pinned before running comparisons")
    if not study.get("knowledge_release_id") or not study.get("knowledge_snapshot_hash"):
        blockers.append("A governed knowledge release and exact snapshot are required")
    if (not study.get("source_corpus") or
            study.get("source_corpus_manifest_hash") != content_hash(study["source_corpus"])):
        blockers.append("Raw RAG and scKG need one frozen source-revision corpus")
    split_by_lineage = defaultdict(set)
    split_by_work = defaultdict(set)
    split_by_experiment = defaultdict(set)
    split_by_dataset = defaultdict(set)
    confirmation_domains = defaultdict(set)
    for case in cases:
        cid = case.get("case_id")
        split = case.get("split")
        if split not in {"development", "confirmation"} or not case.get("question") or not case.get("dependency_group_id"):
            raise ValueError(f"{cid}: split, question and dependency group are required")
        split_by_lineage[case["dependency_group_id"]].add(split)
        for work in case.get("source_work_ids", []):
            split_by_work[work].add(split)
        for experiment in case.get("experiment_ids", []):
            split_by_experiment[experiment].add(split)
        for dataset in case.get("dataset_ids", []):
            split_by_dataset[dataset].add(split)
        if split == "confirmation":
            if (not any(case.get(key) for key in ("source_work_ids", "experiment_ids", "dataset_ids")) or
                    case.get("prior_development_exposure") is not False):
                blockers.append(f"{cid}: independent source, experiment or dataset lineage and no development exposure need verification")
            domain = case.get("domain")
            if domain not in DOMAINS:
                inferential_blockers.append(f"{cid}: one of the five declared confirmation domains is required")
            else:
                confirmation_domains[case["dependency_group_id"]].add(domain)
        votes = case.get("gold_reviews", [])
        if (len(votes) != 2 or len({v.get("reviewer_id") for v in votes}) != 2
                or any(not v.get("reviewer_id") or not v.get("scientific_rubric") for v in votes)
                or not case.get("adjudicated_gold")):
            blockers.append(f"{cid}: two independent domain gold reviews and adjudication are missing")
    if any(len(splits) > 1 for mapping in (
        split_by_lineage, split_by_work, split_by_experiment, split_by_dataset,
    ) for splits in mapping.values()):
        raise ValueError("Shared experiment, work or dataset crosses development and confirmation splits")
    if any(case["split"] == "confirmation" for case in cases):
        inferential_blockers.extend(check_confirmation_power_plan(study.get("confirmation_power_plan"), study))
        # Blind identifiers and two reviewer IDs do not prove that reviewers
        # never saw the assignment map. A separate blind-packet custody flow
        # is required before a positive claim can be reported.
        inferential_blockers.append(
            "Blind review assignment-map separation is unverified; confirmation scores remain descriptive"
        )
        counts = defaultdict(int)
        for domains in confirmation_domains.values():
            if len(domains) != 1:
                inferential_blockers.append("Each independent confirmation group must belong to exactly one domain")
            else:
                counts[next(iter(domains))] += 1
        for domain in DOMAINS:
            if counts[domain] < MIN_GROUPS_PER_DOMAIN:
                inferential_blockers.append(f"{domain}: fewer than {MIN_GROUPS_PER_DOMAIN} independent confirmation groups")
        planned = (study.get("confirmation_power_plan") or {}).get("planned_independent_groups")
        if type(planned) is int and len(confirmation_domains) < planned:
            inferential_blockers.append("Confirmation has fewer independent groups than its power plan")
    return {
        "status": ("preparation_only" if blockers else
                   "ready_for_descriptive_runs" if inferential_blockers else
                   "ready_for_measured_runs"),
        "study_hash": study["study_hash"], "case_count": len(cases),
        "development_case_count": sum(c["split"] == "development" for c in cases),
        "confirmation_case_count": sum(c["split"] == "confirmation" for c in cases),
        "independent_dependency_groups": len(split_by_lineage),
        "blockers": blockers + inferential_blockers,
        "run_blockers": blockers,
        "inferential_blockers": inferential_blockers,
        "scientific_scores": None,
    }


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _paired_interval(groups: list[dict], arm: str, baseline: str, key: str, seed: int) -> tuple[float, list[float]]:
    observations = [g[arm][key] - g[baseline][key] for g in groups]
    difference = sum(observations) / len(observations)
    if all(value == observations[0] for value in observations):
        return difference, [difference, difference]
    rng = random.Random(seed)
    replicates = [sum(observations[rng.randrange(len(observations))] for _ in observations) / len(observations)
                  for _ in range(2000)]
    return difference, [_percentile(replicates, 0.025), _percentile(replicates, 0.975)]


def summarize_runs(study: dict, runs: list[dict], grades: list[dict]) -> dict:
    """Score only complete, pinned, two-reviewer paired runs with blind IDs.

    Development and confirmation results remain descriptive until an audited
    blind-packet custody flow proves that reviewers did not see the arm-to-ID
    assignment map. A power plan and enough groups alone cannot prove this.
    """
    readiness = validate_study(study)
    if readiness["run_blockers"]:
        return {"status": "not_scored", "blockers": readiness["run_blockers"],
                "submitted_runs": len(runs), "submitted_grades": len(grades), "scores": None}
    case_by_id = {c["case_id"]: c for c in study["cases"]}
    expected = {(cid, arm, repeat) for cid in case_by_id for arm in ARMS
                for repeat in range(study["replicates"])}
    by_key, by_blind = {}, {}
    config_hash = content_hash(study["fixed_configuration"])
    for run in runs:
        key = (run.get("case_id"), run.get("arm_id"), run.get("replicate"))
        blind = run.get("blind_id")
        if key not in expected or key in by_key or not blind or blind in by_blind:
            raise ValueError("Runs must have unique case, arm, repeat and blinded identities")
        if (run.get("study_hash") != study["study_hash"] or run.get("config_hash") != config_hash
                or run.get("knowledge_release_id") != study["knowledge_release_id"]
                or run.get("source_corpus_manifest_hash") != study["source_corpus_manifest_hash"]
                or run.get("status") != "succeeded" or not run.get("output_hash")):
            raise ValueError("A run is incomplete or differs from its frozen configuration")
        by_key[key] = run
        by_blind[blind] = run
    if set(by_key) != expected:
        return {"status": "not_scored", "blockers": ["Paired B/R/K run receipts are incomplete"],
                "submitted_runs": len(runs), "submitted_grades": len(grades), "scores": None}
    votes = defaultdict(list)
    for grade in grades:
        blind = grade.get("blind_id")
        if any(key in grade for key in ("arm_id", "case_id", "run_id", "evidence_mode")):
            raise ValueError("Blind grades cannot disclose run assignment")
        if blind not in by_blind or not grade.get("reviewer_id") or not grade.get("reason"):
            raise ValueError("A blind grade must identify an output, reviewer and reason")
        if type(grade.get("plan_correct")) is not bool or type(grade.get("critical_error")) is not bool:
            raise ValueError("Scientific grades must be explicit booleans")
        votes[blind].append(grade)
    scored = {}
    unresolved = []
    for blind in by_blind:
        pair = votes.get(blind, [])
        if (len(pair) != 2 or len({v["reviewer_id"] for v in pair}) != 2
                or any((v["plan_correct"], v["critical_error"]) !=
                       (pair[0]["plan_correct"], pair[0]["critical_error"]) for v in pair)):
            unresolved.append(blind)
        else:
            scored[blind] = {"plan_correct": int(pair[0]["plan_correct"]),
                             "critical_error": int(pair[0]["critical_error"])}
    if unresolved:
        return {"status": "not_scored", "blockers": ["Blind scientific grades incomplete or disputed"],
                "unresolved_blind_ids": sorted(unresolved), "scores": None}
    by_split = {}
    for split in ("development", "confirmation"):
        cases = [c for c in case_by_id.values() if c["split"] == split]
        if not cases:
            continue
        clusters = defaultdict(lambda: defaultdict(list))
        for case in cases:
            for arm in ARMS:
                for repeat in range(study["replicates"]):
                    run = by_key[(case["case_id"], arm, repeat)]
                    clusters[case["dependency_group_id"]][arm].append(scored[run["blind_id"]])
        groups = []
        for cluster in clusters.values():
            groups.append({arm: {metric: sum(score[metric] for score in cluster[arm]) / len(cluster[arm])
                                 for metric in ("plan_correct", "critical_error")} for arm in ARMS})
        rates = {arm: {metric: sum(g[arm][metric] for g in groups) / len(groups)
                       for metric in ("plan_correct", "critical_error")} for arm in ARMS}
        comparisons = {}
        for baseline in ("B", "R"):
            gain, interval = _paired_interval(groups, "K", baseline, "plan_correct", study["bootstrap_seed"])
            error_gain, error_interval = _paired_interval(
                groups, "K", baseline, "critical_error", study["bootstrap_seed"] + 1)
            target = study.get("minimum_independent_confirmation_groups")
            eligible = (split == "confirmation" and not readiness["inferential_blockers"] and
                        target is not None and len(groups) >= target)
            comparisons[f"K_vs_{baseline}"] = {
                "plan_gain": gain, "plan_gain_95pct_cluster_bootstrap": interval,
                "critical_error_difference": error_gain,
                "critical_error_95pct_cluster_bootstrap": error_interval,
                "superiority_criterion_met": (gain >= 0.10 and interval[0] > 0 and error_interval[1] <= 0)
                if eligible else None,
            }
        confirm_target = study.get("minimum_independent_confirmation_groups")
        confirm_ready = (split == "confirmation" and not readiness["inferential_blockers"] and
                         confirm_target is not None and len(groups) >= confirm_target)
        by_split[split] = {"independent_groups": len(groups), "group_weighted_rates": rates,
                           "paired_comparisons": comparisons,
                           "interpretation": ("confirmation_threshold_test" if confirm_ready else
                                              "confirmation_descriptive_only" if split == "confirmation" else
                                              "development_descriptive_only")}
    return {"status": "measured", "study_hash": study["study_hash"],
            "run_count": len(runs), "grade_count": len(grades), "scores": by_split,
            "inferential_blockers": readiness["inferential_blockers"],
            "blinding_status": "assignment_map_separation_unverified",
            "caution": ("A passing engineering preflight is not a scientific superiority result. "
                        "Receipt IDs alone cannot prove actual reviewer blinding; formal superiority is disabled.")}
