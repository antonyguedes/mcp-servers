# SPDX-License-Identifier: MIT
"""Sculpt (voxel remesh & procedural brush strokes) and Grease Pencil (v2/v3) MCP tools."""

from __future__ import annotations

from typing import Any, Literal

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from blender_mcp.tools import ToolRuntime

_CREATE = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False)
_MUTATE = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False)


def register(mcp: MCPServer, rt: ToolRuntime) -> None:
    @mcp.tool(annotations=_MUTATE)
    async def sculpt_remesh(
        object: str,
        voxel_size: float = 0.08,
        smooth_shading: bool = True,
    ) -> dict[str, Any]:
        """Perform voxel remeshing on a mesh to create uniform sculptable topology (headless-safe)."""
        return await rt.invoke(
            "sculpt.remesh",
            {
                "object": object,
                "voxel_size": voxel_size,
                "smooth_shading": smooth_shading,
            },
            audit=True,
        )

    @mcp.tool(annotations=_MUTATE)
    async def sculpt_stroke(
        object: str,
        points: list[list[float]],
        brush: Literal["DRAW", "INFLATE", "SMOOTH", "FLATTEN", "PINCH", "GRAB"] = "DRAW",
        radius: float = 0.3,
        strength: float = 0.15,
        symmetry_x: bool = False,
    ) -> dict[str, Any]:
        """Apply a procedural sculpt brush stroke along 3D world-space `points` (supports X-symmetry, works headless)."""
        return await rt.invoke(
            "sculpt.brush_stroke",
            {
                "object": object,
                "points": points,
                "brush": brush,
                "radius": radius,
                "strength": strength,
                "symmetry_x": symmetry_x,
            },
            audit=True,
        )

    @mcp.tool(annotations=_CREATE)
    async def gp_create_object(
        name: str = "GreasePencil",
        layer_name: str = "Lines",
        color: list[float] | None = None,
        location: list[float] | None = None,
        frame: int = 1,
        collection: str | None = None,
    ) -> dict[str, Any]:
        """Create a Grease Pencil object with an initial layer and stroke material (supports GPv3 4.3+/5.x and GPv2 3.6-4.2)."""
        return await rt.invoke(
            "gp.create_object",
            {
                "name": name,
                "layer_name": layer_name,
                "color": color,
                "location": location,
                "frame": frame,
                "collection": collection,
            },
            audit=True,
        )

    @mcp.tool(annotations=_MUTATE)
    async def gp_draw_stroke(
        object: str,
        points: list[list[float]],
        layer: str = "Lines",
        frame: int | None = None,
        radius: float = 0.02,
        opacity: float = 1.0,
        cyclic: bool = False,
    ) -> dict[str, Any]:
        """Draw a 3D stroke onto a Grease Pencil object (works identically on GPv3 and GPv2)."""
        params: dict[str, Any] = {
            "object": object,
            "points": points,
            "layer": layer,
            "radius": radius,
            "opacity": opacity,
            "cyclic": cyclic,
        }
        if frame is not None:
            params["frame"] = frame
        return await rt.invoke("gp.draw_stroke", params, audit=True)
