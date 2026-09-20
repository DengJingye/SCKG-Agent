from __future__ import annotations

import inspect
import json
from pathlib import Path

from streamlit.testing.v1 import AppTest

import app as app_module
from engine.scientific_knowledge_studio import (
    ScientificKnowledgeStudioService,
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
