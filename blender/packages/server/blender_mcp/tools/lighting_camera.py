# SPDX-License-Identifier: MIT
"""Lighting presets, physical sky/HDRI world, and camera framing/DOF MCP tools."""

from __future__ import annotations

from typing import Any, Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from blender_mcp.tools import ToolRuntime
from blender_mcp_protocol import BridgeError

_CREATE = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False)
_MUTATE = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=True)


def register(mcp: MCPServer, rt: ToolRuntime) -> None:
    @mcp.tool(annotations=_CREATE)
    async def add_light(
        light_type: Literal["POINT", "SUN", "SPOT", "AREA"] = "AREA",
        name: str | None = None,
        location: list[float] | None = None,
        rotation_degrees: list[float] | None = None,
        look_at: str | list[float] | None = None,
        energy: float = 250.0,
        color: list[float] | None = None,
        size: float = 1.0,
        spot_angle_degrees: float = 45.0,
        spot_blend: float = 0.25,
        collection: str | None = None,
    ) -> dict[str, Any]:
        """Create a POINT, SUN, SPOT, or AREA light aimed via `look_at` (object name or [x,y,z]) or `rotation_degrees`."""
        return await rt.invoke(
            "lighting.add_light",
            {
                "light_type": light_type,
                "name": name,
                "location": location,
                "rotation_degrees": rotation_degrees,
                "look_at": look_at,
                "energy": energy,
                "color": color,
                "size": size,
                "spot_angle_degrees": spot_angle_degrees,
                "spot_blend": spot_blend,
                "collection": collection,
            },
            audit=True,
        )

    @mcp.tool(annotations=_MUTATE)
    async def setup_lighting_preset(
        preset: Literal["three_point", "studio", "dramatic", "outdoor"] = "three_point",
        target_objects: list[str] | None = None,
        intensity: float = 1.0,
        clear_existing_lights: bool = True,
    ) -> dict[str, Any]:
        """Auto-position a complete lighting rig (`three_point`, `studio`, `dramatic`, or `outdoor`) around the scene or target objects."""
        return await rt.invoke(
            "lighting.setup_preset",
            {
                "preset": preset,
                "target_objects": target_objects,
                "intensity": intensity,
                "clear_existing_lights": clear_existing_lights,
            },
            audit=True,
        )

    @mcp.tool(annotations=_MUTATE)
    async def set_world_sky(
        sky_type: str = "nishita",
        sun_elevation: float = 25.0,
        sun_rotation: float = 0.0,
        strength: float = 1.0,
        air_density: float | None = None,
        dust_density: float | None = None,
    ) -> dict[str, Any]:
        """Configure a physical Sky Texture in the World shader (adapts Nishita/Multiple-Scattering across Blender 3.6-5.3+)."""
        params: dict[str, Any] = {
            "sky_type": sky_type,
            "sun_elevation": sun_elevation,
            "sun_rotation": sun_rotation,
            "strength": strength,
        }
        if air_density is not None:
            params["air_density"] = air_density
        if dust_density is not None:
            params["dust_density"] = dust_density
        return await rt.invoke("lighting.set_world_sky", params, audit=True)

    @mcp.tool(annotations=_MUTATE)
    async def set_world_hdri(
        filepath: str,
        strength: float = 1.0,
        rotation_degrees: float = 0.0,
    ) -> dict[str, Any]:
        """Load an HDRI (.hdr/.exr/image) into the World shader with Z-rotation mapping and strength control."""
        try:
            resolved = rt.path_guard.validate(filepath, must_exist=True)
        except BridgeError as err:
            raise ToolError(err.format_for_agent()) from err
        return await rt.invoke(
            "lighting.set_world_hdri",
            {
                "filepath": str(resolved),
                "strength": strength,
                "rotation_degrees": rotation_degrees,
            },
            audit=True,
        )

    @mcp.tool(annotations=_CREATE)
    async def add_camera(
        name: str = "Camera",
        location: list[float] | None = None,
        look_at: str | list[float] | None = None,
        rotation_degrees: list[float] | None = None,
        lens: float = 50.0,
        sensor_width: float = 36.0,
        set_active: bool = True,
        collection: str | None = None,
    ) -> dict[str, Any]:
        """Create a camera aimed at `look_at` (object name or [x,y,z]) and optionally set it as active."""
        return await rt.invoke(
            "camera.add_camera",
            {
                "name": name,
                "location": location,
                "look_at": look_at,
                "rotation_degrees": rotation_degrees,
                "lens": lens,
                "sensor_width": sensor_width,
                "set_active": set_active,
                "collection": collection,
            },
            audit=True,
        )

    @mcp.tool(annotations=_MUTATE)
    async def camera_look_at(
        target: str | list[float],
        camera: str | None = None,
    ) -> dict[str, Any]:
        """Aim a camera (or the active scene camera) at an object's center or world point `[x, y, z]`."""
        return await rt.invoke(
            "camera.look_at",
            {"target": target, "camera": camera},
            audit=True,
        )

    @mcp.tool(annotations=_MUTATE)
    async def camera_frame_objects(
        objects: list[str] | None = None,
        camera: str | None = None,
        direction: list[float] | None = None,
        margin: float = 1.3,
    ) -> dict[str, Any]:
        """Auto-position a camera so target objects (or the whole scene) fill the frame cleanly."""
        return await rt.invoke(
            "camera.frame_objects",
            {
                "objects": objects,
                "camera": camera,
                "direction": direction,
                "margin": margin,
            },
            audit=True,
        )

    @mcp.tool(annotations=_MUTATE)
    async def set_camera_lens_dof(
        camera: str | None = None,
        lens: float | None = None,
        camera_type: Literal["PERSP", "ORTHO", "PANO"] | None = None,
        use_dof: bool | None = None,
        focus_object: str | None = None,
        focus_distance: float | None = None,
        fstop: float | None = None,
        clip_start: float | None = None,
        clip_end: float | None = None,
    ) -> dict[str, Any]:
        """Configure camera focal length, projection type, clipping range, and depth of field (DOF)."""
        return await rt.invoke(
            "camera.set_lens_dof",
            {
                "camera": camera,
                "lens": lens,
                "camera_type": camera_type,
                "use_dof": use_dof,
                "focus_object": focus_object,
                "focus_distance": focus_distance,
                "fstop": fstop,
                "clip_start": clip_start,
                "clip_end": clip_end,
            },
            audit=True,
        )
