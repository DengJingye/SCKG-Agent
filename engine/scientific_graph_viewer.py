"""Reusable, offline scientific graph viewer for Streamlit HTML components.

The viewer is deliberately read-only. It receives an already-governed
``KnowledgeGraphView`` projection and never creates relations, mutates source
artifacts, or reaches a network dependency. Layout, density, filtering, and
selection are browser-local presentation concerns.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any


VIEWER_MODES = {"ontology_schema", "candidate_kg", "scientific_kg"}
LAYOUT_MODES = {"force", "hierarchical", "circular"}
DENSITY_MODES = {"focus", "standard", "global"}

SEMANTIC_STYLES = {
    "existing": {"label": "Existing KG", "color": "#16804C"},
    "statement": {"label": "Candidate Statement", "color": "#3978E8"},
    "scope": {"label": "Scope", "color": "#8B63C7"},
    "entity": {"label": "Method / Operator", "color": "#0A8F84"},
    "evidence": {"label": "Evidence", "color": "#D6A92E"},
    "source": {"label": "Source", "color": "#B87426"},
    "schema": {"label": "Ontology Type", "color": "#526173"},
    "other": {"label": "Other", "color": "#64748B"},
    "invalid": {"label": "Invalid", "color": "#C44747"},
}


@dataclass(frozen=True)
class ScientificGraphViewerConfig:
    mode: str = "candidate_kg"
    default_layout: str = "force"
    default_density: str = "standard"
    show_evidence_by_default: bool = False
    standard_node_cap: int = 260
    global_node_cap: int = 2000
    canvas_height: int = 690

    def __post_init__(self) -> None:
        if self.mode not in VIEWER_MODES:
            raise ValueError(f"unsupported scientific graph viewer mode: {self.mode}")
        if self.default_layout not in LAYOUT_MODES:
            raise ValueError(f"unsupported graph layout: {self.default_layout}")
        if self.default_density not in DENSITY_MODES:
            raise ValueError(f"unsupported graph density: {self.default_density}")
        if self.standard_node_cap < 1 or self.global_node_cap < self.standard_node_cap:
            raise ValueError("graph viewer caps must be positive and global >= standard")


def build_scientific_graph_viewer_html(
    graph: Any,
    *,
    config: ScientificGraphViewerConfig | None = None,
) -> str:
    """Render a page-owned graph workbench without a nested product shell."""

    settings = config or ScientificGraphViewerConfig()
    requested = [node_id for node_id in graph.visible_node_ids if node_id in graph.nodes]
    if not requested:
        return '<div style="padding:32px;color:#64748b;font-family:system-ui">No graph nodes available.</div>'
    degree = _degree(graph.edges)
    requested.sort(key=lambda node_id: (-degree.get(node_id, 0), node_id))
    requested = requested[: settings.global_node_cap]
    requested_set = set(requested)

    nodes: list[dict[str, Any]] = []
    for node_id in requested:
        node = graph.nodes[node_id]
        metadata = dict(node.metadata or {})
        semantic_group = _semantic_group(node.kind, metadata, settings.mode)
        validation_status = str(
            metadata.get("validation_status")
            or metadata.get("candidate_state")
            or metadata.get("status")
            or "CANDIDATE"
        ).upper()
        candidate_state = (
            "INVALID"
            if "INVALID" in validation_status
            else "VALIDATED"
            if validation_status == "VALID"
            else "CANDIDATE"
        )
        is_invalid = candidate_state == "INVALID"
        style = SEMANTIC_STYLES["invalid" if is_invalid else semantic_group]
        display_label = str(metadata.get("display_label") or node.label)
        nodes.append(
            {
                "id": node.node_id,
                "type": node.kind,
                "ontologyType": metadata.get("ontology_type") or metadata.get("proposal_node_type") or node.kind,
                "group": semantic_group,
                "groupLabel": SEMANTIC_STYLES[semantic_group]["label"],
                "displayLabel": display_label,
                "fullLabel": str(metadata.get("full_label") or node.label),
                "color": style["color"],
                "degree": degree.get(node_id, 0),
                "candidateState": candidate_state,
                "invalid": is_invalid,
                "evidenceLayer": semantic_group in {"evidence", "source"},
                "properties": metadata,
            }
        )

    pair_counts: Counter[tuple[str, str]] = Counter()
    for edge in graph.edges:
        if edge.source in requested_set and edge.target in requested_set:
            pair_counts[(edge.source, edge.target)] += 1
    pair_indexes: defaultdict[tuple[str, str], int] = defaultdict(int)
    edges: list[dict[str, Any]] = []
    for index, edge in enumerate(graph.edges):
        if edge.source not in requested_set or edge.target not in requested_set:
            continue
        metadata = dict(edge.metadata or {})
        pair = (edge.source, edge.target)
        parallel_index = pair_indexes[pair]
        pair_indexes[pair] += 1
        status = str(
            metadata.get("validation_status")
            or metadata.get("candidate_state")
            or metadata.get("status")
            or "CANDIDATE"
        ).upper()
        edges.append(
            {
                "id": str(metadata.get("edge_id") or f"edge:{index}:{edge.source}:{edge.target}:{edge.relation}"),
                "source": edge.source,
                "target": edge.target,
                "relation": edge.relation,
                "candidateState": (
                    "INVALID" if "INVALID" in status else "VALIDATED" if status == "VALID" else "CANDIDATE"
                ),
                "parallelIndex": parallel_index,
                "parallelTotal": pair_counts[pair],
                "properties": metadata,
                "provenance": metadata.get("provenance") or metadata.get("provenance_refs") or metadata.get("origin") or [],
                "reason": metadata.get("reason") or metadata.get("validation_reasons") or metadata.get("origin") or "",
            }
        )

    group_counts = Counter(node["group"] for node in nodes)
    payload = {
        "nodes": nodes,
        "edges": edges,
        "styles": SEMANTIC_STYLES,
        "groupCounts": dict(group_counts),
        "summary": {
            "fullNodes": len(nodes),
            "fullEdges": len(edges),
            "sourceNodes": len(graph.nodes),
            "sourceEdges": len(graph.edges),
            "truncated": bool(graph.truncated or len(requested) < len(graph.visible_node_ids)),
        },
        "config": {
            "mode": settings.mode,
            "defaultLayout": settings.default_layout,
            "defaultDensity": settings.default_density,
            "showEvidence": settings.show_evidence_by_default,
            "standardNodeCap": settings.standard_node_cap,
            "canvasHeight": settings.canvas_height,
        },
    }
    return _HTML.replace("__PAYLOAD__", _safe_script_json(payload)).replace(
        "__CANVAS_HEIGHT__", str(settings.canvas_height)
    )


def _semantic_group(kind: str, metadata: dict[str, Any], mode: str) -> str:
    explicit = str(metadata.get("viewer_group") or "").casefold()
    if explicit in SEMANTIC_STYLES and explicit != "invalid":
        return explicit
    ontology_type = str(metadata.get("ontology_type") or metadata.get("proposal_node_type") or kind)
    normalized = ontology_type.casefold()
    kind_normalized = str(kind).casefold()
    if mode == "ontology_schema":
        return "schema"
    if kind_normalized == "existing_kg" or metadata.get("existing_identity"):
        return "existing"
    if any(token in normalized for token in ("statement", "claim")):
        return "statement"
    if "scope" in normalized:
        return "scope"
    if "evidence" in normalized or kind_normalized == "evidence_span":
        return "evidence"
    if "source" in normalized or kind_normalized == "source":
        return "source"
    if any(
        token in normalized
        for token in (
            "method",
            "operator",
            "software",
            "package",
            "representation",
            "tool",
            "entity",
        )
    ):
        return "entity"
    return "other"


def _degree(edges: list[Any]) -> dict[str, int]:
    result: defaultdict[str, int] = defaultdict(int)
    for edge in edges:
        result[edge.source] += 1
        result[edge.target] += 1
    return dict(result)


def _safe_script_json(value: object) -> str:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )


_HTML = r'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<style>
:root{--ink:#172033;--muted:#667085;--line:#DDE3EC;--panel:#fff;--canvas:#F8FAFD;--blue:#285FC8;--blue-soft:#EAF1FF}
*{box-sizing:border-box}body{margin:0;color:var(--ink);font-family:Inter,"PingFang SC",system-ui,sans-serif;background:#fff;overflow:hidden}button,input{font:inherit;color:inherit}
.sgv{height:__CANVAS_HEIGHT__px;display:grid;grid-template-rows:auto auto minmax(0,1fr);border:1px solid var(--line);border-radius:9px;background:#fff;overflow:hidden}
.toolbar{display:flex;align-items:center;gap:7px;flex-wrap:wrap;padding:9px 11px;border-bottom:1px solid var(--line);background:#fff}.toolbar.secondary{padding:6px 11px;background:#FBFCFE}
.search{position:relative;min-width:210px;flex:1;max-width:390px}.search input{width:100%;height:34px;border:1px solid #CAD3E0;border-radius:6px;padding:0 30px 0 10px;outline:none}.search input:focus{border-color:#6C91ED;box-shadow:0 0 0 3px #E8EFFF}.search button{position:absolute;right:4px;top:4px;width:26px;height:26px;border:0;background:transparent;color:#758096;cursor:pointer}
.control-group{display:flex;align-items:center;gap:2px;border-left:1px solid var(--line);padding-left:7px}.control-label{font-size:9px;color:#788499;text-transform:uppercase;margin-right:3px;font-weight:700}.btn{height:30px;border:1px solid transparent;background:transparent;border-radius:5px;padding:0 7px;font-size:10px;cursor:pointer;white-space:nowrap}.btn:hover{background:#F0F4FA}.btn.active{background:var(--blue-soft);border-color:#B9CBF1;color:var(--blue);font-weight:700}.icon{font-size:15px;min-width:30px;padding:0}
.chip{display:flex;align-items:center;gap:5px;border:1px solid #D7DFE9;background:#fff;border-radius:14px;padding:4px 8px;font-size:9px;cursor:pointer}.chip:not(.active){opacity:.38}.chip i,.legend i{width:8px;height:8px;border-radius:50%;background:var(--c);display:inline-block}.chip b{font-size:8px;color:#6E7A90}.count{margin-left:auto;font-size:9px;color:#68758A;white-space:nowrap}.count strong{color:#26344C}
.workbench{min-height:0;display:grid;grid-template-columns:minmax(0,1fr) 300px}.canvas-wrap{position:relative;min-height:0;background-color:var(--canvas);background-image:radial-gradient(#D8E0EB 1px,transparent 1px);background-size:22px 22px}.canvas-wrap svg{width:100%;height:100%;display:block;touch-action:none;cursor:grab}.canvas-wrap svg.panning{cursor:grabbing}.viewport{transform-origin:0 0}
.edge{fill:none;stroke:#98A6B8;stroke-width:1.2;stroke-opacity:.46;vector-effect:non-scaling-stroke}.edge.invalid{stroke:#C44747;stroke-dasharray:5 4}.edge.highlighted{stroke:#285FC8;stroke-width:2.4;stroke-opacity:1}.edge.dimmed{stroke-opacity:.07}.edge-hit{fill:none;stroke:transparent;stroke-width:13;pointer-events:stroke;cursor:pointer}.edge-label{font-size:8px;fill:#607087;text-anchor:middle;paint-order:stroke;stroke:#fff;stroke-width:3px;stroke-linejoin:round;pointer-events:none}.edge-label.hidden{display:none}
.node{cursor:pointer}.node circle{stroke:#fff;stroke-width:2;filter:drop-shadow(0 1px 2px rgba(36,48,71,.22));vector-effect:non-scaling-stroke}.node text{font-size:10px;font-weight:650;fill:#28364C;text-anchor:middle;paint-order:stroke;stroke:#fff;stroke-width:3px;stroke-linejoin:round;pointer-events:none}.node.invalid circle{stroke:#8D2525;stroke-width:3}.node.highlighted circle{stroke:#162033;stroke-width:4}.node.search-match circle{stroke:#F59E0B;stroke-width:4}.node.dimmed{opacity:.13}.node-label.hidden{display:none}
.empty{display:none;position:absolute;inset:0;place-items:center;color:#778399;font-size:12px;pointer-events:none}.canvas-note{position:absolute;left:10px;bottom:8px;font-size:8px;color:#788499;background:rgba(255,255,255,.88);border:1px solid #E1E7EF;border-radius:4px;padding:3px 6px}
.inspector{min-height:0;overflow:auto;border-left:1px solid var(--line);background:#fff}.inspector-head{padding:13px;border-bottom:1px solid var(--line)}.inspector-head span{display:block;font-size:9px;color:var(--blue);text-transform:uppercase;font-weight:800}.inspector-head h2{font-size:15px;margin:4px 0;line-height:1.3;word-break:break-word}.inspector-head p{font-size:9px;color:#7A8699;margin:0;word-break:break-all}.inspector-body{padding:12px}.state{display:inline-flex;border-radius:10px;padding:3px 7px;background:#F0F4FA;font-size:9px;font-weight:750}.state.invalid{background:#FDECEC;color:#A73333}.state.validated{background:#E8F5EE;color:#177048}.meta-grid{display:grid;grid-template-columns:1fr 1fr;gap:6px;margin:10px 0}.meta{border:1px solid #E1E7EF;border-radius:5px;padding:7px}.meta span{display:block;font-size:8px;color:#7A8699}.meta strong{display:block;font-size:10px;margin-top:3px;word-break:break-word}.section{margin-top:12px}.section h3{font-size:9px;text-transform:uppercase;color:#6C788D;margin:0 0 5px}.json{margin:0;padding:8px;background:#F7F9FC;border:1px solid #E2E7EF;border-radius:5px;white-space:pre-wrap;word-break:break-word;font-size:9px;line-height:1.45;max-height:230px;overflow:auto}.overview{font-size:10px;line-height:1.55;color:#5F6C80;background:#F4F7FC;border:1px solid #E1E7EF;border-radius:6px;padding:10px}
.legend{display:flex;gap:10px;flex-wrap:wrap;margin-top:10px}.legend span{display:flex;gap:4px;align-items:center;font-size:8px;color:#6D798D}
@media(max-width:850px){.workbench{grid-template-columns:1fr}.inspector{display:none}.control-label{display:none}.btn{padding:0 5px}.count{width:100%;margin-left:0}}
</style></head><body>
<div class="sgv" data-viewer="ScientificGraphViewer"><div class="toolbar">
  <div class="search"><input id="search" type="search" placeholder="Search nodes, types, or properties"><button id="clearSearch">×</button></div>
  <div class="control-group" id="scopeControls"><span class="control-label">View</span><button class="btn" data-scope="focus">Focus</button><button class="btn" data-scope="standard">Standard</button><button class="btn" data-scope="global">Global</button></div>
  <div class="control-group" id="layoutControls"><span class="control-label">Layout</span><button class="btn" data-layout="force">Force-directed</button><button class="btn" data-layout="hierarchical">Hierarchical</button><button class="btn" data-layout="circular">Circular</button></div>
  <div class="control-group"><button class="btn" id="showEvidence">Show Evidence</button><button class="btn icon" id="zoomOut" title="Zoom out">−</button><button class="btn icon" id="zoomIn" title="Zoom in">+</button><button class="btn" id="fit">Fit</button></div>
</div><div class="toolbar secondary"><div id="filterBar" style="display:flex;gap:5px;flex-wrap:wrap"></div><div class="count" id="counts"></div></div>
<div class="workbench"><div class="canvas-wrap"><svg id="canvas" viewBox="0 0 1200 720" aria-label="Scientific knowledge graph canvas"><defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" fill="#8796AA"/></marker></defs><g id="viewport" class="viewport"><g id="edges"></g><g id="edgeLabels"></g><g id="nodes"></g></g></svg><div class="empty" id="empty">No nodes match the current view.</div><div class="canvas-note">Wheel: zoom · drag canvas: pan · click blank: reset highlight</div></div><aside class="inspector"><div id="inspector"></div></aside></div></div>
<script id="payload" type="application/json">__PAYLOAD__</script><script>
(()=>{const data=JSON.parse(document.getElementById('payload').textContent),ns='http://www.w3.org/2000/svg';
const byId=id=>document.getElementById(id),nodeById=new Map(data.nodes.map(n=>[n.id,n])),edgeById=new Map(data.edges.map(e=>[e.id,e])),neighbors=new Map(data.nodes.map(n=>[n.id,new Set()]));data.edges.forEach(e=>{if(neighbors.has(e.source)&&neighbors.has(e.target)){neighbors.get(e.source).add(e.target);neighbors.get(e.target).add(e.source)}});
const state={layout:data.config.defaultLayout,density:data.config.defaultDensity,showEvidence:data.config.showEvidence,activeGroups:new Set(data.nodes.map(n=>n.group)),includeInvalid:true,selectedNode:null,selectedEdge:null,query:'',visibleNodes:[],visibleEdges:[],transform:{x:0,y:0,k:1},pan:null};
const svg=byId('canvas'),viewport=byId('viewport'),nodeLayer=byId('nodes'),edgeLayer=byId('edges'),edgeLabelLayer=byId('edgeLabels');
function escapeHTML(v){return String(v??'').replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]))}
function searchable(n){return[n.displayLabel,n.fullLabel,n.type,n.ontologyType,JSON.stringify(n.properties)].join(' ').toLowerCase()}
function matches(n){return!state.query||searchable(n).includes(state.query)}
function baseNodes(){return data.nodes.filter(n=>state.activeGroups.has(n.group)&&(state.showEvidence||!n.evidenceLayer)&&(state.includeInvalid||!n.invalid))}
function scopedNodes(){const base=baseNodes(),baseIds=new Set(base.map(n=>n.id));if(state.density==='global')return base;if(state.density==='standard'){if(base.length<=data.config.standardNodeCap)return base;const matched=base.filter(matches),ordered=[...base].sort((a,b)=>b.degree-a.degree||a.id.localeCompare(b.id)),ids=new Set(matched.map(n=>n.id));for(const n of ordered){if(ids.size>=data.config.standardNodeCap)break;ids.add(n.id)}return base.filter(n=>ids.has(n.id))}let seed=state.selectedNode&&baseIds.has(state.selectedNode)?state.selectedNode:null;if(!seed){const match=base.find(matches);seed=(match||[...base].sort((a,b)=>b.degree-a.degree||a.id.localeCompare(b.id))[0])?.id}if(!seed)return[];const ids=new Set([seed]);(neighbors.get(seed)||new Set()).forEach(id=>{if(baseIds.has(id))ids.add(id)});return base.filter(n=>ids.has(n.id))}
function hash(value){let h=2166136261;for(let i=0;i<value.length;i++){h^=value.charCodeAt(i);h=Math.imul(h,16777619)}return Math.abs(h)}
function circularLayout(nodes){const groups=new Map();nodes.forEach(n=>{if(!groups.has(n.group))groups.set(n.group,[]);groups.get(n.group).push(n)});const ordered=[...groups.entries()].sort((a,b)=>a[0].localeCompare(b[0])),flat=[];ordered.forEach(([,items])=>flat.push(...items.sort((a,b)=>a.id.localeCompare(b.id))));const radius=Math.min(300,100+flat.length*7);flat.forEach((n,i)=>{const a=-Math.PI/2+2*Math.PI*i/Math.max(1,flat.length);n.x=600+radius*Math.cos(a);n.y=360+radius*.82*Math.sin(a)})}
function hierarchicalLayout(nodes,edges){const ids=new Set(nodes.map(n=>n.id)),incoming=new Map(nodes.map(n=>[n.id,0])),out=new Map(nodes.map(n=>[n.id,[]]));edges.forEach(e=>{if(ids.has(e.source)&&ids.has(e.target)){incoming.set(e.target,(incoming.get(e.target)||0)+1);out.get(e.source).push(e.target)}});let roots=nodes.filter(n=>(incoming.get(n.id)||0)===0&&n.degree>0).sort((a,b)=>b.degree-a.degree||a.id.localeCompare(b.id));if(!roots.length&&nodes.length)roots=[[...nodes].sort((a,b)=>b.degree-a.degree||a.id.localeCompare(b.id))[0]];if(roots.length===1&&Array.isArray(roots[0]))roots=roots[0];const levels=new Map(),queue=[];roots.forEach(n=>{levels.set(n.id,0);queue.push(n.id)});while(queue.length){const id=queue.shift(),next=(levels.get(id)||0)+1;(out.get(id)||[]).forEach(target=>{if(!levels.has(target)){levels.set(target,next);queue.push(target)}})}const max=Math.max(0,...levels.values()),isolated=[];nodes.forEach(n=>{if(!levels.has(n.id)){if(n.degree===0)isolated.push(n);else levels.set(n.id,max+1)}});const rows=new Map();nodes.filter(n=>!isolated.includes(n)).forEach(n=>{const level=levels.get(n.id)||0;if(!rows.has(level))rows.set(level,[]);rows.get(level).push(n)});[...rows.entries()].forEach(([level,row])=>{row.sort((a,b)=>b.degree-a.degree||a.id.localeCompare(b.id));const step=1080/(row.length+1);row.forEach((n,i)=>{n.x=60+step*(i+1);n.y=80+level*Math.min(145,500/Math.max(1,rows.size-1))})});isolated.sort((a,b)=>a.id.localeCompare(b.id)).forEach((n,i)=>{const cols=Math.ceil(Math.sqrt(isolated.length));n.x=120+(i%cols)*Math.min(100,900/Math.max(1,cols));n.y=610+Math.floor(i/cols)*45})}
function largeForceLayout(nodes,edges){circularLayout(nodes);const by=new Map(nodes.map(n=>[n.id,n]));for(let iter=0;iter<36;iter++){const cooling=1-iter/36,forces=new Map(nodes.map(n=>[n.id,{x:0,y:0}]));edges.forEach(e=>{const a=by.get(e.source),b=by.get(e.target);if(!a||!b)return;const dx=b.x-a.x,dy=b.y-a.y,dist=Math.max(1,Math.hypot(dx,dy)),f=(dist-80)*.0025;forces.get(a.id).x+=dx/dist*f;forces.get(a.id).y+=dy/dist*f;forces.get(b.id).x-=dx/dist*f;forces.get(b.id).y-=dy/dist*f});nodes.forEach(n=>{const f=forces.get(n.id),jitter=((hash(n.id)%17)-8)*.003;n.x=Math.max(35,Math.min(1165,n.x+f.x*cooling*10+(600-n.x)*.001+jitter));n.y=Math.max(35,Math.min(685,n.y+f.y*cooling*10+(350-n.y)*.001-jitter))})}}
function forceLayout(nodes,edges){if(nodes.length>220){largeForceLayout(nodes,edges);return}const count=Math.max(1,nodes.length),radius=Math.min(260,90+count*6);nodes.forEach((n,i)=>{const a=2*Math.PI*((hash(n.id)%10000)/10000+i/count);n.x=600+radius*Math.cos(a);n.y=350+radius*.72*Math.sin(a)});const by=new Map(nodes.map(n=>[n.id,n])),iterations=nodes.length<70?220:100;for(let iter=0;iter<iterations;iter++){const cooling=1-iter/iterations,forces=new Map(nodes.map(n=>[n.id,{x:0,y:0}]));for(let i=0;i<nodes.length;i++)for(let j=i+1;j<nodes.length;j++){const a=nodes[i],b=nodes[j],dx=a.x-b.x,dy=a.y-b.y,d2=Math.max(80,dx*dx+dy*dy),f=2600/d2,dist=Math.sqrt(d2);forces.get(a.id).x+=dx/dist*f;forces.get(a.id).y+=dy/dist*f;forces.get(b.id).x-=dx/dist*f;forces.get(b.id).y-=dy/dist*f}edges.forEach(e=>{const a=by.get(e.source),b=by.get(e.target);if(!a||!b)return;const dx=b.x-a.x,dy=b.y-a.y,dist=Math.max(1,Math.hypot(dx,dy)),f=(dist-115)*.006;forces.get(a.id).x+=dx/dist*f;forces.get(a.id).y+=dy/dist*f;forces.get(b.id).x-=dx/dist*f;forces.get(b.id).y-=dy/dist*f});nodes.forEach(n=>{const f=forces.get(n.id);n.x=Math.max(45,Math.min(1155,n.x+f.x*cooling*8+(600-n.x)*.002));n.y=Math.max(45,Math.min(675,n.y+f.y*cooling*8+(350-n.y)*.002))})}const isolated=nodes.filter(n=>n.degree===0),connected=nodes.filter(n=>n.degree>0);if(isolated.length){const outer=connected.length?315:220;isolated.forEach((n,i)=>{const a=2*Math.PI*i/isolated.length;n.x=600+outer*Math.cos(a);n.y=350+outer*.8*Math.sin(a)})}}
function layout(nodes,edges){if(state.layout==='circular')circularLayout(nodes);else if(state.layout==='hierarchical')hierarchicalLayout(nodes,edges);else forceLayout(nodes,edges)}
function curve(e){const s=nodeById.get(e.source),t=nodeById.get(e.target),dx=t.x-s.x,dy=t.y-s.y,len=Math.max(1,Math.hypot(dx,dy)),offset=(e.parallelIndex-(e.parallelTotal-1)/2)*24,px=-dy/len,py=dx/len,cx=(s.x+t.x)/2+px*offset,cy=(s.y+t.y)/2+py*offset;return{path:`M${s.x},${s.y} Q${cx},${cy} ${t.x},${t.y}`,label:{x:.25*s.x+.5*cx+.25*t.x,y:.25*s.y+.5*cy+.25*t.y}}}
function render(){const nodes=scopedNodes(),ids=new Set(nodes.map(n=>n.id)),edges=data.edges.filter(e=>ids.has(e.source)&&ids.has(e.target));state.visibleNodes=nodes;state.visibleEdges=edges;layout(nodes,edges);edgeLayer.replaceChildren();edgeLabelLayer.replaceChildren();nodeLayer.replaceChildren();edges.forEach(e=>{const c=curve(e),path=document.createElementNS(ns,'path');path.setAttribute('d',c.path);path.setAttribute('marker-end','url(#arrow)');path.classList.add('edge');if(e.candidateState==='INVALID')path.classList.add('invalid');path.dataset.edgeId=e.id;const hit=document.createElementNS(ns,'path');hit.setAttribute('d',c.path);hit.classList.add('edge-hit');hit.dataset.edgeId=e.id;hit.addEventListener('click',event=>{event.stopPropagation();selectEdge(e.id)});edgeLayer.append(path,hit);const label=document.createElementNS(ns,'text');label.classList.add('edge-label');label.dataset.edgeId=e.id;label.setAttribute('x',c.label.x);label.setAttribute('y',c.label.y);label.textContent=e.relation;edgeLabelLayer.appendChild(label)});nodes.forEach(n=>{const g=document.createElementNS(ns,'g');g.classList.add('node');if(n.invalid)g.classList.add('invalid');g.dataset.nodeId=n.id;g.setAttribute('transform',`translate(${n.x} ${n.y})`);const circle=document.createElementNS(ns,'circle'),r=state.density==='global'?Math.max(4,Math.min(8,4+Math.sqrt(n.degree))):state.density==='focus'?14:Math.max(8,Math.min(13,8+Math.sqrt(n.degree)));circle.setAttribute('r',r);circle.setAttribute('fill',n.color);const text=document.createElementNS(ns,'text');text.classList.add('node-label');text.setAttribute('y',-r-6);text.textContent=(state.density==='global'||state.layout==='hierarchical')&&n.group==='statement'?n.displayLabel.split(' · ')[0]:n.displayLabel;g.append(circle,text);g.addEventListener('click',event=>{event.stopPropagation();selectNode(n.id)});nodeLayer.appendChild(g)});byId('empty').style.display=nodes.length?'none':'grid';byId('counts').innerHTML=`Full graph: <strong>${data.summary.fullNodes} nodes · ${data.summary.fullEdges} edges</strong> &nbsp; Visible: <strong>${nodes.length} nodes · ${edges.length} edges</strong>`;syncControls();applyHighlight();updateLOD();renderInspector()}
function syncControls(){document.querySelectorAll('[data-layout]').forEach(b=>b.classList.toggle('active',b.dataset.layout===state.layout));document.querySelectorAll('[data-scope]').forEach(b=>b.classList.toggle('active',b.dataset.scope===state.density));byId('showEvidence').classList.toggle('active',state.showEvidence);byId('showEvidence').textContent=state.showEvidence?'Hide Evidence':'Show Evidence';document.querySelectorAll('.chip[data-group]').forEach(b=>b.classList.toggle('active',state.activeGroups.has(b.dataset.group)));const invalid=byId('invalidFilter');if(invalid)invalid.classList.toggle('active',state.includeInvalid)}
function relatedIds(){const ids=new Set();if(state.selectedNode){ids.add(state.selectedNode);(neighbors.get(state.selectedNode)||new Set()).forEach(id=>ids.add(id))}else if(state.selectedEdge){const e=edgeById.get(state.selectedEdge);if(e){ids.add(e.source);ids.add(e.target)}}return ids}
function applyHighlight(){const related=relatedIds(),matched=new Set(state.visibleNodes.filter(matches).map(n=>n.id)),hasQuery=!!state.query,hasSelection=related.size>0;nodeLayer.querySelectorAll('.node').forEach(g=>{const id=g.dataset.nodeId,isRelated=related.has(id),isMatch=matched.has(id);g.classList.toggle('highlighted',isRelated);g.classList.toggle('search-match',hasQuery&&isMatch);g.classList.toggle('dimmed',(hasSelection&&!isRelated)||(hasQuery&&!isMatch&&!related.has(id)))});edgeLayer.querySelectorAll('.edge').forEach(path=>{const e=edgeById.get(path.dataset.edgeId),selected=state.selectedEdge===e.id||state.selectedNode&&(e.source===state.selectedNode||e.target===state.selectedNode),searchRelated=matched.has(e.source)||matched.has(e.target);path.classList.toggle('highlighted',!!selected);path.classList.toggle('dimmed',(hasSelection&&!selected)||(hasQuery&&!searchRelated))});edgeLabelLayer.querySelectorAll('.edge-label').forEach(label=>{const e=edgeById.get(label.dataset.edgeId),keep=state.selectedEdge===e.id||state.selectedNode&&(e.source===state.selectedNode||e.target===state.selectedNode);label.style.opacity=hasSelection&&!keep?'.08':'1'})}
function updateLOD(){const focus=state.density==='focus',zoom=state.transform.k;nodeLayer.querySelectorAll('.node').forEach(g=>{const n=nodeById.get(g.dataset.nodeId),label=g.querySelector('.node-label'),meaningful=n.degree>=4||n.group==='statement'||(state.query&&matches(n))||state.selectedNode===n.id,show=focus||zoom>1.7||meaningful;label.classList.toggle('hidden',!show)});edgeLabelLayer.querySelectorAll('.edge-label').forEach(label=>{const show=(state.visibleEdges.length<=55&&(focus||zoom>1.7))||state.selectedEdge===label.dataset.edgeId;label.classList.toggle('hidden',!show)})}
function selectNode(id){state.selectedNode=id;state.selectedEdge=null;if(state.density==='focus')render();else{applyHighlight();updateLOD();renderInspector()}}
function selectEdge(id){state.selectedEdge=id;state.selectedNode=null;applyHighlight();updateLOD();renderInspector()}
function stateClass(value){return value==='INVALID'?'invalid':value==='VALIDATED'?'validated':''}
function renderInspector(){const root=byId('inspector');if(state.selectedEdge){const e=edgeById.get(state.selectedEdge),s=nodeById.get(e.source),t=nodeById.get(e.target);root.innerHTML=`<div class="inspector-head"><span>Relation</span><h2>${escapeHTML(e.relation)}</h2><p>${escapeHTML(e.id)}</p></div><div class="inspector-body"><span class="state ${stateClass(e.candidateState)}">${escapeHTML(e.candidateState)}</span><div class="meta-grid"><div class="meta"><span>Source</span><strong>${escapeHTML(s?.displayLabel||e.source)}</strong></div><div class="meta"><span>Target</span><strong>${escapeHTML(t?.displayLabel||e.target)}</strong></div></div><div class="section"><h3>Provenance</h3><pre class="json">${escapeHTML(JSON.stringify(e.provenance,null,2))}</pre></div><div class="section"><h3>Reason / properties</h3><pre class="json">${escapeHTML(JSON.stringify({reason:e.reason,...e.properties},null,2))}</pre></div></div>`;return}if(state.selectedNode){const n=nodeById.get(state.selectedNode);root.innerHTML=`<div class="inspector-head"><span>${escapeHTML(n.groupLabel)} · ${escapeHTML(n.ontologyType)}</span><h2>${escapeHTML(n.fullLabel)}</h2><p>${escapeHTML(n.id)}</p></div><div class="inspector-body"><span class="state ${stateClass(n.candidateState)}">${escapeHTML(n.candidateState)}</span><div class="meta-grid"><div class="meta"><span>Connections</span><strong>${n.degree}</strong></div><div class="meta"><span>Semantic group</span><strong>${escapeHTML(n.groupLabel)}</strong></div></div><div class="section"><h3>Full detail / provenance</h3><pre class="json">${escapeHTML(JSON.stringify(n.properties,null,2))}</pre></div></div>`;return}root.innerHTML=`<div class="inspector-head"><span>ScientificGraphViewer</span><h2>${escapeHTML(data.config.mode.replaceAll('_',' '))}</h2><p>Ontology-driven, read-only graph projection</p></div><div class="inspector-body"><div class="overview">Select a node or relation to inspect its full label, validation state, provenance, and raw properties. Focus view follows the selected node and its real one-hop neighborhood.</div><div class="legend">${Object.entries(data.styles).filter(([key])=>key!=='other'&&key!=='schema').map(([,style])=>`<span><i style="--c:${style.color}"></i>${escapeHTML(style.label)}</span>`).join('')}</div></div>`}
function fit(){const nodes=state.visibleNodes;if(!nodes.length)return;const xs=nodes.map(n=>n.x),ys=nodes.map(n=>n.y),minX=Math.min(...xs),maxX=Math.max(...xs),minY=Math.min(...ys),maxY=Math.max(...ys),w=Math.max(100,maxX-minX+100),h=Math.max(100,maxY-minY+100),k=Math.min(1.8,1100/w,640/h);state.transform={x:600-(minX+maxX)*k/2,y:360-(minY+maxY)*k/2,k};applyTransform()}
function applyTransform(){viewport.setAttribute('transform',`translate(${state.transform.x} ${state.transform.y}) scale(${state.transform.k})`);updateLOD()}
function buildFilters(){const bar=byId('filterBar'),groups=[...new Set(data.nodes.map(n=>n.group))].sort();groups.forEach(group=>{const style=data.styles[group],button=document.createElement('button');button.className='chip active';button.dataset.group=group;button.innerHTML=`<i style="--c:${style.color}"></i><span>${escapeHTML(style.label)}</span><b>${data.groupCounts[group]||0}</b>`;button.addEventListener('click',()=>{state.activeGroups.has(group)?state.activeGroups.delete(group):state.activeGroups.add(group);render();fit()});bar.appendChild(button)});const invalidCount=data.nodes.filter(n=>n.invalid).length;if(invalidCount){const button=document.createElement('button');button.id='invalidFilter';button.className='chip active';button.innerHTML=`<i style="--c:${data.styles.invalid.color}"></i><span>Invalid</span><b>${invalidCount}</b>`;button.addEventListener('click',()=>{state.includeInvalid=!state.includeInvalid;render();fit()});bar.appendChild(button)}}
document.querySelectorAll('[data-layout]').forEach(button=>button.addEventListener('click',()=>{state.layout=button.dataset.layout;render();fit()}));document.querySelectorAll('[data-scope]').forEach(button=>button.addEventListener('click',()=>{state.density=button.dataset.scope;render();fit()}));byId('showEvidence').addEventListener('click',()=>{state.showEvidence=!state.showEvidence;render();fit()});byId('search').addEventListener('input',event=>{state.query=event.target.value.trim().toLowerCase();applyHighlight();updateLOD()});byId('clearSearch').addEventListener('click',()=>{byId('search').value='';state.query='';applyHighlight();updateLOD()});byId('zoomIn').addEventListener('click',()=>{state.transform.k=Math.min(5,state.transform.k*1.2);applyTransform()});byId('zoomOut').addEventListener('click',()=>{state.transform.k=Math.max(.18,state.transform.k*.82);applyTransform()});byId('fit').addEventListener('click',fit);
svg.addEventListener('click',event=>{if(event.target===svg){state.selectedNode=null;state.selectedEdge=null;applyHighlight();updateLOD();renderInspector()}});svg.addEventListener('pointerdown',event=>{if(event.target===svg){svg.setPointerCapture(event.pointerId);state.pan={x:event.clientX,y:event.clientY,tx:state.transform.x,ty:state.transform.y};svg.classList.add('panning')}});svg.addEventListener('pointermove',event=>{if(!state.pan)return;const rect=svg.getBoundingClientRect();state.transform.x=state.pan.tx+(event.clientX-state.pan.x)*1200/rect.width;state.transform.y=state.pan.ty+(event.clientY-state.pan.y)*720/rect.height;applyTransform()});function endPan(){state.pan=null;svg.classList.remove('panning')}svg.addEventListener('pointerup',endPan);svg.addEventListener('pointercancel',endPan);svg.addEventListener('wheel',event=>{event.preventDefault();const rect=svg.getBoundingClientRect(),px=(event.clientX-rect.left)*1200/rect.width,py=(event.clientY-rect.top)*720/rect.height,old=state.transform.k,next=Math.max(.18,Math.min(5,old*(event.deltaY<0?1.12:.89)));state.transform.x=px-(px-state.transform.x)*next/old;state.transform.y=py-(py-state.transform.y)*next/old;state.transform.k=next;applyTransform()},{passive:false});
buildFilters();render();fit();
})();
</script></body></html>'''
