from __future__ import annotations

import re
from typing import Any

from core.open_world_evaluation_models import ClaimRecordV3, GroundedAnswerAuditV3


_UNVERIFIED_HEADINGS = (
    "模型通识（尚未核验）",
    "模型通识(尚未核验)",
    "unverified model knowledge",
)


def audit_grounded_answer_v3(
    content: str,
    *,
    references: list[dict[str, Any]],
    execution_request_count: int,
) -> GroundedAnswerAuditV3:
    by_index = {
        int(ref["index"]): ref
        for ref in references
        if ref.get("index") is not None
    }
    allowed = set(by_index)
    cited = {int(value) for value in re.findall(r"\[(\d+)\]", content)}
    invalid = sorted(cited - allowed)
    execution_claim = execution_request_count == 0 and _claims_execution(content)
    claims = _extract_claims(content, by_index=by_index)
    scientific = [claim for claim in claims if claim.claim_type != "non_scientific"]
    verified = [
        claim
        for claim in scientific
        if claim.authority in {"source_bound", "tool_contract"}
        and claim.governance_action in {"keep", "qualify"}
    ]
    unverified = [
        claim
        for claim in scientific
        if claim.authority == "model_knowledge_unverified"
    ]
    unsupported = [
        claim
        for claim in scientific
        if claim.governance_action in {"remove", "show_conflict"}
    ]
    mapped = [
        claim
        for claim in scientific
        if claim.citation_mapping in {"valid", "not_applicable"}
    ]
    precision = len(cited & allowed) / len(cited) if cited else (1.0 if not verified else 0.0)
    coverage = len(mapped) / len(scientific) if scientific else 1.0
    structural_rate = len(verified) / max(1, len(scientific) - len(unverified))
    violations = len(invalid) + int(execution_claim) + len(unsupported)
    passed = not invalid and not execution_claim and not unsupported
    reasons: list[str] = []
    if invalid:
        reasons.append("invalid_reference_index")
    if execution_claim:
        reasons.append("unsupported_execution_claim")
    if unsupported:
        reasons.append("unsupported_or_conflicting_scientific_claim")
    return GroundedAnswerAuditV3(
        passed=passed,
        claims=claims,
        verified_claims=verified,
        unverified_model_knowledge_claims=unverified,
        cited_references=sorted(cited),
        invalid_citations=invalid,
        citation_precision=round(precision, 6),
        citation_coverage=round(coverage, 6),
        structurally_supported_claim_rate=round(min(1.0, structural_rate), 6),
        semantic_claim_correctness=None,
        unsupported_claim_count=len(unsupported),
        execution_claim_violation=execution_claim,
        governance_violation_count=violations,
        reasons=reasons,
    )


def _extract_claims(
    content: str,
    *,
    by_index: dict[int, dict[str, Any]],
) -> list[ClaimRecordV3]:
    claims: list[ClaimRecordV3] = []
    unverified_section = False
    reference_section = False
    claim_index = 0
    for raw in content.splitlines():
        line = raw.strip()
        if not line:
            continue
        normalized_heading = line.strip("#* ：:").casefold()
        if any(heading.casefold() in normalized_heading for heading in _UNVERIFIED_HEADINGS):
            unverified_section = True
            reference_section = False
            continue
        if normalized_heading in {"已核验证据", "verified evidence", "参考资料", "references"}:
            unverified_section = False
            reference_section = normalized_heading in {"参考资料", "references"}
            continue
        if normalized_heading == "参考":
            unverified_section = False
            reference_section = True
            continue
        if reference_section:
            continue
        for segment in re.split(r"(?<=[。！？!?])\s+", line):
            clean = segment.strip(" -*\t")
            if not clean:
                continue
            claim_index += 1
            cited_indexes = [int(value) for value in re.findall(r"\[(\d+)\]", clean)]
            claim_text = re.sub(r"\[(\d+)\]", "", clean).strip()
            if line.startswith("#") or not _looks_scientific(claim_text):
                claims.append(
                    ClaimRecordV3(
                        claim_id=f"claim-{claim_index:03d}",
                        claim_text=claim_text,
                        claim_type="non_scientific",
                        citation_mapping="not_applicable",
                        governance_action="keep",
                    )
                )
                continue
            refs = [by_index[index] for index in cited_indexes if index in by_index]
            bound = [
                ref
                for ref in refs
                if ref.get("authority") in {"source_bound", "tool_contract"}
                and ref.get("source_bound", True)
            ]
            if unverified_section:
                claims.append(
                    ClaimRecordV3(
                        claim_id=f"claim-{claim_index:03d}",
                        claim_text=claim_text,
                        claim_type=_claim_type(claim_text),
                        authority="model_knowledge_unverified",
                        citation_mapping="invalid" if cited_indexes else "not_applicable",
                        governance_action="remove" if cited_indexes else "label_unverified",
                        reasons=(
                            ["unverified_model_knowledge_must_not_cite_governed_sources"]
                            if cited_indexes
                            else ["not_scientific_authority"]
                        ),
                    )
                )
                continue
            source_ids = [
                str(ref.get("source_span_id") or ref.get("source_id") or "")
                for ref in bound
                if ref.get("source_span_id") or ref.get("source_id")
            ]
            claim_kind = _claim_type(claim_text)
            typed_metadata_present = any(
                ref.get("claim_type") or ref.get("support_claim_types")
                for ref in bound
            )
            typed_bound = [
                ref
                for ref in bound
                if claim_kind in {
                    str(ref.get("claim_type") or ""),
                    *[str(value) for value in ref.get("support_claim_types") or []],
                }
            ]
            semantic_bound = (
                typed_bound
                if typed_metadata_present
                and claim_kind
                in {"input_requirement", "output", "failure_mode", "benchmark"}
                else bound
            )
            lexical = max(
                (
                    _overlap(claim_text, str(ref.get("claim_text") or ""))
                    for ref in semantic_bound
                ),
                default=0.0,
            )
            scope = _scope_match(claim_text, semantic_bound)
            numeric = _numeric_scope_match(claim_text, semantic_bound)
            if not cited_indexes or not bound:
                action = "remove"
                reasons = ["verified_scientific_claim_requires_source_bound_citation"]
                mapping = "missing" if not cited_indexes else "invalid"
                authority = "none"
            elif typed_metadata_present and not semantic_bound:
                action = "remove"
                reasons = ["citation_claim_type_mismatch"]
                mapping = "valid"
                authority = "source_bound"
            elif scope == "mismatch" or numeric == "mismatch":
                action = "remove"
                reasons = ["citation_scope_mismatch"]
                mapping = "valid"
                authority = "source_bound"
            else:
                action = "keep" if lexical >= 0.08 or scope == "match" else "qualify"
                reasons = [] if action == "keep" else ["lexical_support_is_weak_semantic_review_not_run"]
                mapping = "valid"
                authority = "source_bound"
            claims.append(
                ClaimRecordV3(
                    claim_id=f"claim-{claim_index:03d}",
                    claim_text=claim_text,
                    claim_type=claim_kind,
                    source_span_ids=source_ids,
                    authority=authority,
                    lexical_support=round(lexical, 6),
                    citation_mapping=mapping,
                    scope_match=scope,
                    numeric_scope_match=numeric,
                    semantic_review_status="not_run",
                    governance_action=action,
                    reasons=reasons,
                )
            )
    return claims


def _scope_match(claim: str, refs: list[dict[str, Any]]) -> str:
    claim_tools = _tool_tokens(claim)
    ref_tools = {
        str(ref.get("tool_name") or "").casefold()
        for ref in refs
        if ref.get("tool_name")
    }
    if not claim_tools:
        return "unknown"
    return "match" if claim_tools & ref_tools else "mismatch"


def _numeric_scope_match(claim: str, refs: list[dict[str, Any]]) -> str:
    normalized_claim = re.sub(r"^\s*\d+[.)]\s*", "", claim)
    numbers = set(re.findall(r"(?<!\w)\d+(?:\.\d+)?%?(?!\w)", normalized_claim))
    metric_markers = {
        marker
        for marker in ("auprc", "auroc", "f1", "rank", "排名", "top")
        if marker in normalized_claim.casefold()
    }
    if not numbers and not metric_markers:
        return "not_applicable"
    source = " ".join(str(ref.get("claim_text") or "") for ref in refs).casefold()
    if numbers and not numbers.issubset(set(re.findall(r"(?<!\w)\d+(?:\.\d+)?%?(?!\w)", source))):
        return "mismatch"
    if metric_markers and not all(marker in source for marker in metric_markers):
        return "mismatch"
    return "match"


def _tool_tokens(value: str) -> set[str]:
    text = value.casefold()
    names = ("scrublet", "scdblfinder", "doubletfinder", "harmony", "scanorama", "celltypist", "singler")
    return {name for name in names if re.search(rf"\b{re.escape(name)}\b", text)}


def _claim_type(value: str) -> str:
    text = value.casefold()
    if any(token in text for token in ("auprc", "auroc", "f1", "rank", "benchmark", "排名")):
        return "benchmark"
    if any(token in text for token in ("input", "raw count", "输入", "matrix")):
        return "input_requirement"
    if any(token in text for token in ("output", "输出", "embedding", "score")):
        return "output"
    if any(token in text for token in ("limit", "caveat", "限制", "失败")):
        return "failure_mode"
    return "scientific"


def _looks_scientific(value: str) -> bool:
    text = value.casefold()
    markers = (
        "single-cell", "scrna", "anndata", "h5ad", "scrublet", "scdblfinder",
        "doubletfinder", "harmony", "scanorama", "celltypist", "singler",
        "doublet", "batch", "matrix", "embedding", "umi", "细胞", "矩阵",
        "表达", "批次", "算法", "输入", "输出", "限制", "阈值",
    )
    return any(marker in text for marker in markers)


def _overlap(left: str, right: str) -> float:
    left_tokens = _tokens(left)
    right_tokens = _tokens(right)
    return len(left_tokens & right_tokens) / len(left_tokens) if left_tokens else 0.0


def _tokens(value: str) -> set[str]:
    normalized = re.sub(r"\s+", " ", value.casefold())
    words = set(re.findall(r"[a-z0-9_.-]{3,}", normalized))
    chinese = "".join(re.findall(r"[\u4e00-\u9fff]", normalized))
    return words | {chinese[i : i + 2] for i in range(max(0, len(chinese) - 1))}


def _claims_execution(content: str) -> bool:
    text = content.casefold()
    return any(
        marker in text
        for marker in (
            "我已经运行", "已经执行成功", "本次执行成功", "已完成运行",
            "actually executed", "execution succeeded",
        )
    )
