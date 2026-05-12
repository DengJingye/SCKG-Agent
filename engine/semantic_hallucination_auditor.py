import re
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set

from pydantic import Field

from core.models import (
    Evidence,
    EvidenceBundle,
    MigrationPath,
    ScientificBaseModel,
    ScoredTool,
    ToolCandidate,
    WorkflowRecommendation,
)


SEVERITY_ORDER = {"low": 1, "medium": 2, "high": 3, "critical": 4}

COMMON_TOOL_ALIASES = {
    "cellrank": "CellRank",
    "harmony": "Harmony",
    "liger": "LIGER",
    "mofa": "MOFA",
    "mofa2": "MOFA2",
    "moscot": "moscot",
    "scanorama": "Scanorama",
    "scanpy": "Scanpy",
    "scgpt": "scGPT",
    "scib": "scIB",
    "scvi": "scvi-tools",
    "scvi-tools": "scvi-tools",
    "seurat": "Seurat",
    "seuratextend": "SeuratExtend",
    "singler": "SingleR",
    "tradeSeq".lower(): "tradeSeq",
    "velociraptor": "velociraptor",
    "wot": "wot",
}

NEGATIVE_OR_UNCERTAIN_TERMS = (
    "cannot",
    "can't",
    "could not",
    "do not",
    "does not",
    "lack",
    "lacks",
    "insufficient",
    "limited",
    "missing",
    "no ",
    "not ",
    "uncertain",
    "without",
    "exploratory",
    "absence",
    "absent",
    "cannot",
    "missing",
    "no direct",
    "不能",
    "不包含",
    "不应",
    "不具备",
    "不足",
    "不确定",
    "无法",
    "没有",
    "无",
    "无 ",
    "无直接",
    "无匹配",
    "无相关",
    "缺少",
    "缺失",
    "缺乏",
    "未发现",
    "未检索到",
    "未找到",
    "弱证据",
    "探索性",
    "为空",
)

BENCHMARK_TERMS = (
    "benchmark",
    "outperform",
    "outperformed",
    "better than",
    "best",
    "highest score",
    "ranked first",
    "sota",
    "top-tier",
    "state-of-the-art",
    "基准",
    "评测",
    "优于",
    "显著优于",
    "最好",
    "最佳",
    "排名第一",
)

LITERATURE_TERMS = (
    "citation",
    "doi",
    "literature",
    "paper",
    "pmid",
    "published",
    "reported",
    "study",
    "文献",
    "论文",
    "发表",
    "报道",
    "研究",
)

MIGRATION_TERMS = (
    "adapt",
    "borrow",
    "migration",
    "migrate",
    "substitute",
    "transfer",
    "迁移",
    "借鉴",
    "替代",
    "迁入",
    "迁出",
)

CERTAINTY_TERMS = (
    "best choice",
    "definitive",
    "high confidence",
    "production-ready",
    "proven",
    "robust",
    "strongly recommend",
    "validated",
    "首选",
    "强烈推荐",
    "明确推荐",
    "高置信",
    "已验证",
    "稳健",
    "生产级",
)

QUERY_CONTEXT_TERMS = (
    "本次任务",
    "任务为",
    "任务是",
    "用户",
    "需求",
    "要求为",
    "希望",
    "想要",
    "选择依据",
    "比较",
    "咨询",
    "query",
    "user query",
)

RANKING_TERMS = (
    "best",
    "first choice",
    "highest",
    "ranked first",
    "top choice",
    "最佳",
    "首选",
    "排名第一",
    "最高",
)

THRESHOLD_CONTEXT_TERMS = (
    "cutoff",
    "filter",
    "gene",
    "genes",
    "hvg",
    "mitochondrial",
    "mt",
    "pct_counts_mt",
    "threshold",
    "umi",
    "umis",
    "基因",
    "过滤",
    "阈值",
    "线粒体",
)


class HallucinationIssue(ScientificBaseModel):
    issue_type: str
    severity: str
    sentence: str
    unsupported_entity: Optional[str] = None
    expected_evidence: Optional[str] = None
    found_evidence: List[str] = Field(default_factory=list)
    suggestion: str


class HallucinationAuditResult(ScientificBaseModel):
    passed: bool
    hallucination_rate: float = Field(ge=0.0, le=1.0)
    issues: List[HallucinationIssue] = Field(default_factory=list)
    unsupported_tools: List[str] = Field(default_factory=list)
    unsupported_claims: List[str] = Field(default_factory=list)
    audited_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    claim_count: int = Field(default=0, ge=0)
    unsupported_claim_count: int = Field(default=0, ge=0)
    severity_counts: Dict[str, int] = Field(default_factory=dict)


def audit_report(
    final_report: str,
    evidence_bundle: Optional[EvidenceBundle] = None,
    scored_tools: Optional[Sequence[ScoredTool]] = None,
    candidate_tools: Optional[Sequence[ToolCandidate]] = None,
    migration_paths: Optional[Sequence[MigrationPath]] = None,
    workflow_recommendation: Optional[WorkflowRecommendation] = None,
) -> HallucinationAuditResult:
    """Audit a rendered report against structured recommendation evidence."""

    evidence_bundle = evidence_bundle or EvidenceBundle()
    scored_tools = list(scored_tools or [])
    candidate_tools = list(candidate_tools or [])
    migration_paths = list(migration_paths or [])
    sentences = _split_sentences(final_report)
    evidence_items = _collect_evidence(
        evidence_bundle=evidence_bundle,
        scored_tools=scored_tools,
        candidate_tools=candidate_tools,
        migration_paths=migration_paths,
        workflow_recommendation=workflow_recommendation,
    )
    evidence_summary = _EvidenceSummary.from_items(evidence_items, evidence_bundle)
    allowed_tools = _allowed_tool_names(
        scored_tools=scored_tools,
        candidate_tools=candidate_tools,
        migration_paths=migration_paths,
        workflow_recommendation=workflow_recommendation,
    )
    rank_by_tool = {_canon_tool(tool.tool_name): tool.rank for tool in scored_tools}

    issues: List[HallucinationIssue] = []
    for sentence in sentences:
        stripped = sentence.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            continue
        if stripped.startswith("- blocked_issue_types:") or stripped.startswith("- blocked_by:"):
            continue
        lowered = stripped.lower()
        is_negative = _has_any(lowered, NEGATIVE_OR_UNCERTAIN_TERMS)
        is_missing_line = lowered.startswith("- missing_components")

        issues.extend(_audit_tools(stripped, allowed_tools, is_negative))
        issues.extend(_audit_workflow(stripped, workflow_recommendation))
        issues.extend(_audit_ranking(stripped, rank_by_tool))

        if not is_missing_line:
            issues.extend(_audit_benchmark(stripped, evidence_summary, is_negative))
            issues.extend(_audit_literature(stripped, evidence_summary, is_negative))
            issues.extend(_audit_numeric_thresholds(stripped, evidence_summary))
            issues.extend(_audit_migration(stripped, migration_paths, is_negative))
            issues.extend(_audit_certainty(stripped, evidence_summary, is_negative))

    deduped = _dedupe_issues(issues)
    severity_counts = _severity_counts(deduped)
    unsupported_tools = sorted(
        {
            issue.unsupported_entity
            for issue in deduped
            if issue.issue_type == "unsupported_tool_claim" and issue.unsupported_entity
        }
    )
    unsupported_claims = [issue.sentence for issue in deduped]
    claim_count = len(sentences)
    unsupported_sentence_count = len({issue.sentence for issue in deduped})
    rate = unsupported_sentence_count / claim_count if claim_count else 0.0
    return HallucinationAuditResult(
        passed=not deduped,
        hallucination_rate=min(rate, 1.0),
        issues=deduped,
        unsupported_tools=unsupported_tools,
        unsupported_claims=unsupported_claims,
        claim_count=claim_count,
        unsupported_claim_count=len(deduped),
        severity_counts=severity_counts,
    )


class _EvidenceSummary:
    def __init__(
        self,
        source_types: Set[str],
        metric_names: Set[str],
        trusted_count: int,
        recommendation_count: int,
        item_count: int,
        max_confidence: float,
        missing_evidence: Set[str],
    ) -> None:
        self.source_types = source_types
        self.metric_names = metric_names
        self.trusted_count = trusted_count
        self.recommendation_count = recommendation_count
        self.item_count = item_count
        self.max_confidence = max_confidence
        self.missing_evidence = missing_evidence

    @classmethod
    def from_items(cls, items: Sequence[Evidence], bundle: EvidenceBundle) -> "_EvidenceSummary":
        source_types = {item.source_type for item in items}
        metric_names = {item.metric_name for item in items}
        trusted_count = len(
            [
                item for item in items
                if item.trust_level in {"verified", "source_based"}
                and item.review_status != "rejected"
            ]
        )
        recommendation_count = len([item for item in items if item.can_support_recommendation])
        max_confidence = max([item.confidence for item in items], default=0.0)
        return cls(
            source_types=source_types,
            metric_names=metric_names,
            trusted_count=trusted_count,
            recommendation_count=recommendation_count,
            item_count=len(items),
            max_confidence=max_confidence,
            missing_evidence=set(bundle.missing_evidence),
        )

    @property
    def has_benchmark(self) -> bool:
        return (
            "benchmark" in self.source_types
            or any(name.startswith("benchmark") for name in self.metric_names)
            or bool({"benchmark_rank", "benchmark_score", "benchmark_result"} & self.metric_names)
        )

    @property
    def has_paper(self) -> bool:
        return (
            "paper" in self.source_types
            or bool({"citations", "paper_citations", "paper_support"} & self.metric_names)
        )

    @property
    def has_protocol_or_docs(self) -> bool:
        return bool({"docs", "benchmark", "paper", "human_review"} & self.source_types)

    @property
    def recommendation_coverage(self) -> float:
        total = self.item_count + len(self.missing_evidence)
        if total == 0:
            return 0.0
        return self.recommendation_count / total


def _split_sentences(report: str) -> List[str]:
    chunks: List[str] = []
    for line in report.splitlines():
        line = line.strip()
        if not line:
            continue
        pieces = re.split(r"(?<=[.!?。！？])\s+", line)
        chunks.extend(piece.strip() for piece in pieces if piece.strip())
    return chunks


def _collect_evidence(
    evidence_bundle: EvidenceBundle,
    scored_tools: Sequence[ScoredTool],
    candidate_tools: Sequence[ToolCandidate],
    migration_paths: Sequence[MigrationPath],
    workflow_recommendation: Optional[WorkflowRecommendation],
) -> List[Evidence]:
    items: List[Evidence] = list(evidence_bundle.items)
    for tool in scored_tools:
        items.extend(tool.evidence.items)
    for candidate in candidate_tools:
        items.extend(candidate.evidence.items)
    for path in migration_paths:
        items.extend(path.evidence.items)
    if workflow_recommendation:
        items.extend(workflow_recommendation.evidence.items)
        for step in workflow_recommendation.steps:
            items.extend(step.evidence.items)
    deduped = {item.evidence_id: item for item in items}
    return list(deduped.values())


def _allowed_tool_names(
    scored_tools: Sequence[ScoredTool],
    candidate_tools: Sequence[ToolCandidate],
    migration_paths: Sequence[MigrationPath],
    workflow_recommendation: Optional[WorkflowRecommendation],
) -> Set[str]:
    names: Set[str] = set()
    for tool in scored_tools:
        names.add(_canon_tool(tool.tool_name))
    for candidate in candidate_tools:
        names.add(_canon_tool(candidate.tool_name))
    for path in migration_paths:
        names.add(_canon_tool(path.tool_name))
    if workflow_recommendation:
        for step in workflow_recommendation.steps:
            for tool_name in step.candidate_tools:
                names.add(_canon_tool(tool_name))
    expanded = set(names)
    for alias, canonical in COMMON_TOOL_ALIASES.items():
        if _canon_tool(canonical) in names:
            expanded.add(alias)
    return expanded


def _audit_tools(sentence: str, allowed_tools: Set[str], is_negative: bool) -> List[HallucinationIssue]:
    issues = []
    lowered = sentence.lower()
    if _has_any(sentence, QUERY_CONTEXT_TERMS) and not _has_any(lowered, BENCHMARK_TERMS + CERTAINTY_TERMS + RANKING_TERMS):
        return issues
    for canonical in _detect_tool_mentions(sentence):
        canon = _canon_tool(canonical)
        if canon in allowed_tools:
            continue
        if is_negative:
            continue
        issues.append(
            HallucinationIssue(
                issue_type="unsupported_tool_claim",
                severity="high",
                sentence=sentence,
                unsupported_entity=canonical,
                expected_evidence="tool must appear in candidate_tools, scored_tools, workflow steps, or migration_paths",
                found_evidence=[],
                suggestion=f"Remove {canonical} or add structured evidence before mentioning it in the report.",
            )
        )
    return issues


def _audit_benchmark(
    sentence: str,
    evidence: _EvidenceSummary,
    is_negative: bool,
) -> List[HallucinationIssue]:
    if is_negative or not _has_any(sentence.lower(), BENCHMARK_TERMS) or evidence.has_benchmark:
        return []
    return [
        HallucinationIssue(
            issue_type="unsupported_benchmark_claim",
            severity="critical",
            sentence=sentence,
            expected_evidence="benchmark evidence with benchmark_rank, benchmark_score, or benchmark_result",
            found_evidence=sorted(evidence.metric_names),
            suggestion="Downgrade the benchmark wording or attach benchmark evidence before making comparative claims.",
        )
    ]


def _audit_literature(
    sentence: str,
    evidence: _EvidenceSummary,
    is_negative: bool,
) -> List[HallucinationIssue]:
    if is_negative or not _has_any(sentence.lower(), LITERATURE_TERMS) or evidence.has_paper:
        return []
    return [
        HallucinationIssue(
            issue_type="unsupported_literature_claim",
            severity="critical",
            sentence=sentence,
            expected_evidence="paper evidence with DOI/PMID/citation support",
            found_evidence=sorted(evidence.source_types),
            suggestion="State that literature support is missing, or attach verified paper evidence.",
        )
    ]


def _audit_workflow(
    sentence: str,
    workflow: Optional[WorkflowRecommendation],
) -> List[HallucinationIssue]:
    if "->" not in sentence and "→" not in sentence:
        return []
    if not workflow:
        return [
            HallucinationIssue(
                issue_type="unsupported_workflow_transition",
                severity="high",
                sentence=sentence,
                expected_evidence="workflow_recommendation with ordered WorkflowStep objects",
                found_evidence=[],
                suggestion="Remove the workflow transition or construct a validated workflow recommendation.",
            )
        ]
    reported = _parse_transition(sentence)
    expected = [_normalize_step(step.name) for step in workflow.steps]
    if not reported:
        return []
    if reported == expected:
        return []
    if any(step in sentence.lower() for step in expected):
        return []
    return []


def _audit_numeric_thresholds(
    sentence: str,
    evidence: _EvidenceSummary,
) -> List[HallucinationIssue]:
    lowered = sentence.lower()
    has_threshold_number = bool(
        re.search(r"([<>]=?\s*\d+(\.\d+)?|\d+(\.\d+)?\s*%|\bhvg\s*[=:]\s*\d+|\b\d+\s*(umis?|genes?|pcs?)\b)", lowered)
    )
    if not has_threshold_number or not _has_any(lowered, THRESHOLD_CONTEXT_TERMS):
        return []
    if evidence.has_protocol_or_docs:
        return []
    return [
        HallucinationIssue(
            issue_type="unsupported_numeric_claim",
            severity="high",
            sentence=sentence,
            expected_evidence="protocol, docs, benchmark, or paper evidence for numeric thresholds",
            found_evidence=sorted(evidence.source_types),
            suggestion="Remove numeric thresholds or cite protocol/benchmark evidence supporting them.",
        )
    ]


def _audit_migration(
    sentence: str,
    migration_paths: Sequence[MigrationPath],
    is_negative: bool,
) -> List[HallucinationIssue]:
    lowered = sentence.lower()
    if not _has_any(lowered, MIGRATION_TERMS):
        return []
    if not migration_paths and not is_negative:
        return [
            HallucinationIssue(
                issue_type="unsupported_migration_claim",
                severity="high",
                sentence=sentence,
                expected_evidence="MigrationPath with structured compatibility or explicit exploratory status",
                found_evidence=[],
                suggestion="Remove the migration claim or generate a structured MigrationPath first.",
            )
        ]
    if migration_paths and _has_any(lowered, ("straightforward", "low risk", "safe", "直接", "低风险", "很稳")):
        risky = [path for path in migration_paths if path.risk_level in {"exploratory", "high", "unknown"}]
        if risky:
            return [
                HallucinationIssue(
                    issue_type="unsupported_migration_claim",
                    severity="high",
                    sentence=sentence,
                    expected_evidence="low-risk MigrationPath with structured algorithm compatibility",
                    found_evidence=[path.risk_level for path in migration_paths],
                    suggestion="Downgrade migration wording to exploratory and list limitations.",
                )
            ]
    return []


def _audit_ranking(sentence: str, rank_by_tool: Dict[str, int]) -> List[HallucinationIssue]:
    lowered = sentence.lower()
    if not rank_by_tool or not _has_any(lowered, RANKING_TERMS):
        return []
    issues = []
    for canonical in _detect_tool_mentions(sentence):
        canon = _canon_tool(canonical)
        rank = rank_by_tool.get(canon)
        if rank and rank > 1:
            issues.append(
                HallucinationIssue(
                    issue_type="ranking_exaggeration",
                    severity="medium",
                    sentence=sentence,
                    unsupported_entity=canonical,
                    expected_evidence=f"{canonical} must be rank 1 for best/top-choice wording",
                    found_evidence=[f"rank={rank}"],
                    suggestion="Use neutral ranking language or mention the actual rank.",
                )
            )
    return issues


def _audit_certainty(
    sentence: str,
    evidence: _EvidenceSummary,
    is_negative: bool,
) -> List[HallucinationIssue]:
    lowered = sentence.lower()
    if is_negative or not _has_any(lowered, CERTAINTY_TERMS):
        return []
    if evidence.recommendation_coverage >= 0.6 and evidence.trusted_count > 0 and evidence.max_confidence >= 0.6:
        return []
    return [
        HallucinationIssue(
            issue_type="certainty_overclaim",
            severity="medium",
            sentence=sentence,
            expected_evidence="trusted recommendation-grade evidence with sufficient coverage",
            found_evidence=[
                f"recommendation_coverage={evidence.recommendation_coverage:.3f}",
                f"trusted_evidence={evidence.trusted_count}",
                f"max_confidence={evidence.max_confidence:.3f}",
            ],
            suggestion="Downgrade to exploratory/limited-evidence wording.",
        )
    ]


def _detect_tool_mentions(sentence: str) -> Set[str]:
    mentions: Set[str] = set()
    for alias, canonical in COMMON_TOOL_ALIASES.items():
        if _tool_alias_in_text(alias, sentence):
            mentions.add(canonical)
    return mentions


def _tool_alias_in_text(alias: str, text: str) -> bool:
    if not alias:
        return False
    escaped = re.escape(alias)
    return bool(re.search(rf"(?<![A-Za-z0-9_.-]){escaped}(?![A-Za-z0-9_.-])", text, flags=re.IGNORECASE))


def _parse_transition(sentence: str) -> List[str]:
    if ":" in sentence:
        sentence = sentence.split(":", 1)[1]
    parts = re.split(r"\s*(?:->|→)\s*", sentence)
    return [_normalize_step(part) for part in parts if _normalize_step(part)]


def _normalize_step(value: str) -> str:
    value = re.sub(r"^[\-\*\d\.\)\s]+", "", value.strip())
    value = re.sub(r"[。.!?；;，,]+$", "", value)
    return re.sub(r"\s+", " ", value).lower()


def _canon_tool(value: str) -> str:
    return re.sub(r"\s+", "", value.strip().lower())


def _has_any(text: str, terms: Iterable[str]) -> bool:
    return any(term in text for term in terms)


def _dedupe_issues(issues: Sequence[HallucinationIssue]) -> List[HallucinationIssue]:
    deduped: Dict[tuple[str, str, Optional[str]], HallucinationIssue] = {}
    for issue in issues:
        key = (issue.issue_type, issue.sentence, issue.unsupported_entity)
        existing = deduped.get(key)
        if existing is None or SEVERITY_ORDER.get(issue.severity, 0) > SEVERITY_ORDER.get(existing.severity, 0):
            deduped[key] = issue
    return list(deduped.values())


def _severity_counts(issues: Sequence[HallucinationIssue]) -> Dict[str, int]:
    counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    for issue in issues:
        counts[issue.severity] = counts.get(issue.severity, 0) + 1
    return counts
