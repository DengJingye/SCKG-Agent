from __future__ import annotations

import hashlib
import json
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from pydantic import Field, model_validator

from core.execution_models import (
    ExecutionBudget,
    ExecutionRun,
    StrictModel,
    ToolContract,
    ValidationResult,
)


class RepairType(str, Enum):
    REDUCE_PROBE_SIZE = "reduce_probe_size"
    REDUCE_N_PRIN_COMPS = "reduce_n_prin_comps"
    SWITCH_APPROX_NEIGHBORS = "switch_approx_neighbors"
    ADJUST_EXPECTED_DOUBLET_RATE = "adjust_expected_doublet_rate_within_contract"
    RETRY_SAME_REQUEST_ONCE = "retry_same_request_once"
    REDUCE_WORKER_CORE_COUNT = "reduce_worker_core_count"


class RepairReason(str, Enum):
    TIMEOUT = "timeout"
    MEMORY_SOFT_LIMIT = "memory_soft_limit"
    INVALID_N_PRIN_COMPS = "invalid_n_prin_comps"
    INSUFFICIENT_CELLS = "insufficient_cells"
    MISSING_OPTIONAL_ARTIFACT = "missing_optional_artifact"
    TRANSIENT_PROCESS_FAILURE = "transient_process_failure"
    UNAUTHORIZED_EXECUTION = "unauthorized_execution"
    PATH_ESCAPE = "path_escape"
    UNKNOWN_WRAPPER = "unknown_wrapper"
    INVALID_CONTRACT = "invalid_contract"
    UNRESOLVED_COUNT_SOURCE = "unresolved_count_source"
    HASH_MISMATCH = "hash_mismatch"
    SCIENTIFIC_LABEL_ERROR = "scientific_label_error"
    EXECUTION_GATE_FAILURE = "execution_gate_failure"
    UNKNOWN_FAILURE = "unknown_failure"


REPAIRABLE_REASONS = {
    RepairReason.TIMEOUT,
    RepairReason.MEMORY_SOFT_LIMIT,
    RepairReason.INVALID_N_PRIN_COMPS,
    RepairReason.INSUFFICIENT_CELLS,
    RepairReason.MISSING_OPTIONAL_ARTIFACT,
    RepairReason.TRANSIENT_PROCESS_FAILURE,
}

NON_REPAIRABLE_REASONS = {
    RepairReason.UNAUTHORIZED_EXECUTION,
    RepairReason.PATH_ESCAPE,
    RepairReason.UNKNOWN_WRAPPER,
    RepairReason.INVALID_CONTRACT,
    RepairReason.UNRESOLVED_COUNT_SOURCE,
    RepairReason.HASH_MISMATCH,
    RepairReason.SCIENTIFIC_LABEL_ERROR,
    RepairReason.EXECUTION_GATE_FAILURE,
}


class RepairProposal(StrictModel):
    proposal_id: str
    parent_run_id: str
    reason_code: RepairReason
    repair_type: RepairType
    changed_fields: list[str]
    old_values: dict[str, Any]
    new_values: dict[str, Any]
    provenance: dict[str, Any]
    approval_required: bool = False
    changes_execution_scope: bool = False

    @model_validator(mode="after")
    def validate_changes(self) -> "RepairProposal":
        fields = set(self.changed_fields)
        if fields != set(self.old_values) or fields != set(self.new_values):
            raise ValueError("repair changed_fields must match old_values and new_values")
        if self.changes_execution_scope and not self.approval_required:
            raise ValueError("scope-changing repair requires approval")
        return self


class RepairAction(StrictModel):
    action_id: str
    proposal_id: str
    parent_run_id: str
    new_run_id: str
    reason_code: RepairReason
    repair_type: RepairType
    changed_fields: list[str]
    old_values: dict[str, Any]
    new_values: dict[str, Any]
    provenance: dict[str, Any]
    approval_required: bool
    approved: bool


class RunBudgetLedger(StrictModel):
    limits: ExecutionBudget = Field(default_factory=ExecutionBudget)
    initial_runs_used: int = Field(default=0, ge=0)
    repair_runs_used: int = Field(default=0, ge=0)
    validation_reruns_used: int = Field(default=0, ge=0)

    @property
    def total_runs_used(self) -> int:
        return self.initial_runs_used + self.repair_runs_used + self.validation_reruns_used

    def reserve_initial(self, count: int) -> "RunBudgetLedger":
        if count < 0 or self.initial_runs_used + count > self.limits.max_initial_runs:
            raise ValueError("initial_run_budget_exhausted")
        return self._reserve(initial=count)

    def reserve_repair(self, count: int = 1) -> "RunBudgetLedger":
        if count < 0 or self.repair_runs_used + count > self.limits.reserved_repair_runs:
            raise ValueError("repair_run_budget_exhausted")
        return self._reserve(repair=count)

    def reserve_validation_rerun(self, count: int = 1) -> "RunBudgetLedger":
        if count < 0 or self.validation_reruns_used + count > self.limits.reserved_validation_reruns:
            raise ValueError("validation_rerun_budget_exhausted")
        return self._reserve(validation=count)

    def _reserve(
        self, *, initial: int = 0, repair: int = 0, validation: int = 0
    ) -> "RunBudgetLedger":
        updated = self.model_copy(
            update={
                "initial_runs_used": self.initial_runs_used + initial,
                "repair_runs_used": self.repair_runs_used + repair,
                "validation_reruns_used": self.validation_reruns_used + validation,
            }
        )
        if updated.total_runs_used > self.limits.max_total_runs:
            raise ValueError("total_run_budget_exhausted")
        return updated


class RepairPolicy:
    """Deterministic repair policy; it never changes code, tools, or execution scope."""

    def classify(
        self, run: ExecutionRun, validation: ValidationResult
    ) -> RepairReason:
        error = (run.error_type or "").casefold()
        failures = {item.casefold() for item in validation.failures}
        stderr = _read_text(run.stderr_path).casefold()
        combined = " ".join([error, run.error_message or "", stderr]).casefold()

        if error in {"unauthorized_execution", "qualification_route_blocked"}:
            return RepairReason.UNAUTHORIZED_EXECUTION
        if "escape" in error or "path_escape" in combined:
            return RepairReason.PATH_ESCAPE
        if error == "unknown_wrapper":
            return RepairReason.UNKNOWN_WRAPPER
        if error in {"invalid_parameter", "runtime_version_mismatch"}:
            return RepairReason.INVALID_CONTRACT
        if error in {"input_hash_mismatch"} or "artifact_hash_mismatch" in failures:
            return RepairReason.HASH_MISMATCH
        if "scientific_label" in combined:
            return RepairReason.SCIENTIFIC_LABEL_ERROR
        if error in {"execution_gate_failure", "qualification_budget_exceeded"}:
            return RepairReason.EXECUTION_GATE_FAILURE
        if run.status == "timeout" or error == "timeout":
            return RepairReason.TIMEOUT
        if "memory_soft_limit" in failures or "memory soft limit" in combined:
            return RepairReason.MEMORY_SOFT_LIMIT
        if (
            "n_components" in combined
            or "n_prin_comps" in combined
            or "principal components" in combined
        ):
            return RepairReason.INVALID_N_PRIN_COMPS
        if "insufficient_cells" in failures or "too few cells" in combined:
            return RepairReason.INSUFFICIENT_CELLS
        if "missing_optional_artifact" in failures:
            return RepairReason.MISSING_OPTIONAL_ARTIFACT
        if run.status == "failed" and error == "wrapper_exit_nonzero":
            return RepairReason.TRANSIENT_PROCESS_FAILURE
        return RepairReason.UNKNOWN_FAILURE

    def propose(
        self,
        *,
        run: ExecutionRun,
        validation: ValidationResult,
        contract: ToolContract,
        expected_cells: int,
        previous_repairs_for_parent: int = 0,
    ) -> Optional[RepairProposal]:
        reason = self.classify(run, validation)
        if reason not in REPAIRABLE_REASONS:
            return None
        old = dict(run.parameters)
        is_scdblfinder = contract.tool_name.casefold() == "scdblfinder"
        repair_type: RepairType
        changes: dict[str, Any]

        if reason in {RepairReason.INVALID_N_PRIN_COMPS, RepairReason.INSUFFICIENT_CELLS}:
            if is_scdblfinder:
                return None
            current = int(old.get("n_prin_comps", 30))
            minimum = int(
                contract.parameter_schema["properties"]["n_prin_comps"].get("minimum", 2)
            )
            repaired = max(minimum, min(10, current - 1, expected_cells - 1))
            if repaired >= current:
                return None
            repair_type = RepairType.REDUCE_N_PRIN_COMPS
            changes = {"n_prin_comps": repaired}
        elif reason == RepairReason.TIMEOUT:
            repair_type = RepairType.REDUCE_PROBE_SIZE
            changes = {"probe_max_cells": max(10, expected_cells // 2)}
        elif reason == RepairReason.MEMORY_SOFT_LIMIT:
            if is_scdblfinder:
                current_cores = int(old.get("n_cores", 1))
                if current_cores <= 1:
                    return None
                repair_type = RepairType.REDUCE_WORKER_CORE_COUNT
                changes = {"n_cores": max(1, current_cores // 2)}
            else:
                repair_type = RepairType.SWITCH_APPROX_NEIGHBORS
                changes = {"use_approx_neighbors": True}
        elif reason == RepairReason.MISSING_OPTIONAL_ARTIFACT:
            repair_type = RepairType.RETRY_SAME_REQUEST_ONCE
            changes = {"retry_token": previous_repairs_for_parent + 1}
        else:
            if previous_repairs_for_parent >= 1:
                return None
            repair_type = RepairType.RETRY_SAME_REQUEST_ONCE
            changes = {"retry_token": 1}

        old_values = {name: old.get(name) for name in changes}
        proposal_payload = {
            "parent_run_id": run.run_id,
            "reason": reason.value,
            "repair_type": repair_type.value,
            "old": old_values,
            "new": changes,
        }
        proposal_id = "repair-proposal-" + _hash(proposal_payload)[:16]
        return RepairProposal(
            proposal_id=proposal_id,
            parent_run_id=run.run_id,
            reason_code=reason,
            repair_type=repair_type,
            changed_fields=sorted(changes),
            old_values=old_values,
            new_values=changes,
            provenance={
                "origin": "repair_policy",
                "policy_version": "phase4-repair-policy-v1",
                "contract_id": contract.contract_id,
                "contract_version": contract.contract_version,
            },
            approval_required=False,
            changes_execution_scope=False,
        )

    def apply(
        self,
        *,
        proposal: RepairProposal,
        new_run_id: str,
        approved: bool,
    ) -> RepairAction:
        if proposal.changes_execution_scope:
            raise ValueError("repair_scope_change_requires_new_approval")
        if proposal.approval_required and not approved:
            raise ValueError("repair_approval_required")
        if not approved:
            raise ValueError("repair_rejected")
        return RepairAction(
            action_id="repair-action-" + _hash(
                {"proposal": proposal.proposal_id, "new_run_id": new_run_id}
            )[:16],
            proposal_id=proposal.proposal_id,
            parent_run_id=proposal.parent_run_id,
            new_run_id=new_run_id,
            reason_code=proposal.reason_code,
            repair_type=proposal.repair_type,
            changed_fields=proposal.changed_fields,
            old_values=proposal.old_values,
            new_values=proposal.new_values,
            provenance=proposal.provenance,
            approval_required=proposal.approval_required,
            approved=True,
        )


def apply_repair_parameters(
    parameters: dict[str, Any], proposal: RepairProposal
) -> dict[str, Any]:
    repaired = dict(parameters)
    for name, value in proposal.new_values.items():
        if name not in {"probe_max_cells", "retry_token"}:
            repaired[name] = value
    return repaired


def _read_text(path_text: str) -> str:
    path = Path(path_text)
    try:
        return path.read_text(encoding="utf-8") if path.is_file() else ""
    except OSError:
        return ""


def _hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()
