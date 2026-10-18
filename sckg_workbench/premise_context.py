"""Pure provenance for model-extracted user premises, never scientific evidence.

Callers must first validate the originating plan's actual model receipt with
retrieval_planning._validate_run. These checks bind text and offsets only; they
cannot prove that the model extracted every premise or interpreted it correctly.
"""
from __future__ import annotations

from copy import deepcopy

from .retrieval_planning import EvidenceQueryPlan, _validate_plan_input
from .storage import content_hash


def unicode_spans(text: str, quote: str) -> list[dict]:
    """Return every exact overlapping Unicode [start,end) match, not byte offsets."""
    if not isinstance(text, str) or not isinstance(quote, str) or not quote:
        raise ValueError("Premise spans require text and a nonempty exact quote")
    spans, offset = [], 0
    while (start := text.find(quote, offset)) != -1:
        spans.append({"start": start, "end": start + len(quote)})
        offset = start + 1
    return spans


def derive_reported_premises(plan_run: dict) -> dict:
    """Derive stable P aliases from an already receipt-validated query-plan run."""
    if (not isinstance(plan_run, dict)
            or plan_run.get("binding_hash") != content_hash({
                key: value for key, value in plan_run.items() if key != "binding_hash"})
            or plan_run.get("input_hash") != content_hash(plan_run.get("input_material"))
            or plan_run.get("plan_hash") != content_hash(plan_run.get("plan"))):
        raise ValueError("Reported-premise source plan binding changed")
    plan = EvidenceQueryPlan.model_validate(plan_run["plan"])
    material = plan_run["input_material"]
    _validate_plan_input(plan, material)
    question = material["question"]
    premises = []
    for index, premise in enumerate(plan.stated_premises, 1):
        spans = unicode_spans(question, premise.quote) if premise.source == "question" else []
        if premise.source == "question" and not spans:
            raise ValueError("Reported question premise has no exact character span")
        premises.append({
            "premise_id": f"P{index}", "source": premise.source,
            "pointer": premise.pointer, "quote": premise.quote,
            "unicode_spans": spans,
            "span_scope": "original_question" if premise.source == "question" else "profile_pointer_value",
            "span_unit": "unicode_characters_half_open",
            "semantic_origin": "model_extracted_user_input_not_evidence",
            "independent_verification": "not_established",
        })
    context = {
        "schema_version": "reported-premise-context-v1",
        "question_hash": content_hash(question),
        "plan_binding_hash": plan_run["binding_hash"],
        "premises": premises,
        "extraction_completeness": "not_verified",
        "semantic_interpretation": "model_judgment_not_scientific_gold",
        "independent_verification": "not_established",
    }
    context["context_hash"] = content_hash(context)
    return context


def validate_reported_premises(context: dict, plan_run: dict) -> dict:
    """Pure exact reconstruction; does not upgrade the originating plan's trust."""
    expected = derive_reported_premises(plan_run)
    if context != expected:
        raise ValueError("Reported premise quotes, spans, identities or source binding changed")
    return deepcopy(expected)
