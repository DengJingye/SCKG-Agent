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
    source = (ROOT / "app.py").read_text(encoding="utf-8")
    for label in [
        '"Subject"', '"Predicate"', '"Object"', '"Scope"', '"EvidenceSpan"',
        '"SourceRevision"', '"Validation"', '"Governance status"',
    ]:
        assert label in source


def test_legacy_replay_labels_validation_as_structural_not_scientific_truth() -> None:
    source = (ROOT / "app.py").read_text(encoding="utf-8")
    assert "STRUCTURAL VALID" in source
    assert "STRUCTURAL INVALID" in source
    assert "They do not assert scientific truth" in source
