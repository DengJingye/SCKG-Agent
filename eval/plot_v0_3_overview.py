import argparse
import csv
import html
from pathlib import Path
from typing import Dict, List, Optional


PROJECT_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_RECOMMENDATION_SUMMARY = (
    PROJECT_ROOT
    / "eval"
    / "ablation_deepseek_aura_v0_2_blind_after_mcdm_qual_benchmark_fix_v2"
    / "ablation_summary.tsv"
)
DEFAULT_MIGRATION_SUMMARY = PROJECT_ROOT / "eval" / "migration_v0_3_1_eval_summary.tsv"
DEFAULT_OUTPUT = PROJECT_ROOT / "eval" / "scKG_v0_3_recommendation_migration_overview.svg"

MODE_LABELS = {
    "pure_llm": "Pure LLM",
    "evidence_gate": "Evidence Gate",
    "evidence_gate_auditor": "Gate + Auditor",
    "full_kg_pipeline": "Full KG",
}

MODE_COLORS = {
    "pure_llm": "#6b7280",
    "evidence_gate": "#2563eb",
    "evidence_gate_auditor": "#059669",
    "full_kg_pipeline": "#7c3aed",
}


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def parse_float(value: str | None) -> Optional[float]:
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def fmt_percent(value: Optional[float]) -> str:
    if value is None:
        return "N/A"
    return f"{value * 100:.1f}%"


def fmt_seconds(value: Optional[float]) -> str:
    if value is None:
        return "N/A"
    return f"{value:.1f}s"


def fmt_score(value: Optional[float]) -> str:
    if value is None:
        return "N/A"
    return f"{value:.3f}"


def load_recommendation_summary(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def load_migration_summary(path: Path) -> dict[str, dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    return {row["metric"]: row for row in rows}


def row_for_mode(rows: List[Dict[str, str]], mode: str) -> dict[str, str]:
    for row in rows:
        if row.get("mode") == mode:
            return row
    return {}


def rec_value(rows: List[Dict[str, str]], mode: str, metric: str) -> Optional[float]:
    return parse_float(row_for_mode(rows, mode).get(metric))


def mig_value(metrics: dict[str, dict[str, str]], metric: str) -> Optional[float]:
    return parse_float(metrics.get(metric, {}).get("value"))


def card(
    x: int,
    y: int,
    width: int,
    height: int,
    title: str,
    value: str,
    subtitle: str,
    color: str,
) -> str:
    return "\n".join(
        [
            f'<rect x="{x}" y="{y}" width="{width}" height="{height}" rx="16" fill="#ffffff" stroke="#d1d5db"/>',
            f'<text x="{x + 24}" y="{y + 32}" font-size="15" font-weight="700" fill="#374151">{esc(title)}</text>',
            f'<text x="{x + 24}" y="{y + 78}" font-size="34" font-weight="800" fill="{color}">{esc(value)}</text>',
            f'<text x="{x + 24}" y="{y + 108}" font-size="13" fill="#6b7280">{esc(subtitle)}</text>',
        ]
    )


def horizontal_bar(
    x: int,
    y: int,
    width: int,
    label: str,
    value: Optional[float],
    color: str,
    formatter=fmt_percent,
    max_value: float = 1.0,
) -> str:
    bar_x = x + 170
    bar_w = width - 260
    fill_w = 0.0 if value is None else max(0.0, min(value / max_value, 1.0)) * bar_w
    value_text = formatter(value)
    return "\n".join(
        [
            f'<text x="{x}" y="{y + 16}" font-size="14" fill="#374151">{esc(label)}</text>',
            f'<rect x="{bar_x}" y="{y}" width="{bar_w}" height="20" rx="10" fill="#e5e7eb"/>',
            f'<rect x="{bar_x}" y="{y}" width="{fill_w:.1f}" height="20" rx="10" fill="{color}"/>',
            f'<text x="{bar_x + bar_w + 14}" y="{y + 16}" font-size="14" font-weight="700" fill="#111827">{esc(value_text)}</text>',
        ]
    )


def render_route_bars(rows: List[Dict[str, str]], x: int, y: int, width: int) -> str:
    parts = [
        f'<rect x="{x}" y="{y}" width="{width}" height="266" rx="16" fill="#ffffff" stroke="#d1d5db"/>',
        f'<text x="{x + 24}" y="{y + 36}" font-size="22" font-weight="800" fill="#111827">Recommendation Route Comparison</text>',
        f'<text x="{x + 24}" y="{y + 62}" font-size="14" fill="#6b7280">Blind v0.2 set; C is the default safety route.</text>',
    ]
    modes = ["pure_llm", "evidence_gate", "evidence_gate_auditor", "full_kg_pipeline"]
    yy = y + 92
    for mode in modes:
        value = rec_value(rows, mode, "top_k_hit")
        color = MODE_COLORS.get(mode, "#111827")
        parts.append(horizontal_bar(x + 24, yy, width - 48, MODE_LABELS.get(mode, mode), value, color))
        yy += 40
    return "\n".join(parts)


def render_latency_bars(rows: List[Dict[str, str]], x: int, y: int, width: int) -> str:
    parts = [
        f'<rect x="{x}" y="{y}" width="{width}" height="266" rx="16" fill="#ffffff" stroke="#d1d5db"/>',
        f'<text x="{x + 24}" y="{y + 36}" font-size="22" font-weight="800" fill="#111827">Cost and Latency Diagnostic</text>',
        f'<text x="{x + 24}" y="{y + 62}" font-size="14" fill="#6b7280">Full KG remains useful as an exploration baseline, not the default route.</text>',
    ]
    modes = ["pure_llm", "evidence_gate", "evidence_gate_auditor", "full_kg_pipeline"]
    max_latency = max(
        [rec_value(rows, mode, "mean_latency_seconds") or 0.0 for mode in modes] + [1.0]
    )
    yy = y + 92
    for mode in modes:
        value = rec_value(rows, mode, "mean_latency_seconds")
        color = MODE_COLORS.get(mode, "#111827")
        parts.append(
            horizontal_bar(
                x + 24,
                yy,
                width - 48,
                MODE_LABELS.get(mode, mode),
                value,
                color,
                formatter=fmt_seconds,
                max_value=max_latency,
            )
        )
        yy += 40
    return "\n".join(parts)


def render_svg(
    recommendation_rows: List[Dict[str, str]],
    migration_metrics: Dict[str, Dict[str, str]],
    recommendation_path: Path,
    migration_path: Path,
    subtitle: str,
) -> str:
    width = 1600
    height = 1280
    c = row_for_mode(recommendation_rows, "evidence_gate_auditor")
    b = row_for_mode(recommendation_rows, "evidence_gate")
    d = row_for_mode(recommendation_rows, "full_kg_pipeline")

    c_top_hit = parse_float(c.get("top_k_hit"))
    c_benchmark = parse_float(c.get("main_tool_benchmark_evidence_coverage"))
    c_high_hallucination = parse_float(c.get("high_hallucination_rate"))
    c_audit_pass = parse_float(c.get("semantic_audit_pass_rate"))
    b_top_hit = parse_float(b.get("top_k_hit"))
    d_latency = parse_float(d.get("mean_latency_seconds"))

    migration_hit = mig_value(migration_metrics, "top_k_source_tool_hit")
    migration_output = mig_value(migration_metrics, "migration_output_type_hit")
    migration_forbidden = max(
        mig_value(migration_metrics, "forbidden_tool_violation_rate") or 0.0,
        mig_value(migration_metrics, "forbidden_claim_violation_rate") or 0.0,
    )
    caveat = mig_value(migration_metrics, "caveat_presence_rate")
    boundary = mig_value(migration_metrics, "claim_boundary_presence_rate")
    compatibility = mig_value(migration_metrics, "compatibility_gap_presence_rate")
    revise_block = mig_value(migration_metrics, "revise_block_success_rate")
    unreviewed = mig_value(migration_metrics, "unreviewed_migration_path_rate")
    plausibility = mig_value(migration_metrics, "mean_migration_plausibility_score")

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#f8fafc"/>',
        f'<text x="64" y="70" font-size="36" font-weight="850" fill="#0f172a">scKG Agent v0.3 Overview</text>',
        f'<text x="64" y="106" font-size="18" fill="#475569">{esc(subtitle)}</text>',
        '<rect x="64" y="132" width="1472" height="84" rx="18" fill="#ecfdf5" stroke="#10b981"/>',
        '<text x="92" y="166" font-size="21" font-weight="800" fill="#065f46">System thesis: trusted recommendation is separated from exploratory algorithm migration.</text>',
        '<text x="92" y="194" font-size="15" fill="#134e4a">Formal recommendation uses reviewed evidence and auditor checks; migration outputs are hypothesis candidates with caveats and compatibility gaps.</text>',
    ]

    # Recommendation layer.
    parts.extend(
        [
            '<text x="64" y="274" font-size="28" font-weight="850" fill="#111827">Layer 1: Evidence-Governed Recommendation</text>',
            '<text x="64" y="304" font-size="15" fill="#64748b">Default route: Evidence Gate + Auditor. Evidence Gate alone measures ranking; Auditor measures user-visible safety.</text>',
            card(64, 330, 270, 132, "C top-k hit", fmt_percent(c_top_hit), "expected tool in top-3", "#059669"),
            card(354, 330, 270, 132, "C benchmark evidence", fmt_percent(c_benchmark), "main-tool benchmark coverage", "#2563eb"),
            card(644, 330, 270, 132, "C high hallucination", fmt_percent(c_high_hallucination), "lower is better", "#dc2626"),
            card(934, 330, 270, 132, "C audit pass", fmt_percent(c_audit_pass), "semantic audit pass", "#059669"),
            card(1224, 330, 312, 132, "D mean latency", fmt_seconds(d_latency), "full KG diagnostic route", "#7c3aed"),
            render_route_bars(recommendation_rows, 64, 492, 710),
            render_latency_bars(recommendation_rows, 826, 492, 710),
        ]
    )

    # Migration layer.
    parts.extend(
        [
            '<text x="64" y="818" font-size="28" font-weight="850" fill="#111827">Layer 2: Algorithm Migration Hypothesis</text>',
            '<text x="64" y="848" font-size="15" fill="#64748b">Migration is exploratory only. It surfaces transferable mechanisms, I/O gaps, and validation requirements; it does not enter main recommendation top-k.</text>',
            card(64, 874, 270, 132, "Migration output", fmt_percent(migration_output), "correct exploratory type", "#059669"),
            card(354, 874, 270, 132, "Source-tool hit", fmt_percent(migration_hit), "expected source in top-3", "#059669"),
            card(644, 874, 270, 132, "Forbidden violations", fmt_percent(migration_forbidden), "tool or strong-claim violations", "#dc2626"),
            card(934, 874, 270, 132, "Caveat presence", fmt_percent(caveat), "explicit validation language", "#2563eb"),
            card(1224, 874, 312, 132, "Claim boundary", fmt_percent(boundary), "exploratory boundary visible", "#2563eb"),
        ]
    )

    parts.append('<rect x="64" y="1036" width="1472" height="156" rx="18" fill="#ffffff" stroke="#d1d5db"/>')
    parts.append('<text x="92" y="1072" font-size="22" font-weight="800" fill="#111827">Migration Governance Diagnostics</text>')
    diagnostics = [
        ("Compatibility gaps surfaced", fmt_percent(compatibility)),
        ("Revise mechanism blocked", fmt_percent(revise_block)),
        ("Profile-only path rate", fmt_percent(unreviewed)),
        ("Mean plausibility score", fmt_score(plausibility)),
        ("Evidence Gate top-k", fmt_percent(b_top_hit)),
    ]
    for index, (label, value) in enumerate(diagnostics):
        x = 92 + index * 285
        parts.append(f'<text x="{x}" y="1120" font-size="13" fill="#64748b">{esc(label)}</text>')
        parts.append(f'<text x="{x}" y="1150" font-size="25" font-weight="850" fill="#0f172a">{esc(value)}</text>')

    parts.extend(
        [
            '<text x="64" y="1232" font-size="14" fill="#64748b">N/A audit values mean audit was not run for that route; they are not zero-risk results. Profile-only migration paths remain candidate-layer and need review before stronger claims.</text>',
            f'<text x="64" y="1254" font-size="13" fill="#64748b">Recommendation summary: {esc(recommendation_path)}</text>',
            f'<text x="64" y="1272" font-size="13" fill="#64748b">Migration summary: {esc(migration_path)}</text>',
            "</svg>",
        ]
    )
    return "\n".join(parts)


def main() -> None:
    parser = argparse.ArgumentParser(description="Render a combined v0.3 recommendation and migration overview SVG.")
    parser.add_argument("--recommendation-summary", type=Path, default=DEFAULT_RECOMMENDATION_SUMMARY)
    parser.add_argument("--migration-summary", type=Path, default=DEFAULT_MIGRATION_SUMMARY)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--subtitle",
        default="Evidence-governed recommendation plus exploratory migration hypotheses",
    )
    args = parser.parse_args()

    recommendation_rows = load_recommendation_summary(args.recommendation_summary)
    migration_metrics = load_migration_summary(args.migration_summary)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        render_svg(
            recommendation_rows,
            migration_metrics,
            args.recommendation_summary,
            args.migration_summary,
            args.subtitle,
        ),
        encoding="utf-8",
    )
    print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
