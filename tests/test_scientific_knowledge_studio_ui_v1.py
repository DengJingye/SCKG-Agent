from __future__ import annotations

import inspect
import json
from html import escape
from pathlib import Path

from streamlit.testing.v1 import AppTest

import app as app_module
from engine.knowledge_graph_view import build_knowledge_graph_html
from engine.scientific_graph_viewer import (
    ScientificGraphViewerConfig,
    build_scientific_graph_viewer_html,
)
from engine.scientific_knowledge_studio import (
    ScientificKnowledgeStudioService,
    candidate_demo_view,
    load_studio_evaluation_snapshot,
    proposal_graph_view,
)


ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "data/evaluation/scientific_knowledge_studio_v1"


def _app():
    app = AppTest.from_file(str(ROOT / "app.py")).run(timeout=30)
    next(button for button in app.button if button.label == "Scientific KG").click().run(timeout=30)
    assert len(app.exception) == 0
    return app


def _text(app) -> str:
    values = []
    for collection in (app.markdown, app.caption, app.info, app.warning, app.success):
        values.extend(str(item.value) for item in collection)
    return "\n".join(values)


def test_candidate_studio_opens_inside_existing_scientific_kg_workspace() -> None:
    app = _app()
    assert [tab.label for tab in app.tabs[:4]] == [
        "Overview", "Scientific Graph", "Readiness & Integrity", "Candidate Studio"
    ]


def test_preview_only_banner_and_governance_boundaries_are_visible() -> None:
    text = _text(_app())
    assert "PREVIEW ONLY · Scientific KG unchanged" in text
    assert "KG mutation: DISABLED" in text
    assert "ReviewDecision: NOT AVAILABLE" in text
    assert "Canonical promotion: NOT AVAILABLE" in text


def test_pipeline_stepper_renders_all_eight_stages() -> None:
    app = _app()
    labels = {metric.label for metric in app.metric}
    for expected in [
        "1 Upload", "2 Source", "3 Parse", "4 Evidence",
        "5 Extract", "6 Resolve", "7 Validate", "8 Preview",
    ]:
        assert expected in labels


def test_current_kg_metrics_and_proposed_delta_match_frozen_artifact() -> None:
    app = _app()
    diff = json.loads((SNAPSHOT / "candidate_diff.json").read_text(encoding="utf-8"))
    metrics = {metric.label: metric.value for metric in app.metric}
    assert metrics["Current nodes"] == f"{diff['current_nodes']:,}"
    assert metrics["Current edges"] == f"{diff['current_edges']:,}"
    assert metrics["Current candidate claims"] == f"{diff['current_candidate_claims']:,}"
    assert metrics["Entity proposals"] == f"+ {diff['entity_proposals']}"
    assert metrics["Relation proposals"] == f"+ {diff['relation_proposals']}"
    assert metrics["Claim proposals"] == f"+ {diff['atomic_claim_proposals']}"
    assert metrics["Evidence proposals"] == f"+ {diff['evidence_span_proposals']}"


def test_evidence_selection_displays_exact_text_and_stable_locator() -> None:
    app = _app()
    run = load_studio_evaluation_snapshot(SNAPSHOT)
    selected = run["evidence"][0]
    text = _text(app)
    assert selected["segment_id"] in text
    assert f"Page {selected['page_number']}" in text
    assert selected["exact_text"] in text


def test_proposal_graph_is_bounded_and_renderable() -> None:
    run = load_studio_evaluation_snapshot(SNAPSHOT)
    graph = proposal_graph_view(run["proposal_graph"])
    assert len(graph.nodes) == len(run["proposal_graph"]["nodes"])
    assert len(graph.nodes) < 100
    assert {node.kind for node in graph.nodes.values()} >= {
        "EXISTING_KG", "NEW_PROPOSAL", "EVIDENCE_SPAN", "SOURCE"
    }


def test_no_mutation_review_or_promotion_controls_are_visible() -> None:
    app = _app()
    labels = {button.label for button in app.button}
    assert "Promote" not in labels
    assert "ReviewDecision" not in labels
    assert "Merge" not in labels
    assert "Supersede" not in labels


def test_no_candidate_is_labeled_trusted_or_canonical() -> None:
    run = load_studio_evaluation_snapshot(SNAPSHOT)
    scientific = [run["source"], *run["evidence"], *run["entities"], *run["relations"], *run["claims"], *run["scopes"]]
    assert all(row.get("proposal_status") == "candidate_proposal" for row in scientific)
    assert all(row.get("knowledge_status", "candidate_proposal") == "candidate_proposal" for row in scientific)


def test_service_has_no_canonical_mutation_promotion_or_review_api() -> None:
    methods = {
        name for name, value in inspect.getmembers(ScientificKnowledgeStudioService, inspect.isfunction)
        if not name.startswith("_")
    }
    assert not methods & {"promote", "review", "merge", "supersede", "deposit", "index", "mutate"}
    assert methods == {"ontology_contract", "run_pdf", "run_pdf_bytes", "run_from_pages"}


def test_existing_scientific_kg_tabs_and_admin_surfaces_remain_present() -> None:
    source = (ROOT / "app.py").read_text(encoding="utf-8")
    for label in ["Overview", "Scientific Graph", "Readiness & Integrity", "Candidate Studio"]:
        assert f'"{label}"' in source
    for function_name in [
        "_render_graph_explorer_page", "_render_knowledge_review_panel",
        "_render_evidence_admin_panel", "_render_evaluation_admin_panel",
        "_render_scientific_kg_admin_page",
    ]:
        assert f"def {function_name}" in source


def test_ui_copy_never_claims_that_kg_was_mutated() -> None:
    source = inspect.getsource(app_module._render_candidate_studio)
    assert "If accepted, proposed delta would be" in source
    assert "KG 已新增" not in source
    assert "Scientific KG unchanged" in source


def test_verified_soupx_replay_is_explicit_and_not_presented_as_current_inference() -> None:
    text = _text(_app())
    assert "Replay of previously generated real pipeline artifacts" in text
    assert "no current re-inference" in text
    assert "SoupX 1.6.2 manual" in text


def test_candidate_demo_pipeline_counts_are_derived_from_the_loaded_run() -> None:
    run = load_studio_evaluation_snapshot(SNAPSHOT)
    demo = candidate_demo_view(run)
    pipeline = {row["stage"]: row for row in demo["pipeline"]}
    assert demo["document"]["parsed_pages"] == run["manifest"]["parsed_pages"]
    assert demo["document"]["page_count"] == run["manifest"]["page_count"]
    assert pipeline["Evidence"]["value"] == f"{len(run['evidence'])} proposals"
    assert pipeline["Statement"]["value"] == f"{len(run['claims'])} proposals"
    assert pipeline["Scope"]["value"] == f"{len(run['scopes'])} proposals"
    assert pipeline["Candidate KG"]["value"] == (
        f"{len(run['proposal_graph']['nodes'])} nodes · "
        f"{len(run['proposal_graph']['edges'])} edges"
    )


def test_statement_view_preserves_exact_evidence_scope_and_validation_bindings() -> None:
    run = load_studio_evaluation_snapshot(SNAPSHOT)
    demo = candidate_demo_view(run)
    evidence_by_id = {row["proposal_id"]: row for row in run["evidence"]}
    scope_by_id = {row["scope_proposal_id"]: row for row in run["scopes"]}
    assert len(demo["statements"]) == len(run["claims"])
    for statement in demo["statements"]:
        expected_ids = statement["supporting_evidence_span_ids"]
        assert [row["proposal_id"] for row in statement["evidence_bindings"]] == expected_ids
        assert statement["evidence_bindings"] == [evidence_by_id[item] for item in expected_ids]
        assert statement["scope"] == scope_by_id[statement["scope_proposal_id"]]
        assert statement["validation_status"] in {"VALID", "NEEDS_REVIEW", "INVALID"}
        assert statement["polarity_label"] == "NOT_MODELED"


def test_statement_selection_updates_the_visible_bound_evidence() -> None:
    app = _app()
    statement_box = next(
        item for item in app.selectbox if item.label == "Candidate Statement / Claim proposal"
    )
    selected_index = 4
    statement_box.select(statement_box.options[selected_index]).run(timeout=30)
    run = load_studio_evaluation_snapshot(SNAPSHOT)
    claim = run["claims"][selected_index]
    evidence_by_id = {row["proposal_id"]: row for row in run["evidence"]}
    selected_evidence = evidence_by_id[claim["supporting_evidence_span_ids"][0]]
    visible = _text(app)
    assert escape(selected_evidence["exact_text"]) in visible
    assert selected_evidence["segment_id"] in visible
    assert f"Page {selected_evidence['page_number']}" in visible


def test_validation_view_retains_invalid_items_and_real_reasons() -> None:
    run = load_studio_evaluation_snapshot(SNAPSHOT)
    demo = candidate_demo_view(run)
    assert demo["validation_counts"] == {"VALID": 23, "NEEDS_REVIEW": 0, "INVALID": 10}
    invalid = [row for row in demo["validation_rows"] if row["status"] == "INVALID"]
    assert len(invalid) == 10
    assert all(row["reason_or_issue"] != "No validation issue recorded" for row in invalid)
    assert any("INVALID_SUPPORTING_EVIDENCE" in row["reason_or_issue"] for row in invalid)


def test_candidate_graph_summary_is_bounded_to_the_selected_run() -> None:
    run = load_studio_evaluation_snapshot(SNAPSHOT)
    demo = candidate_demo_view(run)
    assert demo["graph"] == {
        "node_count": len(run["proposal_graph"]["nodes"]),
        "edge_count": len(run["proposal_graph"]["edges"]),
        "bounded_to_run": True,
    }
    assert demo["graph"]["node_count"] < 100


def test_candidate_graph_renderer_exposes_node_and_edge_details() -> None:
    run = load_studio_evaluation_snapshot(SNAPSHOT)
    html = build_knowledge_graph_html(proposal_graph_view(run["proposal_graph"]))
    assert "selectNode(n.id)" in html
    assert "selectEdge(e.id)" in html
    assert "Graph relation" in html
    assert "单击节点或关系查看详情" in html
    assert '"NEW_PROPOSAL": "#3978E8"' in html
    assert '"INVALID_PROPOSAL": "#C44747"' in html


def _viewer_payload(html: str) -> dict:
    marker = '<script id="payload" type="application/json">'
    return json.loads(html.split(marker, 1)[1].split("</script>", 1)[0])


def test_scientific_graph_viewer_preserves_soupx_graph_and_has_no_nested_shell() -> None:
    run = load_studio_evaluation_snapshot(SNAPSHOT)
    html = build_scientific_graph_viewer_html(
        proposal_graph_view(run["proposal_graph"]),
        config=ScientificGraphViewerConfig(
            mode="candidate_kg", standard_node_cap=80, global_node_cap=120
        ),
    )
    payload = _viewer_payload(html)

    assert payload["summary"]["fullNodes"] == 35
    assert payload["summary"]["fullEdges"] == 42
    assert {edge["relation"] for edge in payload["edges"]} == {
        edge["relation"] for edge in run["proposal_graph"]["edges"]
    }
    assert not {"RELATED_TO", "SIMILAR", "CONNECTED"} & {
        edge["relation"] for edge in payload["edges"]
    }
    assert 'data-viewer="ScientificGraphViewer"' in html
    assert "scKG Decision Network" not in html
    assert 'src="http' not in html and 'href="http' not in html


def test_scientific_graph_viewer_supports_all_layouts_density_and_interactions() -> None:
    run = load_studio_evaluation_snapshot(SNAPSHOT)
    html = build_scientific_graph_viewer_html(proposal_graph_view(run["proposal_graph"]))

    for value in ("force", "hierarchical", "circular"):
        assert f'data-layout="{value}"' in html
    for value in ("focus", "standard", "global"):
        assert f'data-scope="{value}"' in html
    for interaction in (
        "selectNode(n.id)",
        "selectEdge(e.id)",
        "zoomIn",
        "zoomOut",
        "fit",
        "clearSearch",
        "largeForceLayout",
        "parallelIndex",
        "marker-end",
    ):
        assert interaction in html
    assert "Full graph:" in html
    assert "Visible:" in html
    assert "Show Evidence" in html


def test_shared_viewer_contract_accepts_all_three_semantic_modes() -> None:
    assert {
        ScientificGraphViewerConfig(mode=mode).mode
        for mode in ("ontology_schema", "candidate_kg", "scientific_kg")
    } == {"ontology_schema", "candidate_kg", "scientific_kg"}


def test_candidate_view_uses_short_labels_but_retains_full_evidence_detail() -> None:
    run = load_studio_evaluation_snapshot(SNAPSHOT)
    payload = _viewer_payload(
        build_scientific_graph_viewer_html(proposal_graph_view(run["proposal_graph"]))
    )
    evidence = [node for node in payload["nodes"] if node["group"] == "evidence"]
    statements = [node for node in payload["nodes"] if node["group"] == "statement"]
    sources = [node for node in payload["nodes"] if node["group"] == "source"]

    assert evidence and all(node["displayLabel"].startswith("E") for node in evidence)
    assert all(" · p." in node["displayLabel"] for node in evidence)
    assert all(node["properties"]["exact_text"] not in node["displayLabel"] for node in evidence)
    assert all(node["properties"]["exact_text"] for node in evidence)
    assert statements and all(node["displayLabel"].startswith("S") for node in statements)
    assert sources and all(node["displayLabel"].endswith(" source") for node in sources)
    assert payload["config"]["showEvidence"] is False
