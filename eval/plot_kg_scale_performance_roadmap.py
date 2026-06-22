import argparse
import csv
import html
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from eval.run_eval import run_constraint_eval


GOLD_PATH = PROJECT_ROOT / "eval" / "gold_queries_v0_2_blind.jsonl"


@dataclass(frozen=True)
class Snapshot:
    name: str
    label: str
    plan_path: Path
    prediction_path: Path
    connected: bool = True
    note: str = ""


SNAPSHOTS = [
    Snapshot(
        name="formal_base",
        label="Formal base",
        plan_path=PROJECT_ROOT / "eval" / "evidence_backfill_formal_only_apply_plan.jsonl",
        prediction_path=PROJECT_ROOT
        / "eval"
        / "ablation_deepseek_aura_v0_2_blind_full"
        / "predictions_evidence_gate_auditor.jsonl",
        note="Base formal evidence snapshot.",
    ),
    Snapshot(
        name="cell2location",
        label="+ Cell2location",
        plan_path=PROJECT_ROOT
        / "eval"
        / "evidence_backfill_after_cell2location_benchmark_apply_plan.jsonl",
        prediction_path=PROJECT_ROOT
        / "eval"
        / "ablation_deepseek_aura_v0_2_blind_after_cell2location_benchmark"
        / "predictions_evidence_gate_auditor.jsonl",
        note="Formal publication/benchmark layer expanded.",
    ),
    Snapshot(
        name="mofa2_scvelo",
        label="+ MOFA2/scVelo",
        plan_path=PROJECT_ROOT
        / "eval"
        / "evidence_backfill_after_mofa2_scvelo_benchmark_apply_plan.jsonl",
        prediction_path=PROJECT_ROOT
        / "eval"
        / "ablation_deepseek_aura_v0_2_blind_after_mofa2_scvelo_benchmark"
        / "predictions_evidence_gate_auditor.jsonl",
        note="Benchmark-backed support increases under the same blind protocol.",
    ),
    Snapshot(
        name="mcdm_fix_v2",
        label="MCDM fix v2",
        plan_path=PROJECT_ROOT
        / "eval"
        / "evidence_backfill_after_mofa2_scvelo_benchmark_apply_plan.jsonl",
        prediction_path=PROJECT_ROOT
        / "eval"
        / "ablation_deepseek_aura_v0_2_blind_after_mcdm_qual_benchmark_fix_v2"
        / "predictions_evidence_gate_auditor.jsonl",
        connected=False,
        note="Same KG size; stricter qualitative/caveat benchmark scoring.",
    ),
]


COLORS = {
    "top_k": "#059669",
    "main": "#2563eb",
    "publication": "#7c3aed",
    "benchmark": "#d97706",
    "audit": "#dc2626",
    "text": "#111827",
    "muted": "#64748b",
    "grid": "#e5e7eb",
    "panel": "#ffffff",
    "border": "#cbd5e1",
}


METRIC_LABELS = {
    "top_k_hit": "C top-k hit",
    "main_tool_recommendation_evidence_coverage": "C main-tool evidence support",
    "main_tool_publication_evidence_coverage": "C main-tool publication support",
    "main_tool_benchmark_evidence_coverage": "C main-tool benchmark support",
}


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def fmt_pct(value: Optional[float]) -> str:
    if value is None:
        return "N/A"
    return f"{value * 100:.1f}%"


def fmt_int(value: Optional[int]) -> str:
    if value is None:
        return "N/A"
    return str(value)


def count_plan(path: Path) -> Dict[str, int]:
    tool_names = set()
    evidence_ids = set()
    paper_ids = set()
    benchmark_ids = set()
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("tool_name"):
                tool_names.add(row["tool_name"])
            for evidence_id in row.get("evidence_ids", []):
                evidence_ids.add(evidence_id)
                prefix = evidence_id.split(":", 1)[0]
                if prefix == "paper":
                    paper_ids.add(evidence_id)
                elif prefix == "benchmark":
                    benchmark_ids.add(evidence_id)
    return {
        "formal_tool_count": len(tool_names),
        "formal_evidence_count": len(evidence_ids),
        "formal_publication_count": len(paper_ids),
        "formal_benchmark_count": len(benchmark_ids),
    }


def load_metrics(prediction_path: Path) -> Dict[str, Optional[float]]:
    report = run_constraint_eval(GOLD_PATH, prediction_path)
    return {name: metric.value for name, metric in report.metrics.items()}


def build_rows(snapshots: List[Snapshot]) -> List[Dict[str, object]]:
    rows = []
    for snapshot in snapshots:
        counts = count_plan(snapshot.plan_path)
        metrics = load_metrics(snapshot.prediction_path)
        rows.append(
            {
                "name": snapshot.name,
                "label": snapshot.label,
                "connected_scale_trend": snapshot.connected,
                "plan_path": snapshot.plan_path,
                "prediction_path": snapshot.prediction_path,
                "note": snapshot.note,
                **counts,
                "top_k_hit": metrics.get("top_k_hit"),
                "recommendation_type_accuracy": metrics.get("recommendation_type_accuracy"),
                "evidence_coverage": metrics.get("evidence_coverage"),
                "recommendation_evidence_coverage": metrics.get(
                    "recommendation_evidence_coverage"
                ),
                "main_tool_recommendation_evidence_coverage": metrics.get(
                    "main_tool_recommendation_evidence_coverage"
                ),
                "main_tool_publication_evidence_coverage": metrics.get(
                    "main_tool_publication_evidence_coverage"
                ),
                "main_tool_benchmark_evidence_coverage": metrics.get(
                    "main_tool_benchmark_evidence_coverage"
                ),
                "semantic_audit_pass_rate": metrics.get("semantic_audit_pass_rate"),
                "high_hallucination_rate": metrics.get("high_hallucination_rate"),
            }
        )
    return rows


def x_for_count(count: int, x: int, width: int, min_count: int, max_count: int) -> float:
    if max_count == min_count:
        return x + width / 2
    return x + ((count - min_count) / (max_count - min_count)) * width


def y_for_pct(value: float, y: int, height: int) -> float:
    return y + height - max(0.0, min(value, 1.0)) * height


def render_metric_line(
    rows: List[Dict[str, object]],
    metric: str,
    color: str,
    x: int,
    y: int,
    width: int,
    height: int,
    min_count: int,
    max_count: int,
) -> str:
    points = []
    for row in rows:
        if not row["connected_scale_trend"]:
            continue
        value = row.get(metric)
        if value is None:
            continue
        px = x_for_count(int(row["formal_evidence_count"]), x, width, min_count, max_count)
        py = y_for_pct(float(value), y, height)
        points.append((px, py, float(value), row["label"]))

    parts: List[str] = []
    for left, right in zip(points, points[1:]):
        parts.append(
            f'<line x1="{left[0]:.1f}" y1="{left[1]:.1f}" x2="{right[0]:.1f}" y2="{right[1]:.1f}" '
            f'stroke="{color}" stroke-width="5" stroke-linecap="round"/>'
        )
    for px, py, value, _ in points:
        parts.append(
            f'<circle cx="{px:.1f}" cy="{py:.1f}" r="8" fill="{color}" stroke="#ffffff" stroke-width="3"/>'
        )
        parts.append(
            f'<text x="{px:.1f}" y="{py - 13:.1f}" text-anchor="middle" font-size="13" font-weight="850" fill="{color}">{esc(fmt_pct(value))}</text>'
        )
    if points:
        px, py, _, _ = points[-1]
        parts.append(
            f'<text x="{px + 12:.1f}" y="{py + 5:.1f}" font-size="13" font-weight="850" fill="{color}">{esc(METRIC_LABELS[metric])}</text>'
        )
    return "\n".join(parts)


def render_main_chart(rows: List[Dict[str, object]], x: int, y: int, width: int, height: int) -> str:
    trend_rows = [row for row in rows if row["connected_scale_trend"]]
    min_count = min(int(row["formal_evidence_count"]) for row in trend_rows) - 1
    max_count = max(int(row["formal_evidence_count"]) for row in trend_rows) + 2
    chart_x = x + 86
    chart_y = y + 82
    chart_w = width - 150
    chart_h = height - 168
    parts = [
        f'<rect x="{x}" y="{y}" width="{width}" height="{height}" rx="18" fill="{COLORS["panel"]}" stroke="{COLORS["border"]}"/>',
        f'<text x="{x + 28}" y="{y + 38}" font-size="24" font-weight="900" fill="{COLORS["text"]}">KG Scale vs Recommendation Quality</text>',
        f'<text x="{x + 28}" y="{y + 64}" font-size="14" fill="{COLORS["muted"]}">X-axis is formal KG evidence records, not version labels. Connected points use the same v0.2 blind protocol.</text>',
    ]
    for tick in (0.0, 0.25, 0.5, 0.75, 1.0):
        ty = chart_y + chart_h - tick * chart_h
        parts.append(
            f'<line x1="{chart_x}" y1="{ty:.1f}" x2="{chart_x + chart_w}" y2="{ty:.1f}" stroke="{COLORS["grid"]}"/>'
        )
        parts.append(
            f'<text x="{chart_x - 14}" y="{ty + 5:.1f}" text-anchor="end" font-size="12" fill="{COLORS["muted"]}">{tick * 100:.0f}%</text>'
        )
    parts.append(
        f'<line x1="{chart_x}" y1="{chart_y}" x2="{chart_x}" y2="{chart_y + chart_h}" stroke="#94a3b8"/>'
    )
    parts.append(
        f'<line x1="{chart_x}" y1="{chart_y + chart_h}" x2="{chart_x + chart_w}" y2="{chart_y + chart_h}" stroke="#94a3b8"/>'
    )

    for row in trend_rows:
        count = int(row["formal_evidence_count"])
        px = x_for_count(count, chart_x, chart_w, min_count, max_count)
        parts.append(
            f'<line x1="{px:.1f}" y1="{chart_y}" x2="{px:.1f}" y2="{chart_y + chart_h + 9}" stroke="#f1f5f9"/>'
        )
        parts.append(
            f'<text x="{px:.1f}" y="{chart_y + chart_h + 34}" text-anchor="middle" font-size="13" font-weight="850" fill="{COLORS["text"]}">{count} formal evidence</text>'
        )
        parts.append(
            f'<text x="{px:.1f}" y="{chart_y + chart_h + 54}" text-anchor="middle" font-size="12" fill="{COLORS["muted"]}">{esc(row["label"])}</text>'
        )
        parts.append(
            f'<text x="{px:.1f}" y="{chart_y + chart_h + 74}" text-anchor="middle" font-size="12" fill="{COLORS["muted"]}">{row["formal_publication_count"]} papers / {row["formal_benchmark_count"]} benchmarks</text>'
        )

    parts.append(
        render_metric_line(
            rows,
            "top_k_hit",
            COLORS["top_k"],
            chart_x,
            chart_y,
            chart_w,
            chart_h,
            min_count,
            max_count,
        )
    )
    parts.append(
        render_metric_line(
            rows,
            "main_tool_recommendation_evidence_coverage",
            COLORS["main"],
            chart_x,
            chart_y,
            chart_w,
            chart_h,
            min_count,
            max_count,
        )
    )
    parts.append(
        render_metric_line(
            rows,
            "main_tool_publication_evidence_coverage",
            COLORS["publication"],
            chart_x,
            chart_y,
            chart_w,
            chart_h,
            min_count,
            max_count,
        )
    )
    parts.append(
        render_metric_line(
            rows,
            "main_tool_benchmark_evidence_coverage",
            COLORS["benchmark"],
            chart_x,
            chart_y,
            chart_w,
            chart_h,
            min_count,
            max_count,
        )
    )
    parts.append(
        f'<text x="{x + 28}" y="{y + height - 24}" font-size="13" fill="{COLORS["muted"]}">Publication/benchmark support rates are local to the v0.2 blind top-k main tools. They are not whole-KG completeness rates.</text>'
    )
    return "\n".join(parts)


def render_card(x: int, y: int, width: int, height: int, title: str, value: str, subtitle: str, color: str) -> str:
    return "\n".join(
        [
            f'<rect x="{x}" y="{y}" width="{width}" height="{height}" rx="14" fill="#ffffff" stroke="#e2e8f0"/>',
            f'<text x="{x + 18}" y="{y + 28}" font-size="13" font-weight="850" fill="{COLORS["muted"]}">{esc(title)}</text>',
            f'<text x="{x + 18}" y="{y + 70}" font-size="30" font-weight="900" fill="{color}">{esc(value)}</text>',
            f'<text x="{x + 18}" y="{y + 96}" font-size="12" fill="{COLORS["muted"]}">{esc(subtitle)}</text>',
        ]
    )


def render_side_panel(rows: List[Dict[str, object]], x: int, y: int, width: int, height: int) -> str:
    trend_rows = [row for row in rows if row["connected_scale_trend"]]
    first = trend_rows[0]
    last = trend_rows[-1]
    governance = [row for row in rows if not row["connected_scale_trend"]][0]
    parts = [
        f'<rect x="{x}" y="{y}" width="{width}" height="{height}" rx="18" fill="#ffffff" stroke="{COLORS["border"]}"/>',
        f'<text x="{x + 24}" y="{y + 38}" font-size="22" font-weight="900" fill="{COLORS["text"]}">What Actually Improved</text>',
        f'<text x="{x + 24}" y="{y + 64}" font-size="14" fill="{COLORS["muted"]}">Data scale first; policy fix second.</text>',
        render_card(
            x + 24,
            y + 88,
            width - 48,
            112,
            "Formal evidence records",
            f'{first["formal_evidence_count"]} -> {last["formal_evidence_count"]}',
            f'{first["formal_publication_count"]} -> {last["formal_publication_count"]} papers; {first["formal_benchmark_count"]} -> {last["formal_benchmark_count"]} benchmarks',
            COLORS["main"],
        ),
        render_card(
            x + 24,
            y + 216,
            width - 48,
            112,
            "Top-k main-tool evidence",
            f'{fmt_pct(first["main_tool_recommendation_evidence_coverage"])} -> {fmt_pct(last["main_tool_recommendation_evidence_coverage"])}',
            "Main tool has publication and/or benchmark support.",
            COLORS["main"],
        ),
        render_card(
            x + 24,
            y + 344,
            width - 48,
            112,
            "Benchmark-backed support",
            f'{fmt_pct(first["main_tool_benchmark_evidence_coverage"])} -> {fmt_pct(last["main_tool_benchmark_evidence_coverage"])}',
            "This is the stronger claim for benchmark ingestion.",
            COLORS["benchmark"],
        ),
        render_card(
            x + 24,
            y + 472,
            width - 48,
            112,
            "MCDM v2",
            f'{governance["formal_evidence_count"]} records',
            "Same KG size; qualitative/caveat evidence is stricter.",
            "#7c3aed",
        ),
    ]
    return "\n".join(parts)


def render_explanation(rows: List[Dict[str, object]], x: int, y: int, width: int, height: int) -> str:
    governance = [row for row in rows if not row["connected_scale_trend"]][0]
    parts = [
        f'<rect x="{x}" y="{y}" width="{width}" height="{height}" rx="18" fill="#ffffff" stroke="{COLORS["border"]}"/>',
        f'<text x="{x + 28}" y="{y + 40}" font-size="22" font-weight="900" fill="{COLORS["text"]}">Interpretation Guardrails</text>',
        f'<text x="{x + 28}" y="{y + 76}" font-size="15" fill="{COLORS["text"]}">1. 100% publication support means every evaluated top-k main tool had canonical publication evidence in this blind set; it does not mean the whole KG has complete publications.</text>',
        f'<text x="{x + 28}" y="{y + 108}" font-size="15" fill="{COLORS["text"]}">2. Benchmark support is lower because reviewed benchmark evidence is task-specific and harder to curate than canonical papers.</text>',
        f'<text x="{x + 28}" y="{y + 140}" font-size="15" fill="{COLORS["text"]}">3. The scale trend should use the first three connected points. MCDM v2 is a governance/scoring policy reference at the same 42-record KG scale.</text>',
        f'<text x="{x + 28}" y="{y + 172}" font-size="15" fill="{COLORS["text"]}">4. Under MCDM v2, C-route benchmark support is {fmt_pct(governance["main_tool_benchmark_evidence_coverage"])} because the audited output is stricter; this should not be sold as a data-scale gain.</text>',
        f'<text x="{x + 28}" y="{y + 214}" font-size="13" fill="{COLORS["muted"]}">v0.1 prototype is intentionally excluded from the trend line because it used an earlier protocol; mixing it with v0.2 blind KG-scale snapshots creates the misleading jump you flagged.</text>',
    ]
    return "\n".join(parts)


def render_svg(rows: List[Dict[str, object]]) -> str:
    width = 1680
    height = 1260
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#f8fafc"/>',
        '<text x="64" y="72" font-size="38" font-weight="900" fill="#0f172a">scKG KG-Scale Performance Roadmap</text>',
        '<text x="64" y="110" font-size="18" fill="#475569">A healthier story: as the reviewed formal KG grows, recommendation evidence support improves.</text>',
        '<rect x="64" y="136" width="1552" height="76" rx="18" fill="#eff6ff" stroke="#2563eb"/>',
        '<text x="92" y="168" font-size="20" font-weight="850" fill="#1e3a8a">Use KG evidence scale as the x-axis; do not frame publication support as whole-library completeness.</text>',
        '<text x="92" y="194" font-size="14" fill="#1e40af">The key claim is benchmark-backed support growth from 50.0% to 77.8% as formal evidence grows from 32 to 42 records.</text>',
        render_main_chart(rows, 64, 246, 1120, 580),
        render_side_panel(rows, 1212, 246, 404, 580),
        render_explanation(rows, 64, 866, 1552, 270),
    ]
    y = 1172
    for index, row in enumerate(rows):
        text = (
            f'{row["label"]}: {row["formal_evidence_count"]} formal evidence, '
            f'{row["formal_publication_count"]} papers, {row["formal_benchmark_count"]} benchmarks, '
            f'C top-k {fmt_pct(row["top_k_hit"])}, C benchmark support {fmt_pct(row["main_tool_benchmark_evidence_coverage"])}'
        )
        parts.append(
            f'<text x="64" y="{y + index * 18}" font-size="12" fill="{COLORS["muted"]}">{esc(text)}</text>'
        )
    parts.append("</svg>")
    return "\n".join(parts)


def write_table(rows: List[Dict[str, object]], path: Path) -> None:
    fieldnames = [
        "name",
        "label",
        "connected_scale_trend",
        "formal_tool_count",
        "formal_evidence_count",
        "formal_publication_count",
        "formal_benchmark_count",
        "top_k_hit",
        "recommendation_type_accuracy",
        "evidence_coverage",
        "recommendation_evidence_coverage",
        "main_tool_recommendation_evidence_coverage",
        "main_tool_publication_evidence_coverage",
        "main_tool_benchmark_evidence_coverage",
        "semantic_audit_pass_rate",
        "high_hallucination_rate",
        "note",
        "plan_path",
        "prediction_path",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter="\t")
        writer.writeheader()
        for row in rows:
            out = {}
            for key in fieldnames:
                value = row.get(key)
                if isinstance(value, Path):
                    value = str(value.relative_to(PROJECT_ROOT))
                out[key] = value
            writer.writerow(out)


def main() -> None:
    parser = argparse.ArgumentParser(description="Render KG-scale performance roadmap.")
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "eval" / "scKG_v0_2_kg_scale_performance_roadmap.svg",
    )
    parser.add_argument(
        "--table-output",
        type=Path,
        default=PROJECT_ROOT / "eval" / "scKG_v0_2_kg_scale_performance_roadmap.tsv",
    )
    args = parser.parse_args()

    rows = build_rows(SNAPSHOTS)
    args.output.write_text(render_svg(rows), encoding="utf-8")
    write_table(rows, args.table_output)
    print(f"wrote {args.output}")
    print(f"wrote {args.table_output}")


if __name__ == "__main__":
    main()
