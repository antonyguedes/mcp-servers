# SPDX-License-Identifier: MIT
"""Object creation, transformation, hierarchy, and mesh utility MCP tools."""

from __future__ import annotations

from typing import Any, Literal

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from blender_mcp.tools import ToolRuntime

_CREATE = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False)
_MUTATE = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=True)
_DESTRUCTIVE = ToolAnnotations(read_only_hint=False, destructive_hint=True, idempotent_hint=False)


def register(mcp: MCPServer, rt: ToolRuntime) -> None:
    @mcp.tool(annotations=_CREATE)
    async def create_primitive(
        primitive: Literal[
            "cube",
            "uv_sphere",
            "ico_sphere",
            "cylinder",
            "cone",
            "torus",
            "plane",
            "grid",
            "monkey",
            "empty",
            "text",
        ] = "cube",
        name: str | None = None,
        location: list[float] | None = None,
        rotation_degrees: list[float] | None = None,
        scale: list[float] | float | None = None,
        size: float = 2.0,
        radius: float | None = None,
        depth: float | None = None,
        segments: int = 32,
        rings: int = 16,
        subdivisions: int = 2,
        smooth: bool = False,
        text: str | None = None,
        collection: str | None = None,
    ) -> dict[str, Any]:
        """Create a 3D primitive (mesh, empty, or text) at the given transform.

        Units are meters (Z-up) and rotations are Euler XYZ degrees.
        Returns persistent `uid`, created `name`, `bbox_world`, and scene `diff`.
        """
        params: dict[str, Any] = {
            "primitive": primitive,
            "size": size,
            "segments": segments,
            "rings": rings,
            "subdivisions": subdivisions,
            "smooth": smooth,
        }
        if name is not None:
            params["name"] = name
        if location is not None:
            params["location"] = location
        if rotation_degrees is not None:
            params["rotation_degrees"] = rotation_degrees
        if scale is not None:
            params["scale"] = scale
        if radius is not None:
            params["radius"] = radius
        if depth is not None:
            params["depth"] = depth
        if text is not None:
            params["text"] = text
        if collection is not None:
            params["collection"] = collection
        return await rt.invoke("objects.create_primitive", params, audit=True)

    @mcp.tool(annotations=_CREATE)
    async def create_mesh_object(
        name: str,
        vertices: list[list[float]],
        faces: list[list[int]] | None = None,
        edges: list[list[int]] | None = None,
        location: list[float] | None = None,
        rotation_degrees: list[float] | None = None,
        scale: list[float] | float | None = None,
        smooth: bool = False,
        collection: str | None = None,
    ) -> dict[str, Any]:
        """Create a custom mesh object directly from vertex coordinates and face/edge index lists."""
        params: dict[str, Any] = {
            "name": name,
            "vertices": vertices,
            "edges": edges or [],
            "faces": faces or [],
            "smooth": smooth,
        }
        if location is not None:
            params["location"] = location
        if rotation_degrees is not None:
            params["rotation_degrees"] = rotation_degrees
        if scale is not None:
            params["scale"] = scale
        if collection is not None:
            params["collection"] = collection
        return await rt.invoke("objects.create_mesh_object", params, audit=True)

    @mcp.tool(annotations=_MUTATE)
    async def transform_object(
        object: str,
        location: list[float] | None = None,
        rotation_degrees: list[float] | None = None,
        scale: list[float] | float | None = None,
        relative: bool = False,
        space: Literal["world", "local"] = "world",
    ) -> dict[str, Any]:
        """Move, rotate (degrees), or scale an object (absolute or relative, world or local space)."""
        return await rt.invoke(
            "objects.transform",
            {
                "object": object,
                "location": location,
                "rotation_degrees": rotation_degrees,
                "scale": scale,
                "relative": relative,
                "space": space,
            },
            audit=True,
        )

    @mcp.tool(annotations=_CREATE)
    async def duplicate_object(
        object: str,
        new_name: str | None = None,
        offset: list[float] | None = None,
        count: int = 1,
        linked: bool = False,
    ) -> dict[str, Any]:
        """Duplicate an object one or more times, optionally linked (shared mesh data) and spaced by `offset`."""
        return await rt.invoke(
            "objects.duplicate",
            {
                "object": object,
                "new_name": new_name,
                "offset": offset,
                "count": count,
                "linked": linked,
            },
            audit=True,
        )

    @mcp.tool(annotations=_DESTRUCTIVE)
    async def delete_objects(
        objects: list[str],
        include_children: bool = False,
    ) -> dict[str, Any]:
        """Delete one or more objects (and optionally their child hierarchy) from the scene."""
        return await rt.invoke(
            "objects.delete",
            {"objects": objects, "include_children": include_children},
            audit=True,
        )

    @mcp.tool(annotations=_MUTATE)
    async def parent_objects(
        children: list[str],
        parent: str | None = None,
        keep_transform: bool = True,
    ) -> dict[str, Any]:
        """Parent objects to `parent`, or unparent them when `parent` is null."""
        return await rt.invoke(
            "objects.parent",
            {"children": children, "parent": parent, "keep_transform": keep_transform},
            audit=True,
        )

    @mcp.tool(annotations=_DESTRUCTIVE)
    async def join_objects(
        target: str,
        sources: list[str],
    ) -> dict[str, Any]:
        """Merge source mesh objects into `target` mesh, preserving materials and removing merged sources."""
        return await rt.invoke(
            "objects.join",
            {"target": target, "sources": sources},
            audit=True,
        )

    @mcp.tool(annotations=_MUTATE)
    async def apply_transforms(
        object: str,
        location: bool = False,
        rotation: bool = True,
        scale: bool = True,
    ) -> dict[str, Any]:
        """Bake object location/rotation/scale transforms directly into mesh geometry."""
        return await rt.invoke(
            "objects.apply_transforms",
            {
                "object": object,
                "location": location,
                "rotation": rotation,
                "scale": scale,
            },
            audit=True,
        )

    @mcp.tool(annotations=_MUTATE)
    async def set_origin(
        object: str,
        origin_type: Literal["bounds", "geometry", "bottom_center", "world", "cursor", "custom"] = "bounds",
        point: list[float] | None = None,
    ) -> dict[str, Any]:
        """Reposition a mesh object's pivot/origin without moving its geometry in world space."""
        return await rt.invoke(
            "objects.set_origin",
            {"object": object, "origin_type": origin_type, "point": point},
            audit=True,
        )

    @mcp.tool(annotations=_MUTATE)
    async def rename_object(
        object: str,
        new_name: str,
        rename_data: bool = False,
    ) -> dict[str, Any]:
        """Rename an object (and optionally its underlying data-block). Its persistent `uid` remains unchanged."""
        return await rt.invoke(
            "objects.rename",
            {"object": object, "new_name": new_name, "rename_data": rename_data},
            audit=True,
        )

    @mcp.tool(annotations=_MUTATE)
    async def align_to_ground(
        objects: list[str],
        target_z: float = 0.0,
    ) -> dict[str, Any]:
        """Rest each object cleanly on `target_z` (default Z=0) using its world-space bounding box."""
        return await rt.invoke(
            "objects.align_to_ground",
            {"objects": objects, "target_z": target_z},
            audit=True,
        )
