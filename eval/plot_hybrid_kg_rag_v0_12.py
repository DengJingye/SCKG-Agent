import argparse
import csv
import html
import json
from pathlib import Path
from typing import Any, Dict, Optional


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONTEXT_AUDIT = PROJECT_ROOT / "eval" / "context_pack_v0_12_report_smoke_audit_summary.json"
DEFAULT_MIGRATION_SUMMARY = PROJECT_ROOT / "eval" / "context_pack_v0_12_report_smoke_migration_eval_summary.tsv"
DEFAULT_OUTPUT = PROJECT_ROOT / "eval" / "context_pack_v0_12_hybrid_kg_rag_overview.svg"


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def parse_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(str(value).strip())
    except ValueError:
        return None


def fmt_percent(value: Optional[float]) -> str:
    if value is None:
        return "N/A"
    return f"{value * 100:.1f}%"


def fmt_num(value: Optional[float]) -> str:
    if value is None:
        return "N/A"
    if abs(value - round(value)) < 1e-9:
        return str(int(round(value)))
    return f"{value:.3f}"


def load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_metric_tsv(path: Path) -> Dict[str, float]:
    metrics: Dict[str, float] = {}
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            value = parse_float(row.get("value"))
            if value is not None:
                metrics[row.get("metric", "")] = value
    return metrics


def card(x: int, y: int, w: int, h: int, title: str, value: str, subtitle: str, color: str) -> str:
    return "\n".join(
        [
            f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="10" fill="#ffffff" stroke="#cbd5e1"/>',
            f'<text x="{x + 20}" y="{y + 31}" font-size="14" font-weight="700" fill="#334155">{esc(title)}</text>',
            f'<text x="{x + 20}" y="{y + 72}" font-size="31" font-weight="850" fill="{color}">{esc(value)}</text>',
            f'<text x="{x + 20}" y="{y + 102}" font-size="12" fill="#64748b">{esc(subtitle)}</text>',
        ]
    )


def box(x: int, y: int, w: int, h: int, title: str, body: list[str], fill: str, stroke: str) -> str:
    parts = [
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="12" fill="{fill}" stroke="{stroke}" stroke-width="1.5"/>',
        f'<text x="{x + 18}" y="{y + 32}" font-size="18" font-weight="800" fill="#0f172a">{esc(title)}</text>',
    ]
    for i, line in enumerate(body[:5]):
        parts.append(f'<text x="{x + 18}" y="{y + 62 + i * 24}" font-size="13" fill="#334155">{esc(line)}</text>')
    return "\n".join(parts)


def arrow(x1: int, y1: int, x2: int, y2: int, label: str = "") -> str:
    mid_x = (x1 + x2) / 2
    mid_y = (y1 + y2) / 2
    parts = [
        f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="#475569" stroke-width="2.4" marker-end="url(#arrow)"/>',
    ]
    if label:
        parts.append(
            f'<text x="{mid_x}" y="{mid_y - 8}" text-anchor="middle" font-size="12" font-weight="700" fill="#475569">{esc(label)}</text>'
        )
    return "\n".join(parts)


def render_svg(context_audit: Dict[str, Any], migration: Dict[str, float], context_path: Path, migration_path: Path, subtitle: str) -> str:
    width = 1640
    height = 1260
    status_counts = context_audit.get("status_counts", {})
    pass_count = int(status_counts.get("pass", 0) + status_counts.get("pass_rebuilt", 0))
    query_count = parse_float(context_audit.get("query_count")) or 0
    context_pass = pass_count / query_count if query_count else None

    mean_rag = parse_float(context_audit.get("mean_formal_rag_snippet_count"))
    migration_paths = parse_float(context_audit.get("total_migration_context_paths"))
    excluded_paths = parse_float(context_audit.get("total_excluded_migration_paths"))
    rankable_violations = parse_float(context_audit.get("total_retrieval_rankable_violations"))
    trusted_violations = parse_float(context_audit.get("total_trusted_non_main_violations"))
    bad_migrations = parse_float(context_audit.get("total_migration_bad_decision_violations"))

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<defs><marker id="arrow" markerWidth="12" markerHeight="12" refX="9" refY="3" orient="auto" markerUnits="strokeWidth"><path d="M0,0 L0,6 L9,3 z" fill="#475569"/></marker></defs>',
        '<rect width="100%" height="100%" fill="#f8fafc"/>',
        '<text x="64" y="68" font-size="36" font-weight="850" fill="#0f172a">scKG Agent v0.12 Minimal Hybrid KG-RAG</text>',
        f'<text x="64" y="104" font-size="18" fill="#475569">{esc(subtitle)}</text>',
        '<rect x="64" y="130" width="1512" height="82" rx="14" fill="#ecfdf5" stroke="#10b981"/>',
        '<text x="92" y="164" font-size="21" font-weight="800" fill="#065f46">LLM does synthesis; KG sets evidence and constraints; RAG explains provenance; Auditor blocks unsafe claims.</text>',
        '<text x="92" y="192" font-size="14" fill="#134e4a">This figure is generated from offline ContextPack and migration-eval outputs. No paid LLM call, no Neo4j write, no formal evidence mutation.</text>',
    ]

    parts.extend(
        [
            card(64, 246, 245, 120, "ContextPack audit", fmt_percent(context_pass), "boundary checks passed", "#059669"),
            card(329, 246, 245, 120, "RAG snippets", fmt_num(mean_rag), "mean formal snippets/query", "#2563eb"),
            card(594, 246, 245, 120, "Migration paths", fmt_num(migration_paths), "accepted context paths", "#7c3aed"),
            card(859, 246, 245, 120, "Excluded paths", fmt_num(excluded_paths), "kept in blocked context", "#d97706"),
            card(1124, 246, 215, 120, "High hallucination", fmt_percent(migration.get("high_hallucination_rate")), "offline smoke", "#dc2626"),
            card(1359, 246, 217, 120, "Unsafe claims", fmt_percent(migration.get("unsupported_tool_claim_rate")), "unsupported tool claims", "#dc2626"),
        ]
    )

    y = 430
    parts.extend(
        [
            box(64, y, 245, 178, "User Query", ["Task, modality, constraints", "May ask recommendation", "May ask migration idea", "May be under-specified"], "#ffffff", "#cbd5e1"),
            box(356, y, 260, 178, "Parser + Gate", ["Task ontology", "Tool-task-modality filter", "Migration intent gate", "Blocked tools / missing inputs"], "#eff6ff", "#60a5fa"),
            box(664, y, 260, 178, "KG Evidence Layer", ["trusted_core evidence", "publications / benchmarks", "MCDM ranking inputs", "candidate evidence isolated"], "#f0fdf4", "#22c55e"),
            box(972, y, 260, 178, "Formal RAG Layer", ["reviewed TSV snippets", "DOI / protocol / claim span", "explanation only", "does not change score"], "#fff7ed", "#fb923c"),
            box(1280, y, 296, 178, "ContextPack", ["trusted_recommendation_context", "retrieval_context", "migration_context", "blocked_context", "prompt_policy"], "#faf5ff", "#a855f7"),
            arrow(309, y + 89, 356, y + 89, "parse"),
            arrow(616, y + 89, 664, y + 89, "filter"),
            arrow(924, y + 72, 972, y + 72, "retrieve"),
            arrow(1232, y + 89, 1280, y + 89, "pack"),
        ]
    )

    y2 = 688
    parts.extend(
        [
            box(64, y2, 352, 186, "Recommendation Output", ["Primary top-k comes from KG + MCDM", "Only trusted recommendation evidence can rank", "RAG snippets may explain why", "Missing evidence stays visible"], "#ffffff", "#cbd5e1"),
            box(464, y2, 352, 186, "MigrationHypothesis Output", ["Exploratory only", "Only accept_exploratory is visible", "revise/reject/profile-only stay excluded", "Must show caveats and I/O gaps"], "#ffffff", "#cbd5e1"),
            box(864, y2, 312, 186, "Deterministic Offline Report", ["Reads ContextPack only", "No unfiltered candidate pool", "No paid LLM in offline mode", "Future LLM gets same pack"], "#eef2ff", "#818cf8"),
            box(1224, y2, 352, 186, "Semantic Auditor", ["Audits user-visible report", "Checks tool/literature/benchmark claims", "RAG snippet treated as provenance", "High/critical issues block report"], "#fef2f2", "#f87171"),
            arrow(241, y + 178, 241, y2, "trusted"),
            arrow(640, y + 178, 640, y2, "explore"),
            arrow(1428, y + 178, 1040, y2, "render"),
            arrow(1176, y2 + 93, 1224, y2 + 93, "audit"),
        ]
    )

    parts.append('<rect x="64" y="944" width="1512" height="176" rx="14" fill="#ffffff" stroke="#cbd5e1"/>')
    parts.append('<text x="92" y="982" font-size="22" font-weight="850" fill="#0f172a">Boundary Invariants Checked</text>')
    invariants = [
        ("retrieval rankable violations", fmt_num(rankable_violations), "#059669" if rankable_violations == 0 else "#dc2626"),
        ("trusted non-main violations", fmt_num(trusted_violations), "#059669" if trusted_violations == 0 else "#dc2626"),
        ("bad migration decisions", fmt_num(bad_migrations), "#059669" if bad_migrations == 0 else "#dc2626"),
        ("accepted hypothesis rate", fmt_percent(migration.get("accepted_hypothesis_rate")), "#059669"),
        ("unreviewed migration rate", fmt_percent(migration.get("unreviewed_migration_path_rate")), "#059669"),
        ("negative false migration", fmt_percent(migration.get("negative_false_migration_rate")), "#059669"),
    ]
    for idx, (label, value, color) in enumerate(invariants):
        x = 92 + idx * 240
        parts.append(f'<text x="{x}" y="1034" font-size="12" fill="#64748b">{esc(label)}</text>')
        parts.append(f'<text x="{x}" y="1065" font-size="26" font-weight="850" fill="{color}">{esc(value)}</text>')

    parts.extend(
        [
            '<text x="64" y="1168" font-size="14" fill="#64748b">Interpretation: v0.12 is not claiming final migration intelligence. It proves the governance pipe: KG-ranked recommendation, RAG provenance, exploratory migration, and auditor safety are separated.</text>',
            f'<text x="64" y="1196" font-size="13" fill="#64748b">ContextPack audit source: {esc(context_path)}</text>',
            f'<text x="64" y="1216" font-size="13" fill="#64748b">Migration eval source: {esc(migration_path)}</text>',
            "</svg>",
        ]
    )
    return "\n".join(parts)


def main() -> None:
    parser = argparse.ArgumentParser(description="Render the v0.12 Hybrid KG-RAG architecture and governance SVG.")
    parser.add_argument("--context-audit-summary", type=Path, default=DEFAULT_CONTEXT_AUDIT)
    parser.add_argument("--migration-summary", type=Path, default=DEFAULT_MIGRATION_SUMMARY)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--subtitle",
        default="EvidenceContextPack separates trusted recommendation, RAG provenance, exploratory migration, and auditor guardrails.",
    )
    args = parser.parse_args()

    context_audit = load_json(args.context_audit_summary)
    migration = load_metric_tsv(args.migration_summary)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        render_svg(context_audit, migration, args.context_audit_summary, args.migration_summary, args.subtitle),
        encoding="utf-8",
    )
    print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
