"""Compatibility exports for the original graph UI.

The pure renderer lives in the isolated workbench package; this facade loads no
legacy data and preserves the existing public rendering API.
"""
from sckg_workbench.graph_renderer import (
    LAYER_LABELS,
    NODE_COLORS,
    build_interactive_graph_workspace_html,
)

__all__ = ["LAYER_LABELS", "NODE_COLORS", "build_interactive_graph_workspace_html"]
