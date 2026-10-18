"""Synthetic regression cases for source-bound prediction artifact definitions.

No real scientific artifact, provider receipt, profile, review or release is
manufactured. Source/metadata labels below are explicit engineering fixtures.
"""
from copy import deepcopy
import hashlib
import json
from types import SimpleNamespace

import pytest

from sckg_workbench.knowledge import KnowledgeService
from sckg_workbench.sources import SourceService
from sckg_workbench.storage import Ledger, Workspace, content_hash
from sckg_workbench.prediction_semantics import (ArtifactBinding, ClauseBinding, PredictionSemanticsError,
    PredictionSemanticsService, configured_prediction_semantics_service, JSON_LIMIT, HEADER_LIMIT)
from sckg_workbench.workflow_inputs import WorkflowInputService


def sha(data):
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def preview(tmp_path, monkeypatch):
    def denied(*args, **kwargs):
        pytest.fail("Prediction semantics must not call a model or network")
    for name in ("invoke", "embed"):
        monkeypatch.setattr("sckg_workbench.model_service.ModelService." + name, denied)
    monkeypatch.setattr("sckg_workbench.sources.fetch_public_url", denied)
    monkeypatch.setattr("socket.create_connection", denied)
    ledger = Ledger(Workspace(tmp_path / "synthetic-preview"))
    knowledge, sources = KnowledgeService(ledger), SourceService(ledger)
    source = sources.register_bytes("synthetic_models.py.txt",
        b"SYNTHETIC ENGINEERING FIXTURE ONLY: sample score definition and source-traced arithmetic.",
        metadata={"source_kind": "author_package_source", "package": "celltypist", "version": "1.7.1",
                  "original_filename": "models.py", "synthetic_fixture": True})
    ir = sources.parse(source["id"]);block = ir["blocks"][0]
    def unit(kind, text):
        claim = {"proposition": text, "subject": "Synthetic test only", "predicate": "fictionally_defines",
            "object": "fixture score", "polarity": "positive", "assertion_kind": kind,
            "conditions": ["Synthetic fixture, never scientific evidence"], "unknowns": ["No scientific validation"],
            "model_self_score": None, "anchors": [{"ir_id": ir["id"], "block_id": block["id"],
                "start": 0, "end": len(block["exact_text"]), "quote": block["exact_text"]}],
            "typed_attributes": [{"name": "workflow.output", "value": text,
                "evidence_anchor_indices": [0], "qualifiers": ["Synthetic only"]}]}
        with ledger.transaction() as conn:
            return knowledge._store_candidate(claim, {"kind": "synthetic_fixture", "not_model_output": True}, conn=conn)
    direct = unit("source_assertion", "Synthetic direct definition")
    synthesis = unit("synthesis", "Synthetic explicitly marked arithmetic synthesis")
    def clause(candidate, role):
        return {"clause_id": role, "label": "SYNTHETIC " + role, "role": role, "binding": {
            "candidate_id": candidate["id"], "candidate_hash": candidate["content_hash"],
            "attribute_index": 0, "attribute_hash": content_hash(candidate["claim"]["typed_attributes"][0]),
            "expected_assertion_kind": candidate["claim"]["assertion_kind"]}}
    catalog = {"schema_version": "development-prediction-semantics-catalog-v1",
        "authority": "developer_source_interpretation_not_human_review", "package": "celltypist", "version": "1.7.1",
        "sources": [{"source_id": source["id"], "blob_sha256": source["blob_sha256"],
            "metadata_hash": content_hash(source["metadata"]), "package": "celltypist", "version": "1.7.1",
            "original_filename": "models.py"}],
        "clauses": [clause(direct, "matrix_definition"), clause(synthesis, "row_sum")]}
    def put_catalog(value):
        digest = content_hash(value);rid = "synthetic-catalog-" + digest
        ledger.put_record("prediction_semantics_catalog", rid, {"id": rid, "catalog": value, "catalog_hash": digest})
        ledger.set_state("prediction_semantics_catalog", {"record_id": rid, "catalog_hash": digest})
    put_catalog(catalog)
    root = ledger.workspace.root
    def bind(*, version="1.7.1", legacy=False, voting=False, label="predicted_labels", calibration=False,
             columns=None, metadata_updates=None, role=None):
        header = ((",".join(columns) + "\n").encode() if columns is not None else
                  b"cell_id,predicted_label,confidence\n" if legacy else b"cell_id,synthetic_type_A,synthetic_type_B\n")
        # Fixture body is present solely to exercise full-content identity.
        score = header + b"SYNTHETIC_ROW,0.2,0.8\n"
        metadata = {"method": "celltypist", "synthetic_fixture": True,
            "parameters": {} if legacy else {"mode": "best match", "majority_voting": voting},
            "confidence_is_calibrated": calibration}
        if version is not None:metadata["tool_version"] = version
        if label is not None:metadata["selected_label_column"] = label
        metadata.update(metadata_updates or {})
        (root / "score.csv").write_bytes(score)
        raw = (json.dumps(metadata,sort_keys=True) + "\n").encode();(root / "metadata.json").write_bytes(raw)
        hashes = {"metadata.json": sha(raw), "score.csv": sha(score)}
        manifest = {"run_id": "SYNTHETIC_RUN", "artifact_hashes": hashes, "synthetic_fixture": True}
        if legacy:manifest = {"runs": [{"slot": "SYNTHETIC_RUN", "prediction": "score.csv"}], "output_hashes": hashes, "synthetic_fixture": True}
        raw_manifest = json.dumps(manifest).encode();(root / "manifest.json").write_bytes(raw_manifest)
        ref = lambda path, digest: {"relative_path": path, "sha256": digest, "manifest_key": path}
        binding = {"schema_version": "developer-prediction-artifact-binding-v1",
            "authority": "developer_snapshot_not_execution_acceptance", "namespace": ledger.workspace.namespace,
            "run_id": "SYNTHETIC_RUN", "run_identity_kind": "legacy_manifest_slot" if legacy else "execution_run_record",
            "manifest": ref("manifest.json", sha(raw_manifest)), "metadata": ref("metadata.json", sha(raw)),
            "parameters": None, "score": ref("score.csv", sha(score)), "header_sha256": sha(header), "delimiter": ",",
            "score_role": role or ("maximum_probability_summary" if legacy else "class_probability_matrix")}
        rid = "prediction-artifact-" + content_hash(binding)
        ledger.put_record("prediction_artifact_binding", rid,
                          {"id": rid, "binding": binding, "binding_hash": content_hash(binding)})
        return rid, binding
    bid, binding = bind()
    return SimpleNamespace(ledger=ledger, knowledge=knowledge, source=source, direct=direct, synthesis=synthesis,
                           catalog=catalog, put_catalog=put_catalog, bind=bind, binding_id=bid, binding=binding)


def test_source_assertion_and_explicit_synthesis_explain_only_exact_bound_definition(preview):
    result = configured_prediction_semantics_service(preview.ledger).explain(preview.binding_id)
    assert result["status"] == "identity_valid_semantics_supported"
    assert [c["binding"]["expected_assertion_kind"] for c in result["clauses"]] == ["source_assertion", "synthesis"]
    assert all(c["applies_to_this_artifact"] for c in result["clauses"])
    assert result["identity_io"]["per_cell_rows_parsed"] == 0 and result["identity_io"]["score_hash_passes"] == 2
    assert result["calibration_status"] == "not_established" and not result["scientific_truth_verified"]
    assert not result["execution_authorized"] and not result["recommendation_eligible"]
    assert result["provider_calls"] == result["fits"] == 0
    for kind in ("model_call", "model_profile", "model_output", "review", "release", "assessment", "task_submission"):
        assert preview.ledger.list_records(kind) == []
    assert not preview.knowledge.search("Synthetic").units


def test_legacy_scalar_metadata_preserves_missing_version_mode_and_observed_label(preview):
    bid, _ = preview.bind(version=None, legacy=True, label=None)
    result = configured_prediction_semantics_service(preview.ledger).explain(bid)
    assert result["status"] == "identity_valid_semantics_unresolved"
    assert {"tool_version", "prediction_mode", "selected_label_column"}.issubset(result["unknowns"])
    assert result["artifact_facts"]["header_columns"] == ["cell_id", "predicted_label", "confidence"]
    assert not any(c["applies_to_this_artifact"] for c in result["clauses"])


def test_read_only_service_does_not_initialize_the_knowledge_fts_projection(preview, monkeypatch):
    def forbidden_initializer(*args, **kwargs):
        pytest.fail("A read-only explanation must not initialize KnowledgeService or FTS")
    monkeypatch.setattr(KnowledgeService, "__init__", forbidden_initializer)
    result = configured_prediction_semantics_service(preview.ledger).explain(preview.binding_id)
    assert result["identity_io"]["per_cell_rows_parsed"] == 0


def test_class_names_are_not_heuristics_for_scalar_schema(preview):
    for name in ("confidence", "predicted_label"):
        bid, _ = preview.bind(columns=["cell_id", name, "synthetic_other_class"])
        result = configured_prediction_semantics_service(preview.ledger).explain(bid)
        assert result["status"] == "identity_valid_semantics_supported"
        assert result["artifact_facts"]["header_columns"][1] == name
    bid, _ = preview.bind(columns=["cell_id", "predicted_label", "confidence"], role="class_probability_matrix")
    with pytest.raises(PredictionSemanticsError):
        configured_prediction_semantics_service(preview.ledger).explain(bid)


@pytest.mark.parametrize("insert_conf", [False, True])
def test_voting_definition_match_does_not_prove_to_adata_call_or_ignore_disabled_insertion(preview, insert_conf):
    catalog = deepcopy(preview.catalog)
    catalog["clauses"][0]["role"] = "voting_confidence"
    preview.put_catalog(catalog)
    bid, _ = preview.bind(voting=True, label="majority_voting", role="label_probability_summary",
        columns=["cell_id", "predicted_label", "confidence"], metadata_updates={
            "confidence_insert_conf": insert_conf, "confidence_insert_conf_by": "majority_voting"})
    result = configured_prediction_semantics_service(preview.ledger).explain(bid)
    assert result["clauses"][0]["applies_to_this_artifact"] is insert_conf
    assert result["to_adata_call_verification"] == "not_established_by_definition_matching"


@pytest.mark.parametrize("damage", ["body", "header", "symlink", "escape"])
def test_file_identity_and_path_boundaries_fail_closed(preview, damage):
    root = preview.ledger.workspace.root
    if damage == "body":
        (root / "score.csv").write_bytes((root / "score.csv").read_bytes() + b"CHANGED_BODY\n")
    elif damage == "header":
        record = preview.ledger.get_record("prediction_artifact_binding", preview.binding_id)
        record["binding"]["header_sha256"] = "f" * 64
        record["binding_hash"] = content_hash(record["binding"])
        record["id"] = "prediction-artifact-" + record["binding_hash"]
        preview.ledger.put_record("prediction_artifact_binding", record["id"], record)
        preview.binding_id = record["id"]
    elif damage == "symlink":
        (root / "original.csv").write_bytes((root / "score.csv").read_bytes())
        (root / "score.csv").unlink();(root / "score.csv").symlink_to(root / "original.csv")
    else:
        value = deepcopy(preview.binding);value["score"]["relative_path"] = "../outside.csv"
        with pytest.raises(ValueError):ArtifactBinding.model_validate(value)
        return
    with pytest.raises(PredictionSemanticsError):
        configured_prediction_semantics_service(preview.ledger).explain(preview.binding_id)


@pytest.mark.parametrize("kind", ["hypothesis", "source_assertion"])
def test_assertion_kind_is_not_widened_by_new_scope(preview, kind):
    if kind == "hypothesis":
        binding = deepcopy(preview.catalog["clauses"][0]["binding"]);binding["expected_assertion_kind"] = kind
        with pytest.raises(ValueError):ClauseBinding.model_validate(binding)
    else:
        catalog = deepcopy(preview.catalog);catalog["clauses"][1]["binding"]["expected_assertion_kind"] = kind
        preview.put_catalog(catalog)
        with pytest.raises(PredictionSemanticsError):
            configured_prediction_semantics_service(preview.ledger).explain(preview.binding_id)
    # The original prerequisite gate remains strictly source_assertion-only.
    original = object.__new__(WorkflowInputService)
    original.ledger = preview.ledger;original.knowledge = preview.knowledge
    with preview.ledger.connect() as conn:
        with pytest.raises(ValueError):original._candidate(preview.synthesis["id"], conn)


@pytest.mark.parametrize("field,value", [("package", "another_package"), ("version", "9.9.9")])
def test_author_package_version_metadata_must_match_exact_catalog(preview, field, value):
    # A different package/version is a NEW source revision, never an overwrite
    # through the immutable ledger. Pin its real hash too, so this exercises
    # package/version scope rather than merely a stale metadata digest.
    metadata = deepcopy(preview.source["metadata"]);metadata[field] = value
    sources = SourceService(preview.ledger)
    source = sources.register_bytes("synthetic_mismatched_source.txt",
        b"SYNTHETIC ENGINEERING FIXTURE ONLY: sample score definition and source-traced arithmetic.", metadata=metadata)
    ir = sources.parse(source["id"]);block = ir["blocks"][0]
    claim = deepcopy(preview.direct["claim"])
    claim["anchors"] = [{"ir_id": ir["id"], "block_id": block["id"], "start": 0,
                         "end": len(block["exact_text"]), "quote": block["exact_text"]}]
    with preview.ledger.transaction() as conn:
        candidate = preview.knowledge._store_candidate(claim, {"kind": "synthetic_fixture", "not_model_output": True}, conn=conn)
    catalog = deepcopy(preview.catalog)
    catalog["sources"] = [{**catalog["sources"][0], "source_id": source["id"],
        "blob_sha256": source["blob_sha256"], "metadata_hash": content_hash(metadata)}]
    catalog["clauses"] = [catalog["clauses"][0]]
    catalog["clauses"][0]["binding"].update(candidate_id=candidate["id"], candidate_hash=candidate["content_hash"])
    preview.put_catalog(catalog)
    with pytest.raises(PredictionSemanticsError):
        configured_prediction_semantics_service(preview.ledger).explain(preview.binding_id)
    assert preview.ledger.get_record("source", preview.source["id"]) == preview.source


def test_catalog_switch_and_source_suspension_invalidate_existing_service(preview):
    service = configured_prediction_semantics_service(preview.ledger)
    service.explain(preview.binding_id)
    preview.knowledge.suspend("source", preview.source["id"], actor="synthetic-test", reason="Synthetic withdrawal")
    with pytest.raises(PredictionSemanticsError):service.explain(preview.binding_id)
    preview.ledger.set_state("prediction_semantics_catalog", {"record_id": "other", "catalog_hash": "f" * 64})
    with pytest.raises(PredictionSemanticsError):service.explain(preview.binding_id)


@pytest.mark.parametrize("version,calibration", [("9.9.9", False), (None, True), ("1.7.1", True)])
def test_version_scope_and_raw_calibration_flags_do_not_certify_correctness(preview, version, calibration):
    bid, _ = preview.bind(version=version, calibration=calibration)
    result = configured_prediction_semantics_service(preview.ledger).explain(bid)
    assert result["calibration_status"] == "not_established"
    assert result["artifact_facts"]["raw_calibration_declaration"] is calibration
    assert any(c["applies_to_this_artifact"] for c in result["clauses"]) is (version == "1.7.1")


def test_requested_voting_does_not_fill_missing_observed_label_column(preview):
    bid, _ = preview.bind(voting=True, label=None)
    result = configured_prediction_semantics_service(preview.ledger).explain(bid)
    assert result["artifact_facts"]["voting_requested"] is True
    assert result["artifact_facts"]["selected_label_column_recorded"] is None
    assert "selected_label_column" in result["unknowns"]


@pytest.mark.parametrize("conflict", [{"tool_name": "another_tool"}, {"label_column": "majority_voting"}])
def test_conflicting_synonymous_metadata_is_rejected_even_with_a_rebound_snapshot(preview, conflict):
    root = preview.ledger.workspace.root
    metadata = json.loads((root / "metadata.json").read_text());metadata.update(conflict)
    raw = json.dumps(metadata).encode();(root / "metadata.json").write_bytes(raw)
    manifest = json.loads((root / "manifest.json").read_text())
    manifest["artifact_hashes"]["metadata.json"] = sha(raw)
    manifest_raw = json.dumps(manifest).encode();(root / "manifest.json").write_bytes(manifest_raw)
    binding = deepcopy(preview.binding);binding["metadata"]["sha256"] = sha(raw)
    binding["manifest"]["sha256"] = sha(manifest_raw)
    rid = "prediction-artifact-" + content_hash(binding)
    preview.ledger.put_record("prediction_artifact_binding", rid,
                             {"id": rid, "binding": binding, "binding_hash": content_hash(binding)})
    with pytest.raises(PredictionSemanticsError):
        configured_prediction_semantics_service(preview.ledger).explain(rid)


@pytest.mark.parametrize("which", ["json", "header"])
def test_bounded_reads_reject_oversize_without_parsing_rows(preview, which):
    root = preview.ledger.workspace.root
    if which == "json":(root / "metadata.json").write_bytes(b" " * (JSON_LIMIT + 1))
    else:(root / "score.csv").write_bytes(b"A" * (HEADER_LIMIT + 1) + b"\nNEVER_PARSE_ME\n")
    with pytest.raises(PredictionSemanticsError):
        configured_prediction_semantics_service(preview.ledger).explain(preview.binding_id)


def test_read_only_refresh_keeps_records_and_files_unchanged(preview):
    root = preview.ledger.workspace.root
    files = lambda: {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    before = files();records = preview.ledger.list_records("candidate")
    service = configured_prediction_semantics_service(preview.ledger)
    assert service.explain(preview.binding_id) == service.explain(preview.binding_id)
    assert files() == before and preview.ledger.list_records("candidate") == records


@pytest.mark.parametrize("insert_conf", ["missing", None, False, 0, "false", True])
def test_voting_definition_needs_explicit_true_insertion_record(preview, insert_conf):
    catalog = deepcopy(preview.catalog)
    catalog["clauses"] = [catalog["clauses"][0]]
    catalog["clauses"][0].update(role="voting_confidence", clause_id="voting_confidence")
    preview.put_catalog(catalog)
    metadata = {"confidence_insert_conf_by": "majority_voting"}
    if insert_conf != "missing":metadata["confidence_insert_conf"] = insert_conf
    bid, _ = preview.bind(legacy=True, label="majority_voting", role="label_probability_summary", metadata_updates=metadata)
    result = configured_prediction_semantics_service(preview.ledger).explain(bid)
    assert result["clauses"][0]["applies_to_this_artifact"] is (insert_conf is True)


def test_malformed_quoted_header_is_a_controlled_unavailable_result(preview):
    bid, _ = preview.bind(columns=["cell_id", '"unclosed'])
    with pytest.raises(PredictionSemanticsError):
        configured_prediction_semantics_service(preview.ledger).explain(bid)


def test_fifo_replacement_is_rejected_promptly_in_a_bounded_child(preview):
    import os
    from pathlib import Path
    import subprocess
    import sys
    path = preview.ledger.workspace.root / "score.csv"
    path.unlink();os.mkfifo(path)
    child = '''import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from sckg_workbench.storage import Ledger, Workspace
from sckg_workbench.prediction_semantics import configured_prediction_semantics_service, PredictionSemanticsError
ledger = Ledger(Workspace(Path(sys.argv[2])))
try:
    configured_prediction_semantics_service(ledger).explain(sys.argv[3])
except PredictionSemanticsError:
    print("nonregular_artifact_rejected")
else:
    raise AssertionError("FIFO must not be accepted")
'''
    # The existing suite supervisor is the outer stop. This inner bound also
    # prevents a blocking open regression from wedging the rest of the tests.
    result = subprocess.run([sys.executable, "-I", "-B", "-c", child,
        str(Path(__file__).resolve().parents[1]), str(preview.ledger.workspace.root), preview.binding_id],
        capture_output=True, text=True, timeout=3)
    assert result.returncode == 0 and result.stdout.strip() == "nonregular_artifact_rejected"


@pytest.mark.parametrize("damage", ["runs_not_list", "run_not_object", "hashes_not_object"])
def test_malformed_manifest_structure_is_controlled_unavailable(preview, damage):
    _, binding = preview.bind(legacy=True)
    path = preview.ledger.workspace.root / "manifest.json"
    manifest = json.loads(path.read_text())
    if damage == "runs_not_list":manifest["runs"] = "invalid"
    elif damage == "run_not_object":manifest["runs"] = ["invalid"]
    else:manifest["output_hashes"] = []
    raw = json.dumps(manifest).encode();path.write_bytes(raw)
    binding["manifest"]["sha256"] = sha(raw)
    rid = "prediction-artifact-" + content_hash(binding)
    preview.ledger.put_record("prediction_artifact_binding", rid,
                             {"id": rid, "binding": binding, "binding_hash": content_hash(binding)})
    with pytest.raises(PredictionSemanticsError):
        configured_prediction_semantics_service(preview.ledger).explain(rid)
