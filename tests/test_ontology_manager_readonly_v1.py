from __future__ import annotations

import hashlib
import inspect
import json
import shutil
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from engine.ontology_manager import (
    OntologyIntegrityError,
    OntologyManagerReadOnlyService,
    build_ontology_schema_graph_html,
    build_ontology_schema_graph_payload,
)


ROOT = Path(__file__).resolve().parents[1]
FROZEN = ROOT / "data/ontology/scientific_decision_ontology_v2_core"


def _service(root: Path = ROOT) -> OntologyManagerReadOnlyService:
    return OntologyManagerReadOnlyService(root)


def _tree_hashes(path: Path) -> dict[str, str]:
    return {
        str(item.relative_to(path)): hashlib.sha256(item.read_bytes()).hexdigest()
        for item in sorted(path.iterdir())
        if item.is_file()
    }


def _sandbox(tmp_path: Path) -> tuple[Path, Path]:
    target = tmp_path / "data/ontology/scientific_decision_ontology_v2_core"
    target.parent.mkdir(parents=True)
    shutil.copytree(FROZEN, target)
    return tmp_path, target


def _rewrite_artifact_and_manifest(
    frozen: Path,
    name: str,
    update: dict[str, object],
    *,
    remove: set[str] | None = None,
) -> None:
    artifact_path = frozen / name
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    artifact.update(update)
    for key in remove or set():
        artifact.pop(key, None)
    artifact_path.write_text(json.dumps(artifact), encoding="utf-8")
    manifest_path = frozen / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["artifacts"][name] = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")


def _text(app: AppTest) -> str:
    values: list[str] = []
    for collection in (app.markdown, app.caption, app.info, app.warning, app.error):
        values.extend(str(item.value) for item in collection)
    return "\n".join(values)


def test_overview_counts_match_frozen_manifest() -> None:
    service = _service()
    overview = service.overview()
    manifest = json.loads((FROZEN / "manifest.json").read_text(encoding="utf-8"))

    assert overview == {
        "ontology_version": manifest["ontology_version"],
        "schema_version": manifest["schema_version"],
        "freeze_commit": manifest["current_head"],
        "core_object_type_count": 26,
        "authoritative_link_count": 23,
        "derived_projection_count": 2,
        "property_count": 74,
        "qualifier_count": 10,
        "extension_count": 7,
        "deferred_count": 8,
        "extension_registry_item_count": 17,
        "deferred_registry_item_count": 39,
        "merged_compatibility_object_count": 4,
        "design_frozen": True,
        "production_migration": False,
    }
    assert service.integrity()["status"] == "VERIFIED"
    assert service.integrity()["artifact_count"] == 12
    assert service.integrity()["version_boundary_artifact_count"] == 11


def test_object_types_search_filters_and_detail_use_frozen_rows() -> None:
    service = _service()

    assert len(service.object_types()) == 41
    assert len(service.object_types(statuses={"Core"})) == 26
    assert len(service.object_types(statuses={"Extension"})) == 7
    assert len(service.object_types(statuses={"Deferred"})) == 8
    runtime = service.object_types(layers={"runtime bridge"})
    assert [row["Object Type"] for row in runtime] == ["RepresentationRecord"]
    assert service.object_types("bounded analysis objective")[0]["Object Type"] == "ScientificTask"

    detail = service.object_detail("OperatorRevision")
    assert detail["definition"]
    assert "id" in detail["required_properties"]
    assert "revision_of" in detail["links_out"]
    assert detail["cq_support"]
    assert detail["v1_compatibility"]["disposition"] == "CORE_OBJECT_TYPE"


def test_link_types_preserve_authority_policies_and_details() -> None:
    service = _service()
    links = service.link_types()

    assert len(links) == 25
    assert len(service.link_types(classifications={"AUTHORITATIVE"})) == 23
    derived = service.link_types(classifications={"DERIVED_PROJECTION"})
    assert {row["Predicate"] for row in derived} == {"consumes", "produces"}
    assert all(row["Authority"] == "DERIVED_PROJECTION" for row in derived)
    detail = service.link_detail("consumes")
    assert detail["classification"] == "DERIVED_PROJECTION"
    assert detail["evidence_policy"]["rule"]
    assert detail["qualifier_policy"]["rule"]


def test_properties_qualifiers_and_effect_description_boundary() -> None:
    service = _service()

    assert len(service.properties()) == 74
    assert len(service.qualifiers()) == 10
    effect = next(row for row in service.properties() if row["Name"] == "effect_description")
    assert effect["Assertion allowed?"] == "FALSE"
    assert effect["Machine authority?"] == "NO MACHINE AUTHORITY"
    assert "display" in effect["Definition"].casefold()
    modality = next(row for row in service.qualifiers() if row["Name"] == "modality")
    assert modality["Allowed context"] == "StatementRevision_or_ApplicabilityScope"
    assert "inline context" in modality["Storage policy"]


def test_schema_graph_is_bounded_schema_only_and_filters_derived() -> None:
    service = _service()
    full = service.schema_graph()
    authoritative = service.schema_graph(authoritative_only=True)
    no_derived = service.schema_graph(show_derived=False)
    runtime = service.schema_graph(modules={"runtime-bridge"})

    assert full["node_count"] == 41
    assert full["instance_nodes_loaded"] == 0
    assert full["bounded"] is True
    assert {row["predicate"] for row in full["edges"]} >= {"consumes", "produces"}
    assert all(row["classification"] == "AUTHORITATIVE" for row in authoritative["edges"])
    assert all(row["classification"] != "DERIVED_PROJECTION" for row in no_derived["edges"])
    assert {row["id"] for row in runtime["nodes"]} == {
        "RepresentationRecord",
        "RepresentationType",
    }
    assert {row["predicate"] for row in runtime["edges"]} == {"binds_to_type"}
    assert runtime["node_count"] < full["node_count"]

    rendered = build_ontology_schema_graph_html(full)
    assert "dataset.nodeId" in rendered
    assert "dataset.edgeId" in rendered
    assert "createElementNS(ns,'path')" in rendered
    assert "e.geometry.path" in rendered
    assert "0 instance nodes" in rendered
    assert "Derived Projection" in rendered


def test_missing_artifact_fails_closed(tmp_path: Path) -> None:
    root, frozen = _sandbox(tmp_path)
    (frozen / "qualifier_registry.json").unlink()

    with pytest.raises(OntologyIntegrityError, match="missing frozen ontology artifact"):
        _service(root)


def test_hash_mismatch_fails_closed(tmp_path: Path) -> None:
    root, frozen = _sandbox(tmp_path)
    path = frozen / "property_registry.json"
    path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    with pytest.raises(OntologyIntegrityError, match="hash mismatch"):
        _service(root)


def test_invalid_registry_fails_closed_after_hash_verification(tmp_path: Path) -> None:
    root, frozen = _sandbox(tmp_path)
    registry_path = frozen / "object_type_registry.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    registry["objects"][1]["item_id"] = registry["objects"][0]["item_id"]
    registry_path.write_text(json.dumps(registry), encoding="utf-8")
    manifest_path = frozen / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["artifacts"]["object_type_registry.json"] = hashlib.sha256(
        registry_path.read_bytes()
    ).hexdigest()
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(OntologyIntegrityError, match="duplicate item_id"):
        _service(root)


@pytest.mark.parametrize(
    ("name", "update"),
    [
        ("evidence_model.json", {"schema_version": "wrong-design-version"}),
        ("scope_policy.json", {"ontology_version": "9.9.9-incompatible"}),
        ("statement_model.json", {"design_only": False}),
    ],
)
def test_all_json_design_boundaries_fail_closed_even_with_updated_hash(
    tmp_path: Path, name: str, update: dict[str, object]
) -> None:
    root, frozen = _sandbox(tmp_path)
    _rewrite_artifact_and_manifest(frozen, name, update)

    with pytest.raises(OntologyIntegrityError, match=name):
        _service(root)


def test_valid_frozen_mapping_migration_boundary_loads() -> None:
    service = _service()

    assert service.integrity()["status"] == "VERIFIED"
    assert service.overview()["production_migration"] is False


@pytest.mark.parametrize(
    ("value", "remove_field"),
    [
        (True, False),
        ("false", False),
        (0, False),
        (None, True),
    ],
    ids=["true", "string-false", "integer-zero", "missing"],
)
def test_mapping_migration_boundary_fails_closed_with_recomputed_hash(
    tmp_path: Path, value: object, remove_field: bool
) -> None:
    root, frozen = _sandbox(tmp_path)
    _rewrite_artifact_and_manifest(
        frozen,
        "v1_v2_mapping_draft.json",
        {} if remove_field else {"migration_implemented": value},
        remove={"migration_implemented"} if remove_field else None,
    )

    with pytest.raises(OntologyIntegrityError, match="migration_implemented"):
        _service(root)


def test_mapping_status_boundary_fails_closed_with_recomputed_hash(tmp_path: Path) -> None:
    root, frozen = _sandbox(tmp_path)
    _rewrite_artifact_and_manifest(
        frozen,
        "v1_v2_mapping_draft.json",
        {"status": "MIGRATION_READY"},
    )

    with pytest.raises(OntologyIntegrityError, match="design boundary mismatch"):
        _service(root)


def test_all_public_nested_projections_are_detached() -> None:
    service = _service()

    object_before = service.object_detail("OperatorRevision")
    object_mutated = service.object_detail("OperatorRevision")
    object_mutated["required_properties"].append("caller_injected")
    object_mutated["frozen_record"]["source_mapping"]["identity_field"] = "caller_changed"
    object_mutated["v1_compatibility"]["reason"] = "caller_changed"
    assert service.object_detail("OperatorRevision") == object_before

    link_before = service.link_detail("consumes")
    link_mutated = service.link_detail("consumes")
    link_mutated["qualifier_policy"]["allowed"].append("caller_injected")
    link_mutated["frozen_record"]["evidence_policy"]["rule"] = "caller_changed"
    assert service.link_detail("consumes") == link_before

    property_before = service.property_detail("effect_description")
    property_mutated = service.property_detail("effect_description")
    property_mutated["owners"].append("caller_injected")
    property_mutated["forbidden_uses"].append("caller_injected")
    assert service.property_detail("effect_description") == property_before

    qualifier_before = service.qualifier_detail("modality")
    qualifier_mutated = service.qualifier_detail("modality")
    qualifier_mutated["owner"] = "caller_changed"
    assert service.qualifier_detail("modality") == qualifier_before

    graph_before = service.schema_graph()
    graph_mutated = service.schema_graph()
    graph_mutated["nodes"][0]["definition"] = "caller_changed"
    graph_mutated["edges"][0]["definition"] = "caller_changed"
    assert service.schema_graph() == graph_before

    payload_before = build_ontology_schema_graph_payload(service.schema_graph())
    payload_mutated = build_ontology_schema_graph_payload(service.schema_graph())
    payload_mutated["edges"][0]["geometry"]["path"] = "caller_changed"
    payload_mutated["edges"][0]["selection"]["predicate"] = "caller_changed"
    assert build_ontology_schema_graph_payload(service.schema_graph()) == payload_before

    integrity_before = service.integrity()
    integrity_mutated = service.integrity()
    integrity_mutated["verified_hashes"]["scope_policy.json"] = "caller_changed"
    assert service.integrity() == integrity_before


def test_extension_and_deferred_display_layers_come_from_frozen_modules() -> None:
    service = _service()
    expected = {
        "TraceSpan": "runtime / observability",
        "GovernedAction": "action / governance",
        "ActionPolicy": "action / governance",
        "MetricDefinition": "evaluation",
        "BenchmarkStudy": "evaluation",
        "IdentityAssertion": "identity / governance",
        "ReferenceArtifact": "scientific",
    }

    for object_type, layer in expected.items():
        assert service.object_detail(object_type)["layer"] == layer
        filtered = service.object_types(layers={layer})
        assert object_type in {row["Object Type"] for row in filtered}
    assert "UNDECLARED" not in {
        service.object_detail(object_type)["layer"] for object_type in expected
    }


def test_parallel_schema_edges_have_deterministic_independent_geometry() -> None:
    service = _service()
    first = build_ontology_schema_graph_payload(service.schema_graph())
    repeated = build_ontology_schema_graph_payload(service.schema_graph())
    assert first == repeated

    parallel = [
        edge
        for edge in first["edges"]
        if edge["source"] == "OperatorRevision"
        and edge["target"] == "RepresentationType"
        and edge["predicate"] in {"consumes", "produces"}
    ]
    assert {edge["predicate"] for edge in parallel} == {"consumes", "produces"}
    assert len({edge["edge_id"] for edge in parallel}) == 2
    assert len({edge["geometry"]["path"] for edge in parallel}) == 2
    assert len({edge["geometry"]["offset"] for edge in parallel}) == 2
    assert {edge["parallel_count"] for edge in parallel} == {2}
    assert {edge["selection"]["predicate"] for edge in parallel} == {
        "consumes",
        "produces",
    }
    assert service.link_detail("consumes")["predicate"] == "consumes"
    assert service.link_detail("produces")["predicate"] == "produces"

    hidden = service.schema_graph(show_derived=False)
    authoritative = service.schema_graph(authoritative_only=True)
    assert not {"consumes", "produces"} & {edge["predicate"] for edge in hidden["edges"]}
    assert not {"consumes", "produces"} & {
        edge["predicate"] for edge in authoritative["edges"]
    }


def test_service_reads_do_not_write_frozen_or_protected_assets() -> None:
    protected = [
        FROZEN,
        ROOT / "agent",
        ROOT / "engine/scientific_kg_evidence.py",
        ROOT / "engine/scientific_knowledge_studio.py",
        ROOT / "engine/capability_planner.py",
    ]
    before = {
        str(path): _tree_hashes(path) if path.is_dir() else _tree_hashes(path.parent)[path.name]
        for path in protected
    }
    service = _service()
    service.overview()
    service.object_detail("ScientificTask")
    service.link_detail("consumes")
    service.schema_graph()
    after = {
        str(path): _tree_hashes(path) if path.is_dir() else _tree_hashes(path.parent)[path.name]
        for path in protected
    }

    assert before == after


def test_service_has_no_mutation_review_or_promotion_surface() -> None:
    methods = {
        name
        for name, value in inspect.getmembers(OntologyManagerReadOnlyService, inspect.isfunction)
        if not name.startswith("_")
    }
    forbidden = {
        "write", "edit", "create", "delete", "update", "review", "promote", "merge", "mutate"
    }
    assert not any(token in method for token in forbidden for method in methods)


def test_ontology_section_opens_with_counts_boundaries_and_no_controls() -> None:
    app = AppTest.from_file(str(ROOT / "app.py")).run(timeout=30)
    next(button for button in app.button if button.label == "Scientific KG").click().run(
        timeout=30
    )

    assert len(app.exception) == 0
    assert [tab.label for tab in app.tabs[:4]] == [
        "Overview",
        "Scientific Graph",
        "Readiness & Integrity",
        "Candidate Studio",
    ]
    nested_labels = {tab.label for tab in app.tabs}
    assert {
        "Ontology",
        "Ontology Overview",
        "Object Types",
        "Link Types",
        "Properties & Qualifiers",
        "Schema Graph",
        "Properties",
        "Qualifiers",
    } <= nested_labels
    metrics = {metric.label: metric.value for metric in app.metric}
    assert metrics["Core object types"] == "26"
    assert metrics["Authoritative links"] == "23"
    assert metrics["Derived projections"] == "2"
    assert metrics["Properties"] == "74"
    assert metrics["Qualifiers"] == "10"
    assert metrics["Extension count"] == "7"
    assert metrics["Deferred count"] == "8"
    text = _text(app)
    assert "DESIGN FROZEN" in text
    assert "PRODUCTION MIGRATION = NO" in text
    assert "effect_description → DISPLAY ONLY / NO MACHINE AUTHORITY" in text
    assert "DERIVED PROJECTION" in text
    labels = {button.label for button in app.button}
    assert not {"Promote", "ReviewDecision", "Edit", "Save", "Delete"} & labels


def test_ui_object_filter_and_detail_work() -> None:
    app = AppTest.from_file(str(ROOT / "app.py")).run(timeout=30)
    next(button for button in app.button if button.label == "Scientific KG").click().run(
        timeout=30
    )
    search = next(item for item in app.text_input if item.key == "ontology_object_search")
    search.input("RepresentationRecord").run(timeout=30)

    assert len(app.exception) == 0
    detail = next(item for item in app.selectbox if item.key == "ontology_object_detail")
    assert detail.value == "RepresentationRecord"
    assert list(detail.options) == ["RepresentationRecord"]

    link_search = next(item for item in app.text_input if item.key == "ontology_link_search")
    link_search.input("consumes").run(timeout=30)
    assert len(app.exception) == 0
    link_detail = next(item for item in app.selectbox if item.key == "ontology_link_detail")
    assert link_detail.value == "consumes"
    assert "DERIVED PROJECTION · non-authoritative computed view" in _text(app)
