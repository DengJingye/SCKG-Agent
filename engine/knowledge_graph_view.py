from __future__ import annotations

import csv
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

import plotly.graph_objects as go


NODE_COLORS = {
    "Tool": (37, 37, 35),
    "Task": (204, 120, 92),
    "Publication": (93, 184, 166),
    "Benchmark": (232, 165, 90),
}

NODE_ORDER = ["Task", "Tool", "Publication", "Benchmark"]
APPROVED_REVIEW_STATUSES = {"reviewed", "verified", "human_reviewed"}
REJECTED_REVIEW_STATUSES = {"rejected", "deprecated"}


@dataclass(frozen=True)
class GraphNode:
    node_id: str
    label: str
    kind: str
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class GraphEdge:
    source: str
    target: str
    relation: str
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class KnowledgeGraphView:
    nodes: Dict[str, GraphNode]
    edges: List[GraphEdge]
    visible_node_ids: List[str]
    visible_edges: List[GraphEdge]
    inventory: Dict[str, int]
    truncated: bool = False

    def neighbors(self, node_id: str) -> Set[str]:
        linked: Set[str] = set()
        for edge in self.visible_edges:
            if edge.source == node_id:
                linked.add(edge.target)
            elif edge.target == node_id:
                linked.add(edge.source)
        return linked


def build_knowledge_graph_view(
    data_dir: Path,
    *,
    selected_kinds: Sequence[str] = ("Tool", "Task"),
    search: str = "",
    max_nodes: int = 120,
) -> KnowledgeGraphView:
    """Build a read-only, display-sized graph from formal TSV evidence.

    Candidate evidence is counted in inventory but is not mixed into the main
    trusted graph. This keeps the visualization useful without weakening the
    evidence governance boundary.
    """

    query = search.strip()
    selected = set(selected_kinds) or {"Tool", "Task"}
    if query:
        selected.update(NODE_ORDER)
    nodes: Dict[str, GraphNode] = {}
    edges_by_key: Dict[Tuple[str, str, str], GraphEdge] = {}

    include_all_tools = bool(query)
    _load_tools(data_dir, nodes, include_all=include_all_tools)
    _load_publications(data_dir, nodes, edges_by_key)
    _load_benchmarks(data_dir, nodes, edges_by_key)

    all_edges = list(edges_by_key.values())
    inventory = _inventory(data_dir, nodes, all_edges)
    visible_ids, truncated = _visible_nodes(nodes, all_edges, selected, query, max_nodes)
    visible_edges = [
        edge
        for edge in all_edges
        if edge.source in visible_ids and edge.target in visible_ids
    ]
    ordered_ids = sorted(
        visible_ids,
        key=lambda node_id: (
            NODE_ORDER.index(nodes[node_id].kind)
            if nodes[node_id].kind in NODE_ORDER
            else 99,
            nodes[node_id].label.lower(),
        ),
    )
    return KnowledgeGraphView(
        nodes=nodes,
        edges=all_edges,
        visible_node_ids=ordered_ids,
        visible_edges=visible_edges,
        inventory=inventory,
        truncated=truncated,
    )


def build_knowledge_graph_figure(
    graph: KnowledgeGraphView,
    *,
    selected_node_id: Optional[str] = None,
) -> go.Figure:
    positions = _layout_positions(graph)
    selected = selected_node_id if selected_node_id in graph.visible_node_ids else None
    active_ids: Set[str] = set()
    if selected:
        active_ids = {selected, *graph.neighbors(selected)}

    active_edges: List[GraphEdge] = []
    dim_edges: List[GraphEdge] = []
    for edge in graph.visible_edges:
        if active_ids and edge.source in active_ids and edge.target in active_ids:
            active_edges.append(edge)
        else:
            dim_edges.append(edge)

    traces: List[go.Scatter] = []
    traces.append(_edge_trace(dim_edges, positions, "rgba(61,61,58,0.12)", "context edges"))
    traces.append(_edge_trace(active_edges, positions, "rgba(204,120,92,0.62)", "selected neighborhood"))

    node_ids = graph.visible_node_ids
    node_x = [positions[node_id][0] for node_id in node_ids]
    node_y = [positions[node_id][1] for node_id in node_ids]
    labels = [graph.nodes[node_id].label for node_id in node_ids]
    kinds = [graph.nodes[node_id].kind for node_id in node_ids]
    colors = [_rgba_for_kind(kind, _node_alpha(node_id, selected, active_ids)) for node_id, kind in zip(node_ids, kinds)]
    sizes = [_node_size(node_id, graph.nodes[node_id].kind, selected, active_ids) for node_id in node_ids]
    text = [
        _short_label(graph.nodes[node_id].label, 22)
        if graph.nodes[node_id].kind in {"Tool", "Task"} or node_id == selected
        else ""
        for node_id in node_ids
    ]
    customdata = [
        [
            node_id,
            graph.nodes[node_id].kind,
            graph.nodes[node_id].label,
            _metadata_summary(graph.nodes[node_id].metadata),
        ]
        for node_id in node_ids
    ]

    traces.append(
        go.Scatter(
            x=node_x,
            y=node_y,
            mode="markers+text",
            text=text,
            textposition="top center",
            textfont={"size": 10, "color": "#252523"},
            marker={
                "size": sizes,
                "color": colors,
                "line": {"width": [2.4 if node_id == selected else 0.8 for node_id in node_ids], "color": "#ffffff"},
            },
            customdata=customdata,
            hovertemplate=(
                "<b>%{customdata[2]}</b><br>"
                "Type: %{customdata[1]}<br>"
                "%{customdata[3]}<extra></extra>"
            ),
            name="nodes",
            showlegend=False,
        )
    )

    fig = go.Figure(data=traces)
    fig.update_layout(
        paper_bgcolor="#ffffff",
        plot_bgcolor="#ffffff",
        margin={"l": 6, "r": 6, "t": 10, "b": 6},
        height=520,
        hovermode="closest",
        dragmode="select",
        xaxis={"visible": False, "showgrid": False, "zeroline": False},
        yaxis={"visible": False, "showgrid": False, "zeroline": False},
        legend={"orientation": "h", "y": -0.06},
    )
    return fig


def build_knowledge_graph_html(graph: KnowledgeGraphView) -> str:
    positions = _layout_positions(graph)
    if not positions:
        return _empty_graph_html()
    xs = [point[0] for point in positions.values()]
    ys = [point[1] for point in positions.values()]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    width = 980
    height = 660
    padding = 70

    def scale(point: Tuple[float, float]) -> Tuple[float, float]:
        x, y = point
        x_span = max(max_x - min_x, 1e-6)
        y_span = max(max_y - min_y, 1e-6)
        sx = padding + (x - min_x) / x_span * (width - 2 * padding)
        sy = padding + (y - min_y) / y_span * (height - 2 * padding)
        return sx, sy

    node_payload = []
    for node_id in graph.visible_node_ids:
        node = graph.nodes[node_id]
        x, y = scale(positions[node_id])
        node_payload.append(
            {
                "id": node_id,
                "label": node.label,
                "kind": node.kind,
                "x": round(x, 2),
                "y": round(y, 2),
                "color": _hex_for_kind(node.kind),
                "radius": _html_node_radius(node.kind),
                "meta": _plain_metadata_summary(node.metadata),
            }
        )
    edge_payload = [
        {
            "source": edge.source,
            "target": edge.target,
            "relation": edge.relation,
        }
        for edge in graph.visible_edges
        if edge.source in positions and edge.target in positions
    ]
    payload_json = json.dumps({"nodes": node_payload, "edges": edge_payload}, ensure_ascii=False)
    safe_payload = payload_json.replace("</", "<\\/")
    return f"""
<div class="sckg-graph-shell">
  <div class="sckg-graph-toolbar">
    <div>
      <strong>Read-only KG explorer</strong>
      <span>Click a node to highlight one-hop neighbors.</span>
    </div>
    <button type="button" id="sckg-reset">Reset</button>
  </div>
  <svg id="sckg-svg" viewBox="0 0 {width} {height}" role="img" aria-label="scKG read-only knowledge graph"></svg>
  <div id="sckg-details" class="sckg-details">Click a node to inspect its neighborhood.</div>
  <script type="application/json" id="sckg-data">{safe_payload}</script>
</div>
<style>
  .sckg-graph-shell {{
    border: 1px solid #e3ded7;
    border-radius: 12px;
    background: #ffffff;
    padding: 14px;
    font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  }}
  .sckg-graph-toolbar {{
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    margin-bottom: 8px;
    color: #252523;
  }}
  .sckg-graph-toolbar span {{
    display: block;
    color: #6c6a64;
    font-size: 12px;
    margin-top: 2px;
  }}
  .sckg-graph-toolbar button {{
    border: 1px solid #d3cec6;
    background: #faf9f5;
    color: #252523;
    border-radius: 8px;
    padding: 7px 12px;
    cursor: pointer;
  }}
  #sckg-svg {{
    width: 100%;
    height: 650px;
    display: block;
    background: #fdfcf9;
    border-radius: 10px;
  }}
  .sckg-edge {{
    stroke: #d9d4cc;
    stroke-width: 1.25;
    opacity: 0.52;
    transition: opacity 120ms ease, stroke 120ms ease, stroke-width 120ms ease;
  }}
  .sckg-node {{
    cursor: pointer;
    transition: opacity 120ms ease, stroke-width 120ms ease, r 120ms ease;
  }}
  .sckg-label {{
    pointer-events: none;
    fill: #252523;
    font-size: 11px;
    paint-order: stroke;
    stroke: #fdfcf9;
    stroke-width: 3px;
    stroke-linejoin: round;
    transition: opacity 120ms ease;
  }}
  .sckg-dim {{
    opacity: 0.12 !important;
  }}
  .sckg-active-edge {{
    stroke: #cc785c !important;
    stroke-width: 2.4 !important;
    opacity: 0.86 !important;
  }}
  .sckg-active-node {{
    stroke: #141413 !important;
    stroke-width: 2.8 !important;
  }}
  .sckg-neighbor-node {{
    stroke: #cc785c !important;
    stroke-width: 2 !important;
  }}
  .sckg-details {{
    margin-top: 10px;
    color: #3d3d3a;
    font-size: 13px;
    line-height: 1.45;
  }}
</style>
<script>
(function() {{
  const dataEl = document.getElementById("sckg-data");
  const svg = document.getElementById("sckg-svg");
  const details = document.getElementById("sckg-details");
  const reset = document.getElementById("sckg-reset");
  if (!dataEl || !svg) return;
  const payload = JSON.parse(dataEl.textContent);
  const nodes = payload.nodes || [];
  const edges = payload.edges || [];
  const nodeById = new Map(nodes.map((node) => [node.id, node]));
  const neighbors = new Map(nodes.map((node) => [node.id, new Set()]));
  const linkedEdges = new Map(nodes.map((node) => [node.id, []]));
  edges.forEach((edge) => {{
    if (neighbors.has(edge.source)) neighbors.get(edge.source).add(edge.target);
    if (neighbors.has(edge.target)) neighbors.get(edge.target).add(edge.source);
    if (linkedEdges.has(edge.source)) linkedEdges.get(edge.source).push({{ id: edge.target, relation: edge.relation }});
    if (linkedEdges.has(edge.target)) linkedEdges.get(edge.target).push({{ id: edge.source, relation: edge.relation }});
  }});
  const ns = "http://www.w3.org/2000/svg";
  function el(name, attrs) {{
    const item = document.createElementNS(ns, name);
    Object.entries(attrs || {{}}).forEach(([key, value]) => item.setAttribute(key, value));
    return item;
  }}
  svg.innerHTML = "";
  edges.forEach((edge, index) => {{
    const source = nodeById.get(edge.source);
    const target = nodeById.get(edge.target);
    if (!source || !target) return;
    const line = el("line", {{
      x1: source.x, y1: source.y, x2: target.x, y2: target.y,
      class: "sckg-edge",
      "data-source": edge.source,
      "data-target": edge.target,
      "data-relation": edge.relation,
      id: "edge-" + index
    }});
    svg.appendChild(line);
  }});
  nodes.forEach((node) => {{
    const group = el("g", {{"data-node": node.id}});
    const circle = el("circle", {{
      cx: node.x,
      cy: node.y,
      r: node.radius,
      fill: node.color,
      stroke: "#ffffff",
      "stroke-width": "1",
      class: "sckg-node",
      "data-node": node.id
    }});
    const title = el("title", {{}});
    title.textContent = node.label + " · " + node.kind + (node.meta ? "\\n" + node.meta : "");
    circle.appendChild(title);
    group.appendChild(circle);
    if (node.kind === "Tool" || node.kind === "Task") {{
      const label = el("text", {{
        x: node.x,
        y: Number(node.y) - Number(node.radius) - 5,
        "text-anchor": "middle",
        class: "sckg-label",
        "data-label": node.id
      }});
      label.textContent = node.label.length > 22 ? node.label.slice(0, 19) + "..." : node.label;
      group.appendChild(label);
    }}
    group.addEventListener("click", () => selectNode(node.id));
    svg.appendChild(group);
  }});
  function setDimmed(element, dimmed) {{
    if (dimmed) element.classList.add("sckg-dim");
    else element.classList.remove("sckg-dim");
  }}
  function selectNode(nodeId) {{
    const node = nodeById.get(nodeId);
    if (!node) return;
    const active = new Set([nodeId, ...(neighbors.get(nodeId) || [])]);
    svg.querySelectorAll(".sckg-node").forEach((circle) => {{
      const id = circle.getAttribute("data-node");
      circle.classList.remove("sckg-active-node", "sckg-neighbor-node");
      setDimmed(circle, !active.has(id));
      if (id === nodeId) circle.classList.add("sckg-active-node");
      else if (active.has(id)) circle.classList.add("sckg-neighbor-node");
    }});
    svg.querySelectorAll(".sckg-label").forEach((label) => {{
      const id = label.getAttribute("data-label");
      setDimmed(label, !active.has(id));
    }});
    svg.querySelectorAll(".sckg-edge").forEach((edge) => {{
      const source = edge.getAttribute("data-source");
      const target = edge.getAttribute("data-target");
      const connected = source === nodeId || target === nodeId;
      edge.classList.toggle("sckg-active-edge", connected);
      setDimmed(edge, !connected);
    }});
    const neighborLabels = (linkedEdges.get(nodeId) || [])
      .map((item) => {{
        const neighbor = nodeById.get(item.id);
        if (!neighbor) return null;
        return neighbor.label + " (" + neighbor.kind + ") via " + item.relation;
      }})
      .filter(Boolean)
      .slice(0, 14)
      .join("; ");
    details.innerHTML = "<strong>" + escapeHtml(node.label) + "</strong> · " + escapeHtml(node.kind)
      + (node.meta ? "<br>" + escapeHtml(node.meta) : "")
      + (neighborLabels ? "<br><span>One-hop: " + escapeHtml(neighborLabels) + "</span>" : "");
  }}
  function clearSelection() {{
    svg.querySelectorAll(".sckg-dim").forEach((item) => item.classList.remove("sckg-dim"));
    svg.querySelectorAll(".sckg-active-edge").forEach((item) => item.classList.remove("sckg-active-edge"));
    svg.querySelectorAll(".sckg-active-node").forEach((item) => item.classList.remove("sckg-active-node"));
    svg.querySelectorAll(".sckg-neighbor-node").forEach((item) => item.classList.remove("sckg-neighbor-node"));
    details.textContent = "Click a node to inspect its neighborhood.";
  }}
  function escapeHtml(text) {{
    return String(text || "").replace(/[&<>"']/g, (char) => ({{
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;"
    }}[char]));
  }}
  reset.addEventListener("click", clearSelection);
}})();
</script>
"""


def selected_node_from_plotly_event(event: Any) -> Optional[str]:
    if not event:
        return None
    selection = None
    if isinstance(event, dict):
        selection = event.get("selection")
    else:
        selection = getattr(event, "selection", None)
    if not selection:
        return None
    points = selection.get("points", []) if isinstance(selection, dict) else getattr(selection, "points", [])
    if not points:
        return None
    first = points[0]
    customdata = first.get("customdata") if isinstance(first, dict) else getattr(first, "customdata", None)
    if isinstance(customdata, (list, tuple)) and customdata:
        return str(customdata[0])
    return None


def _load_tools(data_dir: Path, nodes: Dict[str, GraphNode], *, include_all: bool = False) -> None:
    if not include_all:
        return
    for row in _read_tsv(data_dir / "scrna_tools.tsv"):
        tool = _clean(row.get("Tool"))
        if tool:
            _add_node(nodes, _node_id("Tool", tool), tool, "Tool", {"source": "scrna_tools.tsv"})


def _load_publications(
    data_dir: Path,
    nodes: Dict[str, GraphNode],
    edges_by_key: Dict[Tuple[str, str, str], GraphEdge],
) -> None:
    for row in _read_tsv(data_dir / "tool_publications.tsv"):
        if not _is_approved_trusted(row):
            continue
        tool = _clean(row.get("tool_name"))
        if not tool:
            continue
        tool_id = _node_id("Tool", tool)
        _add_node(nodes, tool_id, tool, "Tool", {"source": "tool_publications.tsv"})
        for task in _split_terms(row.get("task")):
            task_id = _node_id("Task", task)
            _add_node(nodes, task_id, task, "Task", {"source": "tool_publications.tsv"})
            _add_edge(edges_by_key, tool_id, task_id, "publication_support")
        publication_key = _clean(row.get("publication_id")) or _clean(row.get("doi")) or _clean(row.get("title"))
        if publication_key:
            title = _clean(row.get("title")) or publication_key
            pub_id = _node_id("Publication", publication_key)
            _add_node(
                nodes,
                pub_id,
                _short_label(title, 54),
                "Publication",
                {
                    "title": title,
                    "doi": _clean(row.get("doi")),
                    "year": _clean(row.get("publication_year")),
                    "venue": _clean(row.get("venue")),
                    "review_status": _clean(row.get("review_status")),
                    "canonical_scope": _clean(row.get("canonical_scope")),
                    "authority_tier": _clean(row.get("authority_tier")),
                    "evidence_category": _clean(row.get("evidence_category")),
                    "source": "tool_publications.tsv",
                },
            )
            _add_edge(edges_by_key, tool_id, pub_id, "has publication")


def _load_benchmarks(
    data_dir: Path,
    nodes: Dict[str, GraphNode],
    edges_by_key: Dict[Tuple[str, str, str], GraphEdge],
) -> None:
    for row in _read_tsv(data_dir / "tool_benchmarks.tsv"):
        if not _is_approved_trusted(row):
            continue
        tool = _clean(row.get("tool_name"))
        if not tool:
            continue
        tool_id = _node_id("Tool", tool)
        _add_node(nodes, tool_id, tool, "Tool", {"source": "tool_benchmarks.tsv"})
        for task in _split_terms(row.get("task")):
            task_id = _node_id("Task", task)
            _add_node(nodes, task_id, task, "Task", {"source": "tool_benchmarks.tsv"})
            _add_edge(edges_by_key, tool_id, task_id, "benchmark_support")
        benchmark_key = _clean(row.get("benchmark_id")) or _clean(row.get("benchmark_name")) or _clean(row.get("paper_doi"))
        if benchmark_key:
            label = _clean(row.get("benchmark_name")) or _clean(row.get("paper_title")) or benchmark_key
            bench_id = _node_id("Benchmark", benchmark_key)
            _add_node(
                nodes,
                bench_id,
                _short_label(label, 52),
                "Benchmark",
                {
                    "title": _clean(row.get("paper_title")),
                    "doi": _clean(row.get("paper_doi")),
                    "metric": _clean(row.get("metric")),
                    "rank": _clean(row.get("rank")),
                    "review_status": _clean(row.get("review_status")),
                    "canonical_flag": _clean(row.get("canonical_flag")),
                    "work_group_id": _clean(row.get("work_group_id")),
                    "source": "tool_benchmarks.tsv",
                },
            )
            _add_edge(edges_by_key, tool_id, bench_id, "has benchmark")


def _visible_nodes(
    nodes: Dict[str, GraphNode],
    edges: Sequence[GraphEdge],
    selected_kinds: Set[str],
    search: str,
    max_nodes: int,
) -> Tuple[Set[str], bool]:
    filtered = {node_id for node_id, node in nodes.items() if node.kind in selected_kinds}
    degree = _degree(edges)
    query = search.strip().lower()
    if query:
        matched = {
            node_id
            for node_id in filtered
            if query in nodes[node_id].label.lower()
            or query in " ".join(str(value).lower() for value in nodes[node_id].metadata.values())
        }
        visible = set(matched)
        for edge in edges:
            if edge.source in matched and edge.target in filtered:
                visible.add(edge.target)
            if edge.target in matched and edge.source in filtered:
                visible.add(edge.source)
        return _trim_visible(visible, nodes, degree, max_nodes)

    preferred: List[str] = []
    for kind, limit in [("Task", 24), ("Tool", 46), ("Benchmark", 26), ("Publication", 24)]:
        if kind not in selected_kinds:
            continue
        candidates = [node_id for node_id in filtered if nodes[node_id].kind == kind]
        candidates.sort(key=lambda node_id: (-degree.get(node_id, 0), nodes[node_id].label.lower()))
        preferred.extend(candidates[:limit])
    visible = set(preferred)
    return _trim_visible(visible, nodes, degree, max_nodes)


def _trim_visible(
    visible: Set[str],
    nodes: Dict[str, GraphNode],
    degree: Dict[str, int],
    max_nodes: int,
) -> Tuple[Set[str], bool]:
    if len(visible) <= max_nodes:
        return visible, False
    ordered = sorted(
        visible,
        key=lambda node_id: (
            NODE_ORDER.index(nodes[node_id].kind) if nodes[node_id].kind in NODE_ORDER else 99,
            -degree.get(node_id, 0),
            nodes[node_id].label.lower(),
        ),
    )
    return set(ordered[:max_nodes]), True


def _layout_positions(graph: KnowledgeGraphView) -> Dict[str, Tuple[float, float]]:
    by_kind: Dict[str, List[str]] = {kind: [] for kind in NODE_ORDER}
    for node_id in graph.visible_node_ids:
        by_kind.setdefault(graph.nodes[node_id].kind, []).append(node_id)
    positions: Dict[str, Tuple[float, float]] = {}
    radii = {"Task": 0.72, "Tool": 1.85, "Publication": 3.0, "Benchmark": 3.35}
    offsets = {"Task": math.pi / 6, "Tool": 0.0, "Publication": math.pi / 10, "Benchmark": math.pi / 5}
    for kind in NODE_ORDER:
        node_ids = by_kind.get(kind, [])
        if not node_ids:
            continue
        radius = radii.get(kind, 2.4)
        for idx, node_id in enumerate(node_ids):
            angle = offsets.get(kind, 0.0) + (2 * math.pi * idx / max(len(node_ids), 1))
            positions[node_id] = (radius * math.cos(angle), radius * math.sin(angle))
    return positions


def _edge_trace(
    edges: Sequence[GraphEdge],
    positions: Dict[str, Tuple[float, float]],
    color: str,
    name: str,
) -> go.Scatter:
    x_values: List[Optional[float]] = []
    y_values: List[Optional[float]] = []
    for edge in edges:
        if edge.source not in positions or edge.target not in positions:
            continue
        x0, y0 = positions[edge.source]
        x1, y1 = positions[edge.target]
        x_values.extend([x0, x1, None])
        y_values.extend([y0, y1, None])
    return go.Scatter(
        x=x_values,
        y=y_values,
        mode="lines",
        line={"width": 1.2, "color": color},
        hoverinfo="skip",
        name=name,
        showlegend=False,
    )


def _inventory(data_dir: Path, nodes: Dict[str, GraphNode], edges: Sequence[GraphEdge]) -> Dict[str, int]:
    candidate_dir = data_dir / "evidence_candidates"
    candidate_rows = _count_candidate_evidence(candidate_dir)
    return {
        "tools": sum(1 for node in nodes.values() if node.kind == "Tool"),
        "tasks": sum(1 for node in nodes.values() if node.kind == "Task"),
        "publications": sum(1 for node in nodes.values() if node.kind == "Publication"),
        "benchmarks": sum(1 for node in nodes.values() if node.kind == "Benchmark"),
        "edges": len(edges),
        "candidate_evidence": candidate_rows,
    }


def _count_candidate_evidence(candidate_dir: Path) -> int:
    if not candidate_dir.exists():
        return 0
    candidate_ids: Set[str] = set()
    for path in _candidate_evidence_files(candidate_dir):
        rows = _read_tsv(path)
        if "publication_candidates" in path.name:
            id_field = "publication_id"
        elif "benchmark_candidates" in path.name:
            id_field = "benchmark_id"
        else:
            continue
        for index, row in enumerate(rows):
            record_id = _clean(row.get(id_field))
            candidate_ids.add(record_id or f"{path.name}:{index}")
    return len(candidate_ids)


def _candidate_evidence_files(candidate_dir: Path) -> List[Path]:
    return [
        path
        for path in candidate_dir.glob("*.tsv")
        if "tool_publication_candidates" in path.name
        or "tool_benchmark_candidates" in path.name
    ]


def _read_tsv(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def _count_tsv_rows(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        return max(sum(1 for _ in handle) - 1, 0)


def _add_node(
    nodes: Dict[str, GraphNode],
    node_id: str,
    label: str,
    kind: str,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    if node_id in nodes:
        existing = nodes[node_id]
        merged = {**existing.metadata, **(metadata or {})}
        nodes[node_id] = GraphNode(node_id=node_id, label=existing.label, kind=existing.kind, metadata=merged)
        return
    nodes[node_id] = GraphNode(node_id=node_id, label=label, kind=kind, metadata=metadata or {})


def _add_edge(
    edges_by_key: Dict[Tuple[str, str, str], GraphEdge],
    source: str,
    target: str,
    relation: str,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    if not source or not target or source == target:
        return
    key = (source, target, relation)
    if key not in edges_by_key:
        edges_by_key[key] = GraphEdge(source=source, target=target, relation=relation, metadata=metadata or {})


def _degree(edges: Iterable[GraphEdge]) -> Dict[str, int]:
    degree: Dict[str, int] = {}
    for edge in edges:
        degree[edge.source] = degree.get(edge.source, 0) + 1
        degree[edge.target] = degree.get(edge.target, 0) + 1
    return degree


def _is_rejected(row: Dict[str, str]) -> bool:
    status = _clean(row.get("review_status")).lower()
    return status in REJECTED_REVIEW_STATUSES


def _is_approved_trusted(row: Dict[str, str]) -> bool:
    status = _clean(row.get("review_status")).lower()
    trust = _clean(row.get("trust_level")).lower()
    if status in REJECTED_REVIEW_STATUSES:
        return False
    return status in APPROVED_REVIEW_STATUSES and trust == "trusted_core"


def _split_terms(value: Any) -> List[str]:
    text = _clean(value)
    if not text:
        return []
    return [part for part in (_clean(part) for part in text.split(";")) if part]


def _node_id(kind: str, value: str) -> str:
    return f"{kind}:{value.strip().lower()}"


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split())


def _short_label(value: Any, limit: int = 42) -> str:
    text = _clean(value)
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _rgba_for_kind(kind: str, alpha: float) -> str:
    red, green, blue = NODE_COLORS.get(kind, (98, 98, 96))
    return f"rgba({red},{green},{blue},{alpha:.3f})"


def _hex_for_kind(kind: str) -> str:
    red, green, blue = NODE_COLORS.get(kind, (98, 98, 96))
    return f"#{red:02x}{green:02x}{blue:02x}"


def _html_node_radius(kind: str) -> int:
    return {"Task": 12, "Tool": 9, "Publication": 7, "Benchmark": 8}.get(kind, 8)


def _node_alpha(node_id: str, selected: Optional[str], active_ids: Set[str]) -> float:
    if not selected:
        return 0.92
    if node_id == selected:
        return 1.0
    if node_id in active_ids:
        return 0.82
    return 0.16


def _node_size(node_id: str, kind: str, selected: Optional[str], active_ids: Set[str]) -> int:
    base = {"Task": 21, "Tool": 17, "Publication": 11, "Benchmark": 13}.get(kind, 12)
    if node_id == selected:
        return base + 8
    if node_id in active_ids:
        return base + 3
    return base


def _metadata_summary(metadata: Dict[str, Any]) -> str:
    parts = []
    for key in [
        "doi",
        "year",
        "venue",
        "metric",
        "rank",
        "review_status",
        "canonical_scope",
        "authority_tier",
        "work_group_id",
    ]:
        value = _clean(metadata.get(key))
        if value:
            parts.append(f"{key}: {value}")
    return "<br>".join(parts) if parts else "read-only graph node"


def _plain_metadata_summary(metadata: Dict[str, Any]) -> str:
    parts = []
    for key in [
        "doi",
        "year",
        "venue",
        "metric",
        "rank",
        "review_status",
        "canonical_scope",
        "authority_tier",
        "work_group_id",
    ]:
        value = _clean(metadata.get(key))
        if value:
            parts.append(f"{key}: {value}")
    return "; ".join(parts)


def _empty_graph_html() -> str:
    return """
<div style="border:1px solid #e3ded7;border-radius:12px;background:#fff;padding:24px;color:#6c6a64;">
No graph nodes matched the current filters.
</div>
"""
