from dataclasses import dataclass
from typing import Iterable, List

from core.models import Evidence, EvidenceBundle


RECOMMENDATION_EVIDENCE_METRICS = {
    "benchmark_rank",
    "benchmark_result",
    "benchmark_score",
    "citations",
    "paper_citations",
    "paper_support",
    "github_stars",
    "last_updated",
    "maintenance_status",
    "runtime",
    "memory",
    "manual_review",
    "official_docs_support",
}

MAIN_RECOMMENDATION_CANONICAL_SCOPES = {"core_tool", "major_version"}
MAIN_RECOMMENDATION_EVIDENCE_CATEGORIES = {"architectural_core"}
MAIN_RECOMMENDATION_AUTHORITY_TIERS = {"canonical_primary", "canonical_secondary"}
MAIN_RECOMMENDATION_SOURCE_TYPES = {"paper", "benchmark"}
AUTHORITY_TIER_PRIORITY = {
    "canonical_primary": 1.0,
    "canonical_secondary": 0.9,
    "ecosystem_support": 0.0,
    "contextual_support": 0.0,
    "provenance_only": 0.0,
    "manual_required": 0.0,
}

MAIN_RECOMMENDATION_TOP_K = 10
MIGRATION_TOP_K = 3


@dataclass(frozen=True)
class EvidenceAudit:
    recommendation_evidence: List[Evidence]
    retrieval_only_evidence: List[Evidence]
    missing_components: List[str]

    @property
    def recommendation_coverage(self) -> float:
        total = len(self.recommendation_evidence) + len(self.missing_components)
        if total == 0:
            return 0.0
        return len(self.recommendation_evidence) / total

    @property
    def has_recommendation_evidence(self) -> bool:
        return bool(self.recommendation_evidence)

    @property
    def main_recommendation_evidence(self) -> List[Evidence]:
        return [
            item for item in self.recommendation_evidence
            if is_main_recommendation_evidence(item)
        ]

    @property
    def has_main_recommendation_evidence(self) -> bool:
        return bool(self.main_recommendation_evidence)


def audit_evidence(bundle: EvidenceBundle) -> EvidenceAudit:
    recommendation_evidence = [
        item for item in bundle.items
        if item.can_support_recommendation
        and item.metric_name in RECOMMENDATION_EVIDENCE_METRICS
    ]
    retrieval_only_evidence = [
        item for item in bundle.items
        if item not in recommendation_evidence
    ]
    return EvidenceAudit(
        recommendation_evidence=recommendation_evidence,
        retrieval_only_evidence=retrieval_only_evidence,
        missing_components=list(bundle.missing_evidence),
    )


def is_main_recommendation_evidence(item: Evidence) -> bool:
    """Evidence allowed to admit a tool into the primary top-k path."""
    if not item.can_support_recommendation:
        return False
    if item.graph_layer != "trusted_core":
        return False
    if item.metric_name not in RECOMMENDATION_EVIDENCE_METRICS:
        return False
    return is_main_publication_evidence(item) or is_main_benchmark_evidence(item)


def is_main_publication_evidence(item: Evidence) -> bool:
    """Trusted canonical publication support for a primary recommendation."""
    if item.source_type != "paper":
        return False
    if not item.can_support_recommendation:
        return False
    if item.graph_layer != "trusted_core":
        return False
    if item.metric_name not in RECOMMENDATION_EVIDENCE_METRICS:
        return False
    return (
        item.recommendation_eligible is True
        and item.authority_tier in MAIN_RECOMMENDATION_AUTHORITY_TIERS
        and item.canonical_scope in MAIN_RECOMMENDATION_CANONICAL_SCOPES
        and item.evidence_category in MAIN_RECOMMENDATION_EVIDENCE_CATEGORIES
    )


def is_main_benchmark_evidence(item: Evidence) -> bool:
    """Trusted benchmark support for a primary recommendation."""
    return (
        item.source_type == "benchmark"
        and item.can_support_recommendation
        and item.graph_layer == "trusted_core"
        and item.metric_name in RECOMMENDATION_EVIDENCE_METRICS
    )


def main_recommendation_priority(item: Evidence) -> float:
    if not is_main_recommendation_evidence(item):
        return 0.0
    if item.source_type == "benchmark":
        return 1.0
    return AUTHORITY_TIER_PRIORITY.get(item.authority_tier, 0.0)


def bundle_main_recommendation_priority(bundle: EvidenceBundle) -> float:
    return max((main_recommendation_priority(item) for item in bundle.items), default=0.0)


def filter_for_recommendation(items: Iterable[Evidence]) -> List[Evidence]:
    return [
        item for item in items
        if item.can_support_recommendation
        and item.metric_name in RECOMMENDATION_EVIDENCE_METRICS
    ]


def filter_for_main_recommendation(items: Iterable[Evidence]) -> List[Evidence]:
    """Trusted-core evidence allowed into the primary recommendation path."""
    return [
        item for item in items
        if is_main_recommendation_evidence(item)
    ]


def has_main_recommendation_evidence(bundle: EvidenceBundle) -> bool:
    return bool(filter_for_main_recommendation(bundle.items))


def evidence_guardrail_warnings(bundle: EvidenceBundle) -> List[str]:
    audit = audit_evidence(bundle)
    warnings = []
    if not audit.recommendation_evidence:
        warnings.append("No trusted recommendation-grade evidence is available; result must stay exploratory.")
    if audit.retrieval_only_evidence:
        warnings.append(
            f"{len(audit.retrieval_only_evidence)} evidence item(s) are retrieval-only or experimental."
        )
    if audit.missing_components:
        warnings.append(
            "Missing evidence components: " + ", ".join(sorted(set(audit.missing_components)))
        )
    return warnings
