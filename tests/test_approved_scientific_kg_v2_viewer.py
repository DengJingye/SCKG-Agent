from __future__ import annotations

import hashlib
import json
from pathlib import Path

from streamlit.testing.v1 import AppTest

from engine.approved_scientific_kg_v2 import (
    EXPECTED_APPROVED_KG_SHA256,
    ApprovedScientificKGV2Service,
)
from engine.scientific_graph_viewer import (
    ScientificGraphViewerConfig,
    build_scientific_graph_viewer_html,
)
from engine.scientific_kg_admin import ScientificKGAdminSnapshotService


ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "reconstruction/promotion_v2/snapshots/approved-v2-01"
HELD_ID = "statement-revision:d0d887b96b7a1cf45e2c47bf:1"


def _service() -> ApprovedScientificKGV2Service:
    return ApprovedScientificKGV2Service(ROOT)


def _payload(html: str) -> dict:
    marker = '<script id="payload" type="application/json">'
    return json.loads(html.split(marker, 1)[1].split("</script>", 1)[0])


def test_approved_snapshot_hash_count_and_hold_boundary_are_verified() -> None:
    service = _service()
    summary = service.summary()
    actual_hash = hashlib.sha256(
        (SNAPSHOT / "approved_kg.json").read_bytes()
    ).hexdigest()
    global_graph = service.global_graph()

    assert actual_hash == EXPECTED_APPROVED_KG_SHA256
    assert summary["approved_kg_sha256"] == EXPECTED_APPROVED_KG_SHA256
    assert summary["hash_verified"] is True
    assert summary["approved_statements"] == 121
    assert summary["held_statements"] == 1
    assert HELD_ID not in global_graph.nodes
    assert (
        sum(node.kind == "StatementRevision" for node in global_graph.nodes.values())
        == 121
    )


def test_adapter_leaves_promoted_snapshot_unchanged() -> None:
    paths = sorted(path for path in SNAPSHOT.iterdir() if path.is_file())
    before = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths
    }

    service = _service()
    service.global_graph()
    for name in ("Scanpy HVG", "Scanpy PCA", "Scrublet"):
        service.focus_graph(name, max_nodes=160)

    after = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    assert after == before


def test_approved_governance_never_implies_execution_authority() -> None:
    graph = _service().global_graph()
    approved = [
        node for node in graph.nodes.values() if node.kind == "StatementRevision"
    ]

    assert approved
    assert all(node.metadata["knowledge_status"] == "approved" for node in approved)
    assert all(node.metadata["human_review_status"] == "approved" for node in approved)
    assert all(node.metadata["execution_authorized"] is False for node in approved)
    assert all(node.metadata["trusted"] is True for node in approved)


def test_v2_global_graph_preserves_core_object_types_and_cautions() -> None:
    graph = _service().global_graph()
    kinds = {node.kind for node in graph.nodes.values()}

    assert {
        "Method",
        "MethodVariant",
        "ScientificTask",
        "Operator",
        "OperatorRevision",
        "Requirement",
        "ParameterDefinition",
        "OutputPort",
        "ScientificStatement",
        "StatementRevision",
        "EvidenceAssessment",
        "EvidenceSpan",
        "SourceRevision",
        "EvidenceGap",
    } <= kinds
    cautions = [node for node in graph.nodes.values() if node.kind == "EvidenceGap"]
    assert len(cautions) == 166
    assert all(node.metadata["viewer_group"] == "caution" for node in cautions)
    assert all(node.metadata["execution_authorized"] is False for node in cautions)


def test_three_demo_focus_views_include_conditions_evidence_source_and_caution() -> (
    None
):
    service = _service()
    for name in ("Scanpy HVG", "Scanpy PCA", "Scrublet"):
        graph = service.focus_graph(name, max_nodes=160)
        kinds = {node.kind for node in graph.nodes.values()}
        assert "StatementRevision" in kinds, name
        assert {"Requirement", "ParameterDefinition"} & kinds, name
        assert "EvidenceAssessment" in kinds, name
        assert "EvidenceSpan" in kinds, name
        assert "SourceRevision" in kinds, name
        assert "EvidenceGap" in kinds, name
        assert graph.truncated is False, name


def test_approved_statement_evidence_chains_resolve_in_each_focus_view() -> None:
    service = _service()
    for name in ("Scanpy HVG", "Scanpy PCA", "Scrublet"):
        graph = service.focus_graph(name, max_nodes=160)
        statement_ids = [
            node_id
            for node_id, node in graph.nodes.items()
            if node.kind == "StatementRevision"
        ]
        chains = [
            service.get_claim_evidence_chain(node_id) for node_id in statement_ids
        ]
        assert chains, name
        assert all(chain["complete"] for chain in chains), name
        assert all(chain["evidence"] for chain in chains), name


def test_shared_viewer_distinguishes_approved_caution_and_execution_status() -> None:
    graph = _service().focus_graph("Scrublet", max_nodes=160)
    html = build_scientific_graph_viewer_html(
        graph,
        config=ScientificGraphViewerConfig(mode="scientific_kg", global_node_cap=2000),
    )
    payload = _payload(html)
    approved = [
        node for node in payload["nodes"] if node["type"] == "StatementRevision"
    ]
    cautions = [node for node in payload["nodes"] if node["group"] == "caution"]

    assert approved and all(node["candidateState"] == "APPROVED" for node in approved)
    assert all(node["executionAuthorized"] is False for node in approved)
    assert cautions and all(node["candidateState"] == "CAUTION" for node in cautions)
    assert all(node["executionAuthorized"] is False for node in cautions)
    assert payload["styles"]["statement"]["label"] == "Scientific Statement"
    assert payload["styles"]["caution"]["label"] == "Caution / Evidence Gap"
    for layout in ("force", "hierarchical", "circular"):
        assert f'data-layout="{layout}"' in html
    for density in ("focus", "standard", "global"):
        assert f'data-scope="{density}"' in html


def test_legacy_graph_remains_available_unchanged() -> None:
    graph = ScientificKGAdminSnapshotService(ROOT).global_graph()
    assert len(graph.nodes) == 1651
    assert len(graph.edges) == 2429


def test_app_can_switch_to_scientific_kg_v2_without_exceptions() -> None:
    app = AppTest.from_file(str(ROOT / "app.py")).run(timeout=30)
    next(
        button for button in app.button if button.label == "Scientific KG"
    ).click().run(timeout=30)
    source = next(item for item in app.radio if item.label == "Data source")
    source.set_value("Scientific KG v2").run(timeout=30)

    assert len(app.exception) == 0
    captions = "\n".join(str(item.value) for item in app.caption)
    assert "approved-scientific-kg-v2-01" in captions
    assert "121 approved statements" in captions
    assert "1 HOLD excluded" in captions
    assert "execution_authorized=false" in captions

    graph_scope = next(item for item in app.radio if item.label == "Graph scope")
    graph_scope.set_value("Full Scientific KG").run(timeout=30)
    assert len(app.exception) == 0
