from __future__ import annotations

import hashlib
import json
from pathlib import Path

from core.scientific_knowledge_conformance_models import (
    ConformanceBundle,
    OperatorRevision,
    Package,
)
from data_pipeline.build_scientific_kg_content_expansion_v1 import (
    CAPABILITY_FAMILIES,
    DEFAULT_OUTPUT_DIR,
    ECOSYSTEMS,
    build,
)
from data_pipeline.build_scientific_knowledge_conformance_v1_1 import CANONICAL_PATHS


def _json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _bundle(root: Path = DEFAULT_OUTPUT_DIR) -> ConformanceBundle:
    return ConformanceBundle.model_validate(_json(root / "conformance_bundle.json"))


def test_build_is_deterministic_and_keeps_canonical_and_retrieval_inputs_unchanged(tmp_path: Path) -> None:
    before = {path: _sha256(path) for path in CANONICAL_PATHS if path.exists()}

    generated = build(tmp_path)
    frozen = _json(DEFAULT_OUTPUT_DIR / "manifest.json")

    assert generated["status"] == "candidate_only_not_promoted"
    assert generated["artifacts"] == frozen["artifacts"]
    assert generated["canonical_before"] == generated["canonical_after"]
    assert generated["canonical_kg_modified"] is False
    assert generated["retrieval_index_rebuilt"] is False
    assert generated["promotion_performed"] is False
    assert {path: _sha256(path) for path in CANONICAL_PATHS if path.exists()} == before
    for name in generated["artifacts"]:
        assert (tmp_path / name).read_bytes() == (DEFAULT_OUTPUT_DIR / name).read_bytes()


def test_coverage_plan_has_nineteen_ecosystems_and_all_required_capability_families() -> None:
    plan = _json(DEFAULT_OUTPUT_DIR / "coverage_plan.json")

    assert len(ECOSYSTEMS) == 19
    assert plan["target_ecosystem_count"] == 19
    assert set(plan["family_coverage_counts"]) == set(CAPABILITY_FAMILIES)
    assert all(plan["family_coverage_counts"][family] > 0 for family in CAPABILITY_FAMILIES)
    assert {item["label"] for item in plan["ecosystems"]} >= {
        "Scanpy",
        "Seurat",
        "Harmony",
        "Scanorama",
        "scvi-tools",
        "Scrublet",
        "DoubletFinder",
        "scDblFinder",
        "CellTypist",
        "SingleR",
        "scVelo",
        "CellRank",
        "tradeSeq",
        "moscot",
        "WOT",
        "MOFA2",
        "cell2location",
        "MIMOSCA",
        "SoupX",
    }


def test_identity_model_never_flattens_packages_operators_and_methods_into_tool_nodes() -> None:
    bundle = _bundle()
    identity = _json(DEFAULT_OUTPUT_DIR / "identity_graph.json")
    ids = {item.entity_id: item.record_type for item in bundle.entities}

    assert identity["flat_tool_nodes_created"] == 0
    assert "Tool" not in set(ids.values())
    assert ids["software-project:harmony"] == "SoftwareProject"
    assert ids["package:harmony"] == "Package"
    assert ids["operator:harmony.run_harmony"] == "Operator"
    assert ids["operator-revision:harmony.run_harmony:source-snapshot"] == "OperatorRevision"
    assert ids["method:harmony_integration"] == "Method"
    assert ids["package:mofa2"] == "Package"
    assert ids["package:mofapy2"] == "Package"
    assert next(item for item in bundle.entities if isinstance(item, Package) and item.entity_id == "package:mofapy2").project_id == "software-project:mofa2"
    assert len(ids) == len(bundle.entities)


def test_every_operator_revision_has_canonical_ports_and_unresolved_release_is_explicit() -> None:
    revisions = [item for item in _bundle().entities if isinstance(item, OperatorRevision)]
    external = [item for item in revisions if not item.entity_id.startswith("operator-revision:scanpy.")]

    assert len(revisions) == 12
    assert len(external) == 7
    assert all(item.input_ports and item.output_ports for item in revisions)
    assert all(item.package_release_id.endswith(":source-snapshot") for item in external)
    assert all(not item.contract_refs for item in external)
    assert all(port.requirements for item in external for port in item.input_ports)


def test_ports_are_canonical_and_consumes_produces_are_only_projections() -> None:
    bundle = _bundle()
    relations = bundle.derived_relations

    assert sum(item.relation == "CONSUMES" for item in relations) == 18
    assert sum(item.relation == "PRODUCES" for item in relations) == 14
    assert all(item.derivation_type == "port_projection" for item in relations if item.relation in {"CONSUMES", "PRODUCES"})
    assert all(item.input_port_id and not item.output_port_id for item in relations if item.relation == "CONSUMES")
    assert all(item.output_port_id and not item.input_port_id for item in relations if item.relation == "PRODUCES")
    assert all(item.derived_from_claim_revision_ids for item in relations if item.relation in {"CONSUMES", "PRODUCES"})


def test_can_feed_is_reviewed_derived_and_no_requires_before_is_invented() -> None:
    relations = _bundle().derived_relations
    can_feed = [item for item in relations if item.relation == "CAN_FEED"]

    assert len(can_feed) == 6
    assert all(item.derivation_type == "reviewed_rule" for item in can_feed)
    assert all(item.review_status == "candidate_pending_review" for item in can_feed)
    assert all(item.input_port_id and item.output_port_id and item.premise_relation_ids for item in can_feed)
    assert not any(item.relation == "REQUIRES_BEFORE" for item in relations)


def test_all_claims_have_resolvable_source_bound_provenance_and_valid_hashes() -> None:
    bundle = _bundle()
    report = _json(DEFAULT_OUTPUT_DIR / "quality_report.json")
    external_refs = _jsonl(DEFAULT_OUTPUT_DIR / "evidence_span_references.jsonl")
    assessment_claims = {item.claim_revision_id for item in bundle.evidence_assessments}

    assert len(bundle.atomic_claims) == 92
    assert assessment_claims == {item.claim_revision_id for item in bundle.atomic_claims}
    assert all(item.content_hash == hashlib.sha256(item.claim_text.encode("utf-8")).hexdigest() for item in bundle.atomic_claims)
    assert all(item["source_bound"] is True for item in external_refs)
    assert all(item["candidate_only"] is True and item["retrieval_eligible"] is False for item in external_refs)
    assert report["checks"]["evidence_span_resolvability"]["passed"] is True
    assert report["checks"]["source_bound_external_evidence"]["passed"] is True


def test_multiomics_and_reference_sensitive_requirements_remain_typed_or_explicitly_gapped() -> None:
    bundle = _bundle()
    representations = {item.representation_type_id: item for item in bundle.representation_types}
    gaps = _json(DEFAULT_OUTPUT_DIR / "evidence_gaps.json")["gaps"]

    assert representations["representation-type:multiomics_matrices"].modalities == ["rna", "atac", "protein"]
    assert representations["representation-type:cell_type_signatures"].observation_unit == "cell_type"
    assert representations["representation-type:single_cell_expression"].transformation_state == ["normalization_unspecified"]
    assert any(item["ecosystem"] == "CellTypist" and "ReferenceArtifactRevision" in item["missing_knowledge"] for item in gaps)
    assert any(item["ecosystem"] == "MOFA2" and "version-pinned" in item["missing_knowledge"] for item in gaps)


def test_evidence_gaps_are_explicit_and_no_missing_matrix_cell_is_silently_completed() -> None:
    gaps = _json(DEFAULT_OUTPUT_DIR / "evidence_gaps.json")["gaps"]
    report = _json(DEFAULT_OUTPUT_DIR / "quality_report.json")

    assert len(gaps) == 72
    assert all(item["candidate_only"] is True for item in gaps)
    assert all(item["required_source"] for item in gaps)
    assert report["checks"]["unsupported_candidate_relation"] == {
        "passed": True,
        "count": 0,
        "policy": "unproven semantics are emitted only as EvidenceGap",
    }
    assert report["checks"]["entity_identity_uniqueness"] == {
        "passed": True,
        "duplicate_count": 0,
    }


def test_identity_and_version_conflicts_remain_explicit_candidate_blockers() -> None:
    conflicts = _json(DEFAULT_OUTPUT_DIR / "identity_version_conflicts.json")["conflicts"]
    gaps = _json(DEFAULT_OUTPUT_DIR / "evidence_gaps.json")["gaps"]

    assert len(conflicts) == 5
    assert {item["conflict_id"] for item in conflicts} >= {
        "identity-conflict:scvi-tools-vs-scvi-method",
        "identity-conflict:mofa2-r-vs-mofapy2-python",
        "identity-conflict:singler-legacy-vs-bioconductor",
    }
    assert all(item["status"] != "silently_resolved" for item in conflicts)
    assert all(
        any(
            gap["ecosystem"] == label
            and gap["missing_knowledge"] == "immutable package release and OperatorRevision version pin"
            for gap in gaps
        )
        for label in {"Harmony", "Scanorama", "Scrublet", "DoubletFinder", "scDblFinder", "SingleR"}
    )


def test_high_risk_requirements_parameters_and_limitations_require_stronger_review() -> None:
    queue = _json(DEFAULT_OUTPUT_DIR / "high_risk_claims.json")["claims"]
    governance = _jsonl(DEFAULT_OUTPUT_DIR / "claim_governance.jsonl")

    assert len(queue) == 26
    assert all(item["risk_class"] == "R3" for item in queue)
    assert all(item["strong_review_required"] is True for item in queue)
    assert all(item["review_status"] == "candidate_pending_review" for item in governance)
    assert not any(item.get("review_status") == "accepted" for item in governance)


def test_candidate_bundle_contains_no_runtime_instances_or_promotion_side_effects() -> None:
    bundle = _bundle()
    report = _json(DEFAULT_OUTPUT_DIR / "quality_report.json")
    manifest = _json(DEFAULT_OUTPUT_DIR / "manifest.json")

    assert bundle.instance_bindings == []
    assert report["checks"]["runtime_representation_boundary"] == {
        "passed": True,
        "owner": "RepresentationLedger",
    }
    assert report["promotion"]["performed"] is False
    assert report["promotion"]["eligible_now"] is False
    assert manifest["canonical_kg_modified"] is False
    assert manifest["retrieval_index_rebuilt"] is False
    assert manifest["runtime_modified"] is False
