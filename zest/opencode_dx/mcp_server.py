"""Read-only OpenCode session analysis exposed as a local MCP tool."""

from __future__ import annotations

from pathlib import Path

from mcp.server.fastmcp import FastMCP

from .core import analyze_snapshot


mcp = FastMCP("Design decision analysis")


@mcp.tool()
def analyze_snapshot_file(snapshot_path: str) -> dict:
    """Analyze a completed OpenCode session snapshot with the D1-D8 taxonomy.

    The snapshot must have been created by the /show_dx command. Returns a
    summary and local JSON/HTML paths with evidence linked to recorded steps.
    """
    return analyze_snapshot(Path(snapshot_path))


if __name__ == "__main__":
    mcp.run(transport="stdio")
