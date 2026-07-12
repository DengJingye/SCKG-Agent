from __future__ import annotations

import hashlib
import json

from core.execution_models import CandidateEvaluation, DecisionResult, PreferenceProfile


PREFERENCE_WEIGHTS = {
    "performance": {"performance": 0.50, "stability": 0.25, "success": 0.15, "runtime": 0.03, "memory": 0.02, "reproducibility": 0.05},
    "stability": {"performance": 0.25, "stability": 0.45, "success": 0.20, "runtime": 0.03, "memory": 0.02, "reproducibility": 0.05},
    "resource": {"performance": 0.15, "stability": 0.15, "success": 0.15, "runtime": 0.20, "memory": 0.30, "reproducibility": 0.05},
    "fast_local": {"performance": 0.20, "stability": 0.15, "success": 0.15, "runtime": 0.35, "memory": 0.10, "reproducibility": 0.05},
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
            scores = _preference_scores(pareto, vectors, preference_value)
            finalists = pareto
            if preference_value == "performance":
                best_performance = max(
                    vectors[item.candidate_id]["performance"] for item in pareto
                )
                finalists = [
                    item
                    for item in pareto
                    if abs(
                        vectors[item.candidate_id]["performance"] - best_performance
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
                "multitool_doublet_detection" if multitool else "scrublet_configuration"
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
                    "Decision compares normalized engineering metrics across doublet-detection tools; raw scores are never compared directly."
                    if multitool
                    else "Decision compares Scrublet parameter configurations only, not multiple tools."
                ),
                *(
                    [
                        "Cross-tool comparison is incomplete because at least one tool has no eligible candidate."
                    ]
                    if multitool and len({item.tool_name for item in eligible}) < len(tool_names)
                    else []
                ),
                (
                    "Metrics are scientific_pilot_metric limited to GSE108313 and this preprocessing."
                    if scientific
                    else "Metrics are synthetic_engineering_metric and do not establish biological performance."
                ),
                "Runtime uses the seed median; cold-start and run-order effects may still remain.",
                "No undefined confidence percentage is produced.",
            ],
        )


def _vector(candidate: CandidateEvaluation) -> dict[str, float]:
    performance = (
        candidate.metric_summaries.get("scientific_pilot_auprc")
        or candidate.metric_summaries.get("synthetic_engineering_auprc")
        or candidate.metric_summaries.get("scientific_pilot_f1")
        or candidate.metric_summaries.get("synthetic_engineering_f1")
    )
    return {
        "performance": float(
            performance.mean
            if performance and performance.mean is not None
            else 0.0
        ),
        "stability": float(candidate.seed_stability.get("stability_score", 0.0)),
        "success": candidate.execution_success_rate,
        "runtime": float(candidate.runtime_summary.median or float("inf")),
        "memory": float(candidate.peak_memory_summary.median or float("inf")),
        "reproducibility": 1.0 if candidate.reproducibility_level == "Level 2" else 0.0,
    }


def _dominates(left: dict[str, float], right: dict[str, float]) -> bool:
    maximize = ("performance", "stability", "success", "reproducibility")
    minimize = ("runtime", "memory")
    no_worse = all(left[key] >= right[key] for key in maximize) and all(
        left[key] <= right[key] for key in minimize
    )
    strictly_better = any(left[key] > right[key] for key in maximize) or any(
        left[key] < right[key] for key in minimize
    )
    return no_worse and strictly_better


def _preference_scores(candidates, vectors, preference: str) -> dict[str, float]:
    weights = PREFERENCE_WEIGHTS[preference]
    normalized: dict[str, dict[str, float]] = {candidate.candidate_id: {} for candidate in candidates}
    for objective in (
        "performance",
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
            elif objective in {"runtime", "memory"}:
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
