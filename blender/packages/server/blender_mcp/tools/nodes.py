# SPDX-License-Identifier: MIT
"""Declarative bidirectional Nodes DSL MCP tools (Shader, Geometry Nodes, Compositor)."""

from __future__ import annotations

from typing import Any, Literal

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from blender_mcp.tools import ToolRuntime

_READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True)
_MUTATE = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=True)


def register(mcp: MCPServer, rt: ToolRuntime) -> None:
    @mcp.tool(annotations=_READ_ONLY)
    async def get_node_tree(tree: str) -> dict[str, Any]:
        """Serialize any Blender node tree into declarative DSL JSON.

        `tree` examples: `'material:Gold'`, `'world'`, `'compositor'`, `'geonodes:Scatter'`.
        """
        return await rt.invoke("nodes.get_node_tree", {"tree": tree})

    @mcp.tool(annotations=_MUTATE)
    async def build_node_tree(
        tree: str,
        nodes: dict[str, dict[str, Any]],
        links: list[list[str]],
        interface: list[dict[str, Any]] | None = None,
        clear: bool = True,
        layout: Literal["auto", "manual"] = "auto",
        attach_to_object: str | None = None,
        modifier_name: str | None = None,
    ) -> dict[str, Any]:
        """Build a Shader, World, Geometry Nodes, or Compositor graph from declarative DSL JSON.

        Args:
            tree: Target specifier (`'material:Name'`, `'world'`, `'compositor'`, `'geonodes:Name'`). Created if missing.
            nodes: Map of `node_id -> {"type": "ShaderNode...", "props": {...}, "inputs": {...}}`.
                Supports `color_ramp.elements` as `[[pos, [r,g,b,a]], ...]`.
                Implicit `'input'` and `'output'` aliases are auto-created when referenced in `links`.
            links: List of `["src_id.SocketName", "dst_id.SocketName"]` pairs (use `SocketName[1]` or `0` for duplicate sockets).
            interface: Optional node-group sockets `[{"name": "Density", "in_out": "INPUT", "socket_type": "NodeSocketFloat"}]`.
            clear: Replace existing nodes when True (default).
            layout: `'auto'` applies clean topological left-to-right columns.
            attach_to_object: For `geonodes:*`, automatically attaches a Geometry Nodes modifier to this object.
        """
        return await rt.invoke(
            "nodes.build_node_tree",
            {
                "tree": tree,
                "nodes": nodes,
                "links": links,
                "interface": interface,
                "clear": clear,
                "layout": layout,
                "attach_to_object": attach_to_object,
                "modifier_name": modifier_name,
            },
            audit=True,
        )

    @mcp.tool(annotations=_MUTATE)
    async def patch_node_tree(
        tree: str,
        add_nodes: dict[str, dict[str, Any]] | None = None,
        update_nodes: dict[str, dict[str, Any]] | None = None,
        remove_nodes: list[str] | None = None,
        add_links: list[list[str]] | None = None,
        remove_links: list[list[str]] | None = None,
        interface: list[dict[str, Any]] | None = None,
        relayout: bool = False,
    ) -> dict[str, Any]:
        """Incrementally add, update, remove, or rewire nodes in an existing node tree without rebuilding it."""
        return await rt.invoke(
            "nodes.patch_node_tree",
            {
                "tree": tree,
                "add_nodes": add_nodes,
                "update_nodes": update_nodes,
                "remove_nodes": remove_nodes,
                "add_links": add_links,
                "remove_links": remove_links,
                "interface": interface,
                "relayout": relayout,
            },
            audit=True,
        )

    @mcp.tool(annotations=_READ_ONLY)
    async def list_node_types(
        tree_type: Literal["shader", "geometry", "compositor"] = "shader",
        search: str | None = None,
        include_sockets: bool = False,
        limit: int = 40,
    ) -> dict[str, Any]:
        """Discover valid node `bl_idname` types (and live socket names when `include_sockets=True`) on the connected Blender version."""
        return await rt.invoke(
            "nodes.list_node_types",
            {
                "tree_type": tree_type,
                "search": search,
                "include_sockets": include_sockets,
                "limit": limit,
            },
        )

    @mcp.tool(annotations=_MUTATE)
    async def set_group_inputs(
        object: str,
        inputs: dict[str, Any],
        modifier: str | None = None,
    ) -> dict[str, Any]:
        """Set Geometry Nodes modifier input values by socket name or identifier on an object."""
        return await rt.invoke(
            "nodes.set_group_inputs",
            {"object": object, "inputs": inputs, "modifier": modifier},
            audit=True,
        )
