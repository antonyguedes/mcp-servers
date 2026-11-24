# SPDX-License-Identifier: MIT
"""Undo, redo, and named session checkpoint MCP tools."""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from blender_mcp.tools import ToolRuntime

_READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True)
_MUTATE = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False)
_DESTRUCTIVE = ToolAnnotations(read_only_hint=False, destructive_hint=True, idempotent_hint=False)


def register(mcp: MCPServer, rt: ToolRuntime) -> None:
    @mcp.tool(annotations=_MUTATE)
    async def undo(steps: int = 1) -> dict[str, Any]:
        """Undo the last N mutating actions in interactive GUI Blender sessions."""
        return await rt.invoke("history.undo", {"steps": steps}, audit=True)

    @mcp.tool(annotations=_MUTATE)
    async def redo(steps: int = 1) -> dict[str, Any]:
        """Redo the last N undone actions in interactive GUI Blender sessions."""
        return await rt.invoke("history.redo", {"steps": steps}, audit=True)

    @mcp.tool(annotations=_MUTATE)
    async def create_checkpoint(
        name: str | None = None,
        description: str = "",
    ) -> dict[str, Any]:
        """Save a named .blend snapshot of the current scene (works in both GUI and headless modes)."""
        return await rt.invoke(
            "history.create_checkpoint",
            {"name": name, "description": description},
            audit=True,
        )

    @mcp.tool(annotations=_DESTRUCTIVE)
    async def restore_checkpoint(name: str) -> dict[str, Any]:
        """Restore the Blender scene to a previously created named checkpoint."""
        return await rt.invoke("history.restore_checkpoint", {"name": name}, audit=True)

    @mcp.tool(annotations=_READ_ONLY)
    async def list_checkpoints() -> dict[str, Any]:
        """List all checkpoints saved in the current Blender session."""
        return await rt.invoke("history.list_checkpoints")

    @mcp.tool(annotations=_DESTRUCTIVE)
    async def delete_checkpoint(name: str) -> dict[str, Any]:
        """Delete a saved checkpoint from disk."""
        return await rt.invoke("history.delete_checkpoint", {"name": name}, audit=True)
