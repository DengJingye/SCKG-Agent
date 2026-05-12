import argparse
import csv
import html
from pathlib import Path
from typing import Dict, List, Optional


PROJECT_ROOT = Path(__file__).resolve().parent.parent


MODE_LABELS = {
    "pure_llm": "A Pure DeepSeek",
    "evidence_gate": "B Evidence Gate",
    "evidence_gate_auditor": "C Gate + Auditor",
    "full_kg_pipeline": "D Full KG",
}

MODE_COLORS = {
    "pure_llm": "#6b7280",
    "evidence_gate": "#2563eb",
    "evidence_gate_auditor": "#059669",
    "full_kg_pipeline": "#7c3aed",
}

PANELS = [
    ("Top-k hit", "top_k_hit", "higher", "percent"),
    ("Main-tool recommendation evidence", "main_tool_recommendation_evidence_coverage", "higher", "percent"),
    ("Main-tool benchmark evidence", "main_tool_benchmark_evidence_coverage", "higher", "percent"),
    ("High hallucination", "high_hallucination_rate", "lower", "percent"),
    ("Semantic audit pass", "semantic_audit_pass_rate", "higher", "percent"),
    ("Mean latency", "mean_latency_seconds", "lower", "seconds"),
]


def load_summary(path: Path) -> List[Dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def parse_float(value: str) -> Optional[float]:
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def fmt_value(value: Optional[float], unit: str) -> str:
    if value is None:
        return "N/A"
    if unit == "percent":
        return f"{value * 100:.1f}%"
    if unit == "seconds":
        return f"{value:.1f}s"
    return f"{value:.3f}"


def is_audit_metric(metric: str) -> bool:
    return metric in {
        "semantic_hallucination_issue_rate",
        "critical_hallucination_rate",
        "high_hallucination_rate",
        "unsupported_tool_claim_rate",
        "semantic_audit_pass_rate",
    }


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def metric_max(rows: List[Dict[str, str]], metric: str, unit: str) -> float:
    values = [parse_float(row.get(metric, "")) for row in rows]
    values = [value for value in values if value is not None]
    if unit == "percent":
        return 1.0
    if not values:
        return 1.0
    return max(values) * 1.18


def render_panel(
    rows: List[Dict[str, str]],
    title: str,
    metric: str,
    direction: str,
    unit: str,
    x: int,
    y: int,
    width: int,
    height: int,
) -> str:
    axis_left = x + 72
    axis_bottom = y + height - 72
    chart_top = y + 74
    chart_height = axis_bottom - chart_top
    bar_width = 76
    gap = 48
    max_value = metric_max(rows, metric, unit)
    if direction == "higher":
        subtitle = "higher is better"
    elif direction == "lower":
        subtitle = "lower is better"
    else:
        subtitle = "auditor block rate; diagnostic only"
    parts = [
        f'<rect x="{x}" y="{y}" width="{width}" height="{height}" rx="18" fill="#ffffff" stroke="#d1d5db"/>',
        f'<text x="{x + 28}" y="{y + 34}" font-size="22" font-weight="700" fill="#111827">{esc(title)}</text>',
        f'<text x="{x + 28}" y="{y + 58}" font-size="14" fill="#6b7280">{esc(subtitle)}</text>',
        f'<line x1="{axis_left}" y1="{axis_bottom}" x2="{x + width - 34}" y2="{axis_bottom}" stroke="#9ca3af"/>',
        f'<line x1="{axis_left}" y1="{chart_top}" x2="{axis_left}" y2="{axis_bottom}" stroke="#9ca3af"/>',
    ]

    if unit == "percent":
        for tick in (0.0, 0.5, 1.0):
            tick_y = axis_bottom - tick * chart_height
            parts.append(
                f'<line x1="{axis_left - 5}" y1="{tick_y:.1f}" x2="{x + width - 34}" y2="{tick_y:.1f}" stroke="#e5e7eb"/>'
            )
            parts.append(
                f'<text x="{axis_left - 12}" y="{tick_y + 5:.1f}" text-anchor="end" font-size="12" fill="#6b7280">{tick * 100:.0f}%</text>'
            )
    else:
        for tick in (0.0, 0.5, 1.0):
            tick_value = tick * max_value
            tick_y = axis_bottom - tick * chart_height
            parts.append(
                f'<line x1="{axis_left - 5}" y1="{tick_y:.1f}" x2="{x + width - 34}" y2="{tick_y:.1f}" stroke="#e5e7eb"/>'
            )
            parts.append(
                f'<text x="{axis_left - 12}" y="{tick_y + 5:.1f}" text-anchor="end" font-size="12" fill="#6b7280">{tick_value:.0f}s</text>'
            )

    for index, row in enumerate(rows):
        mode = row.get("mode", "")
        value = parse_float(row.get(metric, ""))
        bar_x = axis_left + 34 + index * (bar_width + gap)
        label = MODE_LABELS.get(mode, mode)
        color = MODE_COLORS.get(mode, "#111827")
        if value is None:
            parts.append(
                f'<rect x="{bar_x}" y="{axis_bottom - 10}" width="{bar_width}" height="10" fill="#e5e7eb"/>'
            )
            if is_audit_metric(metric):
                parts.append(
                    f'<text x="{bar_x + bar_width / 2:.1f}" y="{axis_bottom - 30}" text-anchor="middle" font-size="13" font-weight="700" fill="#6b7280">N/A</text>'
                )
                parts.append(
                    f'<text x="{bar_x + bar_width / 2:.1f}" y="{axis_bottom - 14}" text-anchor="middle" font-size="10" fill="#6b7280">audit not run</text>'
                )
            else:
                parts.append(
                    f'<text x="{bar_x + bar_width / 2:.1f}" y="{axis_bottom - 18}" text-anchor="middle" font-size="14" fill="#6b7280">N/A</text>'
                )
        else:
            bar_height = max(4.0, (value / max_value) * chart_height)
            bar_y = axis_bottom - bar_height
            stroke = "#111827" if mode == "evidence_gate_auditor" else color
            stroke_width = "3" if mode == "evidence_gate_auditor" else "0"
            parts.append(
                f'<rect x="{bar_x}" y="{bar_y:.1f}" width="{bar_width}" height="{bar_height:.1f}" rx="8" fill="{color}" stroke="{stroke}" stroke-width="{stroke_width}"/>'
            )
            parts.append(
                f'<text x="{bar_x + bar_width / 2:.1f}" y="{bar_y - 8:.1f}" text-anchor="middle" font-size="14" font-weight="700" fill="#111827">{fmt_value(value, unit)}</text>'
            )
        parts.append(
            f'<text x="{bar_x + bar_width / 2:.1f}" y="{axis_bottom + 20}" text-anchor="middle" font-size="12" fill="#374151">{esc(label.split(" ", 1)[0])}</text>'
        )
        parts.append(
            f'<text x="{bar_x + bar_width / 2:.1f}" y="{axis_bottom + 38}" text-anchor="middle" font-size="11" fill="#6b7280">{esc(label.split(" ", 1)[1] if " " in label else label)}</text>'
        )

    return "\n".join(parts)


def render_svg(rows: List[Dict[str, str]], summary_path: Path, subtitle: str) -> str:
    width = 1480
    height = 1440
    panel_w = 680
    panel_h = 360
    title = "DeepSeek V4 Ablation: Evidence Gate and Auditor"
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#f3f4f6"/>',
        f'<text x="60" y="68" font-size="34" font-weight="800" fill="#111827">{esc(title)}</text>',
        f'<text x="60" y="102" font-size="18" fill="#4b5563">{esc(subtitle)}</text>',
        '<rect x="60" y="126" width="1360" height="58" rx="16" fill="#ecfdf5" stroke="#10b981"/>',
        '<text x="84" y="162" font-size="20" font-weight="700" fill="#065f46">Takeaway: B is the ranker core; C preserves safety while improving benchmark-backed evidence coverage; D remains slower and more intervention-heavy.</text>',
    ]
    positions = [(60, 218), (740, 218), (60, 610), (740, 610), (60, 1002), (740, 1002)]
    for (panel, position) in zip(PANELS, positions):
        parts.append(render_panel(rows, *panel, x=position[0], y=position[1], width=panel_w, height=panel_h))

    parts.extend(
        [
            '<text x="60" y="1374" font-size="14" fill="#6b7280">N/A on semantic metrics means audit was not run for that mode; it is not a zero-risk result.</text>',
            '<text x="60" y="1394" font-size="14" fill="#6b7280">Safety interventions are blocked/replaced reports after high or critical audit issues; this is diagnostic, not simply higher-is-better.</text>',
            '<text x="60" y="1414" font-size="14" fill="#6b7280">Main-tool evidence measures trusted publication/benchmark support for top-k primary recommendations; full bundle coverage remains in the TSV.</text>',
            f'<text x="60" y="1436" font-size="14" fill="#6b7280">Generated from {esc(summary_path)}.</text>',
            "</svg>",
        ]
    )
    return "\n".join(parts)


def main() -> None:
    parser = argparse.ArgumentParser(description="Render ablation summary TSV as a report-ready SVG chart.")
    parser.add_argument(
        "--summary",
        type=Path,
        default=PROJECT_ROOT / "eval" / "ablation_deepseek_aura_smoke" / "ablation_summary.tsv",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "eval" / "ablation_deepseek_aura_smoke" / "ablation_summary_chart.svg",
    )
    parser.add_argument(
        "--subtitle",
        default="Ablation evaluation. Default route: C = DeepSeek V4 + evidence gate + semantic auditor.",
    )
    args = parser.parse_args()
    rows = load_summary(args.summary)
    args.output.write_text(render_svg(rows, args.summary, args.subtitle), encoding="utf-8")
    print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
