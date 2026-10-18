from __future__ import annotations

import csv
import math
from pathlib import Path
from typing import Any

from core.research_workspace_models import (
    PreviewErrorDiagnosis,
    PreviewNextAction,
    PreviewObservedMetric,
    PreviewParameterExplanation,
    PreviewPlotExplanation,
    PreviewResultIntegrity,
    PreviewResultInterpretation,
    PreviewRunResult,
    WorkspaceCheckpointReport,
)


class PreviewResultInterpreter:
    """Translate governed Preview outputs into bounded, user-readable guidance."""

    def interpret(
        self,
        *,
        result: PreviewRunResult,
        integrity: PreviewResultIntegrity,
        checkpoint: WorkspaceCheckpointReport | None = None,
        result_table_path: Path | None = None,
    ) -> PreviewResultInterpretation:
        status = _status(result, integrity, checkpoint)
        parameters = dict(result.execution_run.parameters)
        parameter_explanations = _parameter_explanations(parameters)
        diagnosis = PreviewErrorIntelligence().diagnose(
            result=result, integrity=integrity, checkpoint=checkpoint
        )

        if status != "COMPLETED":
            next_actions = diagnosis.user_actions if diagnosis is not None else []
            return PreviewResultInterpretation(
                run_id=result.execution_run.run_id,
                status=status,
                headline=_failure_headline(status, diagnosis),
                plain_language_summary=_failure_summary(status, diagnosis),
                parameter_explanations=parameter_explanations,
                warnings=_unique(result.validation_result.warnings),
                limitations=_limitations(),
                next_actions=next_actions,
                error_diagnosis=diagnosis,
                usable_for_preview_review=False,
            )

        rows = _read_result_rows(result_table_path)
        scores = [row[0] for row in rows]
        predicted = [row[1] for row in rows]
        expected_cells = len(rows)
        call_rate = (
            sum(predicted) / expected_cells
            if expected_cells
            else _number_or_none(
                result.validation_result.task_metrics.get(
                    "preview_predicted_doublet_call_rate"
                )
            )
        )
        expected_rate = _number_or_none(parameters.get("expected_doublet_rate"))
        observed = _observed_metrics(
            result=result,
            scores=scores,
            expected_cells=expected_cells,
            call_rate=call_rate,
        )
        warnings = list(result.validation_result.warnings)
        warnings.extend(_rate_warnings(call_rate, expected_rate, expected_cells))
        summary = [
            "The fixed Scrublet wrapper completed on the representative Preview, and the required output files, hashes, row count, score range and labels passed engineering validation.",
            _call_rate_summary(call_rate, expected_rate),
            "The score distribution is a diagnostic for deciding whether the configured workflow is plausible; it is not an estimate of biological accuracy because this user-data Preview has no independent doublet ground truth.",
        ]
        return PreviewResultInterpretation(
            run_id=result.execution_run.run_id,
            status="COMPLETED",
            headline="The Preview ran correctly; review the score distribution before planning any full-data analysis.",
            plain_language_summary=summary,
            observed_metrics=observed,
            parameter_explanations=parameter_explanations,
            plot_explanation=_plot_explanation(),
            warnings=_unique(warnings),
            limitations=_limitations(),
            next_actions=_success_actions(),
            error_diagnosis=None,
            usable_for_preview_review=True,
        )


class PreviewErrorIntelligence:
    """Classify governed Preview failures without mutating inputs or retrying."""

    def diagnose(
        self,
        *,
        result: PreviewRunResult,
        integrity: PreviewResultIntegrity,
        checkpoint: WorkspaceCheckpointReport | None = None,
    ) -> PreviewErrorDiagnosis | None:
        return _diagnose(result, integrity, checkpoint)


def _status(
    result: PreviewRunResult,
    integrity: PreviewResultIntegrity,
    checkpoint: WorkspaceCheckpointReport | None,
) -> str:
    if not integrity.passed:
        return "FAILED"
    if checkpoint is not None:
        if checkpoint.overall_status == "STALE":
            return "STALE"
        if checkpoint.overall_status in {"BLOCKED", "FAILED"}:
            return checkpoint.overall_status
    if result.status == "blocked" or result.execution_run.status == "blocked":
        return "BLOCKED"
    if result.status == "validated" and result.validation_result.passed:
        return "COMPLETED"
    return "FAILED"


def _read_result_rows(path: Path | None) -> list[tuple[float, bool]]:
    if path is None or not path.is_file():
        return []
    rows: list[tuple[float, bool]] = []
    try:
        with path.open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle, delimiter="\t"):
                score = float(row.get("doublet_score", "nan"))
                label = row.get("predicted_doublet")
                if math.isfinite(score) and 0 <= score <= 1 and label in {"true", "false"}:
                    rows.append((score, label == "true"))
    except (OSError, TypeError, ValueError):
        return []
    return rows


def _observed_metrics(
    *,
    result: PreviewRunResult,
    scores: list[float],
    expected_cells: int,
    call_rate: float | None,
) -> list[PreviewObservedMetric]:
    metrics = [
        PreviewObservedMetric(
            metric_id="preview_cells",
            label="Preview cells",
            display_value=f"{expected_cells:,}" if expected_cells else "Unavailable",
            raw_value=expected_cells or None,
            meaning="Cells represented in this bounded Preview result, not necessarily the full dataset.",
        ),
        PreviewObservedMetric(
            metric_id="predicted_call_rate",
            label="Predicted call rate",
            display_value=_percent(call_rate),
            raw_value=call_rate,
            meaning="Fraction called doublet by this Scrublet configuration on the Preview; it is not a measured ground-truth doublet rate.",
        ),
        PreviewObservedMetric(
            metric_id="median_score",
            label="Median score",
            display_value=_decimal(_quantile(scores, 0.5)),
            raw_value=_quantile(scores, 0.5),
            meaning="Middle Scrublet score across Preview cells. Compare distributions, not this number alone.",
        ),
        PreviewObservedMetric(
            metric_id="score_p90",
            label="Score P90",
            display_value=_decimal(_quantile(scores, 0.9)),
            raw_value=_quantile(scores, 0.9),
            meaning="Ninetieth percentile of Preview scores; useful for locating the high-score tail.",
        ),
        PreviewObservedMetric(
            metric_id="runtime_seconds",
            label="Runtime",
            display_value=f"{result.execution_run.runtime_seconds:.2f}s",
            raw_value=result.execution_run.runtime_seconds,
            meaning="Observed local runtime for this representative Preview only.",
        ),
        PreviewObservedMetric(
            metric_id="peak_memory_mb",
            label="Peak memory",
            display_value=(
                f"{result.execution_run.peak_memory_mb:.1f} MiB"
                if result.execution_run.peak_memory_mb is not None
                else "Unavailable"
            ),
            raw_value=result.execution_run.peak_memory_mb,
            meaning="Observed process memory for this Preview; full-data requirements may be larger.",
        ),
    ]
    return metrics


def _parameter_explanations(parameters: dict[str, Any]) -> list[PreviewParameterExplanation]:
    definitions = {
        "expected_doublet_rate": (
            "Sets Scrublet's prior expectation and influences thresholding; it does not force the observed call rate to match this value.",
            "Check it against the loading and recovery for each 10x capture. Do not tune it merely to make the output equal the prior.",
        ),
        "n_prin_comps": (
            "Controls the dimensionality used to construct the neighbor space; too many components for a small Preview can fail or add noisy structure.",
            "Keep changes inside the ToolContract. A changed value invalidates the existing approval and requires a new governed run.",
        ),
        "sim_doublet_ratio": (
            "Controls how many synthetic doublets Scrublet simulates relative to observed cells.",
            "Use the reviewed contract range; this Preview does not justify automatic optimization.",
        ),
        "random_state": (
            "Fixes stochastic operations so the same Preview and parameters can be reproduced.",
            "Keep fixed when comparing parameter changes; otherwise parameter and seed effects become confounded.",
        ),
        "use_approx_neighbors": (
            "Chooses approximate neighbor search, which can reduce resource cost on larger inputs.",
            "Treat a change as a new governed configuration and compare validated artifacts rather than assuming equivalence.",
        ),
    }
    explanations = []
    for name, (effect, guidance) in definitions.items():
        if name in parameters:
            explanations.append(
                PreviewParameterExplanation(
                    parameter_name=name,
                    value=parameters[name],
                    effect=effect,
                    review_guidance=guidance,
                )
            )
    return explanations


def _plot_explanation() -> PreviewPlotExplanation:
    return PreviewPlotExplanation(
        artifact_name="doublet_score_histogram.png",
        title="Scrublet score distribution",
        x_axis="Scrublet doublet score; farther right means more doublet-like under this fitted model.",
        y_axis="Number of cells from the representative Preview in each score bin.",
        how_to_read=[
            "Look for a high-score tail or a separated high-score group, then inspect how the predicted calls sit in that region.",
            "Compare captures or parameter configurations with the same seed and Preview lineage; do not compare unrelated subsets as if they were identical experiments.",
            "Use the distribution together with 10x loading information and downstream biological review, not as a stand-alone pass/fail plot.",
        ],
        caution="A clean or separated histogram does not establish sensitivity, specificity or biological correctness because this Preview has no independent truth labels.",
    )


def _success_actions() -> list[PreviewNextAction]:
    return [
        PreviewNextAction(
            priority=1,
            action_id="review_score_distribution",
            label="Review the high-score tail and predicted call rate",
            reason="This checks whether the fixed configuration produces a plausible diagnostic pattern before any larger run.",
        ),
        PreviewNextAction(
            priority=2,
            action_id="verify_capture_metadata",
            label="Verify 10x loading and expected doublet rate per capture",
            reason="Expected doublet burden depends on loading and recovery, and pooled samples can obscure capture-specific behavior.",
        ),
        PreviewNextAction(
            priority=3,
            action_id="prepare_separate_full_data_plan",
            label="Prepare a separately governed full-data plan if the Preview is acceptable",
            reason="Preview approval is single-use and does not authorize full-data scientific execution.",
            requires_new_approval=True,
        ),
    ]


def _diagnose(
    result: PreviewRunResult,
    integrity: PreviewResultIntegrity,
    checkpoint: WorkspaceCheckpointReport | None,
) -> PreviewErrorDiagnosis | None:
    if not integrity.passed:
        evidence = list(integrity.issues)
        evidence.extend(f"missing:{item}" for item in integrity.missing_artifacts)
        evidence.extend(f"hash_mismatch:{item}" for item in integrity.hash_mismatches)
        evidence.extend(f"escaped:{item}" for item in integrity.escaped_artifacts)
        return PreviewErrorDiagnosis(
            stage="integrity",
            category="artifact_integrity",
            error_code=evidence[0] if evidence else "preview_artifact_integrity_failed",
            severity="critical",
            retryable=False,
            likely_causes=[
                "A persisted result or output artifact changed, disappeared, or resolved outside the owner-scoped run directory."
            ],
            evidence=_unique(evidence),
            user_actions=[
                PreviewNextAction(
                    priority=1,
                    action_id="preserve_and_rebuild_result",
                    label="Do not use the artifacts; preserve logs and rebuild from the earliest invalid checkpoint",
                    reason="Integrity failures cannot be repaired by relabeling or silently rerunning the same result.",
                    requires_new_approval=True,
                )
            ],
        )

    if checkpoint is not None and checkpoint.overall_status == "STALE":
        return PreviewErrorDiagnosis(
            stage="lineage",
            category="stale_lineage",
            error_code=f"stale_from_{checkpoint.first_invalid_stage or 'unknown'}",
            severity="warning",
            retryable=False,
            likely_causes=_unique(
                [reason for node in checkpoint.nodes for reason in node.reasons]
            ),
            evidence=[
                f"first_invalid_stage={checkpoint.first_invalid_stage}",
                f"rebuild_from={checkpoint.rebuild_from}",
            ],
            user_actions=[
                PreviewNextAction(
                    priority=1,
                    action_id=f"rebuild_from_{checkpoint.rebuild_from or 'source'}",
                    label=checkpoint.user_action,
                    reason="A downstream result must not be reused after its source, profile, Preview, template, contract, environment or approval lineage changes.",
                    requires_new_approval=True,
                )
            ],
        )

    context = result.error_context
    code = (
        context.error_code
        if context is not None
        else (
            result.execution_run.error_type
            or (
                result.validation_result.failures[0]
                if result.validation_result.failures
                else "preview_failure_unknown"
            )
        )
    )
    normalized = code.casefold()
    if any(token in normalized for token in ("unauthorized", "approval", "policy", "gate")):
        category = "authorization_or_policy"
    elif "timeout" in normalized or "memory" in normalized:
        category = "resource_limit"
    elif any(token in normalized for token in ("parameter", "n_prin", "count", "input")):
        category = "parameter_or_input"
    elif any(token in normalized for token in ("hash", "escape", "integrity")):
        category = "artifact_integrity"
    elif any(token in normalized for token in ("artifact", "score", "label", "metadata", "validation")):
        category = "output_validation"
    elif any(token in normalized for token in ("wrapper", "runtime", "process", "exit")):
        category = "runtime_or_wrapper"
    else:
        category = "unknown"
    stage = context.stage if context is not None else "validation"
    retryable = bool(context.retryable) if context is not None else False
    evidence = list(result.validation_result.failures)
    if result.execution_run.error_type:
        evidence.append(result.execution_run.error_type)
    action = (
        "Review the governed runtime log and rebuild a smaller Preview or revised notebook under a new approval."
        if retryable
        else "Review the blocker and rebuild from the affected checkpoint before requesting any new approval."
    )
    return PreviewErrorDiagnosis(
        stage=stage,
        category=category,
        error_code=code,
        severity="critical" if category == "artifact_integrity" else "error",
        retryable=retryable,
        likely_causes=_likely_causes(category),
        evidence=_unique(evidence),
        user_actions=[
            PreviewNextAction(
                priority=1,
                action_id="review_and_rebuild_preview_run",
                label=action,
                reason="Preview repair is not automatic; any changed input or parameter must pass the same contract and approval gates again.",
                requires_new_approval=True,
            )
        ],
    )


def _likely_causes(category: str) -> list[str]:
    return {
        "authorization_or_policy": [
            "The data grant, local-user allowlist, execution policy or plan-specific approval did not match the exact request."
        ],
        "resource_limit": [
            "The Preview exceeded its bounded runtime or observed resource envelope."
        ],
        "parameter_or_input": [
            "The raw-count input state or a contract-bounded Scrublet parameter was incompatible with this Preview."
        ],
        "output_validation": [
            "The process returned, but one or more required artifacts, rows, scores, labels or metadata failed validation."
        ],
        "runtime_or_wrapper": [
            "The fixed wrapper or its qualified runtime did not complete successfully."
        ],
        "artifact_integrity": [
            "An input or output hash, ownership path or persisted result digest did not match."
        ],
        "unknown": [
            "The available structured trace does not yet identify a more specific root cause."
        ],
    }.get(category, ["The structured failure record is incomplete."])


def _failure_headline(
    status: str, diagnosis: PreviewErrorDiagnosis | None
) -> str:
    if status == "STALE":
        return "This result is stale and must not be used until its lineage is rebuilt."
    if status == "BLOCKED":
        return "The Preview was correctly blocked before a usable result was admitted."
    if diagnosis is not None:
        return f"The Preview is not usable: {diagnosis.category.replace('_', ' ')}."
    return "The Preview did not produce a validated result."


def _failure_summary(
    status: str, diagnosis: PreviewErrorDiagnosis | None
) -> list[str]:
    if diagnosis is None:
        return ["No user-facing interpretation is available because validation did not pass."]
    message = (
        "The recorded run is preserved for audit, but its metrics and plot are withheld from scientific interpretation."
    )
    if status == "STALE":
        message = "The original run may have completed, but a later lineage change invalidated reuse of its result."
    return [
        message,
        *diagnosis.likely_causes,
        "No parameter, input, approval or artifact is changed automatically.",
    ]


def _limitations() -> list[str]:
    return [
        "The representative Preview can establish schema, runtime and artifact compatibility only; it cannot establish full-data behavior or scientific accuracy.",
        "No independent doublet ground truth is available for user data, so sensitivity, specificity, precision and recall are not estimated here.",
        "Homotypic doublets and cells on continuous biological trajectories can remain difficult to distinguish from singlets.",
        "Preview sampling can alter score distributions, especially for small or heterogeneous captures.",
    ]


def _rate_warnings(
    call_rate: float | None, expected_rate: float | None, expected_cells: int
) -> list[str]:
    warnings: list[str] = []
    if expected_cells and expected_cells < 100:
        warnings.append(
            "The Preview contains fewer than 100 cells, so its score distribution and call rate may be unstable."
        )
    if call_rate is None or expected_rate is None or expected_rate <= 0:
        return warnings
    ratio = call_rate / expected_rate
    if ratio >= 2.5:
        warnings.append(
            "The Preview call rate is more than 2.5 times the configured expected rate. Review capture metadata, low-quality cells and the score threshold; do not automatically force the rate downward."
        )
    elif ratio <= 0.25:
        warnings.append(
            "The Preview call rate is below one quarter of the configured expected rate. Review Preview representativeness and score separation; do not automatically force the rate upward."
        )
    return warnings


def _call_rate_summary(call_rate: float | None, expected_rate: float | None) -> str:
    if call_rate is None:
        return "The Preview call rate could not be summarized from a verified result table."
    if expected_rate is None:
        return f"Scrublet called {_percent(call_rate)} of Preview cells as doublets; no expected-rate comparison is available."
    return (
        f"Scrublet called {_percent(call_rate)} of Preview cells as doublets with an expected_doublet_rate of "
        f"{_percent(expected_rate)}. A difference is a diagnostic signal, not by itself an error."
    )


def _quantile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def _number_or_none(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def _percent(value: float | None) -> str:
    return f"{value:.1%}" if value is not None else "Unavailable"


def _decimal(value: float | None) -> str:
    return f"{value:.3f}" if value is not None else "Unavailable"


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))
