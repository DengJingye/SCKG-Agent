from typing import Any, Dict, List, Optional

from core.evidence_policy import bundle_main_recommendation_priority


QUALITATIVE_BENCHMARK_SUPPORT = 0.6
SCOPED_QUALITATIVE_BENCHMARK_SUPPORT = 0.45
CAVEAT_BENCHMARK_SUPPORT = 0.0

POSITIVE_BENCHMARK_TYPES = {
    "comparative_benchmark",
    "third_party_comparative_benchmark",
}
SCOPED_BENCHMARK_TYPES = {
    "comparative_interpretability_benchmark",
}
CAVEAT_BENCHMARK_TYPES = {
    "negative_control_and_assumption_benchmark",
    "caveat_benchmark",
    "assumption_benchmark",
}
CAVEAT_TEXT_MARKERS = {
    "negative-control",
    "negative control",
    "caveat evidence",
    "critique",
    "must include caveats",
    "not positive ranking evidence",
    "not as a positive performance ranking",
    "fails",
    "reverse known",
    "reverse trajectories",
    "assumption",
    "sensitivity",
}
SCOPED_TEXT_MARKERS = {
    "bounded",
    "context dependent",
    "context-dependent",
    "not be described as the overall best",
    "not overall best",
    "not universal superiority",
    "do not claim unique best",
    "alongside",
    "moderate",
    "minimal causal regulatory logic",
}


class MCDMCalculator:
    """
    多准则决策 (MCDM) 引擎
    基于证据（Benchmark 排名、GitHub 数据、引用量）对候选工具进行量化打分排序。
    """
    def __init__(self, weights: Dict[str, float] = None):
        # 如果未指定权重，使用默认的经验权重 (总和为 1.0)
        # 学术Benchmark表现最重要 (50%)，学术引用量其次 (30%)，工程可行性 (20%)
        self.weights = weights or {
            "benchmark_rank": 0.5,
            "citations": 0.3,
            "github_stars": 0.2
        }

    def normalize_rank(self, rank: int, total_items: int) -> float:
        """
        相对排名归一化 (对应开题报告中的 Snorm 公式)
        Snorm(t, b) = 1 - (rank(t, b) - 1) / (|Ib| - 1)
        """
        if total_items <= 1:
            return 1.0  # 只有一个候选时，直接满分
        # 确保不会出现负分，并且排名第一的得分最高
        return max(0.0, 1.0 - (rank - 1) / (total_items - 1))

    def min_max_normalize(self, value: float, min_val: float, max_val: float) -> float:
        """经典的 Min-Max 归一化 (用于 Stars 和 Citations 这种绝对数值)"""
        if max_val == min_val:
            return 1.0
        return (value - min_val) / (max_val - min_val)

    def _component_weight(self, name: str) -> float:
        if name in {
            "benchmark_score",
            "qualitative_benchmark_support",
            "scoped_qualitative_benchmark_support",
            "caveat_benchmark_support",
        }:
            return self.weights["benchmark_rank"]
        return self.weights[name]

    def _benchmark_result_items(self, evidence_bundle: Any) -> List[Any]:
        if evidence_bundle is None:
            return []
        return [
            item
            for item in (getattr(evidence_bundle, "items", []) or [])
            if getattr(item, "metric_name", "") == "benchmark_result"
            and getattr(item, "can_support_recommendation", False)
        ]

    def _qualitative_benchmark_support(
        self,
        evidence_bundle: Any,
    ) -> tuple[Optional[str], Optional[float], List[str]]:
        result_items = self._benchmark_result_items(evidence_bundle)
        if not result_items:
            return None, None, ["benchmark"]

        benchmark_types = {
            str(getattr(item, "benchmark_type", "") or "").strip().lower()
            for item in result_items
            if str(getattr(item, "benchmark_type", "") or "").strip()
        }
        result_text = " ".join(
            str(getattr(item, "metric_value", "") or "")
            for item in result_items
        ).lower()
        source_text = " ".join(
            str(getattr(item, "source_title", "") or "")
            for item in result_items
        ).lower()
        combined_text = f"{source_text} {result_text}"

        if benchmark_types & CAVEAT_BENCHMARK_TYPES or any(
            marker in combined_text for marker in CAVEAT_TEXT_MARKERS
        ):
            return (
                "caveat_benchmark_support",
                CAVEAT_BENCHMARK_SUPPORT,
                ["numeric_benchmark_rank", "positive_benchmark_evidence"],
            )
        if benchmark_types & SCOPED_BENCHMARK_TYPES or any(
            marker in combined_text for marker in SCOPED_TEXT_MARKERS
        ):
            return (
                "scoped_qualitative_benchmark_support",
                SCOPED_QUALITATIVE_BENCHMARK_SUPPORT,
                ["numeric_benchmark_rank"],
            )
        if benchmark_types & POSITIVE_BENCHMARK_TYPES:
            return (
                "qualitative_benchmark_support",
                QUALITATIVE_BENCHMARK_SUPPORT,
                ["numeric_benchmark_rank"],
            )
        return (
            "scoped_qualitative_benchmark_support",
            SCOPED_QUALITATIVE_BENCHMARK_SUPPORT,
            ["numeric_benchmark_rank", "benchmark_type"],
        )

    def _numeric_evidence_value(self, evidence_bundle: Any, metric_names: set[str]) -> Optional[float]:
        if evidence_bundle is None:
            return None
        values = []
        for item in getattr(evidence_bundle, "items", []) or []:
            if getattr(item, "metric_name", "") not in metric_names:
                continue
            value = getattr(item, "metric_value", None)
            if isinstance(value, (int, float)):
                values.append(float(value))
            elif isinstance(value, str):
                try:
                    values.append(float(value.replace(",", "")))
                except ValueError:
                    continue
        if not values:
            return None
        return max(values)

    def _has_evidence_metric(self, evidence_bundle: Any, metric_names: set[str]) -> bool:
        if evidence_bundle is None:
            return False
        return any(
            getattr(item, "metric_name", "") in metric_names
            for item in (getattr(evidence_bundle, "items", []) or [])
        )

    def _tool_citations(self, tool: Dict[str, Any]) -> Optional[float]:
        if tool.get("citations") is not None:
            return float(tool["citations"])
        return self._numeric_evidence_value(
            tool.get("evidence_bundle"),
            {"citations", "paper_citations"},
        )

    def _tool_benchmark_score_component(
        self,
        tool: Dict[str, Any],
        total_tools: int,
    ) -> tuple[Optional[str], Optional[float], List[str]]:
        missing = []
        if tool.get("benchmark_rank") is not None:
            return (
                "benchmark_rank",
                self.normalize_rank(int(tool.get("benchmark_rank")), total_tools),
                missing,
            )
        if tool.get("benchmark_score") is not None:
            return ("benchmark_score", float(tool.get("benchmark_score")), missing)

        evidence_bundle = tool.get("evidence_bundle")
        rank = self._numeric_evidence_value(evidence_bundle, {"benchmark_rank"})
        if rank is not None:
            return ("benchmark_rank", self.normalize_rank(int(rank), total_tools), missing)
        score = self._numeric_evidence_value(evidence_bundle, {"benchmark_score"})
        if score is not None:
            return ("benchmark_score", score, missing)
        return self._qualitative_benchmark_support(evidence_bundle)

    def calculate_scores(self, tools_metrics: List[Dict]) -> List[Dict]:
        """
        输入包含多个工具原始指标的列表，返回计算了最终 Score(t) 并排好序的列表。
        """
        if not tools_metrics:
            return []

        total_tools = len(tools_metrics)

        available_stars = [
            t.get("github_stars") for t in tools_metrics
            if t.get("github_stars") is not None
        ]
        available_cites = [
            self._tool_citations(t) for t in tools_metrics
            if self._tool_citations(t) is not None
        ]
        max_stars = max(available_stars) if available_stars else None
        min_stars = min(available_stars) if available_stars else None
        max_cites = max(available_cites) if available_cites else None
        min_cites = min(available_cites) if available_cites else None

        scored_tools = []
        for tool in tools_metrics:
            evidence_bundle = tool.get("evidence_bundle")
            recommendation_coverage = (
                evidence_bundle.recommendation_coverage
                if evidence_bundle is not None
                else 0.0
            )
            canonical_priority = (
                bundle_main_recommendation_priority(evidence_bundle)
                if evidence_bundle is not None
                else 0.0
            )
            task_alignment = float(tool.get("task_alignment") or 0.0)
            components = {}
            missing = []

            benchmark_component, benchmark_value, benchmark_missing = (
                self._tool_benchmark_score_component(tool, total_tools)
            )
            if benchmark_component and benchmark_value is not None:
                components[benchmark_component] = benchmark_value
            missing.extend(benchmark_missing)

            citations = self._tool_citations(tool)
            if citations is not None and min_cites is not None and max_cites is not None:
                components["citations"] = self.min_max_normalize(
                    citations,
                    min_cites,
                    max_cites,
                )
            else:
                missing.append("citations")

            if tool.get("github_stars") is not None and min_stars is not None and max_stars is not None:
                components["github_stars"] = self.min_max_normalize(
                    tool.get("github_stars"),
                    min_stars,
                    max_stars,
                )
            else:
                missing.append("github_stars")

            total_weight = sum(self.weights.values())
            final_score = 0.0
            if total_weight > 0:
                final_score = sum(
                    self._component_weight(name) * value for name, value in components.items()
                ) / total_weight
            final_score *= recommendation_coverage
            final_score *= canonical_priority
            if task_alignment > 0:
                final_score *= task_alignment
            
            # 将打分细节拼装回去，方便出具解释报告
            tool_result = tool.copy()
            tool_result["mcdm_score"] = final_score
            tool_result["evidence_breakdown"] = {
                "available_components": {
                    name: round(value, 4) for name, value in components.items()
                },
                "missing_components": missing,
                "evidence_completeness": round(
                    len(components) / len(self.weights),
                    4,
                ),
                "recommendation_evidence_coverage": round(
                    recommendation_coverage,
                    4,
                ),
                "canonical_scope_priority": round(canonical_priority, 4),
                "task_alignment": round(task_alignment, 4),
            }
            scored_tools.append(tool_result)

        # 按最终得分从高到低排序
        scored_tools.sort(key=lambda x: x["mcdm_score"], reverse=True)
        return scored_tools
