from core.deterministic_router import DeterministicRouter, RouterRoute
from core.execution_models import PlanningGateResult
from execution.local_controlled_executor import LocalControlledExecutor
from execution.validators.doublet import DoubletValidator
from tests.qualification_helpers import build_qualification_case


def test_qualification_router_only_allows_maintainer_synthetic_fixture(tmp_path):
    case = build_qualification_case(tmp_path)
    assert case["decision"].route == RouterRoute.QUALIFICATION_EXECUTION
    assert case["decision"].execution_allowed is True
    assert case["decision"].qualification_only is True

    scenarios = [
        (
            case["request"].model_copy(
                update={"actor": case["request"].actor.model_copy(update={"role": "user"})}
            ),
            case["artifact"],
            case["planning_gate"],
            case["environment_registry"].get("scRNAseq"),
            "qualification_requires_maintainer",
        ),
        (
            case["request"],
            case["artifact"].model_copy(update={"allowlisted": False}),
            case["planning_gate"],
            case["environment_registry"].get("scRNAseq"),
            "artifact_not_allowlisted",
        ),
        (
            case["request"],
            case["artifact"].model_copy(update={"synthetic": False}),
            case["planning_gate"],
            case["environment_registry"].get("scRNAseq"),
            "synthetic_qualification_requires_synthetic_fixture",
        ),
        (
            case["request"],
            case["artifact"],
            PlanningGateResult(
                allowed=False,
                contract_id=case["contract"].contract_id,
                reasons=["precondition_failed"],
            ),
            case["environment_registry"].get("scRNAseq"),
            "planning_gate:precondition_failed",
        ),
        (
            case["request"],
            case["artifact"],
            case["planning_gate"],
            None,
            "unknown_environment",
        ),
        (
            case["request"].model_copy(update={"timeout_seconds": 121}),
            case["artifact"],
            case["planning_gate"],
            case["environment_registry"].get("scRNAseq"),
            "qualification_timeout_budget_exceeded",
        ),
    ]
    router = DeterministicRouter()
    for request, artifact, gate, environment, reason in scenarios:
        decision = router.route_qualification(
            request=request,
            artifact=artifact,
            tool_contract=case["contract"],
            environment=environment,
            planning_gate=gate,
            max_timeout_seconds=120,
        )
        assert decision.route == RouterRoute.BLOCKED
        assert decision.execution_allowed is False
        assert reason in decision.reasons


def test_parent_cannot_override_qualification_router(tmp_path):
    case = build_qualification_case(tmp_path)
    blocked_request = case["request"].model_copy(
        update={"actor": case["request"].actor.model_copy(update={"role": "user"})}
    )
    decision = DeterministicRouter().route_qualification(
        request=blocked_request,
        artifact=case["artifact"],
        tool_contract=case["contract"],
        environment=case["environment_registry"].get("scRNAseq"),
        planning_gate=case["planning_gate"],
        max_timeout_seconds=120,
        parent_route_override=RouterRoute.QUALIFICATION_EXECUTION,
    )
    assert decision.route == RouterRoute.BLOCKED
    assert decision.parent_override_ignored is True
    assert decision.execution_allowed is False


def test_scientific_pilot_route_only_allows_registered_public_datasets(tmp_path):
    case = build_qualification_case(tmp_path)
    request = case["request"].model_copy(
        update={
            "qualification": case["request"].qualification.model_copy(
                update={"purpose": "scientific_pilot"}
            )
        }
    )
    artifact = case["artifact"].model_copy(
        update={
            "synthetic": False,
            "public_dataset": True,
            "user_data": False,
            "accession": "GSE108313",
        }
    )
    router = DeterministicRouter()
    allowed = router.route_qualification(
        request=request,
        artifact=artifact,
        tool_contract=case["contract"],
        environment=case["environment_registry"].get("scRNAseq"),
        planning_gate=case["planning_gate"],
        max_timeout_seconds=120,
    )
    blocked = router.route_qualification(
        request=request,
        artifact=artifact.model_copy(update={"accession": "GSE999999"}),
        tool_contract=case["contract"],
        environment=case["environment_registry"].get("scRNAseq"),
        planning_gate=case["planning_gate"],
        max_timeout_seconds=120,
    )
    assert allowed.execution_allowed is True
    pbmc3k = router.route_qualification(
        request=request,
        artifact=artifact.model_copy(update={"accession": "Scanpy-PBMC3K"}),
        tool_contract=case["contract"],
        environment=case["environment_registry"].get("scRNAseq"),
        planning_gate=case["planning_gate"],
        max_timeout_seconds=120,
    )
    assert pbmc3k.execution_allowed is True
    assert "scientific_pilot_dataset_not_allowlisted" in blocked.reasons


def test_scrublet_qualification_executes_and_validates_synthetic_probe(tmp_path):
    case = build_qualification_case(tmp_path, run_id="scrublet-integration")
    run = LocalControlledExecutor(
        run_root=tmp_path / "runs",
        approved_input_root=tmp_path / "probes",
        environment_registry=case["environment_registry"],
    ).execute(
        request=case["request"],
        artifact=case["artifact"],
        contract=case["contract"],
        router_decision=case["decision"],
    )
    validation = DoubletValidator().validate(
        run, expected_cells=case["artifact"].expected_cells
    )

    assert run.status == "succeeded"
    assert run.exit_code == 0
    assert set(run.artifact_paths) == {
        "doublet_results.tsv",
        "parameters.json",
        "result_metadata.json",
    }
    assert validation.passed is True
    assert validation.metric_authority == "synthetic_engineering_metric"
