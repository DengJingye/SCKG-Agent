from __future__ import annotations

import html
import json
import math
from collections import Counter, defaultdict, deque
from typing import Any


NODE_COLORS = {
    "Tool": "#3978E8",
    "Task": "#169C8E",
    "Category": "#8B63C7",
    "Modality": "#43A36C",
    "Publication": "#DB8D25",
    "Benchmark": "#D94D6D",
    "Source": "#B87426",
    "SourceChunk": "#D6A92E",
    "ToolContract": "#7057D9",
    "Environment": "#64748B",
    "Dataset": "#0A9CB0",
    "Evaluation": "#C73557",
    "Language": "#0B8E82",
    "RuntimePlatform": "#816B4D",
    "Hardware": "#526173",
    "Resolution": "#1A9C97",
    "AlgorithmFamily": "#AC5D99",
    "InputArtifact": "#3E82B8",
    "OutputArtifact": "#4A956F",
    "DataAssumption": "#BF6257",
    "Parameter": "#956EA7",
    "Action": "#E17345",
    "FailureMode": "#B84F54",
    "ValidationRule": "#36806F",
    "KnowHow": "#7A6AA8",
}

LAYER_LABELS = {
    "trusted_core": "可信核心",
    "execution_verified": "执行已验证",
    "contract_verified": "契约已验证",
    "evaluation_scoped": "数据集范围评估",
    "source_material": "来源材料",
    "catalog_seed": "目录发现",
    "retrieval_only": "仅检索",
    "frozen": "已冻结",
    "quarantined": "已隔离",
    "blocked": "未通过准入",
    "legacy": "旧版兼容",
}


def build_interactive_graph_workspace_html(
    graph: Any,
    *,
    expansion_cap: int = 1200,
) -> str:
    """Render a deterministic SVG workspace with bounded neighbor expansion."""

    requested_ids = list(graph.visible_node_ids)
    if not requested_ids:
        return _empty_html()
    degree = _degree(graph.edges)
    initial_ids = _initial_projection(graph, requested_ids, degree)
    pool_ids = _expansion_pool(
        graph,
        initial_ids,
        requested_ids,
        degree,
        expansion_cap,
    )
    positions = _cluster_positions(
        [graph.nodes[node_id] for node_id in pool_ids if node_id in graph.nodes]
    )
    positions.update(
        _backbone_positions(
            [graph.nodes[node_id] for node_id in initial_ids if node_id in graph.nodes]
        )
    )
    initial = set(initial_ids)
    pool = set(pool_ids)
    nodes = []
    for node_id in pool_ids:
        node = graph.nodes[node_id]
        x, y = positions[node_id]
        layer = str(node.metadata.get("governance_layer") or "legacy")
        nodes.append(
            {
                "id": node.node_id,
                "type": node.kind,
                "label": node.label,
                "properties": node.metadata,
                "governance": {
                    "layer": layer,
                    "source_bound": bool(node.metadata.get("source_bound")),
                    "decision_eligible": bool(node.metadata.get("decision_eligible")),
                    "provenance_refs": node.metadata.get("provenance_refs", []),
                },
                "degree": degree.get(node_id, 0),
                "initial": node_id in initial,
                "x": round(x, 2),
                "y": round(y, 2),
            }
        )
    edges = []
    for index, edge in enumerate(graph.edges):
        if edge.source not in pool or edge.target not in pool:
            continue
        layer = str(edge.metadata.get("governance_layer") or "legacy")
        edges.append(
            {
                "id": f"edge:{index}:{edge.source}:{edge.target}:{edge.relation}",
                "source": edge.source,
                "target": edge.target,
                "relation": edge.relation,
                "properties": edge.metadata,
                "governance": {
                    "layer": layer,
                    "provenance_refs": edge.metadata.get("provenance_refs", []),
                },
            }
        )
    type_counts = Counter(node["type"] for node in nodes)
    layer_counts = Counter(node["governance"]["layer"] for node in nodes)
    payload = {
        "nodes": nodes,
        "edges": edges,
        "summary": {
            "snapshotNodes": len(graph.nodes),
            "snapshotEdges": len(graph.edges),
            "initialNodes": len(initial),
            "poolNodes": len(nodes),
            "poolEdges": len(edges),
            "truncated": bool(graph.truncated or len(pool) < len(graph.nodes)),
        },
    }
    document = _HTML_TEMPLATE
    document = document.replace("__PAYLOAD__", _safe_script_json(payload))
    document = document.replace("__NODE_COLORS__", json.dumps(NODE_COLORS))
    document = document.replace("__LAYER_LABELS__", json.dumps(LAYER_LABELS, ensure_ascii=False))
    document = document.replace(
        "__TYPE_CONTROLS__",
        "".join(
            _filter_button(
                "type", node_type, node_type, type_counts[node_type], NODE_COLORS.get(node_type, "#94A3B8")
            )
            for node_type in sorted(type_counts)
        ),
    )
    document = document.replace(
        "__LAYER_CONTROLS__",
        "".join(
            _filter_button(
                "layer",
                layer,
                LAYER_LABELS.get(layer, layer),
                layer_counts[layer],
                _layer_color(layer),
            )
            for layer in sorted(layer_counts)
        ),
    )
    document = document.replace("__INITIAL_COUNT__", str(len(initial)))
    document = document.replace("__POOL_COUNT__", str(len(nodes)))
    document = document.replace("__EDGE_COUNT__", str(len(edges)))
    return document


def _initial_projection(
    graph: Any,
    requested_ids: list[str],
    degree: dict[str, int],
    *,
    cap: int = 24,
) -> list[str]:
    if len(requested_ids) <= cap:
        return requested_ids
    kind_priority = {
        kind: index
        for index, kind in enumerate(
            (
                "Action",
                "Task",
                "Tool",
                "ToolContract",
                "InputArtifact",
                "DataAssumption",
                "Parameter",
                "OutputArtifact",
                "Environment",
                "Dataset",
                "Evaluation",
                "ValidationRule",
                "FailureMode",
                "KnowHow",
                "Category",
                "Modality",
            )
        )
    }
    kind_quotas = {
        "Action": 2,
        "Task": 4,
        "Tool": 8,
        "ToolContract": 8,
        "InputArtifact": 4,
        "OutputArtifact": 4,
        "Environment": 4,
        "Dataset": 4,
        "Evaluation": 4,
        "ValidationRule": 2,
        "FailureMode": 2,
        "KnowHow": 2,
        "DataAssumption": 2,
    }
    requested = set(requested_ids)
    adjacency: dict[str, set[str]] = defaultdict(set)
    for edge in graph.edges:
        if edge.source in requested and edge.target in requested:
            adjacency[edge.source].add(edge.target)
            adjacency[edge.target].add(edge.source)
    semantic_seeds = {
        node_id for node_id in requested_ids if graph.nodes[node_id].kind == "Action"
    }
    kind_quotas["Action"] = max(kind_quotas["Action"], len(semantic_seeds))
    if semantic_seeds:
        core_kinds = {
            "Action",
            "Task",
            "Tool",
            "ToolContract",
            "Environment",
            "Dataset",
            "Evaluation",
            "InputArtifact",
        }
        semantic_core = set(semantic_seeds)
        frontier = set(semantic_seeds)
        for _ in range(3):
            discovered = {
                neighbor
                for current in frontier
                for neighbor in adjacency.get(current, set())
                if graph.nodes[neighbor].kind in core_kinds
            } - semantic_core
            semantic_core.update(discovered)
            frontier = discovered
    else:
        best_priority = min(
            (
                kind_priority.get(graph.nodes[node_id].kind, len(kind_priority))
                for node_id in requested_ids
            ),
            default=len(kind_priority),
        )
        semantic_core = {
            node_id
            for node_id in requested_ids
            if kind_priority.get(graph.nodes[node_id].kind, len(kind_priority)) == best_priority
        }
    ordered_candidates = sorted(
        semantic_core,
        key=lambda node_id: (
            kind_priority.get(graph.nodes[node_id].kind, len(kind_priority)),
            -degree.get(node_id, 0),
            graph.nodes[node_id].label.casefold(),
        ),
    )
    ordered: list[str] = []
    selected_by_kind: Counter[str] = Counter()
    for node_id in ordered_candidates:
        kind = graph.nodes[node_id].kind
        if selected_by_kind[kind] >= kind_quotas.get(kind, 1):
            continue
        ordered.append(node_id)
        selected_by_kind[kind] += 1
        if len(ordered) >= cap:
            break
    seen = set(ordered)
    queue = deque(ordered)
    while queue and len(ordered) < cap:
        current = queue.popleft()
        adjacent = sorted(
            adjacency.get(current, set()) - seen,
            key=lambda node_id: (
                kind_priority.get(graph.nodes[node_id].kind, len(kind_priority)),
                -degree.get(node_id, 0),
                graph.nodes[node_id].label.casefold(),
            ),
        )
        for node_id in adjacent:
            kind = graph.nodes[node_id].kind
            if selected_by_kind[kind] >= kind_quotas.get(kind, 1):
                continue
            seen.add(node_id)
            ordered.append(node_id)
            selected_by_kind[kind] += 1
            queue.append(node_id)
            if len(ordered) >= cap:
                break
    remaining = sorted(
        requested - seen,
        key=lambda node_id: (
            kind_priority.get(graph.nodes[node_id].kind, len(kind_priority)),
            -degree.get(node_id, 0),
            graph.nodes[node_id].label.casefold(),
        ),
    )
    return (ordered + remaining)[:cap]


def _backbone_positions(nodes: list[Any]) -> dict[str, tuple[float, float]]:
    """Lay the initial governed backbone out as readable semantic lanes."""

    lane_by_kind = {
        "Task": 0,
        "Action": 1,
        "Tool": 2,
        "ToolContract": 3,
        "InputArtifact": 4,
        "DataAssumption": 4,
        "Parameter": 4,
        "Environment": 5,
        "Dataset": 5,
        "Evaluation": 5,
        "OutputArtifact": 6,
        "ValidationRule": 6,
        "FailureMode": 6,
        "KnowHow": 6,
    }
    lanes: dict[int, list[Any]] = defaultdict(list)
    for node in nodes:
        lanes[lane_by_kind.get(node.kind, 6)].append(node)
    x_positions = (95, 255, 420, 585, 750, 915, 1080)
    positions: dict[str, tuple[float, float]] = {}
    for lane, lane_nodes in lanes.items():
        ordered = sorted(lane_nodes, key=lambda item: (item.kind, item.label.casefold()))
        count = len(ordered)
        if count == 1:
            y_values = [390.0]
        else:
            top, bottom = 105.0, 675.0
            step = (bottom - top) / (count - 1)
            y_values = [top + index * step for index in range(count)]
        for node, y_value in zip(ordered, y_values):
            positions[node.node_id] = (x_positions[lane], y_value)
    return positions


def _expansion_pool(
    graph: Any,
    initial_ids: list[str],
    requested_ids: list[str],
    degree: dict[str, int],
    cap: int,
) -> list[str]:
    initial = set(initial_ids)
    requested = set(requested_ids)
    neighbors: dict[str, set[str]] = defaultdict(set)
    for edge in graph.edges:
        if edge.source in requested and edge.target in requested:
            neighbors[edge.source].add(edge.target)
            neighbors[edge.target].add(edge.source)
    ordered_initial = sorted(
        initial,
        key=lambda node_id: (-degree.get(node_id, 0), graph.nodes[node_id].label.casefold()),
    )
    queue = deque(ordered_initial)
    ordered_pool = list(ordered_initial)
    seen = set(ordered_initial)
    while queue and len(ordered_pool) < cap:
        current = queue.popleft()
        adjacent = sorted(
            neighbors.get(current, set()) - seen,
            key=lambda node_id: (
                -degree.get(node_id, 0),
                graph.nodes[node_id].label.casefold(),
            ),
        )
        for node_id in adjacent:
            seen.add(node_id)
            ordered_pool.append(node_id)
            queue.append(node_id)
            if len(ordered_pool) >= cap:
                break
    remaining = sorted(
        requested - seen,
        key=lambda node_id: (-degree.get(node_id, 0), graph.nodes[node_id].label.casefold()),
    )
    return (ordered_pool + remaining)[: max(len(ordered_initial), cap)]


def _cluster_positions(nodes: list[Any]) -> dict[str, tuple[float, float]]:
    groups: dict[str, list[Any]] = defaultdict(list)
    for node in nodes:
        groups[node.kind].append(node)
    positions: dict[str, tuple[float, float]] = {}
    ordered_types = sorted(groups)
    count = max(1, len(ordered_types))
    for group_index, node_type in enumerate(ordered_types):
        angle = -math.pi / 2 + 2 * math.pi * group_index / count
        centre_radius = 250 if count > 1 else 0
        centre_x = 600 + centre_radius * math.cos(angle)
        centre_y = 390 + centre_radius * 0.72 * math.sin(angle)
        group = sorted(groups[node_type], key=lambda item: item.label.casefold())
        for index, node in enumerate(group):
            ring = int(math.sqrt(index))
            ring_start = ring * ring
            ring_size = max(1, (ring + 1) ** 2 - ring_start)
            local_angle = 2 * math.pi * (index - ring_start) / ring_size + group_index * 0.41
            local_radius = 18 + ring * 31
            positions[node.node_id] = (
                centre_x + local_radius * math.cos(local_angle),
                centre_y + local_radius * math.sin(local_angle),
            )
    return positions


def _degree(edges: list[Any]) -> dict[str, int]:
    result: defaultdict[str, int] = defaultdict(int)
    for edge in edges:
        result[edge.source] += 1
        result[edge.target] += 1
    return dict(result)


def _filter_button(kind: str, value: str, label: str, count: int, color: str) -> str:
    return (
        f'<button class="filter-chip active" data-filter-kind="{html.escape(kind)}" '
        f'data-filter-value="{html.escape(value, quote=True)}" aria-pressed="true">'
        f'<i style="--chip-color:{color}"></i><span>{html.escape(label)}</span><b>{count}</b></button>'
    )


def _layer_color(layer: str) -> str:
    return {
        "trusted_core": "#16804C",
        "execution_verified": "#2E6DD1",
        "contract_verified": "#2E6DD1",
        "evaluation_scoped": "#5E8E62",
        "source_material": "#8490A2",
        "catalog_seed": "#9AA5B5",
        "retrieval_only": "#8490A2",
        "frozen": "#BE7822",
        "quarantined": "#C44747",
        "blocked": "#C44747",
    }.get(layer, "#94A3B8")


def _safe_script_json(value: object) -> str:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )


def _empty_html() -> str:
    return '<div style="padding:32px;color:#64748b;font-family:system-ui">No graph nodes available.</div>'


_HTML_TEMPLATE = r'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<style>
:root{--bg:#F4F7FB;--panel:#FFF;--ink:#172033;--muted:#657087;--line:#E1E7EF;--brand:#285FC8;--brand-soft:#EAF1FF;--shadow:0 10px 26px rgba(30,48,82,.08)}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font-family:Inter,"PingFang SC","Microsoft YaHei",system-ui,sans-serif;overflow:hidden}button,input{font:inherit}button{color:inherit}
.app{height:840px;display:grid;grid-template-rows:62px minmax(0,1fr)}header{display:flex;align-items:center;gap:16px;padding:0 20px;background:#17243F;color:#fff;border-bottom:1px solid rgba(255,255,255,.08)}
.brand{display:flex;align-items:center;gap:10px;min-width:260px}.logo{width:34px;height:34px;display:grid;place-items:center;border-radius:8px;background:#3978E8;font-size:12px;font-weight:800}.brand h1{font-size:15px;margin:0}.brand p{font-size:10px;margin:2px 0 0;color:#B8C6E3}.header-stats{display:flex;gap:8px;margin-left:auto}.stat{padding:6px 10px;border:1px solid rgba(255,255,255,.13);border-radius:6px;background:rgba(255,255,255,.06);font-size:10px;color:#C9D4E9}.stat strong{display:block;color:#fff;font-size:14px}.header-action{border:1px solid rgba(255,255,255,.2);background:transparent;color:#fff;border-radius:6px;padding:7px 10px;cursor:pointer}
.workspace{min-height:0;display:grid;grid-template-columns:248px minmax(480px,1fr) 320px;gap:10px;padding:10px}.workspace.inspector-hidden{grid-template-columns:248px minmax(480px,1fr)}.panel{min-height:0;background:var(--panel);border:1px solid var(--line);border-radius:7px;box-shadow:var(--shadow)}
.sidebar{padding:14px;overflow:auto}.section{padding-bottom:14px;margin-bottom:14px;border-bottom:1px solid var(--line)}.section:last-child{border:0}.section-title{display:flex;justify-content:space-between;align-items:center;font-size:11px;font-weight:720;color:#43506A;margin-bottom:8px}.section-title button{border:0;background:none;color:var(--brand);font-size:10px;cursor:pointer}
.search-wrap{position:relative}.search-wrap input{width:100%;height:36px;padding:0 32px 0 10px;border:1px solid #D4DDE8;border-radius:6px;background:#FAFCFF;outline:none}.search-wrap input:focus{border-color:#6C91ED;box-shadow:0 0 0 3px #E8EFFF}.clear-search{display:none;position:absolute;right:6px;top:6px;width:24px;height:24px;border:0;border-radius:5px;background:#E8EDF5;cursor:pointer}
.filter-list{display:grid;gap:4px}.filter-chip{display:grid;grid-template-columns:8px minmax(0,1fr) auto;align-items:center;gap:7px;width:100%;border:1px solid transparent;border-radius:5px;padding:6px 7px;background:transparent;text-align:left;cursor:pointer;color:#49556D;font-size:11px}.filter-chip:hover{background:#F2F6FB}.filter-chip:not(.active){opacity:.35}.filter-chip i{width:7px;height:7px;border-radius:50%;background:var(--chip-color)}.filter-chip span{overflow:hidden;text-overflow:ellipsis}.filter-chip b{font-size:9px;color:#718096;background:#EDF2F7;border-radius:8px;padding:2px 5px}
.hint{font-size:10px;line-height:1.5;color:#7B879B;margin:7px 0 0}.graph-panel{position:relative;overflow:hidden;display:grid;grid-template-rows:46px minmax(0,1fr) 30px}.graph-toolbar{z-index:3;display:flex;align-items:center;gap:6px;padding:0 10px;border-bottom:1px solid var(--line)}.tool-button{min-width:32px;height:30px;border:1px solid #D4DDE8;background:#fff;border-radius:5px;padding:5px 8px;cursor:pointer;font-size:10px}.tool-button:hover,.tool-button.active{border-color:#7D9BDD;background:var(--brand-soft);color:var(--brand)}.tool-button.icon{font-size:17px;line-height:1;padding:0}.result-label{margin-left:auto;font-size:10px;color:var(--muted);white-space:nowrap}
.stage{position:relative;min-height:0;background-color:#FBFCFE;background-image:radial-gradient(#D7E0EB 1px,transparent 1px);background-size:22px 22px}.stage svg{width:100%;height:100%;display:block;touch-action:none;cursor:grab}.stage svg.panning{cursor:grabbing}.edge{stroke:#9EABBD;stroke-width:1;stroke-opacity:.28;vector-effect:non-scaling-stroke}.edge.selected{stroke:#3978E8;stroke-opacity:.95;stroke-width:2}.edge.blocked{stroke:#C44747;stroke-dasharray:5 4}.node{cursor:pointer}.node circle{stroke:#fff;stroke-width:2;filter:drop-shadow(0 2px 3px rgba(36,48,71,.15));vector-effect:non-scaling-stroke}.node text{font-size:10px;font-weight:620;fill:#2D374C;text-anchor:middle;paint-order:stroke;stroke:#FFF;stroke-width:3px;stroke-linejoin:round;pointer-events:none}.node.context{opacity:.35}.node.match circle{stroke:#111827;stroke-width:3}.node.selected circle{stroke:#111827;stroke-width:4}.node:hover circle{stroke:#172033;stroke-width:3}
.empty{display:none;position:absolute;inset:0;place-items:center;color:var(--muted);font-size:12px;pointer-events:none}.graph-foot{display:flex;align-items:center;justify-content:space-between;padding:0 10px;border-top:1px solid var(--line);font-size:9px;color:#738095;background:#fff}.keyboard{display:flex;gap:9px}.keyboard span{white-space:nowrap}
.inspector{overflow:auto}.inspector.collapsed{display:none}.inspector-head{padding:14px;border-bottom:1px solid var(--line)}.inspector-head span{display:block;color:var(--brand);font-size:9px;font-weight:750;text-transform:uppercase}.inspector-head h2{font-size:16px;margin:4px 0 2px;word-break:break-word}.inspector-head p{font-size:10px;color:var(--muted);margin:0;word-break:break-all}.inspector-body{padding:14px}.overview-card{padding:11px;border-radius:6px;background:#F0F5FF;border:1px solid #DEE7F7}.overview-card strong{display:block;font-size:12px;margin-bottom:4px}.overview-card p{margin:0;color:#627089;font-size:10px;line-height:1.55}.meta-grid{display:grid;grid-template-columns:1fr 1fr;gap:7px;margin:12px 0}.meta{padding:8px;border:1px solid var(--line);border-radius:5px}.meta span{display:block;font-size:9px;color:var(--muted)}.meta strong{display:block;font-size:12px;margin-top:3px;word-break:break-word}.detail-section{margin-top:14px}.detail-section h3{font-size:10px;color:#69758C;text-transform:uppercase;margin:0 0 6px}.json-view{margin:0;padding:8px;border-radius:5px;background:#F6F8FB;border:1px solid #E5E9F0;white-space:pre-wrap;word-break:break-word;font-size:9px;line-height:1.5;max-height:170px;overflow:auto}.connection-list{display:grid;gap:5px}.connection{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:6px;width:100%;padding:7px;border:1px solid var(--line);border-radius:5px;background:#fff;text-align:left;cursor:pointer}.connection:hover{border-color:#8FA9E6;background:#F8FAFF}.connection span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.connection small{color:#788499;font-size:8px}.inspector-action{margin-top:7px;width:100%;border:1px solid #CBD7E6;background:#fff;border-radius:5px;padding:7px;cursor:pointer;font-size:10px}.inspector-action.primary{border-color:#7D9BDD;background:#EAF1FF;color:#285FC8}.inspector-action:disabled{opacity:.4;cursor:default}
@media(max-width:1050px){.workspace{grid-template-columns:220px minmax(360px,1fr)}.inspector{position:absolute;right:10px;top:72px;bottom:10px;width:290px;z-index:6}}@media(max-width:760px){body{overflow:auto}.app{height:auto;min-height:900px}.workspace,.workspace.inspector-hidden{grid-template-columns:1fr}.sidebar{max-height:300px}.graph-panel{height:620px}.inspector{position:static;width:auto}.header-stats{display:none}.brand{min-width:0}.keyboard{display:none}}
</style></head><body><div class="app">
<header><div class="brand"><div class="logo">KG</div><div><h1>scKG Decision Network</h1><p>可拖拽、可展开、受证据治理的单细胞工具网络</p></div></div><div class="header-stats"><div class="stat"><strong>__INITIAL_COUNT__</strong>初始骨架</div><div class="stat"><strong>__POOL_COUNT__</strong>可展开节点</div><div class="stat"><strong>__EDGE_COUNT__</strong>真实关系</div></div><button class="header-action" id="resetAll">重置视图</button></header>
<div class="workspace" id="workspace"><aside class="panel sidebar">
<div class="section"><div class="section-title"><span>搜索已加载节点</span></div><div class="search-wrap"><input id="searchInput" type="search" placeholder="名称、ID、属性…"><button class="clear-search" id="clearSearch">×</button></div><p class="hint">外层精确搜索可载入任意 catalog 节点；这里搜索当前画布与可展开邻居。</p></div>
<div class="section"><div class="section-title"><span>节点类型</span><button data-toggle-all="type">全部切换</button></div><div class="filter-list">__TYPE_CONTROLS__</div></div>
<div class="section"><div class="section-title"><span>治理层</span><button data-toggle-all="layer">全部切换</button></div><div class="filter-list">__LAYER_CONTROLS__</div></div>
</aside><main class="panel graph-panel"><div class="graph-toolbar"><button class="tool-button icon" id="zoomOut" title="缩小" aria-label="缩小">−</button><button class="tool-button icon" id="zoomIn" title="放大" aria-label="放大">+</button><button class="tool-button" id="fitView">适配</button><button class="tool-button active" id="toggleEdges">关系</button><button class="tool-button" id="collapseInitial">收起</button><button class="tool-button" id="toggleInspector">详情</button><span class="result-label" id="resultLabel"></span></div>
<div class="stage" id="stage"><svg id="graphSvg" viewBox="0 0 1200 780" role="img" aria-label="Interactive SCKG knowledge graph" tabindex="0"><defs><marker id="edgeArrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="#9EABBD" opacity=".7"/></marker></defs><g id="viewport"><g id="edgeLayer"></g><g id="nodeLayer"></g></g></svg><div class="empty" id="emptyState">没有符合筛选条件的节点</div></div>
<div class="graph-foot"><span>单击查看详情 · 双击展开一跳邻居</span><div class="keyboard"><span>滚轮：缩放</span><span>拖动画布：平移</span><span>拖动节点：调整布局</span></div></div></main><aside class="panel inspector" id="inspector"><div id="inspectorContent"></div></aside></div></div>
<script id="graphData" type="application/json">__PAYLOAD__</script><script>
(()=>{const data=JSON.parse(document.getElementById('graphData').textContent),svgNS='http://www.w3.org/2000/svg';const nodeById=new Map(data.nodes.map(n=>[n.id,n])),edgeById=new Map(data.edges.map(e=>[e.id,e])),neighbors=new Map(data.nodes.map(n=>[n.id,[]]));data.edges.forEach(e=>{if(neighbors.has(e.source)&&neighbors.has(e.target)){neighbors.get(e.source).push({edge:e,node:nodeById.get(e.target)});neighbors.get(e.target).push({edge:e,node:nodeById.get(e.source)});}});
const initialIds=new Set(data.nodes.filter(n=>n.initial).map(n=>n.id));const state={activeTypes:new Set(data.nodes.map(n=>n.type)),activeLayers:new Set(data.nodes.map(n=>n.governance.layer)),expandedIds:new Set(initialIds),query:'',showEdges:true,selected:null,transform:{x:0,y:0,k:1},visibleIds:new Set(),matchIds:new Set(),drag:null,pan:null,suppressClick:false};const byId=id=>document.getElementById(id),viewport=byId('viewport'),edgeLayer=byId('edgeLayer'),nodeLayer=byId('nodeLayer'),svg=byId('graphSvg'),colors=__NODE_COLORS__,layerLabels=__LAYER_LABELS__;
function searchable(n){return[n.label,n.id,n.type,JSON.stringify(n.properties),JSON.stringify(n.governance)].join(' ').toLowerCase()}function filteredNodes(){let base=data.nodes.filter(n=>state.expandedIds.has(n.id)&&state.activeTypes.has(n.type)&&state.activeLayers.has(n.governance.layer));state.matchIds=new Set();if(state.query){data.nodes.forEach(n=>{if(searchable(n).includes(state.query))state.matchIds.add(n.id)});const context=new Set(state.matchIds);state.matchIds.forEach(id=>(neighbors.get(id)||[]).forEach(x=>context.add(x.node.id)));context.forEach(id=>state.expandedIds.add(id));base=data.nodes.filter(n=>context.has(n.id)&&state.activeTypes.has(n.type)&&state.activeLayers.has(n.governance.layer))}return base.sort((a,b)=>(state.matchIds.has(b.id)-state.matchIds.has(a.id))||b.degree-a.degree||a.label.localeCompare(b.label))}
function render(){const nodes=filteredNodes();state.visibleIds=new Set(nodes.map(n=>n.id));const edges=data.edges.filter(e=>state.visibleIds.has(e.source)&&state.visibleIds.has(e.target));edgeLayer.replaceChildren();nodeLayer.replaceChildren();if(state.showEdges)edges.forEach(e=>{const line=document.createElementNS(svgNS,'line');line.classList.add('edge');if(['blocked','frozen','quarantined'].includes(e.governance.layer))line.classList.add('blocked');line.dataset.edgeId=e.id;line.setAttribute('x1',nodeById.get(e.source).x);line.setAttribute('y1',nodeById.get(e.source).y);line.setAttribute('x2',nodeById.get(e.target).x);line.setAttribute('y2',nodeById.get(e.target).y);line.setAttribute('marker-end','url(#edgeArrow)');const title=document.createElementNS(svgNS,'title');title.textContent=`${e.relation} · ${e.governance.layer}`;line.appendChild(title);edgeLayer.appendChild(line)});nodes.forEach(n=>{const g=document.createElementNS(svgNS,'g');g.classList.add('node');if(state.query&&!state.matchIds.has(n.id))g.classList.add('context');if(state.matchIds.has(n.id))g.classList.add('match');if(state.selected===n.id)g.classList.add('selected');g.dataset.nodeId=n.id;g.setAttribute('transform',`translate(${n.x} ${n.y})`);const c=document.createElementNS(svgNS,'circle'),r=Math.min(18,8+1.5*Math.sqrt(n.degree+1));c.setAttribute('r',r);c.setAttribute('fill',colors[n.type]||'#94A3B8');const label=document.createElementNS(svgNS,'text');label.setAttribute('y',-r-7);label.textContent=n.label.length>28?n.label.slice(0,27)+'…':n.label;const title=document.createElementNS(svgNS,'title');title.textContent=`${n.label} (${n.type})`;g.append(c,label,title);g.addEventListener('pointerdown',event=>startNodeDrag(event,n));g.addEventListener('click',event=>{event.stopPropagation();if(!state.suppressClick)selectNode(n.id)});g.addEventListener('dblclick',event=>{event.preventDefault();event.stopPropagation();expandNeighbors(n.id)});nodeLayer.appendChild(g)});byId('emptyState').style.display=nodes.length?'none':'grid';byId('resultLabel').textContent=`${nodes.length} 节点 · ${edges.length} 关系`;byId('stage').dataset.visibleNodeCount=String(nodes.length);if(state.selected&&!state.visibleIds.has(state.selected))state.selected=null;renderInspector();highlightSelection()}
function selectNode(id){state.selected=id;nodeLayer.querySelectorAll('.node').forEach(item=>item.classList.toggle('selected',item.dataset.nodeId===id));renderInspector();highlightSelection()}function placeAround(parent,items,ring=0){if(!items.length)return;const radius=125+ring*88,step=2*Math.PI/items.length,offset=-Math.PI/2+ring*.32;items.forEach((item,index)=>{const angle=offset+index*step;item.node.x=parent.x+radius*Math.cos(angle);item.node.y=parent.y+radius*Math.sin(angle)})}function expandNeighbors(id){const node=nodeById.get(id),all=neighbors.get(id)||[],hidden=all.filter(item=>!state.expandedIds.has(item.node.id)),batch=hidden.slice(0,12),visibleCount=all.length-hidden.length,ring=Math.floor(visibleCount/12);placeAround(node,batch,ring);batch.forEach(item=>state.expandedIds.add(item.node.id));state.selected=id;render()}function highlightSelection(){edgeLayer.querySelectorAll('.edge').forEach(line=>{const e=edgeById.get(line.dataset.edgeId);line.classList.toggle('selected',!!state.selected&&(e.source===state.selected||e.target===state.selected))})}function escapeHTML(v){return String(v??'').replace(/[&<>'"]/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[ch]))}
function renderInspector(){const root=byId('inspectorContent'),node=state.selected?nodeById.get(state.selected):null;if(!node){root.innerHTML=`<div class="inspector-head"><span>Graph overview</span><h2>图谱概览</h2><p>选择节点查看关系与治理信息</p></div><div class="inspector-body"><div class="overview-card"><strong>真实关系，按需展开</strong><p>初始画布从 Action、Task 与 contract-qualified Tool 的连接骨架开始。双击节点或使用右侧按钮分批展开真实一跳邻居；节点位置不代表证据或流程顺序。</p></div><div class="meta-grid"><div class="meta"><span>当前节点</span><strong>${state.visibleIds.size}</strong></div><div class="meta"><span>可展开池</span><strong>${data.summary.poolNodes}</strong></div><div class="meta"><span>快照节点</span><strong>${data.summary.snapshotNodes}</strong></div><div class="meta"><span>快照关系</span><strong>${data.summary.snapshotEdges}</strong></div></div></div>`;return}const allLinks=(neighbors.get(node.id)||[]).sort((a,b)=>a.node.label.localeCompare(b.node.label)),hidden=allLinks.filter(x=>!state.expandedIds.has(x.node.id)),batchSize=Math.min(12,hidden.length);root.innerHTML='';const head=document.createElement('div');head.className='inspector-head';head.innerHTML=`<span>${escapeHTML(node.type)}</span><h2>${escapeHTML(node.label)}</h2><p>${escapeHTML(node.id)}</p>`;root.appendChild(head);const body=document.createElement('div');body.className='inspector-body';body.innerHTML=`<div class="meta-grid"><div class="meta"><span>治理层</span><strong>${escapeHTML(layerLabels[node.governance.layer]||node.governance.layer)}</strong></div><div class="meta"><span>连接数</span><strong>${node.degree}</strong></div></div><button class="inspector-action primary" id="expandNeighbors" ${hidden.length?'':'disabled'}>展开下一批 · ${batchSize}/${hidden.length}</button><div class="detail-section"><h3>节点属性</h3><pre class="json-view">${escapeHTML(JSON.stringify(node.properties,null,2))}</pre></div><div class="detail-section"><h3>真实关系 · ${allLinks.length}</h3><div class="connection-list" id="connectionList"></div></div>`;root.appendChild(body);const list=body.querySelector('#connectionList');allLinks.slice(0,50).forEach(item=>{const button=document.createElement('button');button.className='connection';button.innerHTML=`<span>${escapeHTML(item.node.label)}</span><small>${escapeHTML(item.edge.relation)}</small>`;button.addEventListener('click',()=>{if(!state.expandedIds.has(item.node.id)){placeAround(node,[item]);state.expandedIds.add(item.node.id);render()}selectNode(item.node.id)});list.appendChild(button)});body.querySelector('#expandNeighbors').addEventListener('click',()=>expandNeighbors(node.id))}
function applyTransform(){viewport.setAttribute('transform',`translate(${state.transform.x} ${state.transform.y}) scale(${state.transform.k})`)}function fitView(){const nodes=[...state.visibleIds].map(id=>nodeById.get(id)).filter(Boolean);if(!nodes.length){state.transform={x:0,y:0,k:1};applyTransform();return}const xs=nodes.map(n=>n.x),ys=nodes.map(n=>n.y),minX=Math.min(...xs),maxX=Math.max(...xs),minY=Math.min(...ys),maxY=Math.max(...ys),w=Math.max(80,maxX-minX),h=Math.max(80,maxY-minY),k=Math.min(1.55,1060/w,650/h);state.transform={x:600-(minX+maxX)*k/2,y:390-(minY+maxY)*k/2,k};applyTransform()}function updateGeometry(id){const node=nodeById.get(id),element=nodeLayer.querySelector(`[data-node-id="${CSS.escape(id)}"]`);if(element)element.setAttribute('transform',`translate(${node.x} ${node.y})`);edgeLayer.querySelectorAll('.edge').forEach(line=>{const edge=edgeById.get(line.dataset.edgeId);if(edge.source===id||edge.target===id){const source=nodeById.get(edge.source),target=nodeById.get(edge.target);line.setAttribute('x1',source.x);line.setAttribute('y1',source.y);line.setAttribute('x2',target.x);line.setAttribute('y2',target.y)}})}function startNodeDrag(event,node){event.stopPropagation();svg.setPointerCapture(event.pointerId);state.drag={id:node.id,pointerId:event.pointerId,startX:event.clientX,startY:event.clientY,moved:false}}
svg.addEventListener('pointerdown',event=>{if(event.target===svg||event.target.parentNode===viewport){svg.setPointerCapture(event.pointerId);state.pan={x:event.clientX,y:event.clientY,tx:state.transform.x,ty:state.transform.y};svg.classList.add('panning')}});svg.addEventListener('pointermove',event=>{if(state.drag){const dx=event.clientX-state.drag.startX,dy=event.clientY-state.drag.startY;if(!state.drag.moved&&Math.hypot(dx,dy)<4)return;state.drag.moved=true;const rect=svg.getBoundingClientRect(),point={x:(event.clientX-rect.left)*1200/rect.width,y:(event.clientY-rect.top)*780/rect.height},node=nodeById.get(state.drag.id);node.x=(point.x-state.transform.x)/state.transform.k;node.y=(point.y-state.transform.y)/state.transform.k;updateGeometry(node.id)}else if(state.pan){const rect=svg.getBoundingClientRect();state.transform.x=state.pan.tx+(event.clientX-state.pan.x)*1200/rect.width;state.transform.y=state.pan.ty+(event.clientY-state.pan.y)*780/rect.height;applyTransform()}});function endPointer(){if(state.drag&&state.drag.moved){state.suppressClick=true;setTimeout(()=>{state.suppressClick=false},0)}state.drag=null;state.pan=null;svg.classList.remove('panning')}svg.addEventListener('pointerup',endPointer);svg.addEventListener('pointercancel',endPointer);svg.addEventListener('lostpointercapture',endPointer);svg.addEventListener('wheel',event=>{event.preventDefault();const rect=svg.getBoundingClientRect(),px=(event.clientX-rect.left)*1200/rect.width,py=(event.clientY-rect.top)*780/rect.height,old=state.transform.k,next=Math.max(.25,Math.min(4,old*(event.deltaY<0?1.12:.89)));state.transform.x=px-(px-state.transform.x)*next/old;state.transform.y=py-(py-state.transform.y)*next/old;state.transform.k=next;applyTransform()},{passive:false});
document.querySelectorAll('.filter-chip').forEach(button=>button.addEventListener('click',()=>{const set=button.dataset.filterKind==='type'?state.activeTypes:state.activeLayers,value=button.dataset.filterValue;set.has(value)?set.delete(value):set.add(value);button.classList.toggle('active',set.has(value));render()}));document.querySelectorAll('[data-toggle-all]').forEach(button=>button.addEventListener('click',()=>{const kind=button.dataset.toggleAll,buttons=[...document.querySelectorAll(`.filter-chip[data-filter-kind="${kind}"]`)],set=kind==='type'?state.activeTypes:state.activeLayers,allOn=buttons.every(item=>set.has(item.dataset.filterValue));buttons.forEach(item=>{allOn?set.delete(item.dataset.filterValue):set.add(item.dataset.filterValue);item.classList.toggle('active',!allOn)});render()}));byId('searchInput').addEventListener('input',event=>{state.query=event.target.value.trim().toLowerCase();byId('clearSearch').style.display=state.query?'block':'none';render()});byId('clearSearch').addEventListener('click',()=>{byId('searchInput').value='';state.query='';byId('clearSearch').style.display='none';render();fitView()});byId('toggleEdges').addEventListener('click',event=>{state.showEdges=!state.showEdges;event.currentTarget.classList.toggle('active',state.showEdges);event.currentTarget.textContent=state.showEdges?'关系':'隐藏';render()});byId('zoomIn').addEventListener('click',()=>{state.transform.k=Math.min(4,state.transform.k*1.2);applyTransform()});byId('zoomOut').addEventListener('click',()=>{state.transform.k=Math.max(.25,state.transform.k/1.2);applyTransform()});byId('fitView').addEventListener('click',fitView);byId('collapseInitial').addEventListener('click',()=>{state.expandedIds=new Set(initialIds);state.selected=null;render();fitView()});byId('toggleInspector').addEventListener('click',()=>{byId('inspector').classList.toggle('collapsed');byId('workspace').classList.toggle('inspector-hidden',byId('inspector').classList.contains('collapsed'))});byId('resetAll').addEventListener('click',()=>{state.activeTypes=new Set(data.nodes.map(n=>n.type));state.activeLayers=new Set(data.nodes.map(n=>n.governance.layer));state.expandedIds=new Set(initialIds);state.query='';state.selected=null;state.showEdges=true;byId('searchInput').value='';document.querySelectorAll('.filter-chip').forEach(item=>item.classList.add('active'));byId('toggleEdges').classList.add('active');byId('toggleEdges').textContent='关系';render();fitView()});render();fitView()})();
</script></body></html>'''
