"""Synthetic delivery fixtures only: no scientific gold, Seed writes or real human approval."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import anndata as ad
import numpy as np
import pandas as pd
import pytest

from execution.annotation_delivery import (
    AnnotationDeliverySession, digest, file_hash, index_hash, marker_state,
    validate_delivery,
)


def fixture(tmp_path, groupby="leiden", *, stale=False):
    data = ad.AnnData(np.array([[1., 0.], [2., 0.], [0., 2.], [0., 1.]]),
                      obs=pd.DataFrame({groupby: pd.Categorical(["a", "a", "b", "b"])},
                                       index=["c1", "c2", "c3", "c4"]),
                      var=pd.DataFrame(index=["SYNTH_G1", "SYNTH_G2"]))
    data.uns["rank_genes_groups"] = {
        "params": {"groupby": groupby, "use_raw": False, "method": "wilcoxon"},
        "names": np.rec.fromarrays([["SYNTH_G1", "SYNTH_G2"], ["SYNTH_G2", "SYNTH_G1"]], names=["a", "b"]),
    }
    input_path = tmp_path / "input.h5ad"
    data.write_h5ad(input_path)
    cluster = {"representation_record_id": "fixture:clusters", "representation_id": "cluster_labels",
               "schema_version": "1.0", "slot": f"obs/{groupby}", "value_state": "categorical",
               "cell_index_hash": index_hash(data.obs_names), "validated": True, "status": "current"}
    record = {"representation_record_id": "fixture:markers", "representation_id": "marker_result",
              "schema_version": "1.0", "value_state": "table", "slot": "uns/rank_genes_groups",
              "cell_index_hash": index_hash(data.obs_names), "gene_index_hash": index_hash(data.var_names),
              "validated": True, "status": "stale" if stale else "current",
              "parent_record_ids": [cluster["representation_record_id"]],
              "stale_reasons": ["fixture_stale"] if stale else []}
    ledger = {"source_hash": file_hash(input_path), "records": [cluster, record]}
    return data, input_path, ledger


def session(tmp_path, data, input_path, ledger):
    return AnnotationDeliverySession(data, ledger=ledger, input_path=input_path,
        output_dir=tmp_path / "output", application_python=sys.executable, plan_id="synthetic-plan")


def evidence(tmp_path, data, *, status="candidate"):
    # Not real biological evidence or a real review. Never exported to a real replay.
    quote = "SYNTHETIC FIXTURE ONLY: SYNTH_G1 supports Fixture-A; SYNTH_G2 supports Fixture-B."
    source_path = tmp_path / "synthetic-source.txt"
    source_path.write_text(quote)
    bindings = []
    for group, gene, label in [("a", "SYNTH_G1", "Fixture-A"), ("b", "SYNTH_G2", "Fixture-B")]:
        item = {"binding_id": f"fixture:{group}", "context_hash": digest(marker_state(data)),
                "candidate": {"cluster_id": group, "candidate_label": label, "marker_genes": [gene],
                              "evidence_source_ids": ["fixture:source"], "status": status},
                "scope": {"scope_id": "scope:synthetic-only", "scope_status": "explicit",
                          "biological_context_ids": ["synthetic-test-only"]},
                "sources": [{"source_id": "fixture:source", "source_revision_id": "fixture:source:1",
                             "span_id": "fixture:span", "path": source_path.name,
                             "sha256": file_hash(source_path), "start": 0, "end": len(quote), "quote": quote,
                             "span_sha256": hashlib.sha256(quote.encode()).hexdigest()}]}
        item["review"] = {"review_decision_id": f"review:synthetic-{group}", "risk_class": "R3",
            "reviewer_type": "qualified_human", "decision": "accepted",
            "reviewed_record_ids": [item["binding_id"]], "reviewed_artifact_hashes": [digest(item)],
            "rationale": "Simulated human acceptance for software fixture only; not scientific approval.",
            "policy_version": "synthetic-fixture", "decided_at": "2026-09-19T00:00:00Z"}
        bindings.append(item)
    path = tmp_path / "fixture-evidence.json"
    path.write_text(json.dumps({"bindings": bindings}))
    return path


@pytest.mark.parametrize("groupby", ["leiden", "louvain"])
@pytest.mark.parametrize("status", ["candidate", "unknown", "conflicting"])
def test_valid_delivery_reloads_without_automatic_confirmation(tmp_path, groupby, status):
    data, inp, ledger = fixture(tmp_path, groupby)
    before = file_hash(inp)
    run = session(tmp_path, data, inp, ledger)
    result = run.deliver(data, evidence(tmp_path, data, status=status))
    assert result["annotation_candidates_satisfied"]
    assert result["status"] == "WAITING_FOR_USER_CONFIRMATION"
    assert all(c["status"] == status for c in result["result"]["candidates"])
    assert result["result"]["candidate_set_hash"] == digest(result["result"]["candidates"])
    assert not result["confirmed_annotation_satisfied"]
    assert "cell_type" not in data.obs and "confirmed_annotation" not in data.uns
    assert run.finish(data)["required_annotation_target_satisfied"]
    assert validate_delivery(run.output_dir, application_python=sys.executable)["annotation_candidates_satisfied"]
    data.write_h5ad(tmp_path / "derived.h5ad")
    loaded = ad.read_h5ad(tmp_path / "derived.h5ad")
    assert json.loads(loaded.uns["annotation_candidates"]["result_json"]) == result["result"]
    assert file_hash(inp) == before


@pytest.mark.parametrize("bundle_kind", ["absent", "empty"])
def test_review_packet_and_empty_candidates_do_not_satisfy_terminal(tmp_path, bundle_kind):
    data, inp, ledger = fixture(tmp_path)
    run = session(tmp_path, data, inp, ledger)
    path = None
    if bundle_kind == "empty":
        path = tmp_path / "empty.json"
        path.write_text('{"bindings": []}')
    result = run.deliver(data, path)
    assert result["status"] == "BLOCKED"
    assert not result["annotation_candidates_satisfied"]
    assert "marker_evidence_candidates_missing" in result["missing_requirements"]
    assert not (run.output_dir / "annotation_candidates.json").exists()
    assert "annotation_candidates" not in data.uns
    packet = json.loads((run.output_dir / "marker_review_packet.json").read_text())
    assert packet["is_annotation_candidates"] is False and packet["candidate_labels"] is None
    with pytest.raises(RuntimeError, match="ANNOTATION_TERMINAL_INCOMPLETE"):
        run.finish(data)
    assert json.loads((run.output_dir / "terminal_validation.json").read_text())["full_scientific_task_completed"] is False


@pytest.mark.parametrize("fault", ["source_missing", "source_hash", "span", "review", "borrowed_source", "cluster", "gene", "context", "partial"])
def test_unbound_invalid_or_incomplete_evidence_is_not_terminal(tmp_path, fault):
    data, inp, ledger = fixture(tmp_path)
    run = session(tmp_path, data, inp, ledger)
    path = evidence(tmp_path, data)
    payload = json.loads(path.read_text())
    item = payload["bindings"][0]
    if fault == "source_missing": item["sources"][0]["path"] = "absent"
    if fault == "source_hash": item["sources"][0]["sha256"] = "0" * 64
    if fault == "span": item["sources"][0]["quote"] = "unrelated"
    if fault == "review": item["review"]["decision"] = "needs_revision"
    if fault == "borrowed_source": item["candidate"]["evidence_source_ids"] = ["another:source"]
    if fault == "cluster": item["candidate"]["cluster_id"] = "not-present"
    if fault == "gene": item["candidate"]["marker_genes"] = ["NOT_A_MARKER"]
    if fault == "context": item["context_hash"] = "0" * 64
    if fault == "partial": payload["bindings"].pop()
    path.write_text(json.dumps(payload))
    result = run.deliver(data, path)
    assert not result["annotation_candidates_satisfied"]
    assert not validate_delivery(run.output_dir, application_python=sys.executable)["annotation_candidates_satisfied"]


@pytest.mark.parametrize("fault", ["stale_record", "cell", "gene", "groupby", "assignment", "statistics", "lineage", "expression"])
def test_stale_identity_and_group_mismatch_rejected(tmp_path, fault):
    data, inp, ledger = fixture(tmp_path, stale=fault == "stale_record")
    if fault == "lineage": ledger["records"][1]["parent_record_ids"] = []
    run = session(tmp_path, data, inp, ledger)
    path = evidence(tmp_path, data)
    if fault == "cell": data.obs_names = ["different", "c2", "c3", "c4"]
    if fault == "gene": data.var_names = ["different", "SYNTH_G2"]
    if fault == "groupby": data.uns["rank_genes_groups"]["params"]["groupby"] = "louvain"
    if fault == "assignment": data.obs["leiden"] = pd.Categorical(["b", "a", "b", "b"])
    if fault == "statistics": data.uns["rank_genes_groups"]["params"]["method"] = "changed"
    if fault == "expression": data.X[0, 0] += 1
    assert not run.deliver(data, path)["annotation_candidates_satisfied"]


def test_raw_marker_producer_and_explicit_human_boundary(tmp_path):
    data, inp, ledger = fixture(tmp_path)
    ledger["records"] = []
    run = session(tmp_path, data, inp, ledger)
    run.record_computed_markers(data)
    result = run.deliver(data, evidence(tmp_path, data))
    assert result["annotation_candidates_satisfied"]
    with pytest.raises(RuntimeError, match="explicit_human_confirmation_required"):
        run.finish(data, require_confirmation=True)
    assert "cell_type" not in data.obs
    from core.annotation_method_models import AnnotationMethodFamilyResult
    from engine.annotation_method_service import AnnotationMethodFamilyService
    # Existing confirmation service is tested, not invoked by the delivery implementation.
    confirmation = AnnotationMethodFamilyService().confirm(
        result=AnnotationMethodFamilyResult.model_validate(result["result"]),
        confirmed_labels={"a": "Fixture-A", "b": "Fixture-B"}, reviewer_id="TEST-ONLY-SIMULATION")
    assert confirmation.candidate_set_hash == result["result"]["candidate_set_hash"]


def test_persisted_candidate_tampering_is_detected(tmp_path):
    data, inp, ledger = fixture(tmp_path)
    run = session(tmp_path, data, inp, ledger)
    run.deliver(data, evidence(tmp_path, data))
    path = run.output_dir / "annotation_candidates.json"
    payload = json.loads(path.read_text())
    payload["candidates"][0]["candidate_label"] = "altered"
    path.write_text(json.dumps(payload))
    assert not validate_delivery(run.output_dir, application_python=sys.executable)["annotation_candidates_satisfied"]


def test_no_reexecution_overwrites_delivery(tmp_path):
    data, inp, ledger = fixture(tmp_path)
    run = session(tmp_path, data, inp, ledger)
    run.deliver(data)
    before = file_hash(run.output_dir / "delivery.json")
    with pytest.raises(ValueError, match="already_written"):
        run.deliver(data)
    assert file_hash(run.output_dir / "delivery.json") == before


def compiled_fixture(tmp_path, *, with_evidence=False):
    from core.capability_pack_registry import CapabilityPackRegistry
    from execution.capability_notebook import GenericNotebookCompiler, NotebookRendererRegistry
    from execution.renderers.scanpy_core import ScanpyCoreNotebookRenderer
    from tests.test_scanpy_adaptive_notebook import _ledger, _record, _profile
    from engine.capability_planner import CapabilityPlanCompiler
    data, inp, real_ledger = fixture(tmp_path, "louvain")
    plan, _ = CapabilityPlanCompiler().compile(pack_id="scanpy_core", pack_version="1.0.0",
        ledger=_ledger(_record("cluster_labels", "categorical", gene_hash=False), _record("marker_result", "table")),
        target_representations=["annotation_candidates"], data_profile=_profile(), requirement_id="synthetic")
    registry = CapabilityPackRegistry()
    path = tmp_path / "compiled.ipynb"
    GenericNotebookCompiler(NotebookRendererRegistry([ScanpyCoreNotebookRenderer()])).compile(
        plan=plan, step_contracts=registry.load_step_contracts(registry.load("scanpy_core", "1.0.0")),
        output_path=path, title="Synthetic delivery", notebook_context={"input_path": str(inp), "representation_ledger": real_ledger,
            "annotation_evidence_bundle": str(evidence(tmp_path, data)) if with_evidence else None})
    return data, inp, real_ledger, path


def test_compiled_production_annotation_cells_execute_synthetic_data(tmp_path):
    data, inp, real_ledger, path = compiled_fixture(tmp_path)
    notebook = json.loads(path.read_text())
    codes = [c["source"] for c in notebook["cells"] if c["cell_type"] == "code"]
    for source in codes: compile(source, "synthetic-notebook", "exec")
    assert len(codes) == 3
    assert "ANNOTATION_SESSION" in codes[0] and "ANNOTATION_SESSION.finish" in codes[-1]
    run = session(tmp_path, data, inp, real_ledger)
    namespace = {"adata": data, "ANNOTATION_SESSION": run, "ANNOTATION_EVIDENCE_BUNDLE": None}
    exec(codes[1], namespace)
    with pytest.raises(RuntimeError, match="ANNOTATION_TERMINAL_INCOMPLETE"):
        exec(codes[2], namespace)
    assert json.loads((run.output_dir / "terminal_validation.json").read_text())["status"] == "BLOCKED"


@pytest.mark.parametrize("with_evidence", [False, True])
def test_actual_science_runtime_executes_generated_cells(tmp_path, with_evidence):
    runtime = os.environ.get("SCKG_TEST_NOTEBOOK_PYTHON")
    if not runtime:
        pytest.skip("set SCKG_TEST_NOTEBOOK_PYTHON to the existing Scanpy kernel interpreter")
    data, inp, ledger, path = compiled_fixture(tmp_path, with_evidence=with_evidence)
    before = file_hash(inp)
    # Execute unchanged generated code cells in the actual science interpreter.
    script = """
import json, sys
from jupyter_client import KernelManager
km = KernelManager()
km.kernel_spec.argv = [sys.executable, '-m', 'ipykernel_launcher', '-f', '{connection_file}']
km.start_kernel()
client = km.blocking_client()
client.start_channels()
try:
    client.wait_for_ready(timeout=30)
    def execute(source):
        msg_id = client.execute(source, stop_on_error=True)
        errors = []
        while True:
            msg = client.get_iopub_msg(timeout=60)
            if msg.get('parent_header', {}).get('msg_id') != msg_id:
                continue
            if msg['msg_type'] == 'error':
                errors.append(msg['content'])
            if msg['msg_type'] == 'status' and msg['content']['execution_state'] == 'idle':
                return errors
    codes = [c['source'] for c in json.load(open(sys.argv[1]))['cells'] if c['cell_type'] == 'code']
    for source in codes[:-1]:
        errors = execute(source)
        assert not errors, errors
    errors = execute(codes[-1])
    if sys.argv[2] == 'False':
        assert len(errors) == 1 and 'ANNOTATION_TERMINAL_INCOMPLETE' in errors[0]['evalue'], errors
    else:
        assert not errors, errors
    assert not execute("assert 'cell_type' not in adata.obs; assert 'confirmed_annotation' not in adata.uns")
    print('GENERATED_NOTEBOOK_SMOKE_COMPLETE')
finally:
    client.stop_channels()
    km.shutdown_kernel(now=True)
"""
    completed = subprocess.run([runtime, "-c", script, str(path), str(with_evidence)],
                               text=True, capture_output=True, cwd=tmp_path, timeout=90)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "GENERATED_NOTEBOOK_SMOKE_COMPLETE" in completed.stdout
    assert file_hash(inp) == before
    terminal_paths = list(tmp_path.glob(".sckg_notebook_artifacts/**/terminal_validation.json"))
    assert len(terminal_paths) == 1
    terminal = json.loads(terminal_paths[0].read_text())
    assert terminal["annotation_candidates_satisfied"] is with_evidence


@pytest.mark.parametrize("fault", ["missing", "empty", "wrong_hash"])
def test_uns_key_alone_cannot_satisfy_contract(tmp_path, fault):
    data, inp, ledger = fixture(tmp_path)
    run = session(tmp_path, data, inp, ledger)
    run.deliver(data, evidence(tmp_path, data))
    if fault == "missing": del data.uns["annotation_candidates"]
    if fault == "empty": data.uns["annotation_candidates"] = {}
    if fault == "wrong_hash": data.uns["annotation_candidates"]["state_hash"] = "0" * 64
    with pytest.raises(RuntimeError, match="annotation_slot_content_mismatch"):
        run.finish(data)


def test_application_service_failure_is_durable_technical_failure(tmp_path):
    data, inp, ledger = fixture(tmp_path)
    run = session(tmp_path, data, inp, ledger)
    run.application_python = str(tmp_path / "missing-interpreter")
    result = run.deliver(data)
    assert result["status"] == "FAILED"
    assert json.loads((run.output_dir / "delivery.json").read_text())["missing_requirements"] == ["annotation_metadata_service_failed"]


def test_human_review_only_plan_cannot_succeed_by_executing_placeholder(tmp_path):
    from execution.renderers.scanpy_core import ScanpyCoreNotebookRenderer
    cells = ScanpyCoreNotebookRenderer().finalize({"planned_operations": ["human_confirmation"], "plan_id": "fixture-human"})
    with pytest.raises(RuntimeError, match="explicit_human_confirmation_required"):
        exec(cells[0]["source"], {"OUTPUT_DIR": tmp_path})
    report = json.loads(next(tmp_path.glob("human-confirmation-*/terminal_validation.json")).read_text())
    assert report["status"] == "WAITING_FOR_USER_CONFIRMATION"
    assert report["review_decision"] is None
    assert report["confirmed_annotation_satisfied"] is False
