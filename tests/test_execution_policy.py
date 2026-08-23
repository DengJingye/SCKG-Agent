from datetime import datetime, timedelta, timezone

from core.tool_contract_registry import ToolContractRegistry
from execution.environment_registry import EnvironmentRegistry
from execution.execution_policy import (
    ExecutionPair,
    ExecutionPolicy,
    ExecutionPolicyMode,
)
from execution.local_user_service import LocalUserAllowlist


def test_execution_policy_defaults_disabled_and_allows_only_registered_pairs(tmp_path):
    environments = EnvironmentRegistry()
    contract = ToolContractRegistry(environment_registry=environments).load(
        "Scrublet", "0.2.3"
    ).model_copy(update={"enabled_for_execution": True})
    environment = environments.get("scRNAseq").model_copy(
        update={"enabled_for_execution": True}
    )

    disabled = ExecutionPolicy().authorize(
        actor_role="user",
        access_origin="local",
        user_allowlisted=True,
        contract=contract,
        environment=environment,
    )
    assert disabled.allowed is False
    assert "execution_policy_disabled" in disabled.reasons

    policy = ExecutionPolicy(mode=ExecutionPolicyMode.ALLOWLISTED_LOCAL_USERS)
    allowed = policy.authorize(
        actor_role="user",
        access_origin="local",
        user_allowlisted=True,
        contract=contract,
        environment=environment,
    )
    assert allowed.allowed is True
    remote = policy.authorize(
        actor_role="user",
        access_origin="remote",
        user_allowlisted=True,
        contract=contract,
        environment=environment,
    )
    assert remote.allowed is False
    unknown = contract.model_copy(
        update={
            "tool_name": "UnknownTool",
            "tool_version": "1.0",
            "wrapper_id": "unknown_wrapper",
        }
    )
    assert policy.authorize(
        actor_role="user",
        access_origin="local",
        user_allowlisted=True,
        contract=unknown,
        environment=environment,
    ).allowed is False


def test_local_user_allowlist_binds_pair_artifact_scope_budget_and_expiry(tmp_path):
    now = datetime(2026, 7, 12, tzinfo=timezone.utc)
    pair = ExecutionPair(
        tool_name="Scrublet",
        tool_version="0.2.3",
        wrapper_id="scrublet_v0_2_3",
        environment_id="scRNAseq",
    )
    allowlist = LocalUserAllowlist(root=tmp_path / "allowlist")
    allowlist.allow_user(
        user_id="user-a",
        allowed_pairs=[pair],
        allowed_artifact_ids=["data-a"],
        allowed_data_scopes=["synthetic_fixture"],
        max_runs=2,
        ttl=timedelta(hours=1),
        now=now,
    )
    assert allowlist.validate(
        user_id="user-a",
        pair=pair,
        artifact_id="data-a",
        data_scope="synthetic_fixture",
        requested_runs=2,
        now=now,
    ).allowed
    allowlist.consume_run(
        user_id="user-a",
        pair=pair,
        artifact_id="data-a",
        data_scope="synthetic_fixture",
        now=now,
    )
    allowlist.consume_run(
        user_id="user-a",
        pair=pair,
        artifact_id="data-a",
        data_scope="synthetic_fixture",
        now=now,
    )
    assert "run_budget" in ";".join(
        allowlist.validate(
            user_id="user-a",
            pair=pair,
            artifact_id="data-a",
            data_scope="synthetic_fixture",
            now=now,
        ).reasons
    )
    assert allowlist.validate(
        user_id="user-b",
        pair=pair,
        artifact_id="data-a",
        data_scope="synthetic_fixture",
        now=now,
    ).allowed is False
    assert allowlist.validate(
        user_id="user-a",
        pair=pair,
        artifact_id="data-a",
        data_scope="synthetic_fixture",
        now=now + timedelta(hours=2),
    ).allowed is False
