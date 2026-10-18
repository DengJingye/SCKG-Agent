"""Create-only fictional method demo; no provider or scientific execution."""
from copy import deepcopy
from importlib.util import module_from_spec, spec_from_file_location
import json
from pathlib import Path

import pytest

from sckg_workbench.knowledge import KnowledgeService
from sckg_workbench.storage import Ledger, Workspace, content_hash
from sckg_workbench.workflow_methods import configured_method_service
from tests.test_workbench_workflow_demo import tree_bytes


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "bootstrap_method_demo.py"
SPEC = spec_from_file_location("workbench_method_demo_bootstrap", SCRIPT)
demo = module_from_spec(SPEC)
SPEC.loader.exec_module(demo)


@pytest.fixture(autouse=True)
def forbid_provider_and_network(monkeypatch):
    def denied(*args, **kwargs):
        pytest.fail("Synthetic method demo attempted a model or network request")
    monkeypatch.setattr("sckg_workbench.model_service.ModelService.invoke", denied)
    monkeypatch.setattr("sckg_workbench.model_service.ModelService.embed", denied)
    monkeypatch.setattr("sckg_workbench.sources.fetch_public_url", denied)
    monkeypatch.setattr("socket.create_connection", denied)


def test_fresh_method_demo_keeps_original_catalog_and_candidates_out_of_ordinary_search(tmp_path, monkeypatch):
    original_bootstrap = demo.bootstrap_demo
    originals = {}

    def capture_original(path):
        receipt = original_bootstrap(path)
        workspace = Path(receipt["workspace"])
        originals.update({name: (workspace / name).read_bytes() for name in
                          ("workflow_demo_manifest.json", "workflow_demo_examples.json")})
        return receipt

    monkeypatch.setattr(demo, "bootstrap_demo", capture_original)
    target = tmp_path / "method-demo"
    receipt = demo.bootstrap_method_demo(target)
    assert receipt["authority"] == demo.DEMO_AUTHORITY and receipt["status"] == "created"
    assert receipt["source_count"] == receipt["candidate_count"] == 4
    assert receipt["model_calls"] == receipt["scientific_fits"] == receipt["human_reviews"] == receipt["releases"] == 0
    assert receipt["recommendation_eligible"] is False and receipt["protocol"] is None
    assert "SYNTHETIC" in receipt["ui_command"] and "SCKG_WORKBENCH_HOME=" in receipt["ui_command"]
    assert {name: (target / name).read_bytes() for name in originals} == originals
    ledger = Ledger(Workspace(target))
    assert ledger.get_state("workflow_input_catalog") == receipt["legacy_input_catalog"]
    old = ledger.get_record("workflow_input_catalog", receipt["legacy_input_catalog"]["record_id"])
    assert [r["route_id"] for r in old["catalog"]["routes"]] == ["demo_counts", "demo_auxiliary", "demo_design"]
    service = configured_method_service(ledger)
    assert service.catalog["protocol"] is None and len(service.catalog["fields"]) == 6
    assert [r["route_id"] for r in service.catalog["routes"]] == [demo.FEATURE_ROUTE, demo.ALTERNATIVE_ROUTE]
    assert all(f["scope"] == "method" for f in service.catalog["fields"])
    assert [r["route_id"] for r in service.inputs.catalog["routes"]] == [demo.FEATURE_ROUTE, demo.ALTERNATIVE_ROUTE]
    assert service.inputs.catalog["routes"][1] == old["catalog"]["routes"][0]
    source_input = service.inputs.catalog["routes"][0]["requirements"][0]["source_bindings"][0]
    candidate = ledger.get_record("candidate", receipt["fictional_candidate_id"])
    assert candidate["claim"]["typed_attributes"][source_input["attribute_index"]]["name"] == "workflow.input"
    assert candidate["origin"]["not_model_output"] is True and candidate["status"] == "candidate"
    assert candidate["claim"]["model_self_score"] is None
    knowledge = KnowledgeService(ledger)
    assert knowledge.search("Fictional Feature Trainer").units == []
    assert knowledge.resolve([c["id"] for c in ledger.list_records("candidate")]).units == []
    for kind in ("model_connection", "model_profile", "model_request", "model_call", "model_output",
                 "external_model_profile", "external_model_run", "assessment", "review", "release", "task_submission",
                 "workflow_local_protocol"):
        assert ledger.list_records(kind) == []
    assert json.loads((target / "method_demo_manifest.json").read_text()) == receipt


@pytest.mark.parametrize("selection,filtered,decision,status", [
    (True, 300, "blocked", "reported_unmet"),
    (True, 301, "conditional_plan", "reported_met"),
    (False, None, "conditional_plan", "not_applicable"),
])
def test_feature_boundary_blocks_only_fictional_trainer_and_retains_lightweight_alternative(
        tmp_path, selection, filtered, decision, status):
    target = tmp_path / "method-demo"
    receipt = demo.bootstrap_method_demo(target)
    example = json.loads((target / "method_demo_example_report.json").read_text())
    assert example["authority"] == demo.DEMO_AUTHORITY and example["actual_user_submission"] is False
    assert example["measurements_established"] is False
    assert receipt["synthetic_example_decisions"] == {demo.FEATURE_ROUTE: "blocked", demo.ALTERNATIVE_ROUTE: "conditional_plan"}
    profile = deepcopy(example["profile"])
    profile["reported_config"]["feature_selection"] = selection
    if filtered is None:
        profile["reported_config"].pop("postfilter_genes")
        profile["reported_config"].pop("top_genes")
    else:
        profile["reported_config"]["postfilter_genes"] = filtered
    ledger = Ledger(Workspace(target))
    before = tree_bytes(target)
    result = configured_method_service(ledger).evaluate([demo.FEATURE_ROUTE, demo.ALTERNATIVE_ROUTE], profile)
    train, alternative = result["route_results"]
    assert train["method_decision"] == decision and train["configuration_checks"][0]["status"] == status
    assert train["configuration_checks"][1]["status"] == "option_not_applicable"
    assert train["configuration_checks"][0]["source_bindings"][0]["attribute_kind"] == "workflow.input"
    assert train["configuration_checks"][1]["source_bindings"][0]["attribute_kind"] == "workflow.action"
    feature_binding = train["configuration_checks"][0]["source_bindings"][0]
    balance_binding = train["configuration_checks"][1]["source_bindings"][0]
    assert feature_binding["attribute_index"] == 1 and "postfilter_genes" in feature_binding["attribute"]["value"]
    assert balance_binding["attribute_index"] == 2 and "both use_sgd=True and mini_batch=True" in balance_binding["attribute"]["value"]
    assert alternative["method_decision"] == "conditional_plan" and alternative["configuration_checks"] == []
    assert result["recommendation_eligible"] is False and result["provider_calls"] == result["scientific_fits"] == 0
    assert result["result_hash"] == content_hash({k: v for k, v in result.items() if k != "result_hash"})
    assert all(route["local_execution"] == {"state": "unbound", "execution_authorized": False,
                                           "execution_attempted": False} for route in result["route_results"])
    assert all(route["local_protocol"]["state"] == "not_requested" for route in result["route_results"])
    assert tree_bytes(target) == before


@pytest.mark.parametrize("production", [False, True])
def test_existing_nonempty_or_production_workspace_is_preserved(tmp_path, monkeypatch, production):
    target = tmp_path / "existing"
    target.mkdir()
    (target / "important-original.txt").write_bytes(b"DO NOT MODIFY")
    if production:
        monkeypatch.setenv("SCKG_WORKBENCH_HOME", str(target))
    before = tree_bytes(target)
    with pytest.raises(ValueError, match="production/default" if production else "completely empty"):
        demo.bootstrap_method_demo(target)
    assert tree_bytes(target) == before
    assert not (target.parent / ("." + target.name + ".sckg-init.lock")).exists()
