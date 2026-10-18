"""Fresh-workspace, offline synthetic demo and existing-data protection checks."""
from importlib.util import module_from_spec, spec_from_file_location
import json
from pathlib import Path

import pytest

from sckg_workbench.knowledge import KnowledgeService
from sckg_workbench.storage import Ledger, Workspace, content_hash
from sckg_workbench.workflow_inputs import WorkflowInputCatalog, WorkflowInputService


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "bootstrap_workflow_demo.py"
SPEC = spec_from_file_location("workbench_workflow_demo_bootstrap", SCRIPT)
demo = module_from_spec(SPEC)
SPEC.loader.exec_module(demo)


def tree_bytes(root):
    return {str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()}


def test_bootstrap_creates_actual_candidate_catalog_and_three_offline_states(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Offline demo attempted a model or network request")
    monkeypatch.setattr("sckg_workbench.model_service.ModelService.invoke", forbidden)
    monkeypatch.setattr("sckg_workbench.model_service.ModelService.embed", forbidden)
    monkeypatch.setattr("sckg_workbench.sources.fetch_public_url", forbidden)
    monkeypatch.setattr("socket.create_connection", forbidden)
    target = tmp_path / "demo"
    receipt = demo.bootstrap_demo(target)
    assert receipt["status"] == "created" and receipt["authority"] == demo.DEMO_AUTHORITY
    assert receipt["source_count"] == receipt["candidate_count"] == 3
    assert receipt["model_calls"] == receipt["scientific_fits"] == receipt["human_reviews"] == receipt["releases"] == 0
    assert receipt["recommendation_eligible"] is False
    ledger = Ledger(Workspace(target))
    for kind in ("model_connection", "model_profile", "model_request", "model_call", "model_output",
                 "external_model_profile", "external_model_run", "assessment", "review", "release", "task_submission"):
        assert ledger.list_records(kind) == []
    candidates = ledger.list_records("candidate")
    assert all(candidate["status"] == "candidate" for candidate in candidates)
    assert all(candidate["origin"]["kind"] == "synthetic_demo_fixture"
               and candidate["origin"]["not_model_output"] is True for candidate in candidates)
    configured = ledger.get_state("workflow_input_catalog")
    assert configured == {"record_id": receipt["catalog_record_id"], "catalog_hash": receipt["catalog_hash"]}
    record = ledger.get_record("workflow_input_catalog", configured["record_id"])
    catalog = WorkflowInputCatalog.model_validate(record["catalog"]).model_dump(mode="json")
    assert content_hash(catalog) == configured["catalog_hash"]
    examples = json.loads((target / "workflow_demo_examples.json").read_text())
    assert examples["actual_user_submission"] is False and examples["authority"] == demo.DEMO_AUTHORITY
    assert "replicate_design" not in examples["profile"]["reported_inputs"]
    service = WorkflowInputService(ledger, catalog, expected_catalog_hash=configured["catalog_hash"])
    review = service.evaluate([route["route_id"] for route in catalog["routes"]], examples["profile"])
    assert [(route["assessment"]["decision_check"]["preconditions_status"],
             route["assessment"]["decision_check"]["action_status"]) for route in review["route_results"]] == [
        ("reported_met", "conditional_plan"), ("reported_unmet", "blocked"), ("unknown", "needs_evidence")]
    assert all(route["local_execution"] == {"state": "unbound", "execution_authorized": False,
                                           "execution_attempted": False} for route in review["route_results"])
    assert KnowledgeService(ledger).resolve([candidate["id"] for candidate in candidates]).units == []
    from sckg_workbench.workflow_chat import catalog_service
    enabled = catalog_service(ledger, {"catalog_record_id": receipt["catalog_record_id"],
                                      "catalog_hash": receipt["catalog_hash"]})
    assert enabled.catalog == catalog
    assert json.loads((target / "workflow_demo_manifest.json").read_text()) == receipt


def test_bootstrap_accepts_existing_completely_empty_folder(tmp_path):
    target = tmp_path / "empty"
    target.mkdir()
    assert demo.bootstrap_demo(target)["status"] == "created"


def test_nonempty_existing_directory_is_unchanged_and_never_initialized(tmp_path):
    target = tmp_path / "important-data"
    target.mkdir()
    (target / "raw-data.txt").write_bytes(b"IMPORTANT ORIGINAL DO NOT MODIFY")
    before = tree_bytes(target)
    with pytest.raises(ValueError, match="completely empty"):
        demo.bootstrap_demo(target)
    assert tree_bytes(target) == before
    assert not (target.parent / ("." + target.name + ".sckg-init.lock")).exists()


def test_repeated_bootstrap_refuses_existing_demo_without_mutation(tmp_path):
    target = tmp_path / "demo"
    demo.bootstrap_demo(target)
    before = tree_bytes(target)
    lock = target.parent / ("." + target.name + ".sckg-init.lock")
    lock_mtime = lock.stat().st_mtime_ns
    with pytest.raises(ValueError, match="completely empty"):
        demo.bootstrap_demo(target)
    assert tree_bytes(target) == before and lock.stat().st_mtime_ns == lock_mtime


@pytest.mark.parametrize("kind", ["target", "parent"])
def test_symlink_workspace_or_parent_is_refused_without_touching_destination(tmp_path, kind):
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    target = link if kind == "target" else link / "demo"
    with pytest.raises(ValueError, match="symlink"):
        demo.bootstrap_demo(target)
    assert list(real.iterdir()) == []


@pytest.mark.parametrize("nested", [False, True])
def test_configured_production_workspace_and_children_are_refused(tmp_path, monkeypatch, nested):
    protected = tmp_path / "configured-production"
    monkeypatch.setenv("SCKG_WORKBENCH_HOME", str(protected))
    target = protected / "demo" if nested else protected
    with pytest.raises(ValueError, match="production/default"):
        demo.bootstrap_demo(target)
    assert not protected.exists()


def test_cli_requires_explicit_workspace_without_a_default(capsys):
    with pytest.raises(SystemExit) as error:
        demo.main([])
    assert error.value.code == 2 and "--workspace" in capsys.readouterr().err


def test_cli_prints_parseable_receipt_and_returns_failure_for_reuse(tmp_path, capsys):
    target = tmp_path / "cli-demo"
    assert demo.main(["--workspace", str(target)]) == 0
    receipt = json.loads(capsys.readouterr().out)
    assert receipt["workspace"] == str(target.resolve()) and receipt["model_calls"] == 0
    assert "SCKG_WORKBENCH_HOME=" in receipt["ui_command"]
    assert demo.main(["--workspace", str(target)]) == 2
    captured = capsys.readouterr()
    assert captured.out == "" and "existing contents are untouched" in captured.err
