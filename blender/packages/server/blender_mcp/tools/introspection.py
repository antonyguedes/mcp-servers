# SPDX-License-Identifier: MIT
"""Safe RNA inspection/mutation, bpy.ops discovery/calling, and live bpy API search MCP tools."""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from blender_mcp.tools import ToolRuntime

_READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True)
_MUTATE = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False)


def register(mcp: MCPServer, rt: ToolRuntime) -> None:
    @mcp.tool(annotations=_READ_ONLY)
    async def get_rna(
        target: str = "scene",
        data_path: str = "",
    ) -> dict[str, Any]:
        """Read a Blender RNA property path without Python scripting.

        `target` examples: `'scene'`, `'render'`, `'world'`, `'object:Cube'`, `'material:Gold'`.
        Leave `data_path` empty to list properties on the target.
        """
        return await rt.invoke("introspection.get_rna", {"target": target, "data_path": data_path})

    @mcp.tool(annotations=_MUTATE)
    async def set_rna(
        target: str,
        data_path: str,
        value: Any,
    ) -> dict[str, Any]:
        """Set a Blender RNA property by target (`scene`, `render`, `object:Cube`, `material:Gold`) and dotted `data_path`."""
        return await rt.invoke(
            "introspection.set_rna",
            {"target": target, "data_path": data_path, "value": value},
            audit=True,
        )

    @mcp.tool(annotations=_READ_ONLY)
    async def list_operators(
        category: str | None = None,
        search: str | None = None,
        limit: int = 40,
    ) -> dict[str, Any]:
        """Search available `bpy.ops` operators (optionally filtered by category and substring)."""
        return await rt.invoke(
            "introspection.list_operators",
            {"category": category, "search": search, "limit": limit},
        )

    @mcp.tool(annotations=_MUTATE)
    async def call_operator(
        operator: str,
        props: dict[str, Any] | None = None,
        active_object: str | None = None,
        selected_objects: list[str] | None = None,
    ) -> dict[str, Any]:
        """Invoke a Blender operator (`'category.name'`) with optional context override (`active_object`, `selected_objects`)."""
        return await rt.invoke(
            "introspection.call_operator",
            {
                "operator": operator,
                "props": props or {},
                "active_object": active_object,
                "selected_objects": selected_objects,
            },
            audit=True,
        )

    @mcp.tool(annotations=_READ_ONLY)
    async def search_bpy_api(
        query: str,
        limit: int = 20,
    ) -> dict[str, Any]:
        """Search live `bpy.types` RNA classes and properties on the connected Blender version."""
        return await rt.invoke("introspection.search_bpy_api", {"query": query, "limit": limit})
