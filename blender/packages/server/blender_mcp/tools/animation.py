# SPDX-License-Identifier: MIT
"""Animation MCP tools (compatible with Blender 5.x Slotted Actions and 3.6-4.x classic Actions)."""

from __future__ import annotations

from typing import Any, Literal

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from blender_mcp.tools import ToolRuntime

_READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True)
_MUTATE = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=True)
_DESTRUCTIVE = ToolAnnotations(read_only_hint=False, destructive_hint=True, idempotent_hint=False)


def register(mcp: MCPServer, rt: ToolRuntime) -> None:
    @mcp.tool(annotations=_MUTATE)
    async def set_frame_range(
        frame_start: int | None = None,
        frame_end: int | None = None,
        fps: int | None = None,
        frame_current: int | None = None,
    ) -> dict[str, Any]:
        """Configure scene timeline frame range, FPS, and optional current frame."""
        return await rt.invoke(
            "animation.set_frame_range",
            {
                "frame_start": frame_start,
                "frame_end": frame_end,
                "fps": fps,
                "frame_current": frame_current,
            },
            audit=True,
        )

    @mcp.tool(annotations=_MUTATE)
    async def set_current_frame(frame: int) -> dict[str, Any]:
        """Scrub the Blender timeline to a specific frame number."""
        return await rt.invoke("animation.set_current_frame", {"frame": frame})

    @mcp.tool(annotations=_MUTATE)
    async def insert_keyframes(
        object: str,
        keyframes: list[dict[str, Any]],
        data_path: str = "location",
        degrees: bool = True,
        interpolation: Literal["CONSTANT", "LINEAR", "BEZIER", "SINE", "QUAD", "CUBIC", "BOUNCE", "ELASTIC"]
        | None = None,
        easing: Literal["AUTO", "EASE_IN", "EASE_OUT", "EASE_IN_OUT"] | None = None,
    ) -> dict[str, Any]:
        """Insert one or more keyframes on an object property.

        Args:
            object: Object name or persistent uid.
            keyframes: List of `{"frame": int, "value": ...}` dicts (rotations in degrees when `degrees=True`).
            data_path: Property path (e.g. `'location'`, `'rotation_euler'`, `'scale'`).
            degrees: Interpret `rotation_euler` values as degrees (default True).
            interpolation: Optional FCurve interpolation mode applied to inserted keyframes.
            easing: Optional easing curve for non-linear interpolations.
        """
        return await rt.invoke(
            "animation.insert_keyframes",
            {
                "object": object,
                "keyframes": keyframes,
                "data_path": data_path,
                "degrees": degrees,
                "interpolation": interpolation,
                "easing": easing,
            },
            audit=True,
        )

    @mcp.tool(annotations=_DESTRUCTIVE)
    async def delete_keyframes(
        object: str,
        data_path: str = "location",
        frames: list[int] | None = None,
    ) -> dict[str, Any]:
        """Delete keyframes at specific `frames` (or all keyframes on `data_path` when `frames` is omitted)."""
        return await rt.invoke(
            "animation.delete_keyframes",
            {"object": object, "data_path": data_path, "frames": frames or []},
            audit=True,
        )

    @mcp.tool(annotations=_MUTATE)
    async def set_interpolation(
        object: str,
        interpolation: Literal["CONSTANT", "LINEAR", "BEZIER", "SINE", "QUAD", "CUBIC", "BOUNCE", "ELASTIC"] = "BEZIER",
        data_path: str | None = None,
        easing: Literal["AUTO", "EASE_IN", "EASE_OUT", "EASE_IN_OUT"] | None = None,
    ) -> dict[str, Any]:
        """Set FCurve keyframe interpolation across an object's action (Slotted Actions & classic Actions)."""
        return await rt.invoke(
            "animation.set_interpolation",
            {
                "object": object,
                "interpolation": interpolation,
                "data_path": data_path,
                "easing": easing,
            },
            audit=True,
        )

    @mcp.tool(annotations=_READ_ONLY)
    async def list_keyframes(object: str) -> dict[str, Any]:
        """List all FCurves and keyframe points on an object's active animation action."""
        return await rt.invoke("animation.list_keyframes", {"object": object})

    @mcp.tool(annotations=_MUTATE)
    async def add_constraint(
        object: str,
        constraint_type: str = "TRACK_TO",
        target: str | None = None,
        name: str | None = None,
        settings: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Add an object constraint (e.g. TRACK_TO, COPY_LOCATION, COPY_ROTATION, FOLLOW_PATH, LIMIT_LOCATION)."""
        return await rt.invoke(
            "animation.add_constraint",
            {
                "object": object,
                "constraint_type": constraint_type,
                "target": target,
                "name": name,
                "settings": settings or {},
            },
            audit=True,
        )

    @mcp.tool(annotations=_MUTATE)
    async def add_driver(
        object: str,
        data_path: str,
        expression: str,
        index: int = -1,
        variables: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Attach a scripted driver expression (e.g. `frame * 0.05`) to an object property."""
        return await rt.invoke(
            "animation.add_driver",
            {
                "object": object,
                "data_path": data_path,
                "expression": expression,
                "index": index,
                "variables": variables or [],
            },
            audit=True,
        )

    @mcp.tool(annotations=_MUTATE)
    async def nla_push_down(
        object: str,
        track_name: str | None = None,
        start_frame: int | None = None,
        clear_active_action: bool = True,
    ) -> dict[str, Any]:
        """Push an object's active Action down onto a named NLA track strip."""
        params: dict[str, Any] = {
            "object": object,
            "track_name": track_name,
            "clear_active_action": clear_active_action,
        }
        if start_frame is not None:
            params["start_frame"] = start_frame
        return await rt.invoke("animation.nla_push_down", params, audit=True)

    @mcp.tool(annotations=_MUTATE)
    async def shape_key_add(
        object: str,
        name: str = "Key",
        vertex_deltas: list[list[float]] | None = None,
        scale_offset: list[float] | None = None,
        value: float = 0.0,
        from_mix: bool = False,
    ) -> dict[str, Any]:
        """Add a named shape key (auto-creating `Basis`) with optional vertex deltas `[idx, dx, dy, dz]` or `scale_offset`."""
        return await rt.invoke(
            "animation.shape_key_add",
            {
                "object": object,
                "name": name,
                "vertex_deltas": vertex_deltas or [],
                "scale_offset": scale_offset,
                "value": value,
                "from_mix": from_mix,
            },
            audit=True,
        )

    @mcp.tool(annotations=_MUTATE)
    async def shape_key_set(
        object: str,
        shape_key: str,
        value: float,
        keyframe_frame: int | None = None,
    ) -> dict[str, Any]:
        """Set a shape key's blend weight (and optionally insert a keyframe at `keyframe_frame`)."""
        return await rt.invoke(
            "animation.shape_key_set",
            {
                "object": object,
                "shape_key": shape_key,
                "value": value,
                "keyframe_frame": keyframe_frame,
            },
            audit=True,
        )
