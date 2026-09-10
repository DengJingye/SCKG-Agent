from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable, Optional, Sequence


@dataclass(frozen=True)
class ClaimRequest:
    """One clause-scoped scientific claim requested by the user."""

    subject: Optional[str]
    predicate: str
    object_constraint: Optional[str]
    query_span: str
    mode: str
    ambiguous: bool = False


@dataclass(frozen=True)
class EvidenceReference:
    """One immutable, source-bound evidence unit supporting an atomic claim."""

    evidence_span_id: str
    source_id: str
    source_span: str
    title: str
    bounded_excerpt: str
    metadata_claim_type: str


@dataclass(frozen=True)
class ClaimEvidenceBinding:
    """Atomic Claim -> Evidence -> Citation provenance used by EVIDENCE_QA."""

    request: ClaimRequest
    claim_text: str
    evidence_refs: tuple[EvidenceReference, ...]
    source_refs: tuple[str, ...]
    support_status: str
    support_type: str
    support_quality: int
    abstain_reason: Optional[str] = None


_PREDICATE_MARKERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "limitation",
        (
            "caveat",
            "limitation",
            "failure mode",
            "limitations",
            "限制",
            "局限",
            "失败模式",
            "注意事项",
        ),
    ),
    ("parameter", ("parameter", "threshold", "default", "参数", "阈值", "默认值")),
    (
        "input_requirement",
        (
            "input",
            "raw count",
            "raw umi",
            "data state",
            "输入",
            "矩阵",
            "需要什么数据",
            "归一化矩阵",
        ),
    ),
    (
        "output",
        (
            "output",
            "artifact",
            "return",
            "produce",
            "输出",
            "返回",
            "结果字段",
            "放在哪里",
            "存在哪里",
            "obsm",
        ),
    ),
    ("metric", ("metric", "precision", "recall", "f1", "指标", "评估指标")),
    ("benchmark_result", ("benchmark", "ranked", "ranking", "排名", "基准评测")),
    (
        "mechanism",
        ("mechanism", "principle", "how does", "how it works", "原理", "机制", "为什么"),
    ),
    (
        "method_type",
        (
            "method type",
            "type of method",
            "supported task",
            "designed for",
            "方法类型",
            "是什么方法",
            "支持的任务",
            "适用任务",
            "用于什么",
        ),
    ),
)

_PREDICATE_PATTERNS: dict[str, tuple[str, ...]] = {
    "input_requirement": (
        r"\binputs?\b.{0,100}\b(?:comprise|include|consist|accept|require)",
        r"\b(?:accepts?|requires?)\b.{0,140}\b(?:input|data|matri(?:x|ces)|counts?|expression|anndata|files?)\b",
        r"\b(?:takes?|uses?|consumes?|expects?)\b.{0,140}\b(?:input|data|matri(?:x|ces)|counts?|expression|anndata|files?)\b",
        r"\b(?:input|data|matri(?:x|ces)|counts?|expression|anndata|files?)\b.{0,120}\b(?:is|are)\s+required\b",
        r"\bgiven\b.{0,180}\b(?:data|matri(?:x|ces)|counts?|expression|anndata|files?)\b",
        r"\bstarting with\b.{0,120}\b(?:counts?|matrix|expression|anndata|data)\b",
        r"\bfile formats?\b.{0,180}\b(?:rows?|columns?|cells?|genes?|matrix)\b",
        r"\b(?:cells?|genes?)\b.{0,50}\b(?:rows?|columns?)\b",
        r"\b(?:log1p|logarithmi[sz]ed|normali[sz]ed|raw counts?|raw umi)\b.{0,140}\b(?:matrix|expression|anndata|input|data)\b",
    ),
    "output": (
        r"\b(?:will\s+)?output\b.{0,140}\b(?:matrix|coordinates?|embedding|labels?|scores?|artifact|entry|states?|probabilities|maps?)\b",
        r"\boutputs?\b.{0,90}\b(?:are|include|comprise|consist(?:s)?\s+of)\b.{0,200}\b(?:states?|probabilities|maps?|trends?|genes?|matrix|coordinates?|embedding|labels?|scores?|artifacts?|results?)\b",
        r"\b(?:returns?|returned|produces?)\b.{0,140}\b(?:matrix|coordinates?|embedding|labels?|scores?|artifact|result|states?|probabilities|maps?)\b",
        r"\b(?:provides?|generates?|creates?|yields?)\b.{0,140}\b(?:representation|coordinates?|matrix|embedding|labels?|scores?|artifact|data|result)\b",
        r"\b(?:stored in|adds? an entry)\b.{0,140}\b(?:obsm|matrix|coordinates?|embedding|labels?|scores?)\b",
        r"\b(?:aims?|objective|goal)\b.{0,110}\b(?:detect|define|assign|infer|identify|estimate|compute)\w*\b.{0,200}\b(?:states?|probabilities|maps?|trajectories|coordinates?|embedding|labels?|artifacts?|results?)\b",
        r"\b(?:detects?|defines?|assigns?|infers?|identifies?|estimates?|computes?)\b.{0,160}\b(?:states?|probabilities|maps?|trajectories|coordinates?|embedding|labels?|artifacts?|results?)\b",
    ),
    "parameter": (
        r"\bparameters?\b.{0,140}\b(?:optimized|clamped|set to|value|default|threshold|range|\d)",
        r"\b(?:resolution|max_epochs|epochs?|warmup|early.stopping|batch.size|minibatch|threshold|theta|lambda|k)\b.{0,110}\b(?:set to|increased|decreased|enabled|disabled|default|range|\d)",
        r"\b(?:by default|default value)\b.{0,110}\b(?:true|false|enabled|disabled|\d)",
    ),
    "limitation": (
        r"\b(?:limitation|caveat|warning|failure mode|drawback)\b",
        r"\b(?:may perform poorly|not universally|should not|only within|overcorrect|over-correct|fails? when|sensitive to)\b",
        r"\b(?:assumes?|not true|difficult problem|cannot|does not)\b",
    ),
    "benchmark_result": (
        r"\b(?:benchmark|evaluated|performance|ranked)\b.{0,140}\b(?:dataset|method|tool|metric|result|performance|rank)\b",
    ),
    "metric": (
        r"\b(?:precision|recall|f1(?:[- ]score)?|auprc|auroc|silhouette|ilisi|clisi|kbet)\b",
        r"\b(?:evaluation|performance)\s+metrics?\b",
    ),
    "mechanism": (
        r"\b(?:method|algorithm|framework|model)\b.{0,150}\b(?:for|performs?|integrat|correct|classif|infer|simulate|model|learn)\w*\b",
        r"\b(?:uses?|applies?|learns?|models?|integrates?|corrects?|simulates?)\b.{0,160}\b(?:data|matrix|neighbors?|embedding|batch|distribution|classifier|model)\b",
    ),
    "method_type": (
        r"\b(?:method|algorithm|framework|model|tool)\b.{0,150}\b(?:for|performs?|integrat|correct|classif|infer|simulate|annotat|predict|map|deconvol)\w*\b",
        r"\b(?:tool|method|algorithm|framework|model)\b.{0,140}\b(?:for|to|that|which)\b.{0,180}\b(?:annotat|classif|correlat|integrat|correct|infer|detect|predict|map|deconvol)\w*\b",
        r"\b(?:developed|introduced|presented)\b.{0,120}\b(?:tool|method|algorithm|framework|model)\b.{0,200}\b(?:annotat|classif|correlat|integrat|correct|infer|detect|predict|map|deconvol)\w*\b",
        r"\b(?:designed|developed)\b.{0,140}\b(?:for|to)\b",
        r"\b(?:enables?|supports?)\b.{0,170}\b(?:annotat|classif|integrat|correct|infer|detect|predict|map|deconvol)\w*\b",
    ),
}

_OBJECT_MARKERS: tuple[str, ...] = (
    "raw umi",
    "raw count",
    "raw counts",
    "log-normalized",
    "log normalized",
    "normalized",
    "scaled",
    "anndata",
    "spliced",
    "unspliced",
    "obsm",
    "x_scanorama",
    "embedding",
    "coordinates",
    "probabilities",
    "labels",
)

_NOISE_MARKERS: tuple[str, ...] = (
    "supplementary figure",
    "figure caption",
    "benchmark",
    "marker genes",
    "marker expression",
)

_SCIENTIFIC_CAPABILITY_MARKERS: tuple[str, ...] = (
    "annotat",
    "classif",
    "integrat",
    "batch correct",
    "infer",
    "predict",
    "trajectory",
    "velocity",
    "doublet",
    "deconvol",
    "cluster",
    "dimension",
    "transcriptom",
    "single-cell",
    "single cell",
    "scRNA",
    "omics",
    "cell type",
    "gene expression",
)

_TASK_OBJECT_STOPWORDS: frozenset[str] = frozenset(
    {
        "about",
        "and",
        "based",
        "find",
        "for",
        "information",
        "method",
        "methods",
        "source",
        "supported",
        "task",
        "the",
        "tool",
        "tools",
        "with",
    }
)


def claim_requests_for_query(
    query: str,
    *,
    subjects: Iterable[str],
    snippets: Sequence[dict[str, Any]],
) -> list[ClaimRequest]:
    """Parse conservative clause-local requests, then resolve entityless discovery."""

    entities = _unique_nonempty(subjects)
    if not entities:
        return _entityless_claim_requests(query, snippets)
    text = _latest_query(query)
    clauses = _claim_scope_clauses(text, entities)
    requests: list[ClaimRequest] = []
    scoped_entities: set[str] = set()
    for clause in clauses:
        clause_entities = [entity for entity in entities if _mentions(clause, entity)]
        if not clause_entities:
            continue
        predicate_text = _mask_entities(clause, entities)
        predicates = _semantic_predicates(predicate_text)
        explicit_predicates = _explicit_semantic_predicates(predicate_text)
        object_constraint = _object_constraint(predicate_text)
        if len(clause_entities) > 1 and not _shared_scope_is_clear(clause, explicit_predicates):
            requests.extend(
                ClaimRequest(
                    subject=entity,
                    predicate=predicates[0] if len(predicates) == 1 else "unspecified",
                    object_constraint=object_constraint,
                    query_span=_bounded_text(clause, 300),
                    mode="clause_local",
                    ambiguous=True,
                )
                for entity in clause_entities
            )
        else:
            requests.extend(
                ClaimRequest(
                    subject=entity,
                    predicate=predicate,
                    object_constraint=object_constraint,
                    query_span=_bounded_text(clause, 300),
                    mode="shared_predicate" if len(clause_entities) > 1 else "clause_local",
                    ambiguous=False,
                )
                for entity in clause_entities
                for predicate in predicates
            )
        scoped_entities.update(entity.casefold() for entity in clause_entities)

    if not requests:
        predicate_text = _mask_entities(text, entities)
        predicates = _semantic_predicates(predicate_text)
        object_constraint = _object_constraint(predicate_text)
        if len(entities) == 1 or _shared_scope_is_clear(text, predicates):
            requests.extend(
                ClaimRequest(
                    subject=entity,
                    predicate=predicate,
                    object_constraint=object_constraint,
                    query_span=_bounded_text(text, 300),
                    mode="shared_predicate" if len(entities) > 1 else "single_entity",
                )
                for entity in entities
                for predicate in predicates
            )
        else:
            requests.extend(
                ClaimRequest(
                    subject=entity,
                    predicate=predicates[0] if len(predicates) == 1 else "unspecified",
                    object_constraint=object_constraint,
                    query_span=_bounded_text(text, 300),
                    mode="ambiguous_scope",
                    ambiguous=True,
                )
                for entity in entities
            )
    elif scoped_entities:
        requests.extend(
            ClaimRequest(
                subject=entity,
                predicate="unspecified",
                object_constraint=None,
                query_span=_bounded_text(text, 300),
                mode="ambiguous_scope",
                ambiguous=True,
            )
            for entity in entities
            if entity.casefold() not in scoped_entities
        )
    return _deduplicate_requests(requests)


def recommendation_claim_requests(
    query: str,
    *,
    subject: Optional[str],
) -> list[ClaimRequest]:
    """Build the bounded scientific support requested by a recommendation.

    Recommendation rank and project qualification are governance decisions, not
    literature claims.  Only the primary candidate's scientific purpose, input
    contract, and limitations are projected into atomic evidence requests.
    """

    normalized_subject = str(subject or "").strip()
    if not normalized_subject:
        return []
    query_span = _bounded_text(_latest_query(query), 300)
    return [
        ClaimRequest(
            subject=normalized_subject,
            predicate=predicate,
            object_constraint=None,
            query_span=query_span,
            mode="recommendation_support",
        )
        for predicate in ("method_type", "input_requirement", "limitation")
    ]


def bind_claim_evidence(
    requests: Iterable[ClaimRequest],
    snippets: Sequence[dict[str, Any]],
    *,
    query: str,
) -> list[ClaimEvidenceBinding]:
    """Bind every atomic request only to directly supporting source-bound evidence."""

    bindings: list[ClaimEvidenceBinding] = []
    for request in requests:
        if request.ambiguous or request.predicate == "unspecified":
            bindings.append(_abstain(request, "ambiguous_target"))
            continue
        entity_rows = [
            row
            for row in snippets
            if _is_source_bound(row) and _entity_compatible(row, request.subject)
        ]
        if not entity_rows:
            bindings.append(_abstain(request, "no_candidate"))
            continue
        supported: list[tuple[dict[str, Any], str, str, int]] = []
        for row in entity_rows:
            excerpt, claim_text, quality = _supporting_proposition(row, request)
            if claim_text:
                supported.append((row, excerpt, claim_text, quality))
        if not supported:
            bindings.append(_abstain(request, "no_direct_support"))
            continue
        if _support_conflicts(supported, request.predicate):
            bindings.append(_abstain(request, "conflicting_support"))
            continue
        row, excerpt, claim_text, quality = max(
            supported,
            key=lambda item: _binding_rank(
                item[0], request=request, support_quality=item[3], claim_text=item[2], query=query
            ),
        )
        source_id = str(row.get("source_id") or "")
        evidence = EvidenceReference(
            evidence_span_id=str(
                row.get("chunk_id") or f"{source_id}:{row.get('source_span')}"
            ),
            source_id=source_id,
            source_span=str(row.get("source_span") or ""),
            title=str(row.get("title") or source_id or "Source"),
            bounded_excerpt=excerpt,
            metadata_claim_type=str(row.get("claim_type") or "general"),
        )
        bindings.append(
            ClaimEvidenceBinding(
                request=request,
                claim_text=claim_text,
                evidence_refs=(evidence,),
                source_refs=(source_id,),
                support_status="supported",
                support_type=(
                    "direct_excerpt_metadata_confirmed"
                    if _metadata_compatible(evidence.metadata_claim_type, request.predicate)
                    else "direct_excerpt"
                ),
                support_quality=quality,
            )
        )
    return bindings


def references_from_bindings(
    bindings: Iterable[ClaimEvidenceBinding],
) -> list[dict[str, Any]]:
    """Project public reference rows from bindings without borrowing citations."""

    rows: list[dict[str, Any]] = []
    by_evidence_id: dict[str, dict[str, Any]] = {}
    for binding in bindings:
        if binding.support_status != "supported":
            continue
        for evidence in binding.evidence_refs:
            row = by_evidence_id.get(evidence.evidence_span_id)
            if row is None:
                row = {
                    "index": len(rows) + 1,
                    "tool_name": binding.request.subject or "Source",
                    "title": evidence.title,
                    "source_id": evidence.source_id,
                    "source_span": evidence.source_span,
                    "source_span_id": evidence.evidence_span_id,
                    "claim_text": evidence.bounded_excerpt,
                    "claim_type": evidence.metadata_claim_type,
                    "support_claim_types": [],
                    "selected_for_claim_types": [],
                    "source_bound": True,
                    "authority": "source_bound",
                }
                rows.append(row)
                by_evidence_id[evidence.evidence_span_id] = row
            legacy_type = legacy_claim_type(binding.request.predicate)
            if legacy_type not in row["support_claim_types"]:
                row["support_claim_types"].append(legacy_type)
            if legacy_type not in row["selected_for_claim_types"]:
                row["selected_for_claim_types"].append(legacy_type)
    return rows


def render_grounded_answer(
    bindings: Sequence[ClaimEvidenceBinding],
    references: Sequence[dict[str, Any]],
    *,
    task_label: str,
    blockers: Iterable[str] = (),
) -> str:
    """Render only binding-backed claims or explicit abstentions."""

    if not bindings:
        return (
            f"我识别到任务为 **{task_label}**，但没有解析出可安全核验的原子科学 claim。"
            "我不会用目录元数据或静态算法卡补造结论。"
        )
    reference_by_id = {
        str(row.get("source_span_id") or ""): row
        for row in references
        if row.get("source_span_id")
    }
    rendered: list[tuple[ClaimEvidenceBinding, str]] = []
    for binding in bindings:
        citations = "".join(
            f"[{reference_by_id[evidence.evidence_span_id]['index']}]"
            for evidence in binding.evidence_refs
            if evidence.evidence_span_id in reference_by_id
        )
        rendered.append((binding, citations))

    if len(rendered) == 1:
        binding, citations = rendered[0]
        subject = binding.request.subject or "该候选方法"
        if binding.support_status == "supported" and citations:
            lines = [
                f"**直接结论：{subject} 的{predicate_label(binding.request.predicate)}是：** "
                f"{binding.claim_text}{citations}"
            ]
        else:
            lines = [binding.claim_text]
    else:
        lines = [f"**{task_label}：直接回答**"]
        for binding, citations in rendered:
            subject = binding.request.subject or "未解析实体"
            label = predicate_label(binding.request.predicate)
            if binding.support_status == "supported" and citations:
                lines.append(f"- **{subject} · {label}**：{binding.claim_text}{citations}")
            else:
                lines.append(f"- **{subject} · {label}**：{binding.claim_text}")
    material_blockers = [
        value
        for value in blockers
        if value != "dense_model_pack_not_installed_using_kg_bm25"
    ]
    if material_blockers:
        lines.append(f"- **证据边界：** `{', '.join(material_blockers[:3])}`。")
    if references:
        lines.extend(["", "### 参考资料"])
        for row in references:
            lines.append(
                f"[{row['index']}] {row['tool_name']} · {row['title']} · {row['source_span']}"
            )
    return "\n".join(lines)


def render_grounded_recommendation(
    bindings: Sequence[ClaimEvidenceBinding],
    references: Sequence[dict[str, Any]],
    *,
    primary_subject: str,
    qualification: str,
) -> str:
    """Render recommendation facts only from their own supported bindings.

    Candidate order, project qualification, and procedural next steps remain
    explicitly separate from scientific evidence.  Abstained bindings are not
    converted into static facts and never borrow another binding's citation.
    """

    reference_by_id = {
        str(row.get("source_span_id") or ""): row
        for row in references
        if row.get("source_span_id")
    }
    supported = [
        binding
        for binding in bindings
        if binding.support_status == "supported" and binding.evidence_refs
    ]
    lines = [f"### 项目治理建议：优先评估 {primary_subject}"]
    if supported:
        lines.extend(["", "### 已核验科学依据"])
        emitted: set[tuple[str, tuple[str, ...]]] = set()
        for binding in supported:
            evidence_ids = tuple(
                evidence.evidence_span_id for evidence in binding.evidence_refs
            )
            key = (binding.claim_text, evidence_ids)
            if key in emitted:
                continue
            emitted.add(key)
            citations = "".join(
                f"[{reference_by_id[evidence_id]['index']}]"
                for evidence_id in evidence_ids
                if evidence_id in reference_by_id
            )
            if not citations:
                continue
            lines.append(
                f"- **{binding.request.subject} · "
                f"{predicate_label(binding.request.predicate)}：** "
                f"{binding.claim_text}{citations}"
            )
    else:
        lines.extend(
            [
                "",
                "当前没有足够的 source-bound 直接依据，因此不输出事实性科学说明。",
            ]
        )

    abstained_count = sum(
        binding.support_status != "supported" for binding in bindings
    )
    if abstained_count:
        lines.append(
            f"证据缺口：{abstained_count} 项候选事实缺少 direct support，已从回答中省略。"
        )

    lines.extend(
        [
            "",
            "### 项目治理资格",
            f"- 状态：{qualification}。这是项目内资格边界，不代表跨数据集科学优越性。",
            "",
            "### 建议步骤",
            "1. 先完成 DataProfile 与合同核对。",
            "2. 在同一条件下做小规模对照，并由人工复核后再确定方案。",
        ]
    )
    if references:
        lines.extend(["", "### 参考资料"])
        for row in references:
            lines.append(
                f"[{row['index']}] {row['tool_name']} · {row['title']} · {row['source_span']}"
            )
    return "\n".join(lines)


def reasoner_binding_projection(
    bindings: Sequence[ClaimEvidenceBinding],
    references: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Expose only pre-bound claims to an optional prose reasoner."""

    by_id = {str(row.get("source_span_id") or ""): row for row in references}
    values: list[dict[str, Any]] = []
    for binding in bindings:
        citation_indexes = [
            int(by_id[evidence.evidence_span_id]["index"])
            for evidence in binding.evidence_refs
            if evidence.evidence_span_id in by_id
        ]
        values.append(
            {
                "entity": binding.request.subject or "",
                "predicate": binding.request.predicate,
                "claim_text": binding.claim_text,
                "evidence_span_ids": [item.evidence_span_id for item in binding.evidence_refs],
                "source_ids": list(binding.source_refs),
                "citation_indexes": citation_indexes,
                "support_status": binding.support_status,
                "support_type": binding.support_type,
                "abstain_reason": binding.abstain_reason or "",
                "authority": "source_bound" if citation_indexes else "none",
            }
        )
    return values


def external_answer_preserves_bindings(
    content: str,
    bindings: Sequence[ClaimEvidenceBinding],
    references: Sequence[dict[str, Any]],
) -> bool:
    """Accept prose only when every scientific claim keeps its fixed citation."""

    normalized = " ".join(str(content).split())
    by_id = {str(row.get("source_span_id") or ""): row for row in references}
    allowed_citations: set[int] = set()
    for binding in bindings:
        if binding.support_status != "supported":
            continue
        indexes = [
            int(by_id[evidence.evidence_span_id]["index"])
            for evidence in binding.evidence_refs
            if evidence.evidence_span_id in by_id
        ]
        if not indexes:
            return False
        allowed_citations.update(indexes)
        exact = f"{' '.join(binding.claim_text.split())}{''.join(f'[{value}]' for value in indexes)}"
        if exact not in normalized:
            return False
    cited = {int(value) for value in re.findall(r"\[(\d+)\]", normalized)}
    return cited == allowed_citations


def legacy_claim_type(predicate: str) -> str:
    return {
        "limitation": "failure_mode",
        "benchmark_result": "benchmark",
        "method_type": "general",
        "mechanism": "general",
        "unspecified": "general",
    }.get(predicate, predicate)


def predicate_label(predicate: str) -> str:
    return {
        "input_requirement": "输入要求",
        "output": "输出",
        "limitation": "主要限制",
        "parameter": "参数依据",
        "metric": "评估指标依据",
        "benchmark_result": "评测结果",
        "mechanism": "核心原理",
        "method_type": "方法类型",
        "unspecified": "请求范围",
    }.get(predicate, "科学结论")


def _entityless_claim_requests(
    query: str,
    snippets: Sequence[dict[str, Any]],
) -> list[ClaimRequest]:
    text = _latest_query(query)
    predicates = _semantic_predicates(text)
    constraint = _object_constraint(text) or _task_object_constraint(text, predicates)
    requests: list[ClaimRequest] = []
    seen: set[tuple[str, str]] = set()
    for row in snippets:
        subject = str(row.get("tool_name") or "").strip()
        if not subject or not _is_source_bound(row):
            continue
        for predicate in predicates:
            request = ClaimRequest(
                subject=subject,
                predicate=predicate,
                object_constraint=constraint,
                query_span=_bounded_text(text, 300),
                mode="entityless_discovery",
            )
            if not _supporting_proposition(row, request)[1]:
                continue
            key = (subject.casefold(), predicate)
            if key in seen:
                continue
            seen.add(key)
            requests.append(request)
            if len(requests) >= 5:
                return requests
    return requests


def _supporting_proposition(
    snippet: dict[str, Any],
    request: ClaimRequest,
) -> tuple[str, str, int]:
    evidence = _bounded_text(str(snippet.get("claim_span") or ""), 900)
    if not evidence:
        return "", "", 0
    patterns = _PREDICATE_PATTERNS.get(request.predicate, ())
    if not patterns:
        return "", "", 0
    sentences = _sentences(evidence)
    candidates: list[tuple[str, int]] = []
    primary_entity = str(snippet.get("tool_name") or "").casefold()
    secondary_entity = bool(
        request.subject and request.subject.casefold() != primary_entity
    )
    for index, sentence in enumerate(sentences):
        proposition = sentence
        lowered = proposition.casefold()
        if request.predicate == "limitation":
            if (
                re.search(r"\bassumes?\b", lowered)
                and index + 1 < len(sentences)
                and re.match(
                    r"^(?:this|that|these|those)\b",
                    sentences[index + 1].casefold(),
                )
            ):
                proposition = f"{proposition} {sentences[index + 1]}"
                lowered = proposition.casefold()
            elif (
                re.match(r"^(?:this|that|these|those)\b", lowered)
                and index > 0
                and re.search(r"\bassumes?\b", sentences[index - 1].casefold())
            ):
                proposition = f"{sentences[index - 1]} {proposition}"
                lowered = proposition.casefold()
        matches = (
            ["method_type_relation"]
            if request.predicate == "method_type"
            and _supports_method_type(proposition, request.subject)
            else [pattern for pattern in patterns if re.search(pattern, lowered)]
            if request.predicate != "method_type"
            else []
        )
        if not matches:
            continue
        if (
            request.predicate == "method_type"
            and not _mentions(proposition, request.subject or "")
        ):
            continue
        if secondary_entity and not _mentions(proposition, request.subject or ""):
            continue
        if request.object_constraint and not _satisfies_object_constraint(
            proposition, request.object_constraint
        ):
            continue
        candidates.append((proposition, len(matches)))
    if not candidates:
        return "", "", 0
    proposition, quality = max(candidates, key=lambda item: (item[1], -len(item[0])))
    claim_text = _bounded_text(proposition.strip(" -*#>\t"), 240)
    excerpt = _bounded_text(proposition, 300)
    return excerpt, claim_text, quality


def _entity_compatible(snippet: dict[str, Any], subject: Optional[str]) -> bool:
    if not subject:
        return False
    if str(snippet.get("tool_name") or "").casefold() == subject.casefold():
        return True
    # Secondary mentions are claim-local only. They never mutate retrieval hits.
    return _mentions(str(snippet.get("claim_span") or ""), subject)


def _is_source_bound(snippet: dict[str, Any]) -> bool:
    return bool(
        snippet.get("source_bound")
        and str(snippet.get("source_id") or "").strip()
        and str(snippet.get("source_span") or "").strip()
        and str(snippet.get("chunk_id") or "").strip()
    )


def _binding_rank(
    snippet: dict[str, Any],
    *,
    request: ClaimRequest,
    support_quality: int,
    claim_text: str,
    query: str,
) -> tuple[int, int, int, int, float]:
    metadata = int(
        _metadata_compatible(str(snippet.get("claim_type") or ""), request.predicate)
    )
    noise = sum(marker in (str(snippet.get("title") or "") + " " + claim_text).casefold() for marker in _NOISE_MARKERS)
    overlap = _query_overlap(claim_text, query)
    return (
        metadata,
        support_quality,
        -noise,
        overlap,
        min(float(snippet.get("relevance_score") or 0.0), 3.0),
    )


def _metadata_compatible(metadata: str, predicate: str) -> bool:
    if metadata == legacy_claim_type(predicate):
        return True
    return predicate in {"method_type", "mechanism"} and metadata in {
        "general",
        "mechanism",
        "workflow",
    }


def _support_conflicts(
    candidates: Sequence[tuple[dict[str, Any], str, str, int]], predicate: str
) -> bool:
    if predicate != "input_requirement" or len(candidates) < 2:
        return False
    values = [item[2].casefold() for item in candidates]
    raw_only = any(
        any(marker in value for marker in ("requires raw", "raw counts only", "must be raw"))
        for value in values
    )
    processed_allowed = any(
        any(marker in value for marker in ("accepts normalized", "accepts log-normalized", "accepts scaled"))
        for value in values
    )
    return raw_only and processed_allowed


def _abstain(request: ClaimRequest, reason: str) -> ClaimEvidenceBinding:
    subject = request.subject or "未解析实体"
    return ClaimEvidenceBinding(
        request=request,
        claim_text=f"缺少 source-bound 直接证据，无法核验 {subject} 的{predicate_label(request.predicate)}。",
        evidence_refs=(),
        source_refs=(),
        support_status="abstained",
        support_type="none",
        support_quality=0,
        abstain_reason=reason,
    )


def _claim_scope_clauses(text: str, entities: Sequence[str]) -> list[str]:
    clauses: list[str] = []
    for coarse in re.split(r"[;；。!?！？]+", text):
        coarse = coarse.strip()
        if not coarse:
            continue
        parts = [
            value.strip()
            for value in re.split(
                r"\s+(?:and|versus|vs)\s+|[，,]|以及|和|与",
                coarse,
                flags=re.IGNORECASE,
            )
            if value.strip()
        ]
        independently_scoped = len(parts) > 1 and all(
            any(_mentions(part, entity) for entity in entities)
            and bool(_explicit_semantic_predicates(_mask_entities(part, entities)))
            for part in parts
        )
        clauses.extend(parts if independently_scoped else [coarse])
    return clauses


def _shared_scope_is_clear(text: str, predicates: Sequence[str]) -> bool:
    lowered = text.casefold()
    if len(set(predicates)) != 1:
        return False
    return any(
        marker in lowered
        for marker in (
            " and ",
            " both ",
            " each ",
            " respectively",
            "分别",
            "各自",
            "两者",
            "以及",
            "和",
            "与",
            "都",
        )
    )


def _semantic_predicates(text: str) -> list[str]:
    return _explicit_semantic_predicates(text) or ["method_type"]


def _explicit_semantic_predicates(text: str) -> list[str]:
    lowered = text.casefold()
    located: list[tuple[int, int, str]] = []
    for order, (predicate, markers) in enumerate(_PREDICATE_MARKERS):
        positions = [lowered.find(marker) for marker in markers if marker in lowered]
        if positions:
            located.append((min(positions), order, predicate))
    return [value for _, _, value in sorted(located)]


def _object_constraint(text: str) -> Optional[str]:
    lowered = text.casefold()
    values = [marker for marker in _OBJECT_MARKERS if marker in lowered]
    if not values:
        return None
    # Prefer the most specific phrase and keep one deterministic hard constraint.
    return max(values, key=lambda value: (len(value), -lowered.find(value)))


def _task_object_constraint(
    text: str,
    predicates: Sequence[str],
) -> Optional[str]:
    if "method_type" not in predicates:
        return None
    tokens = [
        token
        for token in _normalized_semantic_tokens(text)
        if token not in _TASK_OBJECT_STOPWORDS
    ]
    if not tokens:
        return None
    return "task:" + " ".join(dict.fromkeys(tokens))


def _satisfies_object_constraint(text: str, constraint: str) -> bool:
    lowered = text.casefold()
    normalized = constraint.casefold()
    if normalized.startswith("task:"):
        required = set(_normalized_semantic_tokens(normalized.removeprefix("task:")))
        observed = set(_normalized_semantic_tokens(lowered))
        if not required:
            return False
        action_tokens = {
            "annotat",
            "classif",
            "integrat",
            "infer",
            "predict",
            "trajectory",
            "velocity",
            "doublet",
            "deconvol",
            "cluster",
        }
        required_actions = required & action_tokens
        if required_actions and not required_actions.intersection(observed):
            return False
        if "reference" in required and "reference" not in observed:
            return False
        minimum_overlap = max(2, (len(required) + 1) // 2)
        return len(required.intersection(observed)) >= minimum_overlap
    aliases = {
        "raw count": ("raw count", "raw umi", "count matrix"),
        "raw counts": ("raw counts", "raw umi", "count matrix"),
        "raw umi": ("raw umi", "raw count", "count matrix"),
        "log-normalized": ("log-normalized", "log normalized", "normalized"),
        "log normalized": ("log normalized", "log-normalized", "normalized"),
        "coordinates": ("coordinates", "embedding"),
        "embedding": ("embedding", "coordinates", "representation"),
    }
    return any(value in lowered for value in aliases.get(normalized, (normalized,)))


def _supports_method_type(sentence: str, subject: Optional[str]) -> bool:
    """Require a local subject -> scientific purpose/task proposition."""

    if not subject or not _mentions(sentence, subject):
        return False
    lowered = sentence.casefold()
    escaped = re.escape(subject.casefold())
    subject_then_relation = (
        rf"(?<![a-z0-9]){escaped}(?![a-z0-9]).{{0,70}}"
        r"(?:\bis\b|\bare\b|\bwas\b|\bwere\b).{0,60}"
        r"\b(?:method|tool|framework|model|algorithm|pipeline)\b.{0,120}"
        r"\b(?:for|to|that|which)\b",
        rf"(?<![a-z0-9]){escaped}(?![a-z0-9]).{{0,80}}"
        r"\b(?:developed|designed|introduced|presented)\b.{0,100}"
        r"\b(?:for|to)\b",
        rf"(?<![a-z0-9]){escaped}(?![a-z0-9]).{{0,70}}"
        r"\b(?:performs?|enables?|is used for|supports?)\b",
    )
    introduced_subject = (
        r"\b(?:developed|introduced|presented)\b.{0,100}"
        r"\b(?:method|tool|framework|model|algorithm)\b.{0,60}"
        rf"\b(?:called|named)\s+{escaped}(?![a-z0-9])",
        r"\b(?:method|tool|framework|model|algorithm)\b.{0,60}"
        rf"\b(?:called|named)\s+{escaped}(?![a-z0-9]).{{0,140}}"
        r"\b(?:for|to|that|which)\b",
    )
    if not any(
        re.search(pattern, lowered)
        for pattern in (*subject_then_relation, *introduced_subject)
    ):
        return False
    return any(marker.casefold() in lowered for marker in _SCIENTIFIC_CAPABILITY_MARKERS)


def _normalized_semantic_tokens(value: str) -> list[str]:
    tokens = re.findall(r"[a-z0-9]+", value.casefold().replace("scrna-seq", "scrna"))
    normalized: list[str] = []
    for token in tokens:
        if token.startswith("annotat"):
            token = "annotat"
        elif token.startswith("classif"):
            token = "classif"
        elif token.startswith("integrat"):
            token = "integrat"
        elif token.startswith("predict"):
            token = "predict"
        elif token.startswith("infer"):
            token = "infer"
        elif token.startswith("deconvol"):
            token = "deconvol"
        elif token.startswith("cluster"):
            token = "cluster"
        elif token.startswith("reference"):
            token = "reference"
        normalized.append(token)
    return normalized


def _sentences(value: str) -> list[str]:
    return [
        part.strip()
        for part in re.split(r"(?<=[.!?。！？])\s+|[\r\n]+", value)
        if part.strip()
    ] or [value]


def _query_overlap(text: str, query: str) -> int:
    query_tokens = _tokens(_mask_entities(_latest_query(query), ()))
    evidence_tokens = _tokens(text)
    stop = {
        "what",
        "which",
        "does",
        "about",
        "documented",
        "source",
        "information",
        "find",
        "the",
        "and",
        "for",
        "with",
    }
    return len((query_tokens - stop) & evidence_tokens)


def _tokens(value: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9_+-]{2,}", value.casefold())}


def _mentions(text: str, entity: str) -> bool:
    if not entity:
        return False
    return bool(re.search(rf"(?<![A-Za-z0-9]){re.escape(entity)}(?![A-Za-z0-9])", text, re.IGNORECASE))


def _mask_entities(text: str, entities: Iterable[str]) -> str:
    masked = str(text)
    for entity in entities:
        if entity:
            masked = re.sub(re.escape(str(entity)), " ", masked, flags=re.IGNORECASE)
    return masked


def _latest_query(query: str) -> str:
    markers = ("请继续回答这个追问：", "请继续：", "Follow-up:", "follow-up:")
    for marker in markers:
        if marker in query:
            return query.rsplit(marker, 1)[-1].strip()
    return str(query).strip()


def _bounded_text(value: str, limit: int) -> str:
    text = " ".join(str(value).split())
    if len(text) <= limit:
        return text
    boundary = max(text.rfind(". ", 0, limit), text.rfind("。", 0, limit))
    if boundary < 80:
        boundary = limit
    return text[:boundary].rstrip(" .。；;") + "..."


def _unique_nonempty(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value).strip()
        if not text or text.casefold() in seen:
            continue
        seen.add(text.casefold())
        result.append(text)
    return result


def _deduplicate_requests(values: Iterable[ClaimRequest]) -> list[ClaimRequest]:
    result: list[ClaimRequest] = []
    seen: set[tuple[Optional[str], str, Optional[str], bool]] = set()
    for value in values:
        key = (
            value.subject.casefold() if value.subject else None,
            value.predicate,
            value.object_constraint,
            value.ambiguous,
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result
