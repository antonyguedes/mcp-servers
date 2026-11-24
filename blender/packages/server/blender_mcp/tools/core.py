# SPDX-License-Identifier: MIT
"""Core scene inspection and selection MCP tools."""

from __future__ import annotations

from typing import Any, Literal

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from blender_mcp.tools import ToolRuntime

_READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True)
_STATE_MUT = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=True)


def register(mcp: MCPServer, rt: ToolRuntime) -> None:
    @mcp.tool(annotations=_READ_ONLY)
    async def get_blender_info() -> dict[str, Any]:
        """Return Blender version, active scene name, Python version, and runtime capabilities."""
        return await rt.invoke("core.get_blender_info")

    @mcp.tool(annotations=_READ_ONLY)
    async def get_scene_summary() -> dict[str, Any]:
        """Return a compact overview of the active Blender scene (objects, collections, render, frames)."""
        return await rt.invoke("core.get_scene_summary")

    @mcp.tool(annotations=_READ_ONLY)
    async def list_objects(
        object_type: str | None = None,
        collection: str | None = None,
        name_contains: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> dict[str, Any]:
        """List objects in the scene with optional filtering and pagination.

        Args:
            object_type: Optional Blender type filter (MESH, LIGHT, CAMERA, EMPTY, CURVE, ARMATURE, FONT).
            collection: Optional collection name to restrict results to.
            name_contains: Case-insensitive substring filter on object names.
            offset: Pagination start index.
            limit: Maximum number of objects to return (1-500).
        """
        return await rt.invoke(
            "core.list_objects",
            {
                "object_type": object_type,
                "collection": collection,
                "name_contains": name_contains,
                "offset": offset,
                "limit": limit,
            },
        )

    @mcp.tool(annotations=_READ_ONLY)
    async def get_object_details(object: str) -> dict[str, Any]:
        """Inspect detailed geometry, world bounding box, transforms, materials, and modifiers of an object.

        Args:
            object: Exact object name or persistent blender_mcp_uid.
        """
        return await rt.invoke("core.get_object_details", {"object": object})

    @mcp.tool(annotations=_STATE_MUT)
    async def select_objects(
        objects: list[str] | None = None,
        extend: bool = False,
        select_all: bool = False,
        deselect_all: bool = False,
    ) -> dict[str, Any]:
        """Select or deselect objects in the active view layer."""
        return await rt.invoke(
            "core.select",
            {
                "objects": objects or [],
                "extend": extend,
                "select_all": select_all,
                "deselect_all": deselect_all,
            },
        )

    @mcp.tool(annotations=_STATE_MUT)
    async def set_active_object(object: str) -> dict[str, Any]:
        """Set the active object in the scene."""
        return await rt.invoke("core.set_active", {"object": object})

    @mcp.tool(annotations=_STATE_MUT)
    async def set_mode(
        mode: Literal[
            "OBJECT",
            "EDIT",
            "SCULPT",
            "VERTEX_PAINT",
            "WEIGHT_PAINT",
            "TEXTURE_PAINT",
            "POSE",
        ] = "OBJECT",
        object: str | None = None,
    ) -> dict[str, Any]:
        """Switch Blender interaction mode (optionally activating a target object first)."""
        return await rt.invoke("core.set_mode", {"mode": mode, "object": object})
