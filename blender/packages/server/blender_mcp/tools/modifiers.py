# SPDX-License-Identifier: MIT
"""Typed modifier stack MCP tools."""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from blender_mcp.tools import ToolRuntime

_READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True)
_MUTATE = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False)
_MUTATE_IDEM = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=True)
_DESTRUCTIVE = ToolAnnotations(read_only_hint=False, destructive_hint=True, idempotent_hint=False)


def register(mcp: MCPServer, rt: ToolRuntime) -> None:
    @mcp.tool(annotations=_READ_ONLY)
    async def list_modifiers(object: str) -> dict[str, Any]:
        """List all modifiers on an object with their current settings."""
        return await rt.invoke("modifiers.list_modifiers", {"object": object})

    @mcp.tool(annotations=_MUTATE)
    async def add_modifier(
        object: str,
        modifier_type: str,
        name: str | None = None,
        settings: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Add a modifier (e.g. SUBSURF, BEVEL, ARRAY, MIRROR, SOLIDIFY, BOOLEAN, DECIMATE, NODES) with optional settings."""
        return await rt.invoke(
            "modifiers.add_modifier",
            {
                "object": object,
                "modifier_type": modifier_type,
                "name": name,
                "settings": settings or {},
            },
            audit=True,
        )

    @mcp.tool(annotations=_MUTATE_IDEM)
    async def configure_modifier(
        object: str,
        modifier: str,
        settings: dict[str, Any],
    ) -> dict[str, Any]:
        """Update properties (or Geometry Nodes input sockets) on an existing modifier."""
        return await rt.invoke(
            "modifiers.configure_modifier",
            {"object": object, "modifier": modifier, "settings": settings},
            audit=True,
        )

    @mcp.tool(annotations=_MUTATE_IDEM)
    async def reorder_modifier(
        object: str,
        modifier: str,
        index: int,
    ) -> dict[str, Any]:
        """Move a modifier to a specific 0-based position in an object's modifier stack."""
        return await rt.invoke(
            "modifiers.reorder_modifier",
            {"object": object, "modifier": modifier, "index": index},
            audit=True,
        )

    @mcp.tool(annotations=_DESTRUCTIVE)
    async def apply_modifier(
        object: str,
        modifier: str | None = None,
    ) -> dict[str, Any]:
        """Bake a specific modifier (or all modifiers when `modifier` is omitted) into mesh geometry."""
        return await rt.invoke(
            "modifiers.apply_modifier",
            {"object": object, "modifier": modifier},
            audit=True,
        )

    @mcp.tool(annotations=_DESTRUCTIVE)
    async def remove_modifier(
        object: str,
        modifier: str,
    ) -> dict[str, Any]:
        """Remove a modifier from an object without applying it."""
        return await rt.invoke(
            "modifiers.remove_modifier",
            {"object": object, "modifier": modifier},
            audit=True,
        )
