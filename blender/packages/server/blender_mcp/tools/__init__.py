# SPDX-License-Identifier: MIT
"""Tool registration hub and cooperative job polling helper for blender-mcp."""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from blender_mcp.bridge.client import BridgeClient
from blender_mcp.bridge.pool import BridgePool
from blender_mcp.config import ServerSettings
from blender_mcp.security import PathGuard
from blender_mcp_protocol import BridgeError

if TYPE_CHECKING:
    from blender_mcp.integrations import IntegrationsHub


@dataclass
class ToolRuntime:
    """Shared dependencies injected into all MCP tool handlers."""

    bridge: BridgeClient | BridgePool
    settings: ServerSettings
    path_guard: PathGuard
    pool: BridgePool | None = None
    integrations: IntegrationsHub | None = None
    last_scene_event: dict[str, Any] | None = None

    async def invoke(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        audit: bool = False,
        timeout: float | None = None,
    ) -> Any:
        try:
            return await self.bridge.call(
                method,
                params or {},
                timeout=timeout,
                audit=audit,
            )
        except BridgeError as err:
            raise ToolError(err.format_for_agent()) from err


async def wait_for_job(
    rt: ToolRuntime,
    job_id: str,
    ctx: Context | None = None,
    *,
    poll_interval: float = 0.15,
) -> dict[str, Any]:
    """Poll a Blender JobManager job, streaming MCP progress and cancelling on disconnect/cancel."""
    last_step = -1
    try:
        while True:
            state = await rt.invoke("jobs.get_status", {"job_id": job_id})
            step = int(state.get("current_step", 0))
            total = max(1, int(state.get("total_steps", 1)))
            msg = str(state.get("message", ""))
            if ctx is not None and step != last_step:
                last_step = step
                with contextlib.suppress(Exception):
                    await ctx.report_progress(progress=float(step), total=float(total), message=msg)

            status = state.get("status")
            if status == "completed":
                return state
            if status == "cancelled":
                return state
            if status == "failed":
                raise ToolError(f"Blender job {job_id} failed: {state.get('error') or 'unknown error'}")
            await asyncio.sleep(poll_interval)
    except asyncio.CancelledError:
        with contextlib.suppress(Exception):
            await rt.bridge.call("jobs.cancel", {"job_id": job_id}, timeout=5.0)
        raise


def register_toolsets(mcp: MCPServer, runtime: ToolRuntime) -> list[str]:
    """Register toolsets according to profile and security policy."""
    from blender_mcp.tools import (
        animation,
        collections,
        core,
        history,
        introspection,
        io,
        lighting_camera,
        materials,
        mesh,
        modifiers,
        nodes,
        objects,
        physics,
        render,
        rigging,
        scripting,
        sculpt_gp,
        vision,
    )

    enabled: list[str] = []
    profile = runtime.settings.profile

    core.register(mcp, runtime)
    enabled.append("core")

    if profile == "minimal":
        vision.register(mcp, runtime)
        enabled.append("vision")
    elif profile == "modeling":
        for name, mod in (
            ("objects", objects),
            ("collections", collections),
            ("materials", materials),
            ("mesh", mesh),
            ("modifiers", modifiers),
            ("nodes", nodes),
            ("lighting_camera", lighting_camera),
            ("io", io),
            ("history", history),
            ("vision", vision),
        ):
            mod.register(mcp, runtime)
            enabled.append(name)
    elif profile == "animation":
        for name, mod in (
            ("objects", objects),
            ("collections", collections),
            ("lighting_camera", lighting_camera),
            ("animation", animation),
            ("rigging", rigging),
            ("physics", physics),
            ("render", render),
            ("history", history),
            ("vision", vision),
        ):
            mod.register(mcp, runtime)
            enabled.append(name)
    else:
        # "full" includes every toolset
        for name, mod in (
            ("objects", objects),
            ("collections", collections),
            ("materials", materials),
            ("mesh", mesh),
            ("modifiers", modifiers),
            ("nodes", nodes),
            ("lighting_camera", lighting_camera),
            ("animation", animation),
            ("rigging", rigging),
            ("physics", physics),
            ("render", render),
            ("sculpt_gp", sculpt_gp),
            ("io", io),
            ("introspection", introspection),
            ("history", history),
            ("vision", vision),
        ):
            mod.register(mcp, runtime)
            enabled.append(name)

    if scripting.register(mcp, runtime):
        enabled.append("scripting")

    return enabled


register_f1_toolsets = register_toolsets
