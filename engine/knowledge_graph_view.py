from __future__ import annotations

import csv
import json
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

import plotly.graph_objects as go


NODE_COLORS = {
    "Tool": (37, 37, 35),
    "Task": (204, 120, 92),
    "Category": (102, 151, 112),
    "Modality": (82, 126, 153),
    "Publication": (93, 184, 166),
    "Benchmark": (232, 165, 90),
    "Source": (139, 139, 133),
    "SourceChunk": (155, 142, 171),
    "ToolContract": (43, 133, 122),
    "Environment": (187, 141, 58),
    "Dataset": (142, 68, 79),
    "Evaluation": (83, 147, 92),
    "Language": (104, 91, 138),
    "RuntimePlatform": (74, 119, 91),
    "Hardware": (76, 112, 128),
    "Resolution": (168, 95, 122),
    "AlgorithmFamily": (46, 145, 159),
    "InputArtifact": (70, 130, 180),
    "OutputArtifact": (76, 151, 112),
    "DataAssumption": (190, 92, 82),
    "Parameter": (151, 116, 166),
}

NODE_ORDER = [
    "Action",
    "Task",
    "Category",
    "Tool",
    "ToolContract",
    "Environment",
    "Dataset",
    "Evaluation",
    "InputArtifact",
    "OutputArtifact",
    "DataAssumption",
    "Parameter",
    "FailureMode",
    "ValidationRule",
    "KnowHow",
    "Modality",
    "AlgorithmFamily",
    "Language",
    "RuntimePlatform",
    "Hardware",
    "Resolution",
    "Publication",
    "Benchmark",
    "Source",
    "SourceChunk",
]
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
    """Build a read-only, display-sized graph from the governed KG snapshot.

    KG v2 JSONL is preferred. The legacy formal TSV view remains only as a
    compatibility fallback for workspaces that have not built a v2 snapshot.
    """

    query = search.strip()
    selected = set(selected_kinds) or {"Tool", "Task"}
    if query:
        selected.update(NODE_ORDER)
    nodes: Dict[str, GraphNode] = {}
    edges_by_key: Dict[Tuple[str, str, str], GraphEdge] = {}

    snapshot_loaded = _load_v2_snapshot(data_dir, nodes, edges_by_key)
    if not snapshot_loaded:
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


def build_decision_graph_neighborhood_view(
    graph_dir: Path,
    tool_name: str,
    *,
    include_source_chunks: int = 6,
) -> KnowledgeGraphView:
    """Build a compact, tool-centered Decision Graph v3 view."""

    from engine.decision_graph_query import DecisionGraphQuery

    payload = DecisionGraphQuery(graph_dir).neighborhood(
        tool_name, include_source_chunks=include_source_chunks
    )
    nodes = {
        row["node_id"]: GraphNode(
            node_id=row["node_id"],
            label=row["label"],
            kind=row["node_type"],
            metadata={
                **row.get("properties", {}),
                "governance_layer": row.get("governance", {}).get("tier", "source_material"),
                "source_bound": row.get("governance", {}).get("source_bound", False),
                "decision_eligible": row.get("governance", {}).get("decision_eligible", False),
            },
        )
        for row in payload["nodes"]
    }
    edges = [
        GraphEdge(
            source=row["source_id"],
            target=row["target_id"],
            relation=row["relation"],
            metadata={
                **row.get("properties", {}),
                "governance_layer": row.get("governance", {}).get("tier", "source_material"),
                "provenance_refs": row.get("governance", {}).get("provenance_refs", []),
            },
        )
        for row in payload["edges"]
    ]
    visible_ids = sorted(
        nodes,
        key=lambda node_id: (
            NODE_ORDER.index(nodes[node_id].kind)
            if nodes[node_id].kind in NODE_ORDER
            else 99,
            nodes[node_id].label.casefold(),
        ),
    )
    return KnowledgeGraphView(
        nodes=nodes,
        edges=edges,
        visible_node_ids=visible_ids,
        visible_edges=edges,
        inventory=dict(Counter(node.kind for node in nodes.values())),
        truncated=False,
    )


def build_decision_graph_workspace_view(graph_dir: Path) -> KnowledgeGraphView:
    """Load the complete governed Decision Graph for progressive exploration.

    The HTML workspace decides which connected semantic backbone is visible at
    first. Keeping the full snapshot here lets users expand real neighboring
    edges without another server round trip or silently inventing links.
    """

    graph_dir = Path(graph_dir)
    node_rows = _read_jsonl(graph_dir / "nodes.jsonl")
    edge_rows = _read_jsonl(graph_dir / "edges.jsonl")
    nodes: Dict[str, GraphNode] = {}
    for row in node_rows:
        governance = row.get("governance") or {}
        node_id = _clean(row.get("node_id"))
        if not node_id:
            continue
        nodes[node_id] = GraphNode(
            node_id=node_id,
            label=_clean(row.get("label")) or node_id,
            kind=_clean(row.get("node_type")) or "Unknown",
            metadata={
                **(row.get("properties") or {}),
                "governance_layer": governance.get("tier", "source_material"),
                "source_bound": bool(governance.get("source_bound")),
                "decision_eligible": bool(governance.get("decision_eligible")),
                "governance_scope": governance.get("scope"),
                "governance_limitations": governance.get("limitations") or [],
                "provenance_refs": governance.get("provenance_refs") or [],
            },
        )
    edges: List[GraphEdge] = []
    for row in edge_rows:
        source = _clean(row.get("source_id"))
        target = _clean(row.get("target_id"))
        if source not in nodes or target not in nodes:
            continue
        governance = row.get("governance") or {}
        edges.append(
            GraphEdge(
                source=source,
                target=target,
                relation=_clean(row.get("relation")) or "RELATED_TO",
                metadata={
                    **(row.get("properties") or {}),
                    "edge_id": row.get("edge_id"),
                    "governance_layer": governance.get("tier", "source_material"),
                    "source_bound": bool(governance.get("source_bound")),
                    "decision_eligible": bool(governance.get("decision_eligible")),
                    "provenance_refs": governance.get("provenance_refs") or [],
                },
            )
        )
    ordered_ids = sorted(
        nodes,
        key=lambda node_id: (
            NODE_ORDER.index(nodes[node_id].kind)
            if nodes[node_id].kind in NODE_ORDER
            else 99,
            nodes[node_id].label.casefold(),
        ),
    )
    return KnowledgeGraphView(
        nodes=nodes,
        edges=edges,
        visible_node_ids=ordered_ids,
        visible_edges=edges,
        inventory=dict(Counter(node.kind for node in nodes.values())),
        truncated=False,
    )


def build_catalog_landscape_html(data_dir: Path) -> str:
    """Render the complete catalog as an expandable category/tool hierarchy."""

    snapshot_path = Path(data_dir) / "catalog" / "scrna_tools_snapshot.json"
    if not snapshot_path.is_file():
        return _empty_graph_html("Catalog snapshot is not available.")
    payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
    rows = payload.get("tools", []) if isinstance(payload, dict) else payload
    categories: Dict[str, List[str]] = {}
    tools: Dict[str, Dict[str, Any]] = {}
    for row_index, row in enumerate(rows if isinstance(rows, list) else []):
        if not isinstance(row, dict):
            continue
        tool_name = _clean(row.get("Tool"))
        if not tool_name:
            continue
        row_categories = [
            _clean(category) for category in row.get("Categories") or [] if _clean(category)
        ]
        # The upstream catalog contains a small number of repeated display names.
        # Keep every source row reachable instead of silently collapsing them.
        tool_id = f"tool:{row_index}:{tool_name.casefold()}"
        details = [
            {
                "id": f"{tool_id}:categories",
                "label": "Categories",
                "kind": "Category",
                "value": ", ".join(_camel_label(item) for item in row_categories) or "Unclassified",
            },
            {
                "id": f"{tool_id}:platform",
                "label": "Platform",
                "kind": "Platform",
                "value": _clean(row.get("Platform")) or "Not recorded",
            },
            {
                "id": f"{tool_id}:license",
                "label": "License",
                "kind": "Metadata",
                "value": _clean(row.get("License")) or "Not recorded",
            },
            {
                "id": f"{tool_id}:activity",
                "label": "Catalog activity",
                "kind": "Metadata",
                "value": (
                    f"added {_clean(row.get('Added')) or 'unknown'}; "
                    f"updated {_clean(row.get('Updated')) or 'unknown'}; "
                    f"citations {row.get('Citations', 0)}"
                ),
            },
        ]
        code_url = _clean(row.get("Code"))
        if code_url:
            details.append(
                {
                    "id": f"{tool_id}:code",
                    "label": "Code repository",
                    "kind": "Code",
                    "value": code_url,
                    "url": code_url,
                }
            )
        for source_kind, source_rows in (
            ("Publication", row.get("Publications") or []),
            ("Preprint", row.get("Preprints") or []),
        ):
            for source_index, source in enumerate(source_rows):
                if not isinstance(source, dict):
                    continue
                doi = _clean(source.get("DOI"))
                details.append(
                    {
                        "id": f"{tool_id}:{source_kind.casefold()}:{source_index}",
                        "label": source_kind,
                        "kind": source_kind,
                        "value": _clean(source.get("Title")) or doi or "Untitled source",
                        "url": f"https://doi.org/{doi}" if doi else "",
                    }
                )
        tools[tool_id] = {
            "id": tool_id,
            "label": tool_name,
            "kind": "Tool",
            "summary": _clean(row.get("Description")) or "No catalog description recorded.",
            "badges": [
                item
                for item in [
                    _clean(row.get("Platform")),
                    _clean(row.get("License")),
                    f"{row.get('NumPubs', 0)} publications",
                ]
                if item
            ],
            "group_ids": [f"category:{item}" for item in row_categories],
            "details": details,
        }
        for category in row_categories:
            name = _clean(category)
            if name:
                categories.setdefault(name, []).append(tool_id)

    palette = ["#18766f", "#d9784e", "#527da5", "#b58a35", "#725b8c"]
    groups = []
    for index, (name, tool_ids) in enumerate(
        sorted(categories.items(), key=lambda item: (-len(set(item[1])), item[0].casefold()))
    ):
        groups.append(
            {
                "id": f"category:{name}",
                "label": _camel_label(name),
                "kind": "Category",
                "color": palette[index % len(palette)],
                "summary": (
                    f"{len(set(tool_ids))} catalog tools. Category membership supports discovery, "
                    "not execution admission."
                ),
                "item_ids": sorted(set(tool_ids), key=lambda item: tools[item]["label"].casefold()),
            }
        )
    hierarchy = {
        "title": "scRNA-tools catalog landscape",
        "description": "Expand category, tool, and source metadata without flattening the full inventory.",
        "tool_count": len(tools),
        "category_count": len(groups),
        "root": {
            "label": "scRNA-tools",
            "count": len(tools),
            "caption": f"{len(tools):,} tools · {len(groups)} categories",
        },
        "groups": groups,
        "items": tools,
        "page_size": 36,
        "boundary": "Catalog metadata is a discovery layer. It cannot admit a tool for execution.",
    }
    return _build_hierarchy_explorer_html(hierarchy, dom_id="catalog-hierarchy")


def build_decision_hierarchy_html(graph_dir: Path, tool_name: str) -> str:
    """Render a governed tool dossier as an expandable decision hierarchy."""

    from engine.decision_graph_query import DecisionGraphQuery

    dossier = DecisionGraphQuery(graph_dir).tool_dossier(tool_name)
    source_groups = [
        ("contracts", "Contracts", "ToolContract", "#18766f", dossier.contracts),
        ("actions", "Actions", "Action", "#236f8e", dossier.actions),
        ("tasks", "Tasks", "Task", "#d9784e", dossier.tasks),
        ("inputs", "Inputs", "InputArtifact", "#527da5", dossier.inputs),
        ("outputs", "Outputs", "OutputArtifact", "#34906b", dossier.outputs),
        ("assumptions", "Assumptions", "DataAssumption", "#c45f54", dossier.assumptions),
        ("environments", "Environments", "Environment", "#b58a35", dossier.environments),
        ("parameters", "Parameters", "Parameter", "#725b8c", dossier.parameters),
        ("failures", "Failure modes", "FailureMode", "#b75d56", dossier.failure_modes),
        ("validators", "Validation rules", "ValidationRule", "#497f75", dossier.validation_rules),
        ("know-how", "Reviewed know-how", "KnowHow", "#7b6a4d", dossier.know_how),
        ("sources", "Source material", "SourceChunk", "#8a7aa1", dossier.source_material),
        ("evaluations", "Evaluations", "Evaluation", "#4f925d", dossier.evaluations),
    ]
    items: Dict[str, Dict[str, Any]] = {}
    groups = []
    for group_id, label, kind, color, rows in source_groups:
        item_ids = []
        for index, row in enumerate(rows):
            item_id = str(row.get("node_id") or f"{group_id}:{index}")
            item_ids.append(item_id)
            details = [
                {
                    "id": f"{item_id}:relation",
                    "label": "Relation",
                    "kind": "Governance",
                    "value": str(row.get("relation") or "not recorded"),
                },
                {
                    "id": f"{item_id}:scope",
                    "label": "Scope",
                    "kind": "Governance",
                    "value": str(row.get("scope") or "not recorded"),
                },
                {
                    "id": f"{item_id}:tier",
                    "label": "Evidence tier",
                    "kind": "Governance",
                    "value": str(row.get("tier") or "not recorded"),
                },
                {
                    "id": f"{item_id}:eligible",
                    "label": "Decision eligible",
                    "kind": "Governance",
                    "value": "yes" if row.get("decision_eligible") else "no",
                },
            ]
            provenance = row.get("provenance_refs") or []
            if provenance:
                details.append(
                    {
                        "id": f"{item_id}:provenance",
                        "label": "Provenance",
                        "kind": "Provenance",
                        "value": "; ".join(str(value) for value in provenance),
                    }
                )
            for key, value in sorted((row.get("properties") or {}).items()):
                if value in (None, "", [], {}):
                    continue
                details.append(
                    {
                        "id": f"{item_id}:property:{key}",
                        "label": _camel_label(str(key)),
                        "kind": "Property",
                        "value": json.dumps(value, ensure_ascii=False, sort_keys=True)
                        if isinstance(value, (dict, list))
                        else str(value),
                    }
                )
            limitations = row.get("limitations") or []
            if limitations:
                details.append(
                    {
                        "id": f"{item_id}:limitations",
                        "label": "Limitations",
                        "kind": "Limitation",
                        "value": "; ".join(str(value) for value in limitations),
                    }
                )
            items[item_id] = {
                "id": item_id,
                "label": str(row.get("label") or item_id),
                "kind": kind,
                "summary": f"{row.get('relation', kind)} · {row.get('scope', 'scope not recorded')}",
                "badges": [str(row.get("tier") or "source_material"), kind],
                "group_ids": [group_id],
                "details": details,
            }
        if item_ids:
            groups.append(
                {
                    "id": group_id,
                    "label": label,
                    "kind": kind,
                    "color": color,
                    "summary": f"{len(item_ids)} governed {label.casefold()} linked to {tool_name}.",
                    "item_ids": item_ids,
                }
            )
    governance_ids = []
    for kind, values in (("Blocker", dossier.blockers), ("Limitation", dossier.limitations)):
        for index, value in enumerate(values):
            item_id = f"governance:{kind.casefold()}:{index}"
            governance_ids.append(item_id)
            items[item_id] = {
                "id": item_id,
                "label": kind,
                "kind": kind,
                "summary": str(value),
                "badges": ["review required" if kind == "Blocker" else "scope boundary"],
                "group_ids": ["governance"],
                "details": [],
            }
    if governance_ids:
        groups.append(
            {
                "id": "governance",
                "label": "Governance",
                "kind": "Governance",
                "color": "#bd5a52",
                "summary": "Explicit blockers and limitations retained by the decision gate.",
                "item_ids": governance_ids,
            }
        )
    hierarchy = {
        "title": f"{tool_name} decision hierarchy",
        "description": "Expand a capability group, inspect a governed node, then open its provenance and scope.",
        "root": {
            "label": tool_name,
            "count": sum(len(group[4]) for group in source_groups),
            "caption": dossier.readiness.replace("_", " "),
        },
        "groups": groups,
        "items": items,
        "page_size": 30,
        "boundary": (
            "Only contract-implemented actions and dataset-scoped evaluation paths support decision admission. "
            "ActionBundle is planning context; source material remains retrieval context."
        ),
    }
    return _build_hierarchy_explorer_html(hierarchy, dom_id="decision-hierarchy")


def _build_hierarchy_explorer_html(payload: Dict[str, Any], *, dom_id: str) -> str:
    data_json = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    template = r"""
<div id="__DOM_ID__" class="hierarchy-explorer">
  <div class="hierarchy-head">
    <div><strong class="hierarchy-title"></strong><span class="hierarchy-description"></span></div>
    <div class="hierarchy-search"><input type="search" placeholder="Search category, tool, evidence..." aria-label="Search graph"><button type="button" data-action="search">Search</button></div>
  </div>
  <div class="hierarchy-toolbar">
    <div class="hierarchy-breadcrumb" aria-label="Graph breadcrumb"></div>
    <div class="hierarchy-actions"><button type="button" data-action="back">Back</button><button type="button" data-action="overview">Overview</button><button type="button" data-action="previous">Previous</button><span class="hierarchy-page"></span><button type="button" data-action="next">Next</button></div>
  </div>
  <svg class="hierarchy-canvas" viewBox="0 0 1200 620" role="img" aria-label="Expandable hierarchical knowledge graph"></svg>
  <div class="hierarchy-detail">
    <div><strong class="detail-title"></strong><span class="detail-summary"></span></div>
    <div class="detail-content"></div>
  </div>
  <div class="hierarchy-boundary"></div>
  <script type="application/json" class="hierarchy-data">__DATA__</script>
</div>
<style>
  * { box-sizing:border-box; }
  .hierarchy-explorer { color:#18212f; font-family:Inter,ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif; border:1px solid #dbe2e9; border-radius:6px; background:#fff; overflow:hidden; }
  .hierarchy-head { display:flex; align-items:flex-end; justify-content:space-between; gap:18px; padding:14px 16px 12px; border-bottom:1px solid #e2e7ed; }
  .hierarchy-head strong { display:block; font-size:15px; font-weight:680; }
  .hierarchy-head span { display:block; margin-top:3px; color:#697586; font-size:12px; }
  .hierarchy-search { display:flex; gap:6px; min-width:min(360px,45%); }
  .hierarchy-search input { width:100%; height:34px; border:1px solid #cfd7e1; border-radius:5px; padding:0 10px; color:#172033; background:#fff; }
  .hierarchy-search button,.hierarchy-actions button { height:34px; border:1px solid #cfd7e1; border-radius:5px; background:#fff; color:#334155; padding:0 10px; cursor:pointer; }
  .hierarchy-search button:hover,.hierarchy-actions button:hover { border-color:#68778a; background:#f6f8fa; }
  .hierarchy-toolbar { min-height:44px; display:flex; align-items:center; justify-content:space-between; gap:12px; padding:5px 16px; border-bottom:1px solid #e2e7ed; background:#f8fafb; }
  .hierarchy-breadcrumb { min-width:0; color:#526071; font-size:12px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
  .hierarchy-breadcrumb b { color:#18212f; font-weight:650; }
  .hierarchy-actions { display:flex; align-items:center; gap:5px; white-space:nowrap; }
  .hierarchy-page { min-width:72px; text-align:center; color:#697586; font-size:11px; }
  .hierarchy-actions button:disabled { opacity:.35; cursor:default; }
  .hierarchy-canvas { width:100%; height:auto; min-height:520px; display:block; background:#fbfcfd; }
  .h-edge { stroke:#cad3dd; stroke-width:1.1; opacity:.75; }
  .h-node { cursor:pointer; }
  .h-node circle { stroke:#fff; stroke-width:3; transition:stroke 120ms ease,transform 120ms ease; transform-box:fill-box; transform-origin:center; }
  .h-node:hover circle,.h-node.is-selected circle { stroke:#172033; transform:scale(1.08); }
  .h-label { fill:#334155; font-size:10px; font-weight:560; pointer-events:none; paint-order:stroke; stroke:#fbfcfd; stroke-width:4px; stroke-linejoin:round; }
  .h-count { fill:#68778a; font-size:9px; pointer-events:none; paint-order:stroke; stroke:#fbfcfd; stroke-width:3px; }
  .h-center { fill:#172033; stroke:#fff; stroke-width:4; }
  .h-center-value { fill:#fff; font-size:16px; font-weight:700; text-anchor:middle; pointer-events:none; }
  .h-center-label { fill:#dce6ef; font-size:10px; text-anchor:middle; pointer-events:none; }
  .hierarchy-detail { min-height:116px; display:grid; grid-template-columns:minmax(230px,.8fr) minmax(0,2fr); gap:24px; padding:14px 16px; border-top:1px solid #e2e7ed; }
  .hierarchy-detail strong { display:block; font-size:14px; }
  .hierarchy-detail span { display:block; color:#697586; font-size:12px; line-height:1.5; margin-top:4px; }
  .detail-content { display:flex; flex-wrap:wrap; align-content:flex-start; gap:6px; max-height:110px; overflow:auto; }
  .detail-chip { border:1px solid #d8e0e8; border-radius:4px; background:#f8fafb; color:#405168; font-size:11px; padding:4px 7px; cursor:pointer; text-align:left; }
  .detail-chip:hover { border-color:#748398; background:#fff; }
  .detail-chip a { color:#1f6682; text-decoration:none; }
  .hierarchy-boundary { padding:9px 16px; border-top:1px solid #e2e7ed; color:#5d6878; background:#fff8f2; font-size:11px; }
  @media(max-width:760px) {
    .hierarchy-head { align-items:stretch; flex-direction:column; }
    .hierarchy-search { min-width:100%; }
    .hierarchy-toolbar { align-items:flex-start; flex-direction:column; }
    .hierarchy-actions { width:100%; overflow:auto; }
    .hierarchy-canvas { min-height:390px; }
    .hierarchy-detail { grid-template-columns:1fr; gap:10px; }
  }
</style>
<script>
(function(){
  const root=document.getElementById("__DOM_ID__");
  if(!root)return;
  const data=JSON.parse(root.querySelector(".hierarchy-data").textContent);
  const svg=root.querySelector(".hierarchy-canvas"),ns="http://www.w3.org/2000/svg";
  const title=root.querySelector(".hierarchy-title"),description=root.querySelector(".hierarchy-description");
  const breadcrumb=root.querySelector(".hierarchy-breadcrumb"),pageText=root.querySelector(".hierarchy-page");
  const detailTitle=root.querySelector(".detail-title"),detailSummary=root.querySelector(".detail-summary"),detailContent=root.querySelector(".detail-content");
  const input=root.querySelector("input[type=search]");
  const buttons=Object.fromEntries([...root.querySelectorAll("[data-action]")].map(el=>[el.dataset.action,el]));
  const groups=Object.fromEntries(data.groups.map(group=>[group.id,group]));
  const state={level:"overview",groupId:null,itemId:null,page:0,selectedDetail:null};
  title.textContent=data.title; description.textContent=data.description; root.querySelector(".hierarchy-boundary").textContent=data.boundary;
  const make=(name,attrs)=>{const el=document.createElementNS(ns,name);Object.entries(attrs||{}).forEach(([key,value])=>el.setAttribute(key,value));return el;};
  const shorten=(value,max=18)=>String(value||"").length>max?String(value).slice(0,max-1)+"…":String(value||"");
  function positions(count){
    const result=[],rings=count<=12?[count]:count<=24?[12,count-12]:[12,12,count-24];
    const radii=rings.length===1?[235]:rings.length===2?[178,278]:[135,220,292];
    let offset=0;
    rings.forEach((size,ring)=>{for(let index=0;index<size;index++){const angle=-Math.PI/2+(Math.PI*2*index/Math.max(1,size))+(ring%2?Math.PI/size:0);result.push({x:600+radii[ring]*Math.cos(angle),y:300+radii[ring]*Math.sin(angle)});}offset+=size;});
    return result;
  }
  function center(label,value,caption){
    const centerCircle=make("circle",{cx:600,cy:300,r:58,class:"h-center"});svg.appendChild(centerCircle);
    const val=make("text",{x:600,y:296,class:"h-center-value"});val.textContent=value;svg.appendChild(val);
    const lab=make("text",{x:600,y:317,class:"h-center-label"});lab.textContent=shorten(label,20);svg.appendChild(lab);
    const tip=make("title");tip.textContent=label+(caption?" · "+caption:"");centerCircle.appendChild(tip);
  }
  function node(row,position,color,onClick,countLabel){
    svg.appendChild(make("line",{x1:600,y1:300,x2:position.x,y2:position.y,class:"h-edge"}));
    const group=make("g",{class:"h-node"});
    const circle=make("circle",{cx:position.x,cy:position.y,r:20,fill:color||"#527da5"});
    const tip=make("title");tip.textContent=row.label+(countLabel?" · "+countLabel:"");circle.appendChild(tip);group.appendChild(circle);
    const label=make("text",{x:position.x,y:position.y-28,"text-anchor":"middle",class:"h-label"});label.textContent=shorten(row.label);group.appendChild(label);
    if(countLabel){const count=make("text",{x:position.x,y:position.y+4,"text-anchor":"middle",class:"h-count"});count.textContent=countLabel;group.appendChild(count);}
    group.addEventListener("click",onClick);svg.appendChild(group);
  }
  function setDetail(titleValue,summaryValue,chips=[]){
    detailTitle.textContent=titleValue;detailSummary.textContent=summaryValue||"";detailContent.replaceChildren();
    chips.forEach(chip=>{const button=document.createElement("button");button.type="button";button.className="detail-chip";button.textContent=chip.label;button.title=chip.value||chip.summary||chip.label;button.addEventListener("click",chip.onClick||(()=>{}));detailContent.appendChild(button);});
  }
  function setBreadcrumb(parts){
    breadcrumb.replaceChildren();parts.forEach((part,index)=>{if(index){breadcrumb.appendChild(document.createTextNode(" / "));}const el=document.createElement(index===0?"b":"span");el.textContent=part;breadcrumb.appendChild(el);});
  }
  function renderOverview(){
    Object.assign(state,{level:"overview",groupId:null,itemId:null,page:0,selectedDetail:null});svg.replaceChildren();
    const pos=positions(data.groups.length);data.groups.forEach((group,index)=>node(group,pos[index],group.color,()=>renderGroup(group.id),String(group.item_ids.length)));
    center(data.root.label,data.root.count.toLocaleString(),data.root.caption);
    setBreadcrumb([data.root.label,"categories"]);pageText.textContent=data.groups.length+" groups";
    setDetail("Choose a category or capability group","Click a node to replace this overview with its child layer. Search can jump directly to a tool or evidence node.",data.groups.map(group=>({label:group.label+" · "+group.item_ids.length,summary:group.summary,onClick:()=>renderGroup(group.id)})));
    updateActions();
  }
  function renderGroup(groupId,page=0){
    const group=groups[groupId];if(!group)return;const all=group.item_ids.map(id=>data.items[id]).filter(Boolean);const pageSize=data.page_size||30;const pages=Math.max(1,Math.ceil(all.length/pageSize));
    Object.assign(state,{level:"group",groupId,itemId:null,page:Math.max(0,Math.min(page,pages-1)),selectedDetail:null});const shown=all.slice(state.page*pageSize,(state.page+1)*pageSize);svg.replaceChildren();
    const pos=positions(shown.length);shown.forEach((item,index)=>node(item,pos[index],group.color,()=>renderItem(groupId,item.id),item.kind));center(group.label,all.length,String(group.kind||"group"));
    setBreadcrumb([data.root.label,group.label]);pageText.textContent="Page "+(state.page+1)+" / "+pages;
    setDetail(group.label,group.summary,shown.map(item=>({label:item.label,summary:item.summary,onClick:()=>renderItem(groupId,item.id)})));updateActions(pages);
  }
  function renderItem(groupId,itemId){
    const group=groups[groupId],item=data.items[itemId];if(!group||!item)return;Object.assign(state,{level:"item",groupId,itemId,selectedDetail:null});svg.replaceChildren();
    const details=item.details||[],pos=positions(details.length);details.forEach((detail,index)=>node(detail,pos[index],detail.kind==="Limitation"?"#bd5a52":"#7b8da8",()=>selectDetail(detail),detail.kind));center(item.label,details.length,item.kind);
    setBreadcrumb([data.root.label,group.label,item.label]);pageText.textContent=details.length+" details";
    setDetail(item.label,item.summary,(item.badges||[]).map(label=>({label})).concat(details.map(detail=>({label:detail.label,summary:detail.value,onClick:()=>selectDetail(detail)}))));updateActions();
  }
  function selectDetail(detail){
    state.selectedDetail=detail.id;setDetail(detail.label,detail.value||"No value recorded.",detail.url?[{label:"Open source",onClick:()=>{if(/^https?:\/\//.test(detail.url))window.open(detail.url,"_blank","noopener");}}]:[]);
  }
  function search(){
    const term=input.value.trim().toLowerCase();if(!term){renderOverview();return;}
    const matches=[];data.groups.forEach(group=>{if(group.label.toLowerCase().includes(term))matches.push({type:"group",group,label:group.label,summary:group.summary});});
    Object.values(data.items).forEach(item=>{if((item.label+" "+item.summary+" "+(item.badges||[]).join(" ")).toLowerCase().includes(term)){const group=groups[item.group_ids[0]];matches.push({type:"item",group,item,label:item.label,summary:item.summary});}});
    setDetail(matches.length+" search results","Results are navigation shortcuts; they do not change graph governance.",matches.slice(0,80).map(match=>({label:match.label,summary:match.summary,onClick:()=>match.type==="group"?renderGroup(match.group.id):renderItem(match.group.id,match.item.id)})));
  }
  function updateActions(pages=1){buttons.back.disabled=state.level==="overview";buttons.previous.disabled=state.level!=="group"||state.page<=0;buttons.next.disabled=state.level!=="group"||state.page>=pages-1;}
  buttons.overview.addEventListener("click",renderOverview);buttons.back.addEventListener("click",()=>state.level==="item"?renderGroup(state.groupId,state.page):renderOverview());
  buttons.previous.addEventListener("click",()=>renderGroup(state.groupId,state.page-1));buttons.next.addEventListener("click",()=>renderGroup(state.groupId,state.page+1));buttons.search.addEventListener("click",search);input.addEventListener("keydown",event=>{if(event.key==="Enter")search();});
  renderOverview();
})();
</script>
"""
    return template.replace("__DOM_ID__", dom_id).replace("__DATA__", data_json)


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
    from engine.interactive_graph_workspace import (
        build_interactive_graph_workspace_html,
    )

    return build_interactive_graph_workspace_html(graph)


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


def _load_v2_snapshot(
    data_dir: Path,
    nodes: Dict[str, GraphNode],
    edges_by_key: Dict[Tuple[str, str, str], GraphEdge],
) -> bool:
    graph_dir = data_dir / "knowledge_graph_v2"
    nodes_path = graph_dir / "nodes.jsonl"
    edges_path = graph_dir / "edges.jsonl"
    if not nodes_path.is_file() or not edges_path.is_file():
        return False
    for row in _read_jsonl(nodes_path):
        node_id = _clean(row.get("node_id"))
        kind = _clean(row.get("node_type"))
        label = _clean(row.get("label"))
        if not node_id or not kind or not label:
            continue
        governance = row.get("governance") if isinstance(row.get("governance"), dict) else {}
        properties = row.get("properties") if isinstance(row.get("properties"), dict) else {}
        _add_node(
            nodes,
            node_id,
            label,
            kind,
            {
                **properties,
                "governance_layer": governance.get("layer", "retrieval_only"),
                "recommendation_eligible": governance.get("recommendation_eligible", False),
                "source_bound": governance.get("source_bound", False),
                "audit_status": governance.get("audit_status", "unknown"),
                "reason_codes": governance.get("reason_codes", []),
                "source": "knowledge_graph_v2/nodes.jsonl",
            },
        )
    for row in _read_jsonl(edges_path):
        source = _clean(row.get("source_id"))
        target = _clean(row.get("target_id"))
        relation = _clean(row.get("relation"))
        if not source or not target or not relation:
            continue
        governance = row.get("governance") if isinstance(row.get("governance"), dict) else {}
        properties = row.get("properties") if isinstance(row.get("properties"), dict) else {}
        _add_edge(
            edges_by_key,
            source,
            target,
            relation,
            {
                **properties,
                "governance_layer": governance.get("layer", "retrieval_only"),
                "recommendation_eligible": governance.get("recommendation_eligible", False),
                "source_bound": governance.get("source_bound", False),
                "audit_status": governance.get("audit_status", "unknown"),
                "reason_codes": governance.get("reason_codes", []),
            },
        )
    return bool(nodes)


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
    for kind, limit in [
        ("Task", 24),
        ("Category", 33),
        ("Tool", 46),
        ("ToolContract", 12),
        ("Environment", 12),
        ("Dataset", 12),
        ("Evaluation", 18),
        ("Modality", 20),
        ("AlgorithmFamily", 24),
        ("Language", 20),
        ("RuntimePlatform", 12),
        ("Hardware", 12),
        ("Resolution", 16),
        ("Benchmark", 26),
        ("Publication", 24),
        ("Source", 20),
        ("SourceChunk", 24),
    ]:
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
    radii = {
        "Task": 0.72,
        "Category": 1.15,
        "Tool": 1.7,
        "ToolContract": 2.45,
        "Environment": 3.1,
        "Dataset": 3.65,
        "Evaluation": 4.15,
        "Modality": 4.6,
        "AlgorithmFamily": 5.0,
        "Language": 5.35,
        "RuntimePlatform": 5.55,
        "Hardware": 5.8,
        "Resolution": 6.05,
        "Publication": 6.35,
        "Benchmark": 6.65,
        "Source": 6.95,
        "SourceChunk": 7.25,
    }
    offsets = {kind: index * math.pi / 17 for index, kind in enumerate(NODE_ORDER)}
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
    inventory = {
        "tools": sum(1 for node in nodes.values() if node.kind == "Tool"),
        "tasks": sum(1 for node in nodes.values() if node.kind == "Task"),
        "categories": sum(1 for node in nodes.values() if node.kind == "Category"),
        "publications": sum(1 for node in nodes.values() if node.kind == "Publication"),
        "benchmarks": sum(1 for node in nodes.values() if node.kind == "Benchmark"),
        "contracts": sum(1 for node in nodes.values() if node.kind == "ToolContract"),
        "environments": sum(1 for node in nodes.values() if node.kind == "Environment"),
        "evaluations": sum(1 for node in nodes.values() if node.kind == "Evaluation"),
        "source_chunks": sum(1 for node in nodes.values() if node.kind == "SourceChunk"),
        "execution_verified": sum(
            1 for node in nodes.values() if node.metadata.get("governance_layer") == "execution_verified"
        ),
        "frozen": sum(
            1 for node in nodes.values() if node.metadata.get("governance_layer") == "frozen"
        ),
        "quarantined": sum(
            1 for node in nodes.values() if node.metadata.get("governance_layer") == "quarantined"
        ),
        "edges": len(edges),
        "candidate_evidence": candidate_rows,
    }
    quality_path = data_dir / "knowledge_graph_v2" / "quality_report.json"
    if quality_path.is_file():
        try:
            quality = json.loads(quality_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            quality = {}
        inventory.update(
            {
                "connected_components": int(quality.get("connected_component_count", 0)),
                "hypothesis_edges": int(quality.get("hypothesis_edge_count", 0)),
                "semantic_coverage_pct": int(
                    round(float(quality.get("tool_semantic_coverage_rate", 0.0)) * 100)
                ),
                "catalog_category_coverage_pct": int(
                    round(float(quality.get("catalog_category_coverage_rate", 0.0)) * 100)
                ),
            }
        )
    return inventory


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


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                rows.append(value)
    return rows


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
    return {
        "Task": 12,
        "Category": 10,
        "Tool": 10,
        "ToolContract": 9,
        "Environment": 9,
        "Dataset": 9,
        "Evaluation": 8,
        "Language": 7,
        "RuntimePlatform": 7,
        "Hardware": 7,
        "Resolution": 7,
        "AlgorithmFamily": 8,
        "Publication": 7,
        "Benchmark": 8,
        "Source": 7,
        "SourceChunk": 5,
        "InputArtifact": 8,
        "OutputArtifact": 8,
        "DataAssumption": 7,
        "Parameter": 6,
    }.get(kind, 8)


def _governance_color(layer: Any) -> str:
    return {
        "trusted_core": "#252523",
        "execution_verified": "#2b857a",
        "retrieval_only": "#b7b2aa",
        "frozen": "#8b8983",
        "quarantined": "#b94f4f",
        "contract_verified": "#2b857a",
        "evaluation_scoped": "#538f5c",
        "source_material": "#b7b2aa",
        "catalog_seed": "#d9d4cc",
        "blocked": "#b94f4f",
    }.get(_clean(layer), "#ffffff")


def _node_alpha(node_id: str, selected: Optional[str], active_ids: Set[str]) -> float:
    if not selected:
        return 0.92
    if node_id == selected:
        return 1.0
    if node_id in active_ids:
        return 0.82
    return 0.16


def _node_size(node_id: str, kind: str, selected: Optional[str], active_ids: Set[str]) -> int:
    base = {
        "Task": 21,
        "Category": 17,
        "Tool": 18,
        "ToolContract": 16,
        "Environment": 16,
        "Dataset": 15,
        "Evaluation": 14,
        "Language": 12,
        "RuntimePlatform": 12,
        "Hardware": 12,
        "Resolution": 12,
        "AlgorithmFamily": 14,
        "Publication": 11,
        "Benchmark": 13,
        "Source": 10,
        "SourceChunk": 8,
        "InputArtifact": 14,
        "OutputArtifact": 14,
        "DataAssumption": 12,
        "Parameter": 10,
    }.get(kind, 12)
    if node_id == selected:
        return base + 8
    if node_id in active_ids:
        return base + 3
    return base


def _metadata_summary(metadata: Dict[str, Any]) -> str:
    parts = []
    for key in [
        "governance_layer",
        "audit_status",
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
        "governance_layer",
        "audit_status",
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


def _camel_label(value: str) -> str:
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", value).replace("_", " ")


def _empty_graph_html(message: str = "No graph nodes matched the current filters.") -> str:
    return f"""
<div style="border:1px solid #dfe4ea;border-radius:6px;background:#fff;padding:24px;color:#687386;">
{message}
</div>
"""
