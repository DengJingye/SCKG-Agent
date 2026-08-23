from __future__ import annotations

import hashlib
import json

from core.execution_models import CandidateEvaluation, DecisionResult, PreferenceProfile


PREFERENCE_WEIGHTS = {
    "performance": {"auprc": 0.30, "f1": 0.20, "reject": 0.0, "stability": 0.25, "success": 0.15, "runtime": 0.03, "memory": 0.02, "reproducibility": 0.05},
    "stability": {"auprc": 0.15, "f1": 0.10, "reject": 0.0, "stability": 0.45, "success": 0.20, "runtime": 0.03, "memory": 0.02, "reproducibility": 0.05},
    "resource": {"auprc": 0.10, "f1": 0.05, "reject": 0.0, "stability": 0.15, "success": 0.15, "runtime": 0.20, "memory": 0.30, "reproducibility": 0.05},
    "fast_local": {"auprc": 0.12, "f1": 0.08, "reject": 0.0, "stability": 0.15, "success": 0.15, "runtime": 0.35, "memory": 0.10, "reproducibility": 0.05},
}

ANNOTATION_PREFERENCE_WEIGHTS = {
    "performance": {"auprc": 0.28, "f1": 0.30, "reject": 0.08, "stability": 0.12, "success": 0.10, "runtime": 0.03, "memory": 0.02, "reproducibility": 0.07},
    "stability": {"auprc": 0.14, "f1": 0.16, "reject": 0.05, "stability": 0.35, "success": 0.18, "runtime": 0.03, "memory": 0.02, "reproducibility": 0.07},
    "resource": {"auprc": 0.12, "f1": 0.13, "reject": 0.05, "stability": 0.10, "success": 0.10, "runtime": 0.18, "memory": 0.25, "reproducibility": 0.07},
    "fast_local": {"auprc": 0.12, "f1": 0.13, "reject": 0.05, "stability": 0.10, "success": 0.10, "runtime": 0.28, "memory": 0.15, "reproducibility": 0.07},
}

INTEGRATION_PREFERENCE_WEIGHTS = {
    **PREFERENCE_WEIGHTS,
    "performance": {
        "auprc": 0.35,
        "f1": 0.35,
        "stability": 0.10,
        "success": 0.10,
        "runtime": 0.04,
        "memory": 0.01,
        "reproducibility": 0.05,
    },
}


class ParetoDecisionEngine:
    """Compare configurations or tool candidates on normalized engineering objectives."""

    def decide(
        self,
        candidates: list[CandidateEvaluation],
        *,
        preference: PreferenceProfile | str = PreferenceProfile.PERFORMANCE,
    ) -> DecisionResult:
        preference_value = str(preference.value if isinstance(preference, PreferenceProfile) else preference)
        if preference_value not in PREFERENCE_WEIGHTS:
            raise ValueError(f"unsupported preference profile: {preference_value}")
        eligible = [candidate for candidate in candidates if candidate.eligible_for_decision]
        tool_names = {candidate.tool_name for candidate in candidates}
        multitool = len(tool_names) > 1
        batch_integration = bool(candidates) and all(
            _is_batch_integration_candidate(candidate) for candidate in candidates
        )
        annotation = bool(candidates) and all(
            _is_annotation_candidate(candidate) for candidate in candidates
        )
        vectors = {candidate.candidate_id: _vector(candidate) for candidate in eligible}
        pareto = [
            candidate
            for candidate in eligible
            if not any(
                _dominates(vectors[other.candidate_id], vectors[candidate.candidate_id])
                for other in eligible
                if other.candidate_id != candidate.candidate_id
            )
        ]
        recommended = None
        if pareto:
            scores = _preference_scores(
                pareto,
                vectors,
                preference_value,
                weights_by_preference=(
                    INTEGRATION_PREFERENCE_WEIGHTS
                    if batch_integration
                    else ANNOTATION_PREFERENCE_WEIGHTS
                    if annotation
                    else PREFERENCE_WEIGHTS
                ),
            )
            finalists = pareto
            if (
                preference_value == "performance"
                and not batch_integration
                and not annotation
            ):
                best_performance = max(
                    vectors[item.candidate_id]["auprc"] for item in pareto
                )
                finalists = [
                    item
                    for item in pareto
                    if abs(
                        vectors[item.candidate_id]["auprc"] - best_performance
                    )
                    <= 1e-12
                ]
            recommended = max(
                finalists,
                key=lambda item: (scores[item.candidate_id], item.candidate_id),
            )

        elimination: dict[str, list[str]] = {}
        pareto_ids = {candidate.candidate_id for candidate in pareto}
        for candidate in candidates:
            reasons: list[str] = []
            if not candidate.eligible_for_decision:
                reasons.extend(candidate.limitations or ["candidate_not_eligible"])
            elif candidate.candidate_id not in pareto_ids:
                if batch_integration:
                    reasons.append(
                        "dominated_on_multitool_batch_integration_objectives"
                        if multitool
                        else "dominated_on_batch_integration_configuration_objectives"
                    )
                elif annotation:
                    reasons.append(
                        "dominated_on_multitool_annotation_objectives"
                        if multitool
                        else "dominated_on_annotation_configuration_objectives"
                    )
                else:
                    reasons.append(
                        "dominated_on_multitool_engineering_objectives"
                        if multitool
                        else "dominated_on_configuration_level_engineering_objectives"
                    )
            elif recommended is not None and candidate.candidate_id != recommended.candidate_id:
                reasons.append(f"pareto_alternative_under_{preference_value}_preference")
            elimination[candidate.candidate_id] = sorted(set(reasons))

        decision_payload = {
            "candidate_ids": sorted(candidate.candidate_id for candidate in candidates),
            "preference": preference_value,
        }
        decision_id = "decision-" + hashlib.sha256(
            json.dumps(decision_payload, sort_keys=True).encode("utf-8")
        ).hexdigest()[:16]
        scientific = any(
            candidate.metric_authority == "scientific_pilot_metric"
            for candidate in candidates
        )
        return DecisionResult(
            decision_id=decision_id,
            decision_scope=(
                (
                    "multitool_batch_integration"
                    if multitool
                    else "batch_integration_configuration"
                )
                if batch_integration
                else (
                    "multitool_cell_type_annotation"
                    if multitool
                    else "cell_type_annotation_configuration"
                )
                if annotation
                else (
                    "multitool_doublet_detection" if multitool else "scrublet_configuration"
                )
            ),
            eligible_candidate_ids=[candidate.candidate_id for candidate in eligible],
            pareto_candidate_ids=[candidate.candidate_id for candidate in pareto],
            recommended_candidate_id=(recommended.candidate_id if recommended else None),
            alternative_candidate_ids=[
                candidate.candidate_id
                for candidate in pareto
                if recommended is None or candidate.candidate_id != recommended.candidate_id
            ],
            elimination_reasons=elimination,
            preference_profile=preference_value,
            decision_flip_conditions=[
                "Recommendation may change when the preference profile changes.",
                "Recommendation must be recomputed if seeds, probe, contract, or environment changes.",
                (
                    "A broader independent scientific validation may overturn this pilot decision."
                    if scientific
                    else "Scientific validation may overturn this synthetic engineering decision."
                ),
            ],
            limitations=[
                (
                    (
                        "Decision compares normalized batch mixing and biology conservation metrics across integration tools."
                        if multitool
                        else "Decision compares batch-integration parameter configurations for one tool."
                    )
                    if batch_integration
                    else (
                        "Decision compares macro-F1, balanced accuracy, reject rate, stability and resources across annotation tools."
                        if multitool
                        else "Decision compares cell-type annotation parameter configurations for one tool."
                    )
                    if annotation
                    else (
                        "Decision compares normalized engineering metrics across doublet-detection tools; raw scores are never compared directly."
                        if multitool
                        else "Decision compares Scrublet parameter configurations only, not multiple tools."
                    )
                ),
                *(
                    [
                        "Cross-tool comparison is incomplete because at least one tool has no eligible candidate."
                    ]
                    if multitool and len({item.tool_name for item in eligible}) < len(tool_names)
                    else []
                ),
                (
                    "Metrics are scientific_pilot_metric limited to the registered dataset and preprocessing."
                    if scientific
                    else "Metrics are synthetic_engineering_metric and do not establish biological performance."
                ),
                "Runtime uses the seed median; cold-start and run-order effects may still remain.",
                "No undefined confidence percentage is produced.",
            ],
        )


def _vector(candidate: CandidateEvaluation) -> dict[str, float]:
    if _is_batch_integration_candidate(candidate):
        mixing = candidate.metric_summaries.get("batch_mixing_asw")
        biology = candidate.metric_summaries.get("biology_conservation_asw")
        return {
            "auprc": float(mixing.mean if mixing and mixing.mean is not None else 0.0),
            "f1": float(biology.mean if biology and biology.mean is not None else 0.0),
            "reject": 0.0,
            "stability": float(candidate.seed_stability.get("stability_score", 0.0)),
            "success": candidate.execution_success_rate,
            "runtime": float(candidate.runtime_summary.median or float("inf")),
            "memory": float(candidate.peak_memory_summary.median or float("inf")),
            "reproducibility": 1.0 if candidate.reproducibility_level == "Level 2" else 0.0,
        }
    if _is_annotation_candidate(candidate):
        balanced = candidate.metric_summaries.get("balanced_accuracy")
        macro_f1 = candidate.metric_summaries.get("macro_f1")
        reject = candidate.metric_summaries.get("reject_rate")
        return {
            "auprc": float(
                balanced.mean if balanced and balanced.mean is not None else 0.0
            ),
            "f1": float(
                macro_f1.mean if macro_f1 and macro_f1.mean is not None else 0.0
            ),
            "reject": float(
                reject.mean if reject and reject.mean is not None else 1.0
            ),
            "stability": float(candidate.seed_stability.get("stability_score", 0.0)),
            "success": candidate.execution_success_rate,
            "runtime": float(candidate.runtime_summary.median or float("inf")),
            "memory": float(candidate.peak_memory_summary.median or float("inf")),
            "reproducibility": 1.0
            if candidate.reproducibility_level == "Level 2"
            else 0.0,
        }
    auprc = (
        candidate.metric_summaries.get("scientific_pilot_auprc")
        or candidate.metric_summaries.get("synthetic_engineering_auprc")
    )
    f1 = candidate.metric_summaries.get(
        "scientific_pilot_f1"
    ) or candidate.metric_summaries.get("synthetic_engineering_f1")
    if auprc is None:
        auprc = f1
    if f1 is None:
        f1 = auprc
    return {
        "auprc": float(auprc.mean if auprc and auprc.mean is not None else 0.0),
        "f1": float(f1.mean if f1 and f1.mean is not None else 0.0),
        "reject": 0.0,
        "stability": float(candidate.seed_stability.get("stability_score", 0.0)),
        "success": candidate.execution_success_rate,
        "runtime": float(candidate.runtime_summary.median or float("inf")),
        "memory": float(candidate.peak_memory_summary.median or float("inf")),
        "reproducibility": 1.0 if candidate.reproducibility_level == "Level 2" else 0.0,
    }


def _is_batch_integration_candidate(candidate: CandidateEvaluation) -> bool:
    return {
        "batch_mixing_asw",
        "biology_conservation_asw",
    } <= set(candidate.metric_summaries)


def _is_annotation_candidate(candidate: CandidateEvaluation) -> bool:
    return {"macro_f1", "balanced_accuracy", "reject_rate"} <= set(
        candidate.metric_summaries
    )


def _dominates(left: dict[str, float], right: dict[str, float]) -> bool:
    maximize = ("auprc", "f1", "stability", "success", "reproducibility")
    minimize = ("reject", "runtime", "memory")
    no_worse = all(left[key] >= right[key] for key in maximize) and all(
        left[key] <= right[key] for key in minimize
    )
    strictly_better = any(left[key] > right[key] for key in maximize) or any(
        left[key] < right[key] for key in minimize
    )
    return no_worse and strictly_better


def _preference_scores(
    candidates,
    vectors,
    preference: str,
    *,
    weights_by_preference=PREFERENCE_WEIGHTS,
) -> dict[str, float]:
    weights = weights_by_preference[preference]
    normalized: dict[str, dict[str, float]] = {candidate.candidate_id: {} for candidate in candidates}
    for objective in (
        "auprc",
        "f1",
        "reject",
        "stability",
        "success",
        "runtime",
        "memory",
        "reproducibility",
    ):
        values = [vectors[candidate.candidate_id][objective] for candidate in candidates]
        lower, upper = min(values), max(values)
        for candidate in candidates:
            value = vectors[candidate.candidate_id][objective]
            if upper == lower:
                score = 1.0
            elif objective in {"reject", "runtime", "memory"}:
                score = (upper - value) / (upper - lower)
            else:
                score = (value - lower) / (upper - lower)
            normalized[candidate.candidate_id][objective] = score
    return {
        candidate.candidate_id: sum(
            normalized[candidate.candidate_id][objective] * weight
            for objective, weight in weights.items()
        )
        for candidate in candidates
    }
