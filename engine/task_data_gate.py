from __future__ import annotations

from core.execution_models import (
    DataProfile,
    MatrixState,
    RequirementSpec,
    TaskDataEligibility,
    TaskName,
)


_STRUCTURAL_BLOCKERS = (
    "invalid_file_extension",
    "input_file_missing",
    "input_path_not_file",
    "anndata_read_failed",
    "empty_anndata",
)


class TaskDataGate:
    """Interpret one immutable DataProfile against task-specific requirements."""

    def evaluate(
        self,
        requirement: RequirementSpec,
        profile: DataProfile,
    ) -> TaskDataEligibility:
        if requirement.task == TaskName.BATCH_INTEGRATION:
            return self._batch_integration(requirement, profile)
        return self._doublet_detection(profile)

    @staticmethod
    def _doublet_detection(profile: DataProfile) -> TaskDataEligibility:
        reasons = list(profile.blocking_errors)
        if profile.selected_count_source is None and "count_source_unresolved" not in reasons:
            reasons.append("count_source_unresolved")
        return TaskDataEligibility(
            task=TaskName.DOUBLET_DETECTION,
            allowed=not reasons,
            selected_representation=profile.selected_count_source,
            batch_key=profile.batch_key,
            batch_count=profile.batch_count,
            biology_label_mode="not_applicable",
            blocking_reasons=sorted(set(reasons)),
            warnings=list(profile.warnings),
            checks={
                "raw_count_source_resolved": profile.selected_count_source is not None,
                "profile_structurally_valid": not _structural_blockers(profile),
            },
        )

    @staticmethod
    def _batch_integration(
        requirement: RequirementSpec,
        profile: DataProfile,
    ) -> TaskDataEligibility:
        reasons = _structural_blockers(profile)
        warnings: list[str] = []

        if not requirement.batch_key:
            reasons.append("batch_key_required")
        elif profile.batch_key != requirement.batch_key:
            reasons.append(f"batch_key_unresolved:{requirement.batch_key}")
        if profile.batch_count is None or profile.batch_count < 2:
            reasons.append("at_least_two_batches_required")
        if profile.batch_missing_count:
            reasons.append(f"batch_labels_missing:{profile.batch_missing_count}")
        if profile.batch_min_cells is not None and profile.batch_min_cells < 2:
            reasons.append(f"batch_too_small:{profile.batch_min_cells}")
        if profile.batch_imbalance_ratio is not None and profile.batch_imbalance_ratio > 20.0:
            warnings.append(f"severe_batch_imbalance:{profile.batch_imbalance_ratio:.3f}")

        representation: str | None = None
        if profile.has_pca:
            if profile.pca_finite is not True or not profile.pca_n_components:
                reasons.append("invalid_pca_representation")
            else:
                representation = "obsm/X_pca"
        else:
            x_profile = next(
                (item for item in profile.matrix_profiles if item.matrix_id == "X"),
                None,
            )
            fatal_x = bool(
                x_profile
                and {"empty_matrix", "contains_nan", "contains_inf"}.intersection(
                    x_profile.blocking_reasons
                )
            )
            if x_profile is not None and not fatal_x and x_profile.inferred_state in {
                MatrixState.RAW_COUNTS,
                MatrixState.NORMALIZED,
                MatrixState.LOG_NORMALIZED,
                MatrixState.SCALED,
            }:
                representation = "X"
                warnings.append("pca_preprocessing_required")
                if x_profile.inferred_state == MatrixState.RAW_COUNTS:
                    warnings.append("normalization_required_before_pca")
            elif profile.selected_count_source is not None:
                representation = profile.selected_count_source
                warnings.extend(["normalization_required_before_pca", "pca_preprocessing_required"])
            else:
                reasons.append("integration_representation_unresolved")

        if requirement.label_key:
            if profile.label_key != requirement.label_key:
                reasons.append(f"label_key_unresolved:{requirement.label_key}")
                label_mode = "degraded_no_label"
            elif profile.label_count is None or profile.label_count < 2:
                reasons.append("biology_label_requires_two_classes")
                label_mode = "degraded_no_label"
            else:
                label_mode = "available"
                if profile.label_missing_count:
                    warnings.append(f"biology_labels_missing:{profile.label_missing_count}")
        else:
            label_mode = "degraded_no_label"
            warnings.append("biology_conservation_metric_unavailable_without_label")

        return TaskDataEligibility(
            task=TaskName.BATCH_INTEGRATION,
            allowed=not reasons,
            selected_representation=representation,
            batch_key=profile.batch_key,
            batch_count=profile.batch_count,
            biology_label_mode=label_mode,
            blocking_reasons=sorted(set(reasons)),
            warnings=sorted(set(warnings)),
            checks={
                "profile_structurally_valid": not _structural_blockers(profile),
                "batch_key_resolved": profile.batch_key == requirement.batch_key,
                "multi_batch": bool(profile.batch_count and profile.batch_count >= 2),
                "batch_labels_complete": profile.batch_missing_count == 0,
                "representation_resolved": representation is not None,
                "existing_pca_valid": profile.has_pca and profile.pca_finite is True,
                "biology_label_available": label_mode == "available",
                "count_source_required": False,
            },
        )


def _structural_blockers(profile: DataProfile) -> list[str]:
    return sorted(
        {
            reason
            for reason in profile.blocking_errors
            if reason.startswith(_STRUCTURAL_BLOCKERS)
        }
    )
