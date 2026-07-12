from __future__ import annotations

import math
from pathlib import Path
from typing import Iterable, Sequence

import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Rectangle


OUT = Path(__file__).resolve().parent


COL = {
    "ink": "#243142",
    "muted": "#667085",
    "line": "#8A96A8",
    "paper": "#FFFFFF",
    "panel": "#F8FAFC",
    "panel_edge": "#D7DEE8",
    "blue": "#DCEBFA",
    "blue_edge": "#2F6EA3",
    "navy": "#0F4D92",
    "green": "#E2F3E7",
    "green_edge": "#3A8B5A",
    "teal": "#D9F1F0",
    "teal_edge": "#2E8F91",
    "amber": "#FFF1CF",
    "amber_edge": "#D98910",
    "rose": "#FBE2E4",
    "rose_edge": "#C94555",
    "violet": "#ECE7F8",
    "violet_edge": "#6F5AA8",
    "gray": "#EEF2F6",
    "gray_edge": "#64748B",
}


mpl.rcParams.update(
    {
        "font.family": "sans-serif",
        "font.sans-serif": ["Arial", "Helvetica", "DejaVu Sans", "sans-serif"],
        "svg.fonttype": "none",
        "pdf.fonttype": 42,
        "font.size": 7.5,
        "axes.linewidth": 0.7,
    }
)


def setup_ax(width: float, height: float):
    fig, ax = plt.subplots(figsize=(width, height))
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    fig.patch.set_facecolor(COL["paper"])
    ax.set_facecolor(COL["paper"])
    return fig, ax


def save(fig, name: str):
    for ext in ("svg", "pdf", "png"):
        kwargs = {"bbox_inches": "tight", "pad_inches": 0.04}
        if ext == "png":
            kwargs["dpi"] = 450
        fig.savefig(OUT / f"{name}.{ext}", **kwargs)
    plt.close(fig)


def panel(ax, x, y, w, h, title=None, fc=None, ec=None, lw=0.9):
    patch = FancyBboxPatch(
        (x, y),
        w,
        h,
        boxstyle="round,pad=0.008,rounding_size=0.018",
        linewidth=lw,
        facecolor=fc or COL["panel"],
        edgecolor=ec or COL["panel_edge"],
        zorder=0,
    )
    ax.add_patch(patch)
    if title:
        ax.text(
            x + 0.015,
            y + h - 0.025,
            title,
            ha="left",
            va="top",
            fontsize=8.6,
            fontweight="bold",
            color=COL["ink"],
            zorder=5,
        )
    return patch


def box(
    ax,
    x,
    y,
    w,
    h,
    text,
    fc,
    ec,
    fontsize=7.1,
    weight="normal",
    z=4,
):
    patch = FancyBboxPatch(
        (x, y),
        w,
        h,
        boxstyle="round,pad=0.012,rounding_size=0.018",
        linewidth=1.0,
        facecolor=fc,
        edgecolor=ec,
        zorder=z,
    )
    ax.add_patch(patch)
    ax.text(
        x + w / 2,
        y + h / 2,
        text,
        ha="center",
        va="center",
        fontsize=fontsize,
        fontweight=weight,
        color=COL["ink"],
        linespacing=1.12,
        zorder=z + 1,
    )
    return patch


def pill(ax, x, y, w, h, text, fc, ec, fontsize=6.8):
    return box(ax, x, y, w, h, text, fc, ec, fontsize=fontsize)


def label(ax, x, y, text, size=7, color=None, weight="normal", ha="center", va="center"):
    ax.text(
        x,
        y,
        text,
        fontsize=size,
        color=color or COL["muted"],
        fontweight=weight,
        ha=ha,
        va=va,
        linespacing=1.1,
        zorder=6,
    )


def arrow(ax, start, end, color=None, lw=1.0, rad=0.0, style="-|>", dashed=False):
    patch = FancyArrowPatch(
        start,
        end,
        arrowstyle=style,
        mutation_scale=8.5,
        linewidth=lw,
        color=color or COL["line"],
        connectionstyle=f"arc3,rad={rad}",
        linestyle=(0, (3, 2)) if dashed else "solid",
        shrinkA=2,
        shrinkB=2,
        zorder=3,
    )
    ax.add_patch(patch)
    return patch


def lane_arrow(ax, x0, y, x1, color, text=None):
    arrow(ax, (x0, y), (x1, y), color=color, lw=1.2)
    if text:
        label(ax, (x0 + x1) / 2, y + 0.028, text, size=6.4, color=color)


def draw_current_orchestration():
    """Core conclusion: current scKG-Agent is a centralized governed StateGraph, not a decentralized multi-agent system."""
    fig, ax = setup_ax(11.6, 4.2)
    label(ax, 0.02, 0.965, "a", size=10, color=COL["ink"], weight="bold", ha="left")
    label(ax, 0.07, 0.965, "Current scKG-Agent orchestration", size=11.5, color=COL["ink"], weight="bold", ha="left")
    label(
        ax,
        0.07,
        0.925,
        "A centralized StateGraph turns a research request into governed recommendations, migration hypotheses, or a blocked report.",
        size=7.2,
        color=COL["muted"],
        ha="left",
    )

    panel(ax, 0.035, 0.55, 0.17, 0.27, "Input context")
    box(ax, 0.06, 0.71, 0.12, 0.055, "User query", COL["blue"], COL["blue_edge"])
    box(ax, 0.055, 0.62, 0.13, 0.065, "Project memory\nUploads\nChat context", COL["gray"], COL["gray_edge"], fontsize=6.6)
    label(ax, 0.12, 0.575, "context only\nnot evidence", size=6.2, color=COL["amber_edge"])

    panel(ax, 0.245, 0.48, 0.56, 0.36, "Central StateGraph workflow")
    steps = [
        ("Intent\nparser", COL["blue"], COL["blue_edge"]),
        ("Normalized\nconstraints", COL["blue"], COL["blue_edge"]),
        ("KG hard\nfilter", COL["green"], COL["green_edge"]),
        ("Evidence\ngate", COL["amber"], COL["amber_edge"]),
        ("MCDM\nranking", COL["violet"], COL["violet_edge"]),
        ("Report\nbuilder", COL["gray"], COL["gray_edge"]),
        ("Semantic\nauditor", COL["rose"], COL["rose_edge"]),
    ]
    xs = [0.275, 0.35, 0.435, 0.52, 0.605, 0.685, 0.755]
    widths = [0.055, 0.068, 0.06, 0.06, 0.06, 0.058, 0.065]
    y = 0.64
    h = 0.085
    centers = []
    for (txt, fc, ec), x, w in zip(steps, xs, widths):
        box(ax, x, y, w, h, txt, fc, ec, fontsize=6.3)
        centers.append((x + w / 2, y + h / 2))
    for a, b in zip(centers[:-1], centers[1:]):
        arrow(ax, (a[0] + 0.03, a[1]), (b[0] - 0.03, b[1]), lw=1.0)
    label(ax, 0.595, 0.555, "candidate tools?", size=6.4, color=COL["ink"])
    arrow(ax, (0.565, 0.64), (0.635, 0.64), color=COL["violet_edge"], lw=1.1)

    box(ax, 0.615, 0.515, 0.09, 0.08, "Migration\nengine", COL["rose"], COL["rose_edge"], fontsize=6.4)
    arrow(ax, (0.565, 0.64), (0.635, 0.595), color=COL["rose_edge"], lw=1.0, rad=-0.22)
    arrow(ax, (0.705, 0.555), (0.755, 0.64), color=COL["rose_edge"], lw=1.0, rad=0.18)

    panel(ax, 0.255, 0.15, 0.42, 0.23, "Governed evidence plane")
    data_nodes = [
        ("Neo4j / Aura KG", 0.285, COL["green"], COL["green_edge"]),
        ("Offline graph\nfallback", 0.39, COL["green"], COL["green_edge"]),
        ("Formal\npublications", 0.50, COL["gray"], COL["gray_edge"]),
        ("Formal\nbenchmarks", 0.60, COL["gray"], COL["gray_edge"]),
    ]
    for txt, x, fc, ec in data_nodes:
        box(ax, x, 0.235, 0.085, 0.07, txt, fc, ec, fontsize=6.2)
        arrow(ax, (x + 0.042, 0.305), (0.46, 0.64), lw=0.8, dashed=True)
    label(ax, 0.47, 0.185, "candidate evidence stays outside trusted recommendation path", size=6.4, color=COL["amber_edge"])

    panel(ax, 0.835, 0.48, 0.13, 0.34, "Governed outputs")
    box(ax, 0.855, 0.69, 0.085, 0.05, "Ranked tool\nreport", COL["gray"], COL["gray_edge"], fontsize=5.8)
    box(ax, 0.855, 0.615, 0.085, 0.05, "Exploratory\nmigration report", COL["rose"], COL["rose_edge"], fontsize=5.8)
    box(ax, 0.855, 0.54, 0.085, 0.05, "Safe blocked\nreport", COL["rose"], COL["rose_edge"], fontsize=5.8)
    arrow(ax, (0.82, 0.68), (0.855, 0.715), color=COL["gray_edge"])
    arrow(ax, (0.82, 0.68), (0.855, 0.64), color=COL["rose_edge"])
    arrow(ax, (0.82, 0.68), (0.855, 0.565), color=COL["rose_edge"])
    label(ax, 0.835, 0.72, "pass", size=5.4)
    label(ax, 0.835, 0.565, "veto", size=5.4, color=COL["rose_edge"])

    box(ax, 0.785, 0.23, 0.17, 0.09, "Trace + eval artifacts\nconstraint, retrieval, gate,\nMCDM, audit", COL["gray"], COL["gray_edge"], fontsize=6.2)
    for pt in [(0.305, 0.64), (0.46, 0.64), (0.54, 0.64), (0.72, 0.64)]:
        arrow(ax, pt, (0.79, 0.29), dashed=True, lw=0.75)

    save(fig, "scKG_current_agent_orchestration_publication")


def draw_target_architecture():
    """Core conclusion: target scKG is a governed hybrid scientific agent with central control and specialist tools."""
    fig, ax = setup_ax(10.8, 6.2)
    label(ax, 0.02, 0.965, "b", size=10, color=COL["ink"], weight="bold", ha="left")
    label(ax, 0.07, 0.965, "Target architecture: governed hybrid scientific agent", size=11.5, color=COL["ink"], weight="bold", ha="left")
    label(
        ax,
        0.07,
        0.925,
        "The long-term architecture keeps one evidence-governed orchestrator while exposing specialist agents and MCP/HTTP entry points.",
        size=7.2,
        color=COL["muted"],
        ha="left",
    )

    panel(ax, 0.06, 0.77, 0.88, 0.12, "Entry surfaces")
    entry = [
        ("Streamlit UI", 0.12),
        ("CLI / eval", 0.32),
        ("MCP clients", 0.52),
        ("FastAPI trial", 0.72),
    ]
    for txt, x in entry:
        pill(ax, x, 0.81, 0.13, 0.045, txt, COL["blue"], COL["blue_edge"])

    panel(ax, 0.08, 0.49, 0.66, 0.22, "Central governance layer")
    orch = box(ax, 0.39, 0.585, 0.18, 0.065, "Central Orchestrator\nStateGraph + typed state", COL["blue"], COL["blue_edge"], fontsize=6.6, weight="bold")
    policy = box(ax, 0.16, 0.535, 0.15, 0.06, "Evidence policy\nsource of truth", COL["amber"], COL["amber_edge"], fontsize=6.2)
    registry = box(ax, 0.16, 0.605, 0.15, 0.045, "Typed tool registry", COL["gray"], COL["gray_edge"], fontsize=6.2)
    pack = box(ax, 0.59, 0.615, 0.13, 0.045, "EvidenceContextPack", COL["teal"], COL["teal_edge"], fontsize=6.0)
    audit = box(ax, 0.59, 0.535, 0.13, 0.06, "Audit gate\nclaim + ranking veto", COL["rose"], COL["rose_edge"], fontsize=5.9, weight="bold")
    for x, y0 in [(0.185, 0.833), (0.385, 0.833), (0.585, 0.833), (0.785, 0.833)]:
        arrow(ax, (x, y0), (0.50, 0.66), lw=0.9)
    arrow(ax, (0.31, 0.628), (0.39, 0.62))
    arrow(ax, (0.31, 0.565), (0.39, 0.607))
    arrow(ax, (0.57, 0.62), (0.59, 0.638))
    arrow(ax, (0.655, 0.615), (0.655, 0.595), color=COL["rose_edge"])

    panel(ax, 0.055, 0.245, 0.89, 0.18, "Specialist agents and typed tools")
    agents = [
        ("Intent /\nconstraint", 0.09, COL["violet"], COL["violet_edge"]),
        ("KG reasoning\npaths", 0.23, COL["green"], COL["green_edge"]),
        ("Evidence retrieval\nHybrid KG-RAG", 0.39, COL["teal"], COL["teal_edge"]),
        ("Ranking\nMCDM", 0.57, COL["violet"], COL["violet_edge"]),
        ("Migration\nexploratory", 0.70, COL["rose"], COL["rose_edge"]),
        ("Workflow planning\nPlanChain", 0.83, COL["amber"], COL["amber_edge"]),
    ]
    centers = []
    for txt, x, fc, ec in agents:
        box(ax, x, 0.285, 0.105, 0.058, txt, fc, ec, fontsize=5.9)
        centers.append((x + 0.0525, 0.314))
    for a, b in zip(centers[:4], centers[1:5]):
        arrow(ax, (a[0] + 0.05, a[1]), (b[0] - 0.05, b[1]), lw=0.85)
    arrow(ax, (0.48, 0.585), (0.142, 0.343), dashed=True)
    arrow(ax, (0.48, 0.585), (0.442, 0.343), dashed=True)
    arrow(ax, (0.48, 0.585), (0.622, 0.343), dashed=True)
    arrow(ax, (0.48, 0.585), (0.882, 0.343), dashed=True)
    arrow(ax, (0.882, 0.285), (0.93, 0.255), dashed=True)
    label(ax, 0.925, 0.238, "future\nsandbox", size=5.5, color=COL["gray_edge"])

    panel(ax, 0.055, 0.055, 0.89, 0.145, "Knowledge, retrieval, and evaluation plane")
    plane = [
        ("Formal evidence\nstore", 0.10, COL["gray"], COL["gray_edge"]),
        ("scKG Neo4j\nTool-Task-Evidence", 0.29, COL["green"], COL["green_edge"]),
        ("Hybrid index\nBM25 + dense + RRF", 0.50, COL["teal"], COL["teal_edge"]),
        ("Trace/eval store\nbad-case loop", 0.71, COL["gray"], COL["gray_edge"]),
    ]
    for txt, x, fc, ec in plane:
        box(ax, x, 0.085, 0.14, 0.045, txt, fc, ec, fontsize=5.7)
    arrow(ax, (0.17, 0.13), (0.235, 0.535), dashed=True)
    arrow(ax, (0.36, 0.13), (0.282, 0.285), dashed=True)
    arrow(ax, (0.57, 0.13), (0.442, 0.285), dashed=True)
    arrow(ax, (0.78, 0.13), (0.655, 0.535), dashed=True)

    panel(ax, 0.775, 0.49, 0.18, 0.22, None, fc="#FFFFFF", ec="#E5E7EB")
    label(ax, 0.865, 0.68, "Governed outputs", size=8.0, weight="bold", color=COL["ink"])
    box(ax, 0.805, 0.61, 0.12, 0.038, "Recommendation report", COL["gray"], COL["gray_edge"], fontsize=5.8)
    box(ax, 0.805, 0.56, 0.12, 0.038, "Workflow plan", COL["amber"], COL["amber_edge"], fontsize=5.8)
    box(ax, 0.805, 0.51, 0.12, 0.038, "Gap / blocked report", COL["rose"], COL["rose_edge"], fontsize=5.8)
    arrow(ax, (0.72, 0.565), (0.805, 0.63), color=COL["gray_edge"], lw=0.8)
    arrow(ax, (0.72, 0.565), (0.805, 0.58), color=COL["amber_edge"], lw=0.8)
    arrow(ax, (0.72, 0.565), (0.805, 0.53), color=COL["rose_edge"], lw=0.8)

    save(fig, "scKG_target_hybrid_agent_architecture_publication")


def draw_hybrid_kg_rag():
    """Core conclusion: Hybrid KG-RAG uses graph structure for candidate boundaries and RAG for auditable evidence text."""
    fig, ax = setup_ax(11.4, 4.8)
    label(ax, 0.02, 0.965, "c", size=10, color=COL["ink"], weight="bold", ha="left")
    label(ax, 0.07, 0.965, "Evidence-governed Hybrid KG-RAG", size=11.5, color=COL["ink"], weight="bold", ha="left")
    label(
        ax,
        0.07,
        0.925,
        "Graph structure constrains candidate tools and paths; retrieval supplies auditable evidence snippets without upgrading trust or rank.",
        size=7.2,
        color=COL["muted"],
        ha="left",
    )

    panel(ax, 0.04, 0.18, 0.25, 0.62, "1. Curated ingestion")
    sources = [
        ("Reviewed papers", 0.68),
        ("Benchmarks", 0.58),
        ("Protocols / docs", 0.48),
        ("Tool metadata", 0.38),
    ]
    for txt, yy in sources:
        box(ax, 0.065, yy, 0.10, 0.05, txt, COL["gray"], COL["gray_edge"], fontsize=5.9)
        arrow(ax, (0.165, yy + 0.025), (0.205, 0.53), lw=0.7)
    box(ax, 0.20, 0.50, 0.07, 0.07, "Pluggable\nloaders", COL["blue"], COL["blue_edge"], fontsize=5.7)
    box(ax, 0.20, 0.39, 0.07, 0.07, "Evidence\nChunk", COL["teal"], COL["teal_edge"], fontsize=5.7)
    arrow(ax, (0.235, 0.50), (0.235, 0.46))
    label(ax, 0.155, 0.25, "Claim boundary + provenance are created\nbefore runtime retrieval.", size=5.9, color=COL["muted"])

    panel(ax, 0.32, 0.18, 0.23, 0.62, "2. Index and graph build")
    review = box(ax, 0.365, 0.61, 0.14, 0.06, "Review gate\nno auto-promotion", COL["amber"], COL["amber_edge"], fontsize=6.2)
    idxs = [
        ("scKG graph\nTool-Task-Evidence", 0.49, COL["green"], COL["green_edge"]),
        ("BM25 index\nexact terms", 0.38, COL["teal"], COL["teal_edge"]),
        ("Dense index\nsemantic recall", 0.27, COL["teal"], COL["teal_edge"]),
    ]
    arrow(ax, (0.27, 0.425), (0.365, 0.64), lw=0.9)
    for txt, yy, fc, ec in idxs:
        box(ax, 0.365, yy, 0.14, 0.06, txt, fc, ec, fontsize=5.8)
        arrow(ax, (0.435, 0.61), (0.435, yy + 0.06), lw=0.75)

    panel(ax, 0.58, 0.18, 0.25, 0.62, "3. Runtime Hybrid KG-RAG")
    box(ax, 0.605, 0.68, 0.09, 0.055, "User query", COL["blue"], COL["blue_edge"], fontsize=6.1)
    box(ax, 0.72, 0.68, 0.09, 0.055, "Constraint\nparser", COL["blue"], COL["blue_edge"], fontsize=6.1)
    arrow(ax, (0.695, 0.707), (0.72, 0.707))
    lanes = [
        ("KG hard filter\ncandidate boundary", 0.56, COL["green"], COL["green_edge"]),
        ("Sparse search\nformal snippets", 0.45, COL["teal"], COL["teal_edge"]),
        ("Dense search\nsemantic snippets", 0.34, COL["teal"], COL["teal_edge"]),
    ]
    for txt, yy, fc, ec in lanes:
        box(ax, 0.66, yy, 0.13, 0.055, txt, fc, ec, fontsize=5.7)
        arrow(ax, (0.765, 0.68), (0.725, yy + 0.055), lw=0.75)
    box(ax, 0.675, 0.235, 0.10, 0.055, "RRF fusion", COL["amber"], COL["amber_edge"], fontsize=6.0)
    arrow(ax, (0.725, 0.45), (0.725, 0.29), color=COL["teal_edge"], lw=0.9)
    arrow(ax, (0.725, 0.34), (0.725, 0.29), color=COL["teal_edge"], lw=0.9)
    arrow(ax, (0.505, 0.52), (0.66, 0.59), dashed=True)
    arrow(ax, (0.505, 0.41), (0.66, 0.477), dashed=True)
    arrow(ax, (0.505, 0.30), (0.66, 0.367), dashed=True)

    panel(ax, 0.84, 0.18, 0.13, 0.62, "4. Governed decision")
    box(ax, 0.855, 0.66, 0.10, 0.055, "Governance-aware\nrerank", COL["amber"], COL["amber_edge"], fontsize=5.8)
    box(ax, 0.855, 0.54, 0.10, 0.055, "Evidence\nContextPack", COL["teal"], COL["teal_edge"], fontsize=5.8)
    box(ax, 0.855, 0.42, 0.10, 0.055, "Evidence gate\n+ MCDM", COL["violet"], COL["violet_edge"], fontsize=5.8)
    box(ax, 0.855, 0.30, 0.10, 0.055, "Report\n+ audit", COL["rose"], COL["rose_edge"], fontsize=5.8, weight="bold")
    box(ax, 0.855, 0.215, 0.10, 0.045, "Final / blocked\noutput", COL["gray"], COL["gray_edge"], fontsize=5.6)
    arrow(ax, (0.775, 0.262), (0.855, 0.687), color=COL["amber_edge"], lw=0.9, rad=0.05)
    for y0, y1 in [(0.66, 0.595), (0.54, 0.475), (0.42, 0.355), (0.30, 0.26)]:
        arrow(ax, (0.905, y0), (0.905, y1), lw=0.8)

    box(
        ax,
        0.48,
        0.08,
        0.31,
        0.06,
        "Guardrail: RAG snippets explain evidence; they cannot directly upgrade rank or trust.",
        "#FFF8E8",
        COL["amber_edge"],
        fontsize=6.2,
        weight="bold",
    )
    arrow(ax, (0.635, 0.14), (0.855, 0.685), dashed=True, color=COL["amber_edge"], lw=0.8)
    arrow(ax, (0.635, 0.14), (0.855, 0.45), dashed=True, color=COL["amber_edge"], lw=0.8)

    save(fig, "scKG_hybrid_kg_rag_flow_publication")


def main():
    draw_current_orchestration()
    draw_target_architecture()
    draw_hybrid_kg_rag()
    print(f"Rendered publication figures to {OUT}")


if __name__ == "__main__":
    main()
