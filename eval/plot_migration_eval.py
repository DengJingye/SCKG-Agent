import argparse
import csv
import html
import re
from pathlib import Path
from typing import Dict, Optional


PROJECT_ROOT = Path(__file__).resolve().parent.parent

PANELS = [
    ("Source-tool hit", "top_k_source_tool_hit", "higher", "percent"),
    ("Forbidden violations", "combined_forbidden_violation_rate", "lower", "percent"),
    ("Caveat + boundary", "boundary_and_caveat_rate", "higher", "percent"),
    ("Compatibility gaps", "compatibility_gap_presence_rate", "higher", "percent"),
    ("Mean plausibility", "mean_migration_plausibility_score", "diagnostic", "score"),
    ("Audit safety", "semantic_audit_pass_rate", "higher", "percent"),
]

MIXED_PANELS = [
    ("Mixed decision accuracy", "mixed_decision_accuracy", "higher", "percent"),
    ("Positive source hit", "positive_source_tool_hit", "higher", "percent"),
    ("False migration", "negative_false_migration_rate", "lower", "percent"),
    ("Clarification success", "clarification_success_rate", "higher", "percent"),
    ("Revise success", "revise_decision_success_rate", "higher", "percent"),
    ("Trap avoidance", "trap_avoidance_rate", "higher", "percent"),
]

COLORS = {
    "higher": "#059669",
    "lower": "#dc2626",
    "diagnostic": "#2563eb",
}


def load_summary(path: Path) -> dict[str, dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    return {row["metric"]: row for row in rows}


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


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def fmt_value(value: Optional[float], unit: str) -> str:
    if value is None:
        return "N/A"
    if unit == "percent":
        return f"{value * 100:.1f}%"
    return f"{value:.3f}"


def metric_value(summary: dict[str, dict[str, str]], metric: str) -> Optional[float]:
    if metric == "combined_forbidden_violation_rate":
        values = [
            parse_float(summary.get("forbidden_tool_violation_rate", {}).get("value")),
            parse_float(summary.get("forbidden_claim_violation_rate", {}).get("value")),
        ]
        values = [value for value in values if value is not None]
        return max(values) if values else None
    if metric == "boundary_and_caveat_rate":
        values = [
            parse_float(summary.get("caveat_presence_rate", {}).get("value")),
            parse_float(summary.get("claim_boundary_presence_rate", {}).get("value")),
        ]
        values = [value for value in values if value is not None]
        return min(values) if values else None
    return parse_float(summary.get(metric, {}).get("value"))


def subtitle_for(direction: str) -> str:
    if direction == "higher":
        return "higher is better"
    if direction == "lower":
        return "lower is better"
    return "diagnostic score, not a recommendation rank"


def infer_version(path: Path) -> str:
    text = path.as_posix()
    matches = re.findall(r"v(\d+)_(\d+)(?:_(\d+))?", text)
    if not matches:
        return "current"
    major, minor, patch = matches[-1]
    version = f"v{major}.{minor}"
    if patch:
        version += f".{patch}"
    return version


def infer_benchmark_label(path: Path) -> str:
    text = path.as_posix().lower()
    if "challenge" in text:
        return "Challenge"
    if "heldout" in text or "held-out" in text:
        return "Held-out"
    if "mixed" in text:
        return "Mixed"
    if "blind" in text:
        return "Blind"
    return "Migration"


def infer_title(summary: dict[str, dict[str, str]], summary_path: Path) -> str:
    version = infer_version(summary_path)
    label = infer_benchmark_label(summary_path)
    is_mixed = "mixed_decision_accuracy" in summary
    if is_mixed:
        return f"scKG {version} {label} Migration Benchmark"
    return f"scKG {version} Migration Hypothesis Evaluation"


def render_panel(
    summary: dict[str, dict[str, str]],
    title: str,
    metric: str,
    direction: str,
    unit: str,
    x: int,
    y: int,
    width: int,
    height: int,
) -> str:
    value = metric_value(summary, metric)
    color = COLORS.get(direction, "#111827")
    max_value = 1.0
    fill_width = 0.0 if value is None else max(0.0, min(value / max_value, 1.0)) * (width - 70)
    label = fmt_value(value, unit)
    parts = [
        f'<rect x="{x}" y="{y}" width="{width}" height="{height}" rx="16" fill="#ffffff" stroke="#d1d5db"/>',
        f'<text x="{x + 28}" y="{y + 36}" font-size="22" font-weight="750" fill="#111827">{esc(title)}</text>',
        f'<text x="{x + 28}" y="{y + 62}" font-size="14" fill="#6b7280">{esc(subtitle_for(direction))}</text>',
        f'<text x="{x + 28}" y="{y + 112}" font-size="34" font-weight="800" fill="{color}">{esc(label)}</text>',
        f'<rect x="{x + 28}" y="{y + 140}" width="{width - 70}" height="20" rx="10" fill="#e5e7eb"/>',
    ]
    if value is not None:
        parts.append(
            f'<rect x="{x + 28}" y="{y + 140}" width="{fill_width:.1f}" height="20" rx="10" fill="{color}"/>'
        )
    else:
        parts.append(
            f'<text x="{x + 28}" y="{y + 186}" font-size="13" fill="#6b7280">metric not available</text>'
        )
    return "\n".join(parts)


def render_svg(
    summary: dict[str, dict[str, str]],
    summary_path: Path,
    subtitle: str,
    title: Optional[str] = None,
) -> str:
    width = 1480
    height = 1020
    panel_w = 430
    panel_h = 220
    is_mixed = "mixed_decision_accuracy" in summary
    title = title or infer_title(summary, summary_path)
    panels = MIXED_PANELS if is_mixed else PANELS
    query_count = metric_value(summary, "query_count")
    revise_block = metric_value(summary, "revise_block_success_rate")
    accepted = metric_value(summary, "accepted_hypothesis_rate")
    unreviewed = metric_value(summary, "unreviewed_migration_path_rate")
    mean_io = metric_value(summary, "mean_io_compatibility")
    mean_jaccard = metric_value(summary, "mean_graph_jaccard")
    mean_risk = metric_value(summary, "mean_risk_penalty")
    true_positive = metric_value(summary, "true_positive_count")
    true_negative = metric_value(summary, "true_negative_count")
    clarify_count = metric_value(summary, "needs_clarification_count")
    revise_count = metric_value(summary, "revise_only_count")
    trap_count = metric_value(summary, "retrieval_trap_count")

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#f3f4f6"/>',
        f'<text x="60" y="66" font-size="34" font-weight="800" fill="#111827">{esc(title)}</text>',
        f'<text x="60" y="100" font-size="18" fill="#4b5563">{esc(subtitle)}</text>',
        '<rect x="60" y="126" width="1360" height="82" rx="16" fill="#eff6ff" stroke="#60a5fa"/>',
        (
            '<text x="86" y="160" font-size="20" font-weight="750" fill="#1e3a8a">Takeaway: the mixed benchmark exposes real gaps; the goal is calibrated behavior, not perfect positive-only scores.</text>'
            if is_mixed
            else '<text x="86" y="160" font-size="20" font-weight="750" fill="#1e3a8a">Takeaway: migration is now a measurable exploratory layer, separated from formal tool recommendation.</text>'
        ),
        (
            '<text x="86" y="186" font-size="15" fill="#1f2937">Positive, revise-only, negative, clarification, and trap cases are scored separately to reveal false migration and refusal failures.</text>'
            if is_mixed
            else '<text x="86" y="186" font-size="15" fill="#1f2937">Scores describe plausibility and compatibility signals; they are not benchmark proof, not a direct-use guarantee, and not main top-k recommendation evidence.</text>'
        ),
    ]

    positions = [(60, 246), (525, 246), (990, 246), (60, 500), (525, 500), (990, 500)]
    for panel, position in zip(panels, positions):
        parts.append(
            render_panel(
                summary,
                *panel,
                x=position[0],
                y=position[1],
                width=panel_w,
                height=panel_h,
            )
        )

    if is_mixed:
        stats = [
            ("Queries", f"{int(query_count or 0)}"),
            ("Positive cases", f"{int(true_positive or 0)}"),
            ("Revise-only cases", f"{int(revise_count or 0)}"),
            ("Negative cases", f"{int(true_negative or 0)}"),
            ("Clarification cases", f"{int(clarify_count or 0)}"),
            ("Trap cases", f"{int(trap_count or 0)}"),
            ("Unreviewed path rate", fmt_value(unreviewed, "percent")),
        ]
    else:
        stats = [
            ("Queries", f"{int(query_count or 0)}"),
            ("Accepted reviewed paths", fmt_value(accepted, "percent")),
            ("Unreviewed path rate", fmt_value(unreviewed, "percent")),
            ("Revise-block success", fmt_value(revise_block, "percent")),
            ("Mean I/O compatibility", fmt_value(mean_io, "score")),
            ("Mean graph Jaccard", fmt_value(mean_jaccard, "score")),
            ("Mean risk penalty", fmt_value(mean_risk, "score")),
        ]
    parts.append('<rect x="60" y="756" width="1360" height="178" rx="16" fill="#ffffff" stroke="#d1d5db"/>')
    parts.append('<text x="86" y="792" font-size="22" font-weight="750" fill="#111827">Governance Diagnostics</text>')
    for index, (name, value) in enumerate(stats):
        col = index % 4
        row = index // 4
        sx = 86 + col * 330
        sy = 836 + row * 58
        parts.append(f'<text x="{sx}" y="{sy}" font-size="13" fill="#6b7280">{esc(name)}</text>')
        parts.append(f'<text x="{sx}" y="{sy + 26}" font-size="24" font-weight="800" fill="#111827">{esc(value)}</text>')

    parts.extend(
        [
            (
                '<text x="60" y="970" font-size="14" fill="#6b7280">False migration measures reject/clarify cases that still surfaced migration; lower is better and should drive the next fixes.</text>'
                if is_mixed
                else '<text x="60" y="970" font-size="14" fill="#6b7280">Forbidden claim checks ignore explicit negated boundary statements such as "not a validated performance claim".</text>'
            ),
            f'<text x="60" y="992" font-size="14" fill="#6b7280">Generated from {esc(summary_path)}.</text>',
            "</svg>",
        ]
    )
    return "\n".join(parts)


def main() -> None:
    parser = argparse.ArgumentParser(description="Render migration evaluation summary as SVG.")
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--subtitle",
        default="v0.3.1 offline deterministic migration evaluation",
    )
    parser.add_argument(
        "--title",
        default=None,
        help="Optional explicit chart title. Defaults to inferring version/type from --summary path.",
    )
    args = parser.parse_args()
    summary = load_summary(args.summary)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        render_svg(summary, args.summary, args.subtitle, title=args.title),
        encoding="utf-8",
    )
    print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
