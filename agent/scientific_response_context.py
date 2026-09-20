"""Bounded answer inputs and decision-local provenance. No evidence writes.

History is conversational context. Only freshly resolved source bindings supply
citations; even an exact binding is not a human review or semantic proof.
"""
from __future__ import annotations

import re
from typing import Any

from agent.grounded_answer_audit import audit_grounded_answer_v3


def compact_conversation(rows: list[dict]) -> list[dict]:
    result = []
    for row in rows[-8:]:
        if row.get("role") not in {"user", "assistant"}:
            continue
        result.append({"role": row["role"], "content": str(row.get("content", ""))[:1600],
                       "authority": "conversation_only_not_evidence"})
    return result


def _diagnostics(value: dict | None):
    if not value:
        return
    yield value
    for row in value.get("queries", []):
        yield from _diagnostics(row)


def enrich_references(references: list[dict], diagnostic: dict | None, adapter=None, chunks=None) -> list[dict]:
    """Join exact mapped spans only. Candidate status is never promoted."""
    if adapter and hasattr(adapter, "enrich_references"):
        return adapter.enrich_references(references, diagnostic)
    rows = [dict(ref, knowledge_source="RETRIEVAL_GROUNDED", kg_statements=[]) for ref in references]
    for ref in rows:
        chunk = (chunks or {}).get(ref.get("source_span_id"))
        if chunk and chunk.source_id == ref.get("source_id") and chunk.source_span == ref.get("source_span"):
            ref["exact_excerpt"] = chunk.chunk_text
            ref["source_type"] = chunk.source_kind
    claims = {c.claim_revision_id: c for c in adapter.bundle.atomic_claims} if adapter else {}
    assessments = list(adapter.bundle.evidence_assessments) if adapter else []
    for diag in _diagnostics(diagnostic):
        eligible = set(diag.get("final_graph_chunk_ids", []))
        for path in diag.get("paths", []):
            if path.get("status") != "mapped":
                continue
            for evidence in path.get("evidence", []):
                if not evidence.get("binding_verified"):
                    continue
                matched = eligible & set(evidence.get("chunk_ids", []))
                for ref in rows:
                    if (ref.get("source_span_id") not in matched
                            or ref.get("source_id") != evidence.get("source_revision_id")
                            or ref.get("source_span") != evidence.get("locator")):
                        continue
                    claim_id = path["claim_revision_id"]
                    claim = claims.get(claim_id)
                    fact = {"statement_id": claim_id,
                            "statement": claim.claim_text if claim else "",
                            "operator_revision_id": path.get("operator_revision_id"),
                            "predicate": path.get("predicate"), "scope": path.get("scope", {}),
                            "requirements": path.get("requirements", []),
                            "constraints": path.get("constraints", []),
                            "knowledge_status": path.get("knowledge_status", "candidate"),
                            "recommendation_eligible": False, "execution_authorized": False,
                            "assessment_ids": [a.assessment_id for a in assessments
                                if a.claim_revision_id == claim_id and a.stance == "supports"
                                and evidence["evidence_span_id"] in a.evidence_span_ids],
                            "evidence_span_id": evidence["evidence_span_id"],
                            "source_revision_id": evidence["source_revision_id"],
                            "locator": evidence["locator"], "binding_verified": True}
                    if fact not in ref["kg_statements"]:
                        ref["kg_statements"].append(fact)
                    ref["knowledge_source"] = "KG_GROUNDED"
                    if adapter:
                        span = adapter.spans.get(evidence["evidence_span_id"], {})
                        ref["exact_excerpt"] = span.get("source_excerpt", ref.get("claim_text", ""))
                        source = adapter.sources.get(evidence["source_revision_id"], {})
                        ref["source_url"] = source.get("source_url") or source.get("url") or source.get("release_uri") or ""
    return rows


def append_caution_references(references, diagnostic, adapter):
    """Separate reminder citations; NEVER turn EvidenceGap into an assertion."""
    cautions = {}
    for diag in _diagnostics(diagnostic):
        for caution in diag.get("cautions", []):
            cautions.setdefault(caution["caution_id"], caution)
    selected = [c for c in cautions.values() if c.get("evidence")][:2]
    rows = references[:8-len(selected)]
    for caution in selected:
        span = caution["evidence"][0]
        source = adapter.source_for_span(span)
        rows.append({"index": len(rows)+1, "tool_name": "", "title": source["title"],
            "source_id": span["source_revision_id"], "source_span_id": span["evidence_span_id"],
            "source_span": span["locator"]["value"], "source_type": source["source_type"],
            "source_url": source["source_url"], "source_revision": source,
            "source_bound": True, "authority": "source_bound", "claim_type": "failure_mode",
            "claim_text": span["exact_text"], "exact_excerpt": span["exact_text"],
            "knowledge_source": "CAUTION_CONTEXT", "kg_statements": [], "caution_context": caution})
    return rows


def response_context(*, conversation, conversation_state, semantic, references,
                     data_state, contracts, planner, diagnostic) -> dict:
    diagnostics = list(_diagnostics(diagnostic))
    approved = next((d for d in diagnostics if d.get("adapter") == "ApprovedScientificKG"), None)
    cautions = {c["caution_id"]: c for d in diagnostics for c in d.get("cautions", [])}
    return {
        "schema_version": "scientific-response-context-v1",
        "conversation": compact_conversation(conversation),
        "user_reported_context": dict(conversation_state.get("user_reported_context") or {}),
        "current_user_reported_context": semantic.get("user_reported_context", {}),
        "resolved_question": semantic.get("retrieval_query", ""),
        "current_intent": semantic.get("intent"),
        "current_task": semantic.get("canonical_task"),
        "data_state": data_state,
        "scientific_kg": {"facts": [fact for ref in references for fact in ref.get("kg_statements", [])][:12],
                          "identity": "Approved Scientific KG v2" if approved else "Legacy / candidate evidence",
                          "snapshot_id": approved.get("snapshot_id") if approved else None,
                          "approved_kg_sha256": approved.get("approved_kg_sha256") if approved else None,
                          "adapter_called": bool(approved),
                          "legacy_kg_consulted": approved.get("legacy_kg_consulted") if approved else None,
                          "coverage": ("approved_scope_qualified" if approved else "source_bound_candidate") if any(ref.get("kg_statements") for ref in references) else "no_direct_statement",
                          "caution_context": list(cautions.values())[:6],
                          "gaps": [diag.get("fallback_reason") for diag in _diagnostics(diagnostic) if diag.get("fallback_reason")]},
        "evidence": [{key: ref[key] for key in (
            "index", "tool_name", "title", "claim_type", "support_claim_types", "claim_text",
            "source_span_id", "source_id", "source_span", "knowledge_source", "kg_statements", "caution_context") if key in ref}
            for ref in references[:8]],
        "tool_contracts": contracts[:4],
        "planner": {"status": planner.get("status", "not_requested"),
                    "blockers": planner.get("blockers", []), "execution_authorized": False},
        "authority": "History is not evidence. Approval is not applicability. Unknown/partially_known is not wildcard. Explain conditional knowledge without asserting it applies to the user's data. REQUIRED is scientific/API requirement only; never an execution gate. Caution/EvidenceGap is an untrusted, non-assertive reminder, never a scientific assertion or execution permission.",
    }


def compile_answer(payload: dict, references: list[dict]) -> tuple[str, list[dict]]:
    """Validate the citation/quote contract before any generated text is shown."""
    by_index = {int(ref["index"]): ref for ref in references}
    segments = payload.get("segments")
    if not isinstance(segments, list) or len(segments) > 10 or (not segments and not payload.get("clarifying_question")):
        raise ValueError("invalid_answer_segments")
    claims, grounded, model = [], [], []
    for n, segment in enumerate(segments):
        text = str(segment.get("text") or "").strip()
        basis = segment.get("basis")
        citations = segment.get("citations", [])
        if basis == "CAUTION_CONTEXT" and not re.search(r"提醒|警示|可检测|局限|不代表|不能|并非|不是|注意|不足|风险", text):
            raise ValueError("caution_must_be_framed_as_reminder")
        if not text or len(text) > 1800 or re.search(r"\[\d+\]", text):
            raise ValueError("invalid_answer_text")
        if basis not in {"KG_GROUNDED", "RETRIEVAL_GROUNDED", "MODEL_KNOWLEDGE", "CAUTION_CONTEXT"}:
            raise ValueError("invalid_knowledge_basis")
        if basis == "MODEL_KNOWLEDGE":
            if citations:
                raise ValueError("model_knowledge_cannot_borrow_citations")
            model.append(text)
        else:
            if not isinstance(citations, list) or not citations:
                raise ValueError("grounded_claim_requires_citation")
            for citation in citations:
                index, quote = citation.get("index"), str(citation.get("quote") or "")
                ref = by_index.get(index)
                if not ref or not ref.get("source_bound") or len(quote.strip()) < 12:
                    raise ValueError("unbound_citation")
                if quote not in str(ref.get("claim_text") or ""):
                    raise ValueError("quote_not_in_bound_excerpt")
                if basis == "KG_GROUNDED" and not ref.get("kg_statements"):
                    raise ValueError("kg_statement_missing")
                if bool(ref.get("caution_context")) != (basis == "CAUTION_CONTEXT"):
                    raise ValueError("caution_cannot_be_scientific_assertion")
                # The exact source paragraph alone is insufficient for this API
                # branch: the approved descriptor context preserves its conjunction.
                pca = any(f.get("output_ports") and "scanpy.pp.pca" in str(f.get("registered_statement", {}))
                          for f in ref.get("kg_statements", [])) or "scanpy.pp.pca" in str(ref.get("caution_context", {}).get("subject_ids", []))
                normalized = re.sub(r"[\s`'\"]", "", text.casefold())
                if pca and re.search(r"truncated.?svd|截断", normalized):
                    bounded = "chunked=false" in normalized and "zero_center=false" in normalized
                    uncertain = re.search(r"不能仅|不能单独|不能确定|无法确定|不足以|需.{0,5}确认", normalized)
                    if not bounded and not uncertain:
                        raise ValueError("pca_truncated_branch_requires_full_conjunction")
            text += "".join(f"[{c['index']}]" for c in citations)
            grounded.append(text)
        claims.append({"claim_id": f"answer-{n+1}", "text": text, "knowledge_source": basis,
                       "citations": citations, **({"scientific_assertion": False, "trusted": False,
                       "production_retrieval_eligible": False, "execution_gate": False, "execution_authorized": False}
                       if basis == "CAUTION_CONTEXT" else {})})
    parts = grounded
    if model:
        parts += ["模型通识（尚未核验）\n\n当前本地证据未充分覆盖以下说明。\n\n" + "\n\n".join(model)]
    question = str(payload.get("clarifying_question") or "").strip()
    if question:
        if len(question) > 350 or not question.endswith(("？", "?")) or re.search(r"\[\d+\]", question):
            raise ValueError("invalid_clarification")
        parts.append(question)
        claims.append({"claim_id": "clarification", "text": question,
                       "knowledge_source": "USER_CLARIFICATION", "citations": []})
    return "\n\n".join(parts), claims


def recover_prose_payload(content: str, references: list[dict]) -> dict:
    """Some compatible providers ignore JSON mode after prose history.

    Recover only plain prose; never repair invalid JSON or an invented citation.
    Recovered citations still pass the exact-source, entailment and structural
    checks. Uncited prose is explicitly model knowledge, never silently grounded.
    """
    if not content.strip() or content.lstrip().startswith(("{", "[", "```")):
        raise ValueError("malformed_structured_answer")
    by_index = {int(r["index"]): r for r in references}
    segments, question = [], ""
    for paragraph in re.split(r"\n\s*\n", content.strip()):
        paragraph = paragraph.strip()
        if not paragraph or paragraph.startswith("#"):
            continue
        if paragraph.endswith(("?", "？")) and "[" not in paragraph and len(paragraph) <= 350:
            question = paragraph
            continue
        indexes = sorted({int(i) for i in re.findall(r"\[(\d+)\]", paragraph)})
        if any(i not in by_index for i in indexes):
            raise ValueError("unbound_citation")
        segments.append({"text": re.sub(r"\[\d+\]", "", paragraph),
            "basis": ("CAUTION_CONTEXT" if indexes and all(by_index[i].get("caution_context") for i in indexes)
                      else "RETRIEVAL_GROUNDED" if indexes else "MODEL_KNOWLEDGE"),
            "citations": [{"index": i, "quote": by_index[i]["claim_text"]} for i in indexes]})
    return {"segments": segments, "clarifying_question": question}


def bind_source_quotes(payload: dict, references: list[dict]) -> tuple[dict, int]:
    """Quotes belong to the server's evidence store, never to model authority.

    The model selects an index. If it miscopies an excerpt, use the registered
    excerpt as the entailment check's input, discarding the model's invented text.
    Unknown indexes still fail closed; no source or trust level is manufactured.
    """
    by_index = {r["index"]: r for r in references}
    corrections = 0
    for segment in payload.get("segments", []):
        for citation in segment.get("citations", []):
            ref = by_index.get(citation.get("index"))
            if not ref or not ref.get("source_bound"):
                raise ValueError("unbound_citation")
            quote = str(citation.get("quote") or "")
            excerpt = str(ref.get("claim_text") or "")
            if len(quote.strip()) < 12 or quote not in excerpt:
                citation["quote"] = excerpt
                corrections += 1
    return payload, corrections


def audit_answer(claims: list[dict], references: list[dict]) -> dict:
    # Version scope is verified graph metadata, not an invented source quote.
    # Preserve the original excerpt in public provenance.
    audit_refs = []
    for ref in references:
        versions = [str(v.get("expression", "")) for fact in ref.get("kg_statements", [])
                    for v in fact.get("scope", {}).get("registered_scope", {}).get("version_constraints", [])
                    if v.get("status") == "exact"]
        versions += [str(v["expression"]) for fact in ref.get("kg_statements", [])
                     for v in [fact.get("scope", {}).get("qualifiers", {}).get("software_version", {})]
                     if v.get("status") == "exact"]
        audit_refs.append(dict(ref, claim_text=str(ref.get("claim_text", "")) + " " + " ".join(versions)))
    audits = []
    for claim in claims:
        if claim["knowledge_source"] in {"USER_CLARIFICATION", "CAUTION_CONTEXT"}:
            continue
        text = claim["text"]
        if claim["knowledge_source"] == "MODEL_KNOWLEDGE":
            text = "模型通识（尚未核验）\n" + text
        audits.append(audit_grounded_answer_v3(text, references=audit_refs, execution_request_count=0).model_dump(mode="json"))
    result = audit_grounded_answer_v3("", references=[], execution_request_count=0).model_dump(mode="json")
    for key in ("claims", "verified_claims", "unverified_model_knowledge_claims", "reasons", "invalid_citations", "cited_references"):
        result[key] = [value for audit in audits for value in audit.get(key, [])]
    result["passed"] = bool(claims) and all(a["passed"] for a in audits)
    result["unsupported_claim_count"] = sum(a["unsupported_claim_count"] for a in audits)
    result["governance_violation_count"] = sum(a["governance_violation_count"] for a in audits)
    result["semantic_claim_correctness"] = None
    result["contract"] = "exact_quote_and_structural_audit_not_semantic_verification"
    result["caution_context"] = [c for c in claims if c["knowledge_source"] == "CAUTION_CONTEXT"]
    return result


def retain_supported_segments(payload: dict, references: list[dict]) -> tuple[dict, int]:
    """Reject a faulty claim without replacing the whole answer with an FAQ."""
    kept = []
    for segment in payload["segments"]:
        try:
            _, claims = compile_answer({"segments": [segment]}, references)
        except ValueError:
            continue
        if audit_answer(claims, references)["passed"]:
            kept.append(segment)
    return dict(payload, segments=kept), len(payload["segments"]) - len(kept)


def decision_local_projection(answer: str, references: list[dict], claims=()) -> dict:
    used = {int(n) for n in re.findall(r"\[(\d+)\]", answer.split("### 参考资料")[0])}
    selected = [ref for ref in references if int(ref["index"]) in used]
    return {"schema_version": "answer-provenance-v1", "references": selected,
            "claims": list(claims),
            "kg_facts_used": [dict(fact, citation_index=ref["index"]) for ref in selected for fact in ref.get("kg_statements", [])],
            "caution_context_used": [dict(ref["caution_context"], citation_index=ref["index"]) for ref in selected if ref.get("caution_context")],
            "knowledge_sources": sorted({ref.get("knowledge_source", "RETRIEVAL_GROUNDED") for ref in selected}
                | {"MODEL_KNOWLEDGE" for claim in claims if claim.get("knowledge_source") == "MODEL_KNOWLEDGE"}),
            "scientific_kg_used": any(ref.get("kg_statements") for ref in selected),
            "semantic_support_verified": False}
