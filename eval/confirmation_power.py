"""Pre-register a bounded paired confirmation sample from independent pilot groups.

The normal approximation plans the *primary plan-correctness difference* only.
It is not a power analysis for critical-error noninferiority, subgroup claims, or
the eventual cluster bootstrap interval. Pilot records must come from graded
development receipts; this helper cannot authenticate a supplied receipt hash.
"""
from __future__ import annotations

from math import ceil, isfinite
from statistics import NormalDist, variance

from sckg_workbench.storage import content_hash


DOMAINS = (
    "scrna", "rna_protein", "rna_atac", "paired_unpaired_integration", "spatial",
)
COMPARISONS = ("K_vs_B", "K_vs_R")
TARGET_GAIN = 0.10
ALPHA = 0.05
POWER = 0.80
MIN_PILOT_GROUPS = 12
MIN_CONFIRMATION_GROUPS = 60
MAX_CONFIRMATION_GROUPS = 120
MIN_GROUPS_PER_DOMAIN = 8
# A small pilot can report zero variance by chance. The declared design floor
# and inflation protect against treating that as deterministic model behavior.
VARIANCE_FLOOR = 0.10
VARIANCE_INFLATION = 1.25


def plan_confirmation_sample_size(
    pilot_groups: list[dict], *, knowledge_snapshot_hash: str,
    source_corpus_manifest_hash: str, fixed_configuration: dict,
    pilot_receipt_hash: str,
) -> dict:
    """Plan 10-point paired improvement using one outcome per independent group.

    ``pilot_groups`` entries have distinct ``dependency_group_id`` and B/R/K
    plan-correctness scores in [0, 1]. An investigator must first verify that
    these are graded development outcomes, not authored questions or reused
    confirmation works. The plan is frozen by ``plan_hash`` before confirmation.
    """
    if not all(isinstance(v, str) and v for v in (
        knowledge_snapshot_hash, source_corpus_manifest_hash, pilot_receipt_hash,
    )) or not isinstance(fixed_configuration, dict) or not fixed_configuration:
        raise ValueError("Pilot receipts, knowledge snapshot, corpus and fixed configuration are required")
    if not isinstance(pilot_groups, list):
        raise ValueError("Pilot groups must be a list of independent scored groups")
    group_ids = []
    differences = {comparison: [] for comparison in COMPARISONS}
    discordance = {comparison: 0 for comparison in COMPARISONS}
    for group in pilot_groups:
        if not isinstance(group, dict):
            raise ValueError("Every pilot group needs an identity and B/R/K scores")
        group_id = group.get("dependency_group_id")
        if not isinstance(group_id, str) or not group_id or group_id in group_ids:
            raise ValueError("Pilot requires distinct independent dependency groups")
        group_ids.append(group_id)
        for arm in ("B", "R", "K"):
            value = group.get(arm)
            if (isinstance(value, bool) or not isinstance(value, (int, float)) or
                    not isfinite(value) or not 0 <= value <= 1):
                raise ValueError("Pilot B/R/K scores must be numeric values in [0, 1]")
        for baseline in ("B", "R"):
            comparison = f"K_vs_{baseline}"
            difference = float(group["K"] - group[baseline])
            differences[comparison].append(difference)
            discordance[comparison] += int(difference != 0)
    if not pilot_groups:
        raise ValueError("At least one scored development group is required")
    z_two_sided = NormalDist().inv_cdf(1 - ALPHA / 2)
    z_power = NormalDist().inv_cdf(POWER)
    estimates = {}
    for comparison in COMPARISONS:
        observed_variance = variance(differences[comparison]) if len(pilot_groups) >= 2 else None
        design_variance = (max(observed_variance, VARIANCE_FLOOR) * VARIANCE_INFLATION
                           if observed_variance is not None else None)
        required = (ceil((z_two_sided + z_power) ** 2 * design_variance / TARGET_GAIN ** 2)
                    if design_variance is not None and len(pilot_groups) >= MIN_PILOT_GROUPS else None)
        estimates[comparison] = {
            "observed_paired_group_variance": observed_variance,
            "observed_nonzero_difference_fraction": discordance[comparison] / len(pilot_groups),
            "planning_variance": design_variance,
            "normal_approximation_required_groups": required,
        }
    required_groups = max(
        (item["normal_approximation_required_groups"] or 0 for item in estimates.values()),
        default=0,
    )
    planned = max(MIN_CONFIRMATION_GROUPS, required_groups) if required_groups else None
    status = ("pilot_insufficient" if len(pilot_groups) < MIN_PILOT_GROUPS else
              "insufficient_budget" if planned is None or planned > MAX_CONFIRMATION_GROUPS else
              "feasible")
    plan = {
        "schema_version": "sckg-confirmation-power-v1",
        "status": status,
        "pilot_source_split": "development",
        "pilot_receipt_hash": pilot_receipt_hash,
        "pilot_dependency_group_count": len(pilot_groups),
        "pilot_group_outcomes": sorted(pilot_groups, key=lambda x: x["dependency_group_id"]),
        "pilot_group_ids_hash": content_hash(sorted(group_ids)),
        "pilot_outcomes_hash": content_hash(sorted(pilot_groups, key=lambda x: x["dependency_group_id"])),
        "knowledge_snapshot_hash": knowledge_snapshot_hash,
        "source_corpus_manifest_hash": source_corpus_manifest_hash,
        "fixed_configuration_hash": content_hash(fixed_configuration),
        "target_gain": TARGET_GAIN, "two_sided_alpha": ALPHA, "power": POWER,
        "minimum_pilot_groups": MIN_PILOT_GROUPS,
        "minimum_confirmation_groups": MIN_CONFIRMATION_GROUPS,
        "maximum_confirmation_groups": MAX_CONFIRMATION_GROUPS,
        "minimum_groups_per_domain": MIN_GROUPS_PER_DOMAIN,
        "domains": list(DOMAINS),
        "variance_floor": VARIANCE_FLOOR,
        "variance_inflation": VARIANCE_INFLATION,
        "estimates": estimates,
        "required_independent_groups": required_groups if required_groups else None,
        "planned_independent_groups": planned if status == "feasible" else None,
        "assumptions": [
            "One pre-adjudicated plan-correctness score per independent development group and arm",
            "Normal approximation for a 10-point paired mean difference; pilot variance is floored and inflated",
            "K versus B and K versus R are per-comparison two-sided tests, not simultaneous family-wise claims",
            "Actual cluster-bootstrap power and critical-error noninferiority are not guaranteed by this estimate",
            "Confirmation has five declared domains, each with at least eight independent groups",
        ],
    }
    plan["plan_hash"] = content_hash(plan)
    return plan


def check_confirmation_power_plan(plan: dict | None, study: dict) -> list[str]:
    """Return blockers for a *confirmatory claim* without blocking descriptive scores."""
    if not isinstance(plan, dict):
        return ["Confirmation sample size and power plan must be declared before scoring"]
    if plan.get("schema_version") != "sckg-confirmation-power-v1" or plan.get("plan_hash") != content_hash({
        key: value for key, value in plan.items() if key != "plan_hash"
    }):
        return ["Confirmation power plan is missing, changed or uses an unknown schema"]
    blockers = []
    if (plan.get("knowledge_snapshot_hash") != study.get("knowledge_snapshot_hash") or
            plan.get("source_corpus_manifest_hash") != study.get("source_corpus_manifest_hash") or
            plan.get("fixed_configuration_hash") != content_hash(study.get("fixed_configuration"))):
        blockers.append("Confirmation power plan is not bound to this knowledge, corpus and model configuration")
    if not study.get("development_pilot_receipt_hash") or (plan.get("pilot_receipt_hash") !=
            study.get("development_pilot_receipt_hash")):
        blockers.append("Confirmation power plan is not bound to adjudicated development pilot receipts")
    try:
        recalculated = plan_confirmation_sample_size(
            plan.get("pilot_group_outcomes"),
            knowledge_snapshot_hash=plan.get("knowledge_snapshot_hash"),
            source_corpus_manifest_hash=plan.get("source_corpus_manifest_hash"),
            fixed_configuration=study.get("fixed_configuration"),
            pilot_receipt_hash=plan.get("pilot_receipt_hash"),
        )
    except (ValueError, TypeError, KeyError) as exc:
        blockers.append(f"Confirmation pilot group outcomes cannot be rechecked: {exc}")
    else:
        if recalculated != plan:
            blockers.append("Confirmation power plan does not match its pilot group outcomes")
    if (plan.get("target_gain") != TARGET_GAIN or plan.get("two_sided_alpha") != ALPHA or
            plan.get("power") != POWER or plan.get("minimum_pilot_groups") != MIN_PILOT_GROUPS or
            plan.get("minimum_confirmation_groups") != MIN_CONFIRMATION_GROUPS or
            plan.get("maximum_confirmation_groups") != MAX_CONFIRMATION_GROUPS or
            plan.get("minimum_groups_per_domain") != MIN_GROUPS_PER_DOMAIN or
            plan.get("variance_floor") != VARIANCE_FLOOR or
            plan.get("variance_inflation") != VARIANCE_INFLATION or
            plan.get("domains") != list(DOMAINS) or
            plan.get("pilot_source_split") != "development" or
            not plan.get("pilot_receipt_hash") or
            type(plan.get("pilot_dependency_group_count")) is not int or
            plan["pilot_dependency_group_count"] < MIN_PILOT_GROUPS):
        blockers.append("Confirmation power plan does not meet the preregistered design")
    estimates = plan.get("estimates")
    if not isinstance(estimates, dict) or set(estimates) != set(COMPARISONS):
        blockers.append("Confirmation power plan lacks both paired comparisons")
    else:
        required = []
        for comparison in COMPARISONS:
            item = estimates[comparison]
            if not isinstance(item, dict):
                blockers.append("Confirmation power estimates are malformed")
                break
            n = item.get("normal_approximation_required_groups")
            variance_for_design = item.get("planning_variance")
            if (type(n) is not int or n < 1 or
                    not isinstance(variance_for_design, (int, float)) or
                    not isfinite(variance_for_design) or variance_for_design < VARIANCE_FLOOR):
                blockers.append("Confirmation power estimates are incomplete")
                break
            expected = ceil((NormalDist().inv_cdf(1 - ALPHA / 2) + NormalDist().inv_cdf(POWER)) ** 2
                            * variance_for_design / TARGET_GAIN ** 2)
            if n != expected:
                blockers.append("Confirmation power estimate does not match its stated variance")
                break
            required.append(n)
        if len(required) == 2 and plan.get("required_independent_groups") != max(required):
            blockers.append("Confirmation sample target is smaller than a paired comparison requires")
    planned = plan.get("planned_independent_groups")
    required_total = plan.get("required_independent_groups")
    if (plan.get("status") != "feasible" or type(planned) is not int or
            planned < MIN_CONFIRMATION_GROUPS or planned > MAX_CONFIRMATION_GROUPS or
            type(required_total) is not int or
            planned != max(MIN_CONFIRMATION_GROUPS, required_total) or
            study.get("minimum_independent_confirmation_groups") != planned):
        blockers.append("Confirmation budget cannot support the planned power or sample target differs")
    return blockers
