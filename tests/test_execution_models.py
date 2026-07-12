from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from core.execution_models import (
    CountSourceSelection,
    DataProfile,
    ExecutionBudget,
    MatrixProfile,
    RequirementSpec,
    UserApproval,
    WorkflowPlan,
)


def test_requirement_approval_must_bind_plan_and_authorization():
    approval = UserApproval(
        approval_state="approved",
        approved_plan_id="plan_1",
        approved_plan_hash="hash_1",
        approved_budget_snapshot={"max_cells": 1000},
        approved_at=datetime.now(timezone.utc),
    )
    requirement = RequirementSpec(
        request_id="request_1",
        query="detect doublets",
        execution_authorized=True,
        user=approval,
    )
    assert requirement.user.approval_state == "approved"

    with pytest.raises(ValidationError, match="execution_authorized"):
        RequirementSpec(
            request_id="request_2",
            query="detect doublets",
            execution_authorized=False,
            user=approval,
        )


def test_data_profile_rejects_non_raw_selected_source():
    matrix = MatrixProfile(
        matrix_id="X",
        shape=(10, 5),
        dtype="float32",
        is_sparse=False,
        inferred_state="scaled",
        inference_confidence="high",
    )
    with pytest.raises(ValidationError, match="raw_counts"):
        DataProfile(
            profile_id="profile_1",
            file_path_redacted=".../input.h5ad",
            object_type="AnnData",
            n_cells=10,
            n_genes=5,
            matrix_profiles=[matrix],
            selected_count_source="X",
            count_source_selection=CountSourceSelection(method="deterministic_rule"),
        )


def test_unresolved_count_source_is_always_blocking():
    with pytest.raises(ValidationError, match="must be blocking"):
        DataProfile(
            profile_id="profile_2",
            file_path_redacted=".../input.h5ad",
            count_source_selection={"method": "unresolved", "evidence": []},
        )


def test_execution_budget_and_workflow_plan_invariants():
    with pytest.raises(ValidationError, match="exceeds"):
        ExecutionBudget(
            max_initial_runs=12,
            reserved_repair_runs=5,
            reserved_validation_reruns=2,
            max_total_runs=18,
        )

    with pytest.raises(ValidationError, match="must be blocked"):
        WorkflowPlan(
            plan_id="plan_1",
            requirement_id="request_1",
            profile_id="profile_1",
            blocking_conditions=["count_source_unresolved"],
            plan_status="dry_run",
        )

