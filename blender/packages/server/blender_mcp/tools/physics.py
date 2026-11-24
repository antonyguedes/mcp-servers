# SPDX-License-Identifier: MIT
"""Physics setup (Rigid Body, Cloth, Collision, Fluid) and cooperative bake MCP tools."""

from __future__ import annotations

from typing import Any, Literal

from mcp.server.mcpserver import Context, MCPServer
from mcp.types import ToolAnnotations

from blender_mcp.tools import ToolRuntime, wait_for_job

_MUTATE = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=True)


def register(mcp: MCPServer, rt: ToolRuntime) -> None:
    @mcp.tool(annotations=_MUTATE)
    async def add_rigid_body(
        object: str,
        body_type: Literal["ACTIVE", "PASSIVE"] = "ACTIVE",
        mass: float | None = None,
        friction: float | None = None,
        restitution: float | None = None,
        collision_shape: Literal["CONVEX_HULL", "MESH", "BOX", "SPHERE", "CAPSULE", "CYLINDER"] | None = None,
        kinematic: bool | None = None,
    ) -> dict[str, Any]:
        """Enable Rigid Body physics on an object (auto-creating the scene RigidBodyWorld)."""
        return await rt.invoke(
            "physics.add_rigid_body",
            {
                "object": object,
                "body_type": body_type,
                "mass": mass,
                "friction": friction,
                "restitution": restitution,
                "collision_shape": collision_shape,
                "kinematic": kinematic,
            },
            audit=True,
        )

    @mcp.tool(annotations=_MUTATE)
    async def add_cloth(
        object: str,
        quality: int | None = None,
        mass: float | None = None,
        tension_stiffness: float | None = None,
        bending_stiffness: float | None = None,
        pin_group: str | None = None,
    ) -> dict[str, Any]:
        """Add or update a Cloth simulation modifier on a mesh object."""
        return await rt.invoke(
            "physics.add_cloth",
            {
                "object": object,
                "quality": quality,
                "mass": mass,
                "tension_stiffness": tension_stiffness,
                "bending_stiffness": bending_stiffness,
                "pin_group": pin_group,
            },
            audit=True,
        )

    @mcp.tool(annotations=_MUTATE)
    async def add_collision(
        object: str,
        damping: float | None = None,
        thickness_outer: float | None = None,
        friction_factor: float | None = None,
    ) -> dict[str, Any]:
        """Add or update a Collision physics modifier on a mesh object."""
        return await rt.invoke(
            "physics.add_collision",
            {
                "object": object,
                "damping": damping,
                "thickness_outer": thickness_outer,
                "friction_factor": friction_factor,
            },
            audit=True,
        )

    @mcp.tool(annotations=_MUTATE)
    async def add_fluid(
        object: str,
        fluid_type: Literal["DOMAIN", "FLOW", "EFFECTOR"] = "DOMAIN",
        domain_type: Literal["GAS", "LIQUID"] | None = None,
        resolution_max: int | None = None,
        flow_type: Literal["SMOKE", "FIRE", "BOTH", "LIQUID"] | None = None,
        flow_behavior: Literal["INFLOW", "OUTFLOW", "GEOMETRY"] | None = None,
    ) -> dict[str, Any]:
        """Add or configure a Mantaflow Fluid modifier (DOMAIN, FLOW, or EFFECTOR) on a mesh object."""
        return await rt.invoke(
            "physics.add_fluid",
            {
                "object": object,
                "fluid_type": fluid_type,
                "domain_type": domain_type,
                "resolution_max": resolution_max,
                "flow_type": flow_type,
                "flow_behavior": flow_behavior,
            },
            audit=True,
        )

    @mcp.tool(annotations=_MUTATE)
    async def bake_physics(
        frame_start: int | None = None,
        frame_end: int | None = None,
        wait: bool = True,
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        """Step and bake scene physics frame-by-frame as a cancellable job with live MCP progress."""
        params: dict[str, Any] = {}
        if frame_start is not None:
            params["frame_start"] = frame_start
        if frame_end is not None:
            params["frame_end"] = frame_end
        job = await rt.invoke("physics.bake_physics", params, audit=True)
        if not wait:
            return job
        return await wait_for_job(rt, job["job_id"], ctx)
