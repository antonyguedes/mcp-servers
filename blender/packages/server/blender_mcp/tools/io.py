# SPDX-License-Identifier: MIT
"""3D file import/export and .blend management MCP tools (enforcing PathGuard)."""

from __future__ import annotations

from typing import Any, Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from blender_mcp.tools import ToolRuntime
from blender_mcp_protocol import BridgeError

_READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True)
_MUTATE = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False)
_DESTRUCTIVE = ToolAnnotations(read_only_hint=False, destructive_hint=True, idempotent_hint=False)


def _guard(rt: ToolRuntime, filepath: str, *, must_exist: bool = False) -> str:
    try:
        return str(rt.path_guard.validate(filepath, must_exist=must_exist))
    except BridgeError as err:
        raise ToolError(err.format_for_agent()) from err


def register(mcp: MCPServer, rt: ToolRuntime) -> None:
    @mcp.tool(annotations=_MUTATE)
    async def export_file(
        filepath: str,
        file_format: Literal["glb", "gltf", "fbx", "obj", "stl", "ply", "usd", "usdc", "usda", "abc"] | None = None,
        selected_only: bool = False,
    ) -> dict[str, Any]:
        """Export the scene (or selected objects) to glTF/GLB, FBX, OBJ, STL, PLY, USD, or Alembic."""
        safe_path = _guard(rt, filepath, must_exist=False)
        return await rt.invoke(
            "io.export_file",
            {
                "filepath": safe_path,
                "file_format": file_format,
                "selected_only": selected_only,
            },
            audit=True,
        )

    @mcp.tool(annotations=_MUTATE)
    async def import_file(
        filepath: str,
        file_format: Literal["glb", "gltf", "fbx", "obj", "stl", "ply", "usd", "usdc", "usda", "abc"] | None = None,
    ) -> dict[str, Any]:
        """Import a 3D file (glTF/GLB, FBX, OBJ, STL, PLY, USD, Alembic) into the active Blender scene."""
        safe_path = _guard(rt, filepath, must_exist=True)
        return await rt.invoke(
            "io.import_file",
            {"filepath": safe_path, "file_format": file_format},
            audit=True,
        )

    @mcp.tool(annotations=_MUTATE)
    async def save_blend(
        filepath: str,
        copy: bool = False,
        compress: bool = True,
        pack_resources: bool = False,
    ) -> dict[str, Any]:
        """Save the active Blender scene to a `.blend` file."""
        safe_path = _guard(rt, filepath, must_exist=False)
        return await rt.invoke(
            "io.save_blend",
            {
                "filepath": safe_path,
                "copy": copy,
                "compress": compress,
                "pack_resources": pack_resources,
            },
            audit=True,
        )

    @mcp.tool(annotations=_DESTRUCTIVE)
    async def open_blend(filepath: str) -> dict[str, Any]:
        """Open a `.blend` file in Blender (replaces current scene while keeping the MCP bridge connected)."""
        safe_path = _guard(rt, filepath, must_exist=True)
        return await rt.invoke("io.open_blend", {"filepath": safe_path}, audit=True)

    @mcp.tool(annotations=_MUTATE)
    async def link_append(
        filepath: str,
        data_type: Literal["objects", "materials", "collections", "node_groups", "meshes", "worlds"] = "objects",
        names: list[str] | None = None,
        link: bool = False,
    ) -> dict[str, Any]:
        """Append (or link when `link=True`) data-blocks from another `.blend` file."""
        safe_path = _guard(rt, filepath, must_exist=True)
        return await rt.invoke(
            "io.link_append",
            {
                "filepath": safe_path,
                "data_type": data_type,
                "names": names or [],
                "link": link,
            },
            audit=True,
        )

    @mcp.tool(annotations=_READ_ONLY)
    async def list_asset_libraries() -> dict[str, Any]:
        """List Asset Libraries configured in Blender Preferences."""
        return await rt.invoke("io.list_asset_libraries")
