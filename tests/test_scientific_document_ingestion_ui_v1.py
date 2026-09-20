from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest


ROOT = Path(__file__).resolve().parents[1]


def test_hardened_ingestion_ui_uses_dispositions_and_stage_states() -> None:
    app = AppTest.from_file(str(ROOT / "app.py")).run(timeout=30)
    next(button for button in app.button if button.label == "Scientific KG").click().run(timeout=30)
    source_radio = next(item for item in app.radio if item.label == "Document source")
    source_radio.set_value("Replay hardened SoupX ingestion").run(timeout=30)
    assert len(app.exception) == 0
    metric_labels = {metric.label for metric in app.metric}
    for status in [
        "RAW_PROPOSAL", "EVIDENCE_ONLY", "ABSTAINED", "DROPPED", "NEEDS_REVIEW", "CANDIDATE_READY"
    ]:
        assert status in metric_labels
    for stage in [
        "TEXT_QUALITY", "BLOCK_CLASSIFICATION", "CLAIM_LIKENESS", "ENTITY_LINKING",
        "CANONICALIZATION", "SCOPE_RESOLUTION", "EVIDENCE_BINDING", "SEMANTIC_VALIDATION",
    ]:
        assert stage in metric_labels
    captions = "\n".join(str(item.value) for item in app.caption)
    assert "not judgments that a scientific proposition is true or false" in captions
    assert "scientific validity is not assessed" in captions
    assert "Human-readable ontology labels are primary" in captions
    markdown = "\n".join(str(item.value) for item in app.markdown)
    assert "Candidate KG Relations" in markdown
    assert "Candidate KG Graph" in markdown
    assert "same 5 CANDIDATE_READY relations" in captions
    assert "does not add claims or mutate the Scientific KG" in captions
    assert "structural/provenance relations" in captions
    selectbox = next(item for item in app.selectbox if item.label == "HumanReviewPacket")
    assert "SoupX::adjustCounts@1.6.2" in selectbox.options[0]
    assert "operator-revision:soupx" not in selectbox.options[0]
    relations = next(
        dataframe.value
        for dataframe in app.dataframe
        if "Relation class" in dataframe.value.columns
    )
    assert len(relations) == 5
    assert set(relations["Schema contract"]) == {"PASS"}
    scientific_rows = relations[relations["Relation class"] == "Scientific statement candidate"]
    structural_rows = relations[relations["Relation class"].str.startswith("Structural")]
    assert len(scientific_rows) == 3
    assert scientific_rows["StatementRevision"].ne("—").all()
    assert scientific_rows["EvidenceAssessment"].ne("—").all()
    assert len(structural_rows) == 2
    assert structural_rows["StatementRevision"].eq("—").all()
    assert relations[["Subject", "Relation", "Object"]].to_dict("records") == [
        {
            "Subject": "SoupX::adjustCounts@1.6.2",
            "Relation": "is version of",
            "Object": "SoupX::adjustCounts",
        },
        {
            "Subject": "SoupX::adjustCounts@1.6.2",
            "Relation": "implements method",
            "Object": "Ambient RNA count correction",
        },
        {
            "Subject": "SoupX::adjustCounts@1.6.2",
            "Relation": "supports task",
            "Object": "Ambient RNA contamination correction",
        },
        {
            "Subject": "SoupX::adjustCounts@1.6.2",
            "Relation": "has requirement",
            "Object": "Estimated ambient contamination model input",
        },
        {
            "Subject": "Corrected counts output",
            "Relation": "has output representation",
            "Object": "Ambient-corrected counts",
        },
    ]
    assert "contamination_model_input2" not in relations.to_string()
    source = (ROOT / "app.py").read_text(encoding="utf-8")
    for label in [
        '"Subject"', '"Relation"', '"Object"', '"Scope"', '"EvidenceSpan"',
        '"SourceRevision"', '"Validation"', '"Governance status"',
    ]:
        assert label in source
    assert '"Subject canonical ID"' in source
    assert '"Predicate canonical ID"' in source
    assert '"Object canonical ID"' in source
    assert '"Schema contract"' in source
    assert '"Candidate subgraph"' in source


def test_legacy_replay_labels_validation_as_structural_not_scientific_truth() -> None:
    source = (ROOT / "app.py").read_text(encoding="utf-8")
    assert "STRUCTURAL VALID" in source
    assert "STRUCTURAL INVALID" in source
    assert "They do not assert scientific truth" in source
