# SPDX-License-Identifier: MIT
"""Collection and view-layer MCP tools."""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from blender_mcp.tools import ToolRuntime

_READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True)
_MUTATE = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=True)


def register(mcp: MCPServer, rt: ToolRuntime) -> None:
    @mcp.tool(annotations=_READ_ONLY)
    async def list_collections() -> dict[str, Any]:
        """List all collections, their objects, nested children, and visibility flags."""
        return await rt.invoke("collections.list_collections")

    @mcp.tool(annotations=_MUTATE)
    async def create_collection(
        name: str,
        parent: str | None = None,
    ) -> dict[str, Any]:
        """Create a new collection under `parent` (or the root Scene Collection)."""
        return await rt.invoke(
            "collections.create_collection",
            {"name": name, "parent": parent},
            audit=True,
        )

    @mcp.tool(annotations=_MUTATE)
    async def move_to_collection(
        objects: list[str],
        collection: str,
        link_only: bool = False,
    ) -> dict[str, Any]:
        """Move (or link when `link_only=True`) objects into a target collection."""
        return await rt.invoke(
            "collections.move_to_collection",
            {"objects": objects, "collection": collection, "link_only": link_only},
            audit=True,
        )

    @mcp.tool(annotations=_MUTATE)
    async def set_collection_visibility(
        collection: str,
        hide_viewport: bool | None = None,
        hide_render: bool | None = None,
        exclude: bool | None = None,
    ) -> dict[str, Any]:
        """Toggle viewport visibility, render visibility, or view-layer exclusion for a collection."""
        return await rt.invoke(
            "collections.set_collection_visibility",
            {
                "collection": collection,
                "hide_viewport": hide_viewport,
                "hide_render": hide_render,
                "exclude": exclude,
            },
            audit=True,
        )

    @mcp.tool(annotations=_READ_ONLY)
    async def list_view_layers() -> dict[str, Any]:
        """List all view layers in the active scene."""
        return await rt.invoke("collections.list_view_layers")
