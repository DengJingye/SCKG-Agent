from __future__ import annotations

from enum import Enum

from pydantic import Field

from core.execution_models import EnvironmentRecord, StrictModel, ToolContract


class ExecutionPolicyMode(str, Enum):
    DISABLED = "disabled"
    MAINTAINER_ONLY = "maintainer_only"
    ALLOWLISTED_LOCAL_USERS = "allowlisted_local_users"


class ExecutionPair(StrictModel):
    tool_name: str
    tool_version: str
    wrapper_id: str
    environment_id: str


class ExecutionPolicyDecision(StrictModel):
    allowed: bool
    reasons: list[str] = Field(default_factory=list)


SUPPORTED_LOCAL_USER_PAIRS = [
    ExecutionPair(
        tool_name="Scrublet",
        tool_version="0.2.3",
        wrapper_id="scrublet_v0_2_3",
        environment_id="scRNAseq",
    ),
    ExecutionPair(
        tool_name="scDblFinder",
        tool_version="1.24.0",
        wrapper_id="scdblfinder_v1_24_0",
        environment_id="scDblFinder-R",
    ),
    ExecutionPair(
        tool_name="Harmony",
        tool_version="2.0.0",
        wrapper_id="harmony_v2_0_0",
        environment_id="sckg-batch-cpu",
    ),
    ExecutionPair(
        tool_name="Scanorama",
        tool_version="1.7.4",
        wrapper_id="scanorama_v1_7_4",
        environment_id="sckg-batch-cpu",
    ),
]


class ExecutionPolicy(StrictModel):
    mode: ExecutionPolicyMode = ExecutionPolicyMode.DISABLED
    local_user_pairs: list[ExecutionPair] = Field(
        default_factory=lambda: [item.model_copy() for item in SUPPORTED_LOCAL_USER_PAIRS]
    )

    def authorize(
        self,
        *,
        actor_role: str,
        access_origin: str,
        user_allowlisted: bool,
        contract: ToolContract,
        environment: EnvironmentRecord,
    ) -> ExecutionPolicyDecision:
        reasons: list[str] = []
        if self.mode == ExecutionPolicyMode.DISABLED:
            reasons.append("execution_policy_disabled")
        elif self.mode == ExecutionPolicyMode.MAINTAINER_ONLY:
            if actor_role != "maintainer":
                reasons.append("execution_policy_maintainer_only")
        elif self.mode == ExecutionPolicyMode.ALLOWLISTED_LOCAL_USERS:
            if actor_role != "user":
                reasons.append("local_user_policy_requires_user_actor")
            if access_origin != "local":
                reasons.append("remote_or_anonymous_execution_forbidden")
            if not user_allowlisted:
                reasons.append("local_user_not_allowlisted")
            expected = ExecutionPair(
                tool_name=contract.tool_name,
                tool_version=contract.tool_version,
                wrapper_id=contract.wrapper_id,
                environment_id=environment.environment_id,
            )
            if expected not in self.local_user_pairs:
                reasons.append("tool_environment_pair_not_allowlisted")
            if not contract.enabled_for_execution:
                reasons.append("contract_execution_disabled")
            if not environment.enabled_for_execution:
                reasons.append("environment_execution_disabled")
        return ExecutionPolicyDecision(allowed=not reasons, reasons=sorted(set(reasons)))


DEFAULT_EXECUTION_POLICY = ExecutionPolicy()
