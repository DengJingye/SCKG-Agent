from __future__ import annotations

from enum import Enum
from typing import Optional, TYPE_CHECKING

from pydantic import Field

from core.execution_models import (
    EnvironmentRecord,
    ExecutionRequest,
    DataProfile,
    ExecutionGateResult,
    PlanningGateResult,
    QualificationArtifact,
    RequirementSpec,
    StrictModel,
    ToolContract,
    WorkflowPlan,
    ValidationResult,
)
from core.runtime_pack_models import RuntimeCapabilityProbe, RuntimePackState

if TYPE_CHECKING:
    from execution.approval_service import AuthorizationValidation
    from execution.repair_policy import RepairProposal


class RouterMode(str, Enum):
    PROFILE = "profile"
    PLAN = "plan"
    EXECUTION = "execution"
    QUALIFICATION = "qualification"


class RouterRoute(str, Enum):
    PROFILE_ONLY = "PROFILE_ONLY"
    PLAN_ONLY = "PLAN_ONLY"
    EVIDENCE_RECOVERY = "EVIDENCE_RECOVERY"
    CONTRACT_REVIEW = "CONTRACT_REVIEW"
    WAITING_USER_INPUT = "WAITING_USER_INPUT"
    WAITING_DATA_AUTHORIZATION = "WAITING_DATA_AUTHORIZATION"
    WAITING_ENVIRONMENT_APPROVAL = "WAITING_ENVIRONMENT_APPROVAL"
    WAITING_EXECUTION_APPROVAL = "WAITING_EXECUTION_APPROVAL"
    ENVIRONMENT_INSTALLING = "ENVIRONMENT_INSTALLING"
    ENVIRONMENT_UNAVAILABLE = "ENVIRONMENT_UNAVAILABLE"
    BLOCKED = "BLOCKED"
    QUALIFICATION_EXECUTION = "QUALIFICATION_EXECUTION"
    REPAIR_PENDING = "REPAIR_PENDING"
    AGGREGATE_FAILED = "AGGREGATE_FAILED"
    RESTRICTED_USER_EXECUTION = "RESTRICTED_USER_EXECUTION"


class RouterDecision(StrictModel):
    route: RouterRoute
    reasons: list[str] = Field(default_factory=list)
    plan_status: Optional[str] = None
    execution_allowed: bool = False
    parent_override_ignored: bool = False
    qualification_only: bool = False


class DeterministicRouter:
    """Phase 2 policy router. Parent suggestions cannot override deterministic gates."""

    def route(
        self,
        *,
        mode: RouterMode,
        requirement: RequirementSpec,
        data_profile: Optional[DataProfile] = None,
        tool_contract: Optional[ToolContract] = None,
        planning_gate: Optional[PlanningGateResult] = None,
        execution_gate: Optional[ExecutionGateResult] = None,
        plan: Optional[WorkflowPlan] = None,
        parent_route_override: Optional[RouterRoute] = None,
    ) -> RouterDecision:
        route, reasons = self._decide(
            mode=mode,
            requirement=requirement,
            data_profile=data_profile,
            tool_contract=tool_contract,
            planning_gate=planning_gate,
            execution_gate=execution_gate,
            plan=plan,
        )
        ignored = parent_route_override is not None and parent_route_override != route
        if ignored:
            reasons.append(f"parent_route_override_ignored:{parent_route_override}")
        return RouterDecision(
            route=route,
            reasons=sorted(set(reasons)),
            plan_status=plan.plan_status if plan is not None else None,
            execution_allowed=False,
            parent_override_ignored=ignored,
        )

    def route_qualification(
        self,
        *,
        request: ExecutionRequest,
        artifact: QualificationArtifact,
        tool_contract: ToolContract,
        environment: Optional[EnvironmentRecord],
        planning_gate: PlanningGateResult,
        max_timeout_seconds: int,
        parent_route_override: Optional[RouterRoute] = None,
    ) -> RouterDecision:
        reasons: list[str] = []
        if request.actor.role != "maintainer":
            reasons.append("qualification_requires_maintainer")
        if not request.qualification.mode:
            reasons.append("qualification_mode_required")
        if not request.qualification.authorized:
            reasons.append("qualification_not_authorized")
        if not request.qualification.fixture_allowlisted:
            reasons.append("qualification_fixture_not_allowlisted")
        if artifact.user_data:
            reasons.append("user_data_forbidden")
        if request.qualification.purpose == "synthetic_qualification":
            if not artifact.synthetic:
                reasons.append("synthetic_qualification_requires_synthetic_fixture")
        elif request.qualification.purpose == "scientific_pilot":
            if artifact.synthetic:
                reasons.append("scientific_pilot_requires_public_real_dataset")
            if not artifact.public_dataset:
                reasons.append("scientific_pilot_requires_public_dataset")
            if artifact.accession not in {"GSE108313", "scIB-pancreas", "Zheng68K"}:
                reasons.append("scientific_pilot_dataset_not_allowlisted")
        elif request.qualification.purpose == "representative_preview":
            reasons.append("representative_preview_requires_restricted_user_route")
        if not artifact.allowlisted:
            reasons.append("artifact_not_allowlisted")
        if artifact.fixture_id != request.qualification.fixture_id:
            reasons.append("fixture_id_mismatch")
        if not planning_gate.allowed:
            reasons.extend(f"planning_gate:{reason}" for reason in planning_gate.reasons)
        if request.wrapper_id != tool_contract.wrapper_id:
            reasons.append("wrapper_contract_mismatch")
        if request.environment_id != tool_contract.environment_id:
            reasons.append("environment_contract_mismatch")
        if environment is None:
            reasons.append("unknown_environment")
        elif request.environment_id != environment.environment_id:
            reasons.append("environment_registry_mismatch")
        elif environment.qualification_status == "missing":
            reasons.append("environment_qualification_missing")
        elif not environment.import_smoke_passed:
            reasons.append("environment_import_smoke_not_passed")
        if request.timeout_seconds > max_timeout_seconds:
            reasons.append("qualification_timeout_budget_exceeded")

        route = RouterRoute.BLOCKED if reasons else RouterRoute.QUALIFICATION_EXECUTION
        ignored = parent_route_override is not None and parent_route_override != route
        if ignored:
            reasons.append(f"parent_route_override_ignored:{parent_route_override}")
        return RouterDecision(
            route=route,
            reasons=sorted(set(reasons)),
            execution_allowed=not reasons,
            parent_override_ignored=ignored,
            qualification_only=not reasons,
        )

    def route_user_authorization(
        self,
        *,
        data_access: "AuthorizationValidation",
        execution_approval: "AuthorizationValidation | None",
        execution_backend_enabled: bool,
        parent_route_override: Optional[RouterRoute] = None,
    ) -> RouterDecision:
        """Route Phase 6A user authorization without enabling execution."""

        if data_access.code == "missing":
            route = RouterRoute.WAITING_DATA_AUTHORIZATION
            reasons = list(data_access.reasons)
        elif not data_access.allowed:
            route = RouterRoute.BLOCKED
            reasons = list(data_access.reasons)
        elif execution_approval is None or execution_approval.code == "missing":
            route = RouterRoute.WAITING_EXECUTION_APPROVAL
            reasons = (
                list(execution_approval.reasons)
                if execution_approval is not None
                else ["execution_approval_missing"]
            )
        elif not execution_approval.allowed:
            route = RouterRoute.BLOCKED
            reasons = list(execution_approval.reasons)
        elif not execution_backend_enabled:
            route = RouterRoute.BLOCKED
            reasons = ["ordinary_user_execution_disabled_by_policy"]
        else:
            route = RouterRoute.RESTRICTED_USER_EXECUTION
            reasons = ["restricted_local_user_execution_authorized"]

        ignored = parent_route_override is not None and parent_route_override != route
        if ignored:
            reasons.append(f"parent_route_override_ignored:{parent_route_override}")
        return RouterDecision(
            route=route,
            reasons=sorted(set(reasons)),
            execution_allowed=route == RouterRoute.RESTRICTED_USER_EXECUTION,
            parent_override_ignored=ignored,
        )

    def route_runtime_pack(
        self,
        *,
        probe: RuntimeCapabilityProbe,
        parent_route_override: Optional[RouterRoute] = None,
    ) -> RouterDecision:
        """A missing runtime can request consent, but Parent Agent cannot install it."""

        state = RuntimePackState(probe.state)
        if state == RuntimePackState.READY:
            route = RouterRoute.PLAN_ONLY
            reasons = ["runtime_pack_ready"]
        elif state == RuntimePackState.WAITING_APPROVAL:
            route = RouterRoute.WAITING_ENVIRONMENT_APPROVAL
            reasons = ["runtime_pack_install_requires_explicit_approval"]
        elif state in {RuntimePackState.INSTALLING, RuntimePackState.VERIFYING}:
            route = RouterRoute.ENVIRONMENT_INSTALLING
            reasons = [f"runtime_pack_{state.value}"]
        elif state == RuntimePackState.MISSING:
            route = RouterRoute.WAITING_ENVIRONMENT_APPROVAL
            reasons = ["runtime_pack_missing"]
        else:
            route = RouterRoute.ENVIRONMENT_UNAVAILABLE
            reasons = list(probe.warnings) or [f"runtime_pack_{state.value}"]
        ignored = parent_route_override is not None and parent_route_override != route
        if ignored:
            reasons.append(f"parent_route_override_ignored:{parent_route_override}")
        return RouterDecision(
            route=route,
            reasons=sorted(set(reasons)),
            execution_allowed=False,
            parent_override_ignored=ignored,
        )

    def route_repair(
        self,
        *,
        validation: ValidationResult,
        proposal: Optional["RepairProposal"],
        repair_approved: Optional[bool],
        budget_available: bool,
    ) -> RouterDecision:
        """Route a failed validation without allowing Parent Agent overrides."""

        critical_failures = {
            "artifact_hash_mismatch",
            "input_hash_mismatch",
            "unauthorized_execution",
            "path_escape",
            "unknown_wrapper",
            "invalid_contract",
            "unresolved_count_source",
            "scientific_label_error",
            "execution_gate_failure",
        }
        observed = {item.casefold() for item in validation.failures}
        if observed & critical_failures:
            return RouterDecision(
                route=RouterRoute.BLOCKED,
                reasons=sorted(observed & critical_failures),
                execution_allowed=False,
            )
        if validation.passed:
            return RouterDecision(
                route=RouterRoute.AGGREGATE_FAILED,
                reasons=["repair_not_required_for_passed_validation"],
            )
        if proposal is None:
            return RouterDecision(
                route=RouterRoute.AGGREGATE_FAILED,
                reasons=["validation_failure_not_repairable"],
            )
        if not budget_available:
            return RouterDecision(
                route=RouterRoute.AGGREGATE_FAILED,
                reasons=["repair_budget_exhausted"],
            )
        if repair_approved is None:
            return RouterDecision(
                route=RouterRoute.REPAIR_PENDING,
                reasons=[f"repair_proposed:{proposal.reason_code}"],
            )
        if not repair_approved:
            return RouterDecision(
                route=RouterRoute.AGGREGATE_FAILED,
                reasons=["repair_rejected"],
            )
        return RouterDecision(
            route=RouterRoute.QUALIFICATION_EXECUTION,
            reasons=[f"repair_approved:{proposal.reason_code}"],
            execution_allowed=True,
            qualification_only=True,
        )

    def _decide(
        self,
        *,
        mode: RouterMode,
        requirement: RequirementSpec,
        data_profile: Optional[DataProfile],
        tool_contract: Optional[ToolContract],
        planning_gate: Optional[PlanningGateResult],
        execution_gate: Optional[ExecutionGateResult],
        plan: Optional[WorkflowPlan],
    ) -> tuple[RouterRoute, list[str]]:
        if mode == RouterMode.PROFILE:
            if not requirement.input_path and data_profile is None:
                return RouterRoute.WAITING_USER_INPUT, ["profile_requires_input_path"]
            if not requirement.data_access_authorized:
                return RouterRoute.WAITING_DATA_AUTHORIZATION, ["data_access_not_authorized"]
            if data_profile is not None and data_profile.blocking_errors:
                return _profile_failure_route(data_profile)
            return RouterRoute.PROFILE_ONLY, ["profile_request_complete_or_ready"]

        if requirement.input_path and not requirement.data_access_authorized:
            return RouterRoute.WAITING_DATA_AUTHORIZATION, ["data_access_not_authorized"]
        if data_profile is not None and data_profile.blocking_errors:
            return _profile_failure_route(data_profile)
        if tool_contract is None:
            return RouterRoute.EVIDENCE_RECOVERY, ["planning_contract_missing"]
        if planning_gate is None:
            return RouterRoute.CONTRACT_REVIEW, ["planning_gate_result_missing"]
        if not planning_gate.allowed:
            return RouterRoute.CONTRACT_REVIEW, list(planning_gate.reasons)
        if plan is not None and plan.plan_status == "blocked":
            return RouterRoute.BLOCKED, list(plan.blocking_conditions)

        if mode == RouterMode.EXECUTION:
            if execution_gate is None or not execution_gate.allowed:
                reasons = (
                    list(execution_gate.reasons)
                    if execution_gate is not None
                    else ["execution_gate_result_missing"]
                )
                reasons.append("phase2_plan_remains_dry_run")
                return RouterRoute.PLAN_ONLY, reasons
            if not requirement.execution_authorized or requirement.user.approval_state != "approved":
                return RouterRoute.WAITING_EXECUTION_APPROVAL, ["plan_specific_approval_missing"]
            return RouterRoute.BLOCKED, ["phase2_execution_route_disabled"]

        if data_profile is None:
            return RouterRoute.PLAN_ONLY, ["generic_plan_without_data"]
        return RouterRoute.PLAN_ONLY, ["data_aware_dry_run_plan"]


def _profile_failure_route(profile: DataProfile) -> tuple[RouterRoute, list[str]]:
    errors = list(profile.blocking_errors)
    hard_failures = (
        "anndata_read_failed",
        "empty_anndata",
        "input_file_missing",
        "input_path_not_file",
        "invalid_file_extension",
    )
    if any(any(error.startswith(prefix) for prefix in hard_failures) for error in errors):
        return RouterRoute.BLOCKED, errors
    if "count_source_unresolved" in errors:
        return RouterRoute.WAITING_USER_INPUT, errors
    return RouterRoute.BLOCKED, errors
