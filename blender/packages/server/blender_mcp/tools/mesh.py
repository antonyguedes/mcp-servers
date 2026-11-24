# SPDX-License-Identifier: MIT
"""bmesh modeling, boolean, shading, and UV unwrap MCP tools."""

from __future__ import annotations

from typing import Any, Literal

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from blender_mcp.tools import ToolRuntime

_READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True)
_MUTATE = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False)
_MUTATE_IDEM = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=True)
_DESTRUCTIVE = ToolAnnotations(read_only_hint=False, destructive_hint=True, idempotent_hint=False)


def register(mcp: MCPServer, rt: ToolRuntime) -> None:
    @mcp.tool(annotations=_READ_ONLY)
    async def mesh_stats(object: str) -> dict[str, Any]:
        """Inspect mesh topology: verts/edges/faces, tris/quads/ngons, manifold check, surface area, volume, and UVs."""
        return await rt.invoke("mesh.stats", {"object": object})

    @mcp.tool(annotations=_MUTATE)
    async def mesh_extrude(
        object: str,
        distance: float = 0.2,
        direction: Literal["all", "top", "bottom", "front", "back", "right", "left"] = "top",
        face_indices: list[int] | None = None,
        offset: list[float] | None = None,
        scale: float | None = None,
    ) -> dict[str, Any]:
        """Extrude selected faces (by `face_indices` or normal `direction`) along normal or explicit `offset`."""
        return await rt.invoke(
            "mesh.extrude",
            {
                "object": object,
                "distance": distance,
                "direction": direction,
                "face_indices": face_indices,
                "offset": offset,
                "scale": scale,
            },
            audit=True,
        )

    @mcp.tool(annotations=_MUTATE)
    async def mesh_bevel(
        object: str,
        offset: float = 0.05,
        segments: int = 2,
        affect: Literal["EDGES", "VERTICES"] = "EDGES",
        profile: float = 0.5,
        clamp_overlap: bool = True,
        angle_limit_degrees: float | None = None,
    ) -> dict[str, Any]:
        """Bevel edges or vertices of a mesh object via bmesh (optionally restricted to edges sharper than `angle_limit_degrees`)."""
        return await rt.invoke(
            "mesh.bevel",
            {
                "object": object,
                "offset": offset,
                "segments": segments,
                "affect": affect,
                "profile": profile,
                "clamp_overlap": clamp_overlap,
                "angle_limit_degrees": angle_limit_degrees,
            },
            audit=True,
        )

    @mcp.tool(annotations=_MUTATE)
    async def mesh_inset(
        object: str,
        thickness: float = 0.05,
        depth: float = 0.0,
        individual: bool = True,
        direction: Literal["all", "top", "bottom", "front", "back", "right", "left"] = "all",
        face_indices: list[int] | None = None,
    ) -> dict[str, Any]:
        """Inset faces on a mesh object (all faces, by normal direction, or explicit face indices)."""
        return await rt.invoke(
            "mesh.inset",
            {
                "object": object,
                "thickness": thickness,
                "depth": depth,
                "individual": individual,
                "direction": direction,
                "face_indices": face_indices,
            },
            audit=True,
        )

    @mcp.tool(annotations=_MUTATE)
    async def mesh_subdivide(
        object: str,
        cuts: int = 1,
        smoothness: float = 0.0,
        fractal: float = 0.0,
    ) -> dict[str, Any]:
        """Subdivide all edges of a mesh object with optional smoothing or fractal displacement."""
        return await rt.invoke(
            "mesh.subdivide",
            {
                "object": object,
                "cuts": cuts,
                "smoothness": smoothness,
                "fractal": fractal,
            },
            audit=True,
        )

    @mcp.tool(annotations=_DESTRUCTIVE)
    async def mesh_boolean(
        target: str,
        cutter: str,
        operation: Literal["DIFFERENCE", "UNION", "INTERSECT"] = "DIFFERENCE",
        solver: Literal["EXACT", "FAST", "MANIFOLD"] = "EXACT",
        delete_cutter: bool = False,
        hide_cutter: bool = True,
    ) -> dict[str, Any]:
        """Apply a destructive boolean operation (DIFFERENCE, UNION, INTERSECT) between `target` and `cutter` meshes."""
        return await rt.invoke(
            "mesh.boolean",
            {
                "target": target,
                "cutter": cutter,
                "operation": operation,
                "solver": solver,
                "delete_cutter": delete_cutter,
                "hide_cutter": hide_cutter,
            },
            audit=True,
        )

    @mcp.tool(annotations=_MUTATE)
    async def mesh_loop_cut(
        object: str,
        axis: Literal["X", "Y", "Z"] = "Z",
        cuts: int = 1,
    ) -> dict[str, Any]:
        """Insert N evenly spaced parallel cuts across a mesh along local axis X, Y, or Z."""
        return await rt.invoke(
            "mesh.loop_cut",
            {"object": object, "axis": axis, "cuts": cuts},
            audit=True,
        )

    @mcp.tool(annotations=_MUTATE_IDEM)
    async def mesh_merge_by_distance(
        object: str,
        distance: float = 0.001,
    ) -> dict[str, Any]:
        """Weld/merge duplicate vertices within `distance` meters."""
        return await rt.invoke(
            "mesh.merge_by_distance",
            {"object": object, "distance": distance},
            audit=True,
        )

    @mcp.tool(annotations=_MUTATE_IDEM)
    async def mesh_recalc_normals(
        object: str,
        inside: bool = False,
    ) -> dict[str, Any]:
        """Recalculate consistent outward (or inward when `inside=True`) face normals."""
        return await rt.invoke(
            "mesh.recalc_normals",
            {"object": object, "inside": inside},
            audit=True,
        )

    @mcp.tool(annotations=_MUTATE_IDEM)
    async def mesh_set_shading(
        object: str,
        mode: Literal["flat", "smooth", "auto"] = "auto",
        angle_degrees: float = 30.0,
    ) -> dict[str, Any]:
        """Set flat, smooth, or angle-based auto-smooth shading (works across Blender 3.6-5.3+)."""
        return await rt.invoke(
            "mesh.set_shading",
            {"object": object, "mode": mode, "angle_degrees": angle_degrees},
            audit=True,
        )

    @mcp.tool(annotations=_MUTATE_IDEM)
    async def uv_unwrap(
        object: str,
        method: Literal["box", "planar_z", "planar_x", "planar_y", "spherical", "smart"] = "box",
        scale: float = 1.0,
        uv_layer: str = "UVMap",
    ) -> dict[str, Any]:
        """Generate clean UV coordinates for a mesh object (headless-safe projection)."""
        return await rt.invoke(
            "mesh.uv_unwrap",
            {
                "object": object,
                "method": method,
                "scale": scale,
                "uv_layer": uv_layer,
            },
            audit=True,
        )
