from __future__ import annotations

from core.execution_models import CandidateEvaluation


class MultitoolScientificCandidateEvaluator:
    """Join frozen evaluation metrics with development seed stability."""

    def finalize(
        self,
        *,
        development_candidates: list[CandidateEvaluation],
        evaluation_candidates: list[CandidateEvaluation],
    ) -> list[CandidateEvaluation]:
        development = {
            _candidate_key(item): item for item in development_candidates
        }
        results: list[CandidateEvaluation] = []
        for evaluation in evaluation_candidates:
            key = _candidate_key(evaluation)
            source = development.get(key)
            if source is None:
                raise ValueError(
                    "evaluation candidate has no development qualification: "
                    + evaluation.candidate_id
                )
            evaluation_succeeded = (
                len(evaluation.run_ids) == 1
                and len(evaluation.successful_run_ids) == 1
                and not evaluation.failed_run_ids
                and evaluation.execution_success_rate == 1.0
            )
            scientific_metrics = {
                name: value
                for name, value in evaluation.metric_summaries.items()
                if name.startswith("scientific_pilot_")
            }
            eligible = (
                source.eligible_for_decision
                and evaluation_succeeded
                and "scientific_pilot_auprc" in scientific_metrics
                and "scientific_pilot_f1" in scientific_metrics
            )
            limitations = set(source.limitations) | set(evaluation.limitations)
            limitations.discard("fewer_than_two_successful_seeds")
            limitations.add(
                "Evaluation parameters and threshold were frozen from development."
            )
            results.append(
                evaluation.model_copy(
                    update={
                        "metric_summaries": scientific_metrics,
                        "seed_stability": source.seed_stability,
                        "limitations": sorted(limitations),
                        "eligible_for_decision": eligible,
                        "metric_authority": "scientific_pilot_metric",
                    }
                )
            )
        return results


def _candidate_key(candidate: CandidateEvaluation) -> tuple[str, str, str]:
    return (
        candidate.tool_name.casefold(),
        candidate.tool_version,
        candidate.configuration_hash,
    )
