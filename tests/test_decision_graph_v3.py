from __future__ import annotations

from core.settings import PROJECT_ROOT
from engine.decision_graph_builder import DecisionGraphBuilder
from engine.decision_graph_query import DecisionGraphQuery
from engine.knowledge_graph_view import (
    build_catalog_landscape_html,
    build_decision_graph_neighborhood_view,
    build_decision_graph_workspace_view,
    build_decision_hierarchy_html,
    build_knowledge_graph_html,
)


def _build(tmp_path):
    output = tmp_path / "decision_graph_v3"
    nodes, edges, quality = DecisionGraphBuilder(
        data_dir=PROJECT_ROOT / "data",
        contract_root=PROJECT_ROOT / "contracts" / "tools",
        environment_root=PROJECT_ROOT / "execution" / "environments",
        package_root=PROJECT_ROOT / ".sckg_exec" / "packages",
        output_dir=output,
    ).build(write=True)
    return output, nodes, edges, quality


def test_decision_graph_has_no_hypotheses_and_full_provenance(tmp_path):
    _, _, edges, quality = _build(tmp_path)
    assert quality.integrity_passed
    assert quality.hypothesis_edge_count == 0
    assert all(not edge.relation.startswith("HYPOTHESIZED_") for edge in edges)
    assert all(edge.governance.provenance_refs for edge in edges)
    assert quality.edge_provenance_coverage == 1.0
    assert quality.decision_edge_source_bound_rate == 1.0


def test_contract_graph_has_explicit_io_assumptions_and_environment(tmp_path):
    output, _, _, quality = _build(tmp_path)
    query = DecisionGraphQuery(output)
    dossier = query.tool_dossier("Scrublet")
    assert dossier.readiness == "decision_ready"
    assert dossier.inputs
    assert dossier.outputs
    assert dossier.assumptions
    assert dossier.environments
    assert dossier.parameters
    assert dossier.actions
    assert dossier.failure_modes
    assert dossier.validation_rules
    assert dossier.know_how
    assert quality.contract_io_coverage_rate == 1.0


def test_action_nodes_distinguish_qualified_and_planning_only_task_families(tmp_path):
    output, nodes, edges, quality = _build(tmp_path)
    action_nodes = [node for node in nodes if node.node_type == "Action"]
    assert [(node.node_id, node.label) for node in action_nodes] == [
        ("action:batch-integration", "Batch Integration"),
        ("action:cell-type-annotation", "Cell Type Annotation"),
        ("action:doublet-detection", "Doublet Detection")
    ]
    implementations = [edge for edge in edges if edge.relation == "IMPLEMENTS_ACTION"]
    assert len(implementations) == 6
    qualified = [edge for edge in implementations if edge.governance.decision_eligible]
    assert len(qualified) == 4
    assert {edge.target_id for edge in qualified} == {
        "action:batch-integration",
        "action:doublet-detection",
    }
    assert quality.action_count == 3
    assert quality.action_implementation_count == 4
    assert quality.action_bundle_count == 6
    actions = {item["action_id"]: item for item in DecisionGraphQuery(output).list_actions()}
    assert actions["action:batch-integration"]["tools"] == ["Harmony", "Scanorama"]
    assert actions["action:doublet-detection"]["tools"] == [
        "scDblFinder",
        "Scrublet",
    ]
    assert actions["action:cell-type-annotation"]["tools"] == []
    assert actions["action:cell-type-annotation"]["implementation_count"] == 0


def test_source_only_tool_cannot_be_decision_ready(tmp_path):
    output, _, _, _ = _build(tmp_path)
    dossier = DecisionGraphQuery(output).tool_dossier("CellRank")
    assert dossier.readiness == "source_material"
    assert "verified_tool_contract_missing" in dossier.blockers
    assert "dataset_scoped_evaluation_missing" in dossier.blockers


def test_task_explorer_only_uses_contract_capability_edges(tmp_path):
    output, _, _, quality = _build(tmp_path)
    candidates = DecisionGraphQuery(output).find_tools("doublet detection")
    assert {item.tool_name for item in candidates} == {"Scrublet", "scDblFinder"}
    assert all(item.match_basis == "contract" for item in candidates)
    assert quality.decision_ready_tool_count == 4
    assert quality.catalog_tool_count == 1847


def test_disconnected_components_are_reported_not_artificially_repaired(tmp_path):
    _, _, _, quality = _build(tmp_path)
    assert quality.connected_component_count > 1
    assert quality.isolated_node_count == 0


def test_catalog_landscape_exposes_complete_upstream_inventory():
    html = build_catalog_landscape_html(PROJECT_ROOT / "data")
    assert "scRNA-tools catalog landscape" in html
    assert "1,847" in html
    assert '"category_count": 33' in html
    assert '"tool_count": 1847' in html
    assert "renderGroup" in html
    assert "renderItem" in html
    assert "Graph breadcrumb" in html
    assert "Catalog metadata is a discovery layer" in html


def test_decision_hierarchy_expands_governed_groups(tmp_path):
    output, _, _, _ = _build(tmp_path)
    html = build_decision_hierarchy_html(output, "Scrublet")
    assert "Scrublet decision hierarchy" in html
    assert "Contracts" in html
    assert "Actions" in html
    assert "Inputs" in html
    assert "Outputs" in html
    assert "Source material" in html
    assert "Evaluations" in html
    assert "Failure modes" in html
    assert "Validation rules" in html
    assert "Reviewed know-how" in html
    assert "renderGroup" in html
    assert "renderItem" in html
    assert "Only contract-implemented actions" in html


def test_decision_neighborhood_uses_expandable_network_workspace(tmp_path):
    output, _, _, _ = _build(tmp_path)
    graph = build_decision_graph_neighborhood_view(output, "Scrublet")
    html = build_knowledge_graph_html(graph)

    assert "Scrublet" in html
    assert "scKG Decision Network" in html
    assert "展开一跳邻居" in html
    assert "节点位置不代表证据或流程顺序" in html
    assert "拖动节点：调整布局" in html


def test_complete_decision_workspace_starts_from_connected_action_backbone(tmp_path):
    output, nodes, edges, _ = _build(tmp_path)
    graph = build_decision_graph_workspace_view(output)
    html = build_knowledge_graph_html(graph)

    assert len(graph.nodes) == len(nodes)
    assert len(graph.edges) == len(edges)
    assert len(graph.visible_node_ids) == len(nodes)
    assert "scKG Decision Network" in html
    assert "双击展开一跳邻居" in html
    assert 'id="zoomIn"' in html
    assert 'id="zoomOut"' in html
    assert "marker-end" in html
    assert '"initial":true' in html
    assert '"type":"Action"' in html
    assert "function selectNode(id){state.selected=id;nodeLayer.querySelectorAll" in html
    assert "if(!state.suppressClick)selectNode(n.id)" in html
    assert "updateGeometry(node.id)" in html
    assert "pointercancel" in html
    assert "data.visibleNodeCount" not in html

    payload = html.split('<script id="graphData" type="application/json">', 1)[1].split(
        "</script>", 1
    )[0]
    import json

    data = json.loads(payload)
    initial = {row["id"] for row in data["nodes"] if row["initial"]}
    initial_types = [row["type"] for row in data["nodes"] if row["initial"]]
    assert {
        "action:batch-integration",
        "action:cell-type-annotation",
        "action:doublet-detection",
    } <= initial
    assert initial_types.count("Action") == 3
    assert initial_types.count("Task") >= 2
    assert initial_types.count("Tool") >= 4
    assert initial_types.count("ToolContract") >= 4
    assert len(initial) <= 24
    assert any(
        edge["source"] in initial and edge["target"] in initial
        for edge in data["edges"]
    )
    assert "hidden.slice(0,12)" in html
    assert "展开下一批" in html
