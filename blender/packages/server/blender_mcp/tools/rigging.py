# SPDX-License-Identifier: MIT
"""Rigging MCP tools: declarative armatures, skinning weights, bone posing, and IK."""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from blender_mcp.tools import ToolRuntime

_CREATE = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False)
_MUTATE = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=True)


def register(mcp: MCPServer, rt: ToolRuntime) -> None:
    @mcp.tool(annotations=_CREATE)
    async def create_armature(
        bones: list[dict[str, Any]],
        name: str = "Armature",
        location: list[float] | None = None,
        collection: str | None = None,
    ) -> dict[str, Any]:
        """Create an Armature from a declarative bone hierarchy spec.

        Each item in `bones`: `{"name": "Bone", "head": [0,0,0], "tail": [0,0,1], "parent": "Root", "use_connect": true}`.
        """
        return await rt.invoke(
            "rigging.create_armature",
            {
                "name": name,
                "bones": bones,
                "location": location,
                "collection": collection,
            },
            audit=True,
        )

    @mcp.tool(annotations=_MUTATE)
    async def bind_auto_weights(
        mesh: str,
        armature: str,
    ) -> dict[str, Any]:
        """Bind a mesh object to an armature with automatic bone weights (with deterministic distance fallback)."""
        return await rt.invoke(
            "rigging.bind_auto_weights",
            {"mesh": mesh, "armature": armature},
            audit=True,
        )

    @mcp.tool(annotations=_MUTATE)
    async def pose_bone(
        armature: str,
        bone: str,
        location: list[float] | None = None,
        rotation_degrees: list[float] | None = None,
        scale: list[float] | float | None = None,
        keyframe_frame: int | None = None,
    ) -> dict[str, Any]:
        """Pose a bone in local space (degrees) and optionally keyframe it at `keyframe_frame`."""
        return await rt.invoke(
            "rigging.pose_bone",
            {
                "armature": armature,
                "bone": bone,
                "location": location,
                "rotation_degrees": rotation_degrees,
                "scale": scale,
                "keyframe_frame": keyframe_frame,
            },
            audit=True,
        )

    @mcp.tool(annotations=_MUTATE)
    async def setup_ik(
        armature: str,
        bone: str,
        chain_count: int = 2,
        target: str | None = None,
        pole_target: str | None = None,
        pole_angle_degrees: float = 0.0,
        name: str | None = None,
    ) -> dict[str, Any]:
        """Add an Inverse Kinematics (IK) constraint to a bone (auto-creating an Empty target if `target` is omitted)."""
        return await rt.invoke(
            "rigging.setup_ik",
            {
                "armature": armature,
                "bone": bone,
                "chain_count": chain_count,
                "target": target,
                "pole_target": pole_target,
                "pole_angle_degrees": pole_angle_degrees,
                "name": name,
            },
            audit=True,
        )
