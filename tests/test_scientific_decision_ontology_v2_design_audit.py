from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data/ontology/scientific_decision_ontology_v2"
CHECKPOINT_5A = "c8cef942f214efb2844cd3e5bf1aa0c28a4a50ab"


def _json(name: str):
    return json.loads((OUTPUT / name).read_text(encoding="utf-8"))


def _tree_hash(paths: list[Path]) -> str:
    files = []
    for path in paths:
        candidates = [path] if path.is_file() else list(path.rglob("*")) if path.is_dir() else []
        for candidate in candidates:
            if not candidate.is_file() or "__pycache__" in candidate.parts:
                continue
            relative = str(candidate.relative_to(ROOT)).casefold()
            if "sealed" in relative or "quarantine" in relative or "/c7" in relative:
                continue
            files.append(candidate)
    records = {
        str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(set(files))
    }
    return hashlib.sha256("".join(f"{name}\0{value}\n" for name, value in records.items()).encode()).hexdigest()


def test_design_deliverable_set_is_exact() -> None:
    assert {path.name for path in OUTPUT.iterdir() if path.is_file()} == {
        "class_registry.json",
        "interface_registry.json",
        "property_registry.json",
        "predicate_registry.json",
        "qualifier_registry.json",
        "statement_model.json",
        "evidence_model.json",
        "provenance_model.json",
        "action_model.json",
        "constraint_shapes.json",
        "external_alignment.json",
        "v1_v2_gap_analysis.json",
        "competency_question_coverage.json",
        "manifest.json",
    }


def test_competency_questions_are_unique_bounded_and_grouped() -> None:
    coverage = _json("competency_question_coverage.json")
    rows = coverage["questions"]
    ids = [row["competency_question_id"] for row in rows]
    assert 60 <= len(rows) <= 100
    assert len(ids) == len(set(ids))
    assert {row["group"] for row in rows} == {
        "Identity", "Method / implementation", "Representation / transformation",
        "Applicability", "Scientific claims", "Evidence", "Version / provenance / temporal",
        "Knowledge evolution", "Planning / actions", "Governance", "Evaluation",
    }
    assert sum(coverage["coverage_counts"].values()) == len(rows)


def test_every_competency_question_maps_all_four_requirement_kinds() -> None:
    for row in _json("competency_question_coverage.json")["questions"]:
        assert row["required_classes"]
        assert row["required_predicates"]
        assert row["required_qualifiers"]
        assert row["required_constraints"]


def test_competency_question_references_resolve() -> None:
    classes = _json("class_registry.json")
    class_ids = {row["class_id"] for row in classes["current_classes"] + classes["proposed_classes"]}
    interfaces = {row["interface_id"] for row in _json("interface_registry.json")["interfaces"]}
    external_types = {"Activity", "Agent", "PropertyDefinition"}
    predicate_ids = {row["predicate_id"] for row in _json("predicate_registry.json")["proposed_predicates"]}
    qualifier_ids = {row["qualifier_id"] for row in _json("qualifier_registry.json")["qualifiers"]}
    shape_ids = {row["shape_id"] for row in _json("constraint_shapes.json")["shapes"]}
    for row in _json("competency_question_coverage.json")["questions"]:
        assert set(row["required_classes"]) <= class_ids | interfaces | external_types
        assert set(row["required_predicates"]) <= predicate_ids
        assert set(row["required_qualifiers"]) <= qualifier_ids
        assert set(row["required_constraints"]) <= shape_ids


def test_class_ids_are_unique_and_all_classes_are_documented() -> None:
    registry = _json("class_registry.json")
    for key in ["current_classes", "proposed_classes"]:
        rows = registry[key]
        ids = [row["class_id"] for row in rows]
        assert len(ids) == len(set(ids))
        for row in rows:
            assert row["meaning"]
            assert row["owner"]
            assert row["required_properties"]
            assert row["lifecycle"]
            assert isinstance(row["versioned"], bool)
            assert isinstance(row["reviewable"], bool)


def test_current_class_provenance_distinguishes_physical_schema_pilot_and_runtime() -> None:
    statuses = {row["status"] for row in _json("class_registry.json")["current_classes"]}
    assert statuses == {
        "CURRENT_V1_PHYSICAL_GRAPH",
        "CURRENT_V1_SCHEMA_NOT_GRAPH_MATERIALIZED",
        "CURRENT_PILOT_ONLY",
        "CURRENT_RUNTIME_MODEL",
    }


def test_predicate_ids_are_unique_and_registry_is_complete() -> None:
    registry = _json("predicate_registry.json")
    for key in ["current_predicates", "proposed_predicates"]:
        rows = registry[key]
        ids = [row["predicate_id"] for row in rows]
        assert len(ids) == len(set(ids))
        for row in rows:
            assert row["definition"]
            assert row["domain"]
            assert row["range"]
            assert "evidence_required" in row
            assert "transitive" in row


def test_inverse_predicate_references_are_valid_and_reciprocal() -> None:
    rows = _json("predicate_registry.json")["proposed_predicates"]
    by_id = {row["predicate_id"]: row for row in rows}
    for row in rows:
        inverse = row["inverse_predicate"]
        if inverse:
            assert inverse in by_id
            assert by_id[inverse]["inverse_predicate"] == row["predicate_id"]


def test_interfaces_reference_valid_classes_and_properties() -> None:
    classes = _json("class_registry.json")
    class_ids = {row["class_id"] for row in classes["current_classes"] + classes["proposed_classes"]}
    property_ids = {row["property_id"] for row in _json("property_registry.json")["concepts"]}
    for row in _json("interface_registry.json")["interfaces"]:
        assert set(row["implementing_classes"]) <= class_ids
        assert set(row["required_properties"] + row["optional_properties"]) <= property_ids


def test_qualifiers_are_unique_defined_and_not_silent_scope_duplicates() -> None:
    rows = _json("qualifier_registry.json")["qualifiers"]
    ids = [row["qualifier_id"] for row in rows]
    assert len(ids) == len(set(ids))
    for row in rows:
        assert row["definition"]
        assert row["owner"]
        assert row["operational_rule"]
        assert row["not_a_scope_duplicate"] is True


def test_constraint_shapes_reference_valid_classes_properties_and_predicates() -> None:
    classes = _json("class_registry.json")
    class_ids = {row["class_id"] for row in classes["current_classes"] + classes["proposed_classes"]}
    property_ids = {row["property_id"] for row in _json("property_registry.json")["concepts"]}
    predicate_ids = {row["predicate_id"] for row in _json("predicate_registry.json")["proposed_predicates"]}
    for row in _json("constraint_shapes.json")["shapes"]:
        assert row["target_class"] in class_ids
        assert set(row["required_properties"]) <= property_ids
        assert set(row["endpoint_constraints"]) <= predicate_ids


def test_every_add_or_refine_gap_cites_a_valid_competency_question() -> None:
    cq_ids = {row["competency_question_id"] for row in _json("competency_question_coverage.json")["questions"]}
    for row in _json("v1_v2_gap_analysis.json")["entries"]:
        if row["action"] in {"ADD", "REFINE"}:
            assert row["competency_question_ids"]
            assert set(row["competency_question_ids"]) <= cq_ids


def test_deprecated_concepts_have_replacement_or_reason() -> None:
    for row in _json("v1_v2_gap_analysis.json")["entries"]:
        if row["action"] == "DEPRECATE":
            assert row["replacement_or_target"] or row["rationale"]


def test_external_mappings_use_only_declared_mapping_types() -> None:
    alignment = _json("external_alignment.json")
    valid = set(alignment["valid_mapping_types"])
    assert {row["external_model"] for row in alignment["external_models"]} == {
        "EDAM", "PROV-O", "Biolink Model", "OBO Relation Ontology", "RO-Crate 1.3"
    }
    for model in alignment["external_models"]:
        assert model["source_url"].startswith("https://")
        assert all(row["mapping_type"] in valid for row in model["mappings"])


def test_statement_model_separates_identity_revision_projection_and_layers() -> None:
    model = _json("statement_model.json")
    assert model["authoritative_model"]["identity_class"] == "ScientificStatement"
    assert model["authoritative_model"]["revision_class"] == "StatementRevision"
    assert model["graph_projection"]["authoritative"] is False
    assert set(model["layer_separation"]) == {"scientific_knowledge", "runtime_state", "governed_action"}


def test_evidence_support_and_drift_states_are_operationally_defined() -> None:
    model = _json("evidence_model.json")
    assert {row["state"] for row in model["support_states"]} == {
        "DIRECT_SUPPORT", "PARTIAL_SUPPORT", "CONTEXTUAL_SUPPORT", "CONTRADICTS",
        "REFUTES", "DOES_NOT_SUPPORT", "UNCERTAIN",
    }
    assert {row["state"] for row in model["evidence_drift_states"]} == {
        "CURRENT", "EVIDENCE_CHANGED", "STALE_EVIDENCE", "REVALIDATION_REQUIRED", "SUPERSEDED",
    }
    assert all(row["operational_definition"] for row in model["support_states"] + model["evidence_drift_states"])


def test_actions_declare_governance_and_reversibility_without_implementation() -> None:
    actions = _json("action_model.json")["actions"]
    assert len(actions) == 13
    for row in actions:
        assert row["input_object_types"]
        assert row["preconditions"]
        assert row["permissions"]
        assert row["outputs"]
        assert row["trace_stage"]
        assert row["rollback_or_reversibility"]
        assert row["implemented"] is False


def test_manifest_hashes_every_design_artifact_and_document() -> None:
    manifest = _json("manifest.json")
    for name, expected in manifest["artifacts"].items():
        assert hashlib.sha256((OUTPUT / name).read_bytes()).hexdigest() == expected
    for relative, expected in manifest["documents"].items():
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == expected


def test_production_ontology_is_unchanged_from_checkpoint_5a() -> None:
    subprocess.run([
        "git", "diff", "--exit-code", CHECKPOINT_5A, "--",
        "core/scientific_knowledge_conformance_models.py",
        "data/evidence_candidates/scientific_knowledge_schema_v1_1",
    ], cwd=ROOT, check=True, capture_output=True, text=True)


def test_scientific_kg_is_unchanged_from_checkpoint_5a() -> None:
    subprocess.run([
        "git", "diff", "--exit-code", CHECKPOINT_5A, "--", "data/evidence_candidates"
    ], cwd=ROOT, check=True, capture_output=True, text=True)


def test_rag_is_unchanged_from_checkpoint_5a() -> None:
    subprocess.run([
        "git", "diff", "--exit-code", CHECKPOINT_5A, "--", "data/indexes/retrieval_foundation_v1"
    ], cwd=ROOT, check=True, capture_output=True, text=True)


def test_planner_is_unchanged_from_checkpoint_5a() -> None:
    subprocess.run([
        "git", "diff", "--exit-code", CHECKPOINT_5A, "--",
        "engine/capability_planner.py", "engine/execution_planner.py",
    ], cwd=ROOT, check=True, capture_output=True, text=True)


def test_studio_extractor_is_unchanged_from_checkpoint_5a() -> None:
    subprocess.run([
        "git", "diff", "--exit-code", CHECKPOINT_5A, "--", "engine/scientific_knowledge_studio.py"
    ], cwd=ROOT, check=True, capture_output=True, text=True)


def test_protected_tree_hashes_match_current_files() -> None:
    manifest = _json("manifest.json")
    evidence = ROOT / "data/evidence_candidates"
    index = ROOT / "data/indexes/retrieval_foundation_v1"
    paths = {
        "production_ontology": [ROOT / "core/scientific_knowledge_conformance_models.py", evidence / "scientific_knowledge_schema_v1_1"],
        "scientific_kg": [evidence / "scientific_kg_v1_inventory", evidence / "scientific_kg_v1_uat_decision_rules", evidence / "scientific_kg_v1_core", evidence / "scientific_kg_content_expansion_v1", evidence / "scientific_knowledge_scanpy_core_v1_1"],
        "rag": [index],
        "planner": [ROOT / "engine/capability_planner.py", ROOT / "engine/execution_planner.py"],
        "studio_extractor": [ROOT / "engine/scientific_knowledge_studio.py"],
    }
    for name, selected in paths.items():
        assert _tree_hash(selected) == manifest["protected_artifacts"][name]["tree_sha256"]


def test_no_production_mutation_or_quarantined_c7_access_is_claimed() -> None:
    manifest = _json("manifest.json")
    assert manifest["protected_changed_groups"] == []
    assert manifest["production_ontology_changed"] is False
    assert manifest["scientific_kg_changed"] is False
    assert manifest["rag_changed"] is False
    assert manifest["planner_changed"] is False
    assert manifest["studio_extractor_changed"] is False
    assert manifest["quarantined_c7_payload_accessed"] is False
    assert manifest["pdf_rerun"] is False
    assert manifest["external_llm_called"] is False
