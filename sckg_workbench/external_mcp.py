"""Optional stdio MCP bridge. All evidence rules live in ExternalEvidenceService."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Annotated, Any, Literal

from pydantic import Field

from .external_evidence import ExternalEvidenceService
from .storage import Workspace


def create_server(workspace: Workspace):
    """Build three read-only tools with the official MCP Python SDK v2."""
    try:
        from mcp.server import MCPServer
        from mcp.types import ToolAnnotations
    except ImportError as exc:
        raise RuntimeError("Install optional dependency mcp==2.3.0 to run the scKG stdio adapter") from exc

    service = ExternalEvidenceService(workspace)
    server = MCPServer("scKG Evidence", instructions=(
        "Use the current release only. Returned claims are source assertions with conditions, "
        "not independent scientific truth. Check the current version and resolve evidence again "
        "before making a formal recommendation; unavailable evidence must not be inferred false."))
    read_only = ToolAnnotations(read_only_hint=True, open_world_hint=False)

    @server.tool(annotations=read_only)
    def current_version() -> dict[str, Any]:
        """Read the current knowledge Release, governance version and reuse-permission version."""
        return service.current_version()

    @server.tool(annotations=read_only)
    def search_evidence(query: str,
                        purpose: Literal["explanation", "recommendation"] = "explanation",
                        limit: Annotated[int, Field(ge=1, le=100)] = 10) -> dict[str, Any]:
        """Search currently approved evidence that has separately reviewed external reuse permission."""
        return service.search_evidence(query, purpose=purpose, limit=limit)

    @server.tool(annotations=read_only)
    def resolve_evidence(candidate_ids: list[str],
                         purpose: Literal["explanation", "recommendation"] = "explanation") -> dict[str, Any]:
        """Recheck exact knowledge IDs against the live Release, suspension and source rights."""
        return service.resolve_evidence(candidate_ids, purpose=purpose)

    return server


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="scKG read-only evidence MCP server over stdio")
    parser.add_argument("--home", type=Path, help="Initialized independent workbench directory")
    args = parser.parse_args(argv)
    workspace = Workspace(args.home) if args.home else Workspace.default()
    try:
        create_server(workspace).run(transport="stdio")
    except (RuntimeError, ValueError) as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
