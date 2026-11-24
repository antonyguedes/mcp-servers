# SPDX-License-Identifier: MIT
"""Dynamic toolset management with MCP tools/list_changed notifications and multi-instance tools."""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.subscriptions import InMemorySubscriptionBus, ToolsListChanged
from mcp.types import ToolAnnotations

from blender_mcp.tools import ToolRuntime
from blender_mcp_protocol import BridgeError, PythonPolicy

_READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True)
_MUTATE = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=True)

ToolsetRegisterFn = Callable[[MCPServer, ToolRuntime], Any]


@dataclass(frozen=True)
class ToolsetDef:
    name: str
    description: str
    register_fn: ToolsetRegisterFn
    locked: bool = False


def _build_catalog() -> dict[str, ToolsetDef]:
    from blender_mcp.tools import (
        animation,
        collections,
        core,
        history,
        integrations,
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

    defs = [
        ToolsetDef("core", "Scene inspection, object listing, selection, and modes", core.register, locked=True),
        ToolsetDef("objects", "Primitives, custom meshes, transforms, hierarchy, alignment", objects.register),
        ToolsetDef("collections", "Collection organization, visibility, and view layers", collections.register),
        ToolsetDef("materials", "PBR materials, parameter edits, and image texture wiring", materials.register),
        ToolsetDef("mesh", "bmesh modeling (extrude, bevel, inset, boolean, loop cut, UV)", mesh.register),
        ToolsetDef("modifiers", "Typed modifier stack (Subsurf, Bevel, Array, GeoNodes, apply)", modifiers.register),
        ToolsetDef("nodes", "Declarative bidirectional Nodes DSL (Shader, GeoNodes, Compositor)", nodes.register),
        ToolsetDef("lighting_camera", "Lights, presets, physical sky/HDRI, cameras, framing, DOF", lighting_camera.register),
        ToolsetDef("animation", "Keyframes (Slotted/Classic Actions), constraints, drivers, NLA, shape keys", animation.register),
        ToolsetDef("rigging", "Declarative armatures, auto-weights, bone posing, IK", rigging.register),
        ToolsetDef("physics", "Rigid body, cloth, collision, fluid, and cancellable bake jobs", physics.register),
        ToolsetDef("render", "Render settings, async still/animation render jobs, progress & cancel", render.register),
        ToolsetDef("sculpt_gp", "Voxel remesh, procedural sculpt strokes, Grease Pencil v2/v3", sculpt_gp.register),
        ToolsetDef("io", "Import/export glTF/FBX/OBJ/USD/STL/PLY/Alembic and .blend I/O", io.register),
        ToolsetDef("introspection", "Safe RNA get/set, bpy.ops discovery/calling, live bpy API search", introspection.register),
        ToolsetDef("history", "Undo/redo and named session checkpoints", history.register),
        ToolsetDef("vision", "Auto-framed viewport capture, 2x2 multiview grid, render preview", vision.register),
        ToolsetDef(
            "integrations",
            "Poly Haven, ambientCG, Sketchfab, AI 3D generators, and local asset cache",
            integrations.register,
        ),
        ToolsetDef("scripting", "Python execution (governed by BLENDER_MCP_ALLOW_PYTHON)", scripting.register),
    ]
    return {d.name: d for d in defs}


PROFILE_TOOLSETS: dict[str, tuple[str, ...]] = {
    "minimal": ("core", "vision"),
    "modeling": (
        "core",
        "objects",
        "collections",
        "materials",
        "mesh",
        "modifiers",
        "nodes",
        "lighting_camera",
        "io",
        "history",
        "vision",
    ),
    "animation": (
        "core",
        "objects",
        "collections",
        "lighting_camera",
        "animation",
        "rigging",
        "physics",
        "render",
        "history",
        "vision",
    ),
    "integrations": (
        "core",
        "objects",
        "collections",
        "materials",
        "lighting_camera",
        "integrations",
        "history",
        "vision",
    ),
    "full": (
        "core",
        "objects",
        "collections",
        "materials",
        "mesh",
        "modifiers",
        "nodes",
        "lighting_camera",
        "animation",
        "rigging",
        "physics",
        "render",
        "sculpt_gp",
        "io",
        "introspection",
        "integrations",
        "history",
        "vision",
    ),
}


class ToolsetManager:
    """Tracks enabled toolsets and dynamically enables/disables tools at runtime."""

    def __init__(
        self,
        mcp: MCPServer,
        runtime: ToolRuntime,
        bus: InMemorySubscriptionBus | None = None,
    ) -> None:
        self.mcp = mcp
        self.runtime = runtime
        self.bus = bus
        self.catalog = _build_catalog()
        self._tool_names_by_set: dict[str, list[str]] = {}
        self._enabled: set[str] = set()

    def _current_tool_names(self) -> set[str]:
        mgr = getattr(self.mcp, "_tool_manager", None)
        if mgr is not None and hasattr(mgr, "_tools"):
            return set(mgr._tools.keys())
        return set()

    def enable_sync(self, name: str) -> list[str]:
        key = name.strip().lower()
        if key not in self.catalog:
            raise ToolError(
                f"Unknown toolset {name!r}. Available: {', '.join(sorted(self.catalog.keys()))}."
            )
        if key == "scripting" and self.runtime.settings.python_policy == PythonPolicy.FALSE:
            raise ToolError(
                "Cannot enable 'scripting' toolset because BLENDER_MCP_ALLOW_PYTHON=false."
            )
        if key in self._enabled:
            return list(self._tool_names_by_set.get(key, []))

        before = self._current_tool_names()
        res = self.catalog[key].register_fn(self.mcp, self.runtime)
        if key == "scripting" and res is False:
            raise ToolError("Cannot enable 'scripting' toolset under current policy.")
        after = self._current_tool_names()
        added = sorted(after - before)
        self._tool_names_by_set[key] = added
        self._enabled.add(key)
        return added

    def disable_sync(self, name: str) -> list[str]:
        key = name.strip().lower()
        if key not in self.catalog:
            raise ToolError(
                f"Unknown toolset {name!r}. Available: {', '.join(sorted(self.catalog.keys()))}."
            )
        if self.catalog[key].locked:
            raise ToolError(f"Toolset {key!r} is core/required and cannot be disabled.")
        if key not in self._enabled:
            return []

        removed: list[str] = []
        for tool_name in list(self._tool_names_by_set.get(key, [])):
            with contextlib.suppress(Exception):
                self.mcp.remove_tool(tool_name)
                removed.append(tool_name)
        self._tool_names_by_set.pop(key, None)
        self._enabled.discard(key)
        return removed

    def apply_initial_profile(self, profile: str) -> list[str]:
        targets = PROFILE_TOOLSETS.get(profile.strip().lower(), PROFILE_TOOLSETS["full"])
        for ts in targets:
            self.enable_sync(ts)
        if self.runtime.settings.python_policy != PythonPolicy.FALSE:
            self.enable_sync("scripting")
        return sorted(self._enabled)

    def status(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for name, ts_def in self.catalog.items():
            rows.append(
                {
                    "name": name,
                    "enabled": name in self._enabled,
                    "locked": ts_def.locked,
                    "tool_count": len(self._tool_names_by_set.get(name, [])),
                    "description": ts_def.description,
                }
            )
        return rows

    def register_management_tools(self) -> None:
        """Register compact meta-tools for dynamic toolsets and multi-instance switching."""
        mcp = self.mcp
        rt = self.runtime
        mgr = self

        @mcp.tool(annotations=_READ_ONLY)
        async def list_toolsets() -> dict[str, Any]:
            """List all available Blender toolsets, which ones are enabled, and their tool counts."""
            return {
                "profile": rt.settings.profile,
                "total_active_tools": len(mgr._current_tool_names()),
                "toolsets": mgr.status(),
            }

        @mcp.tool(annotations=_MUTATE)
        async def enable_toolset(name: str, ctx: Context | None = None) -> dict[str, Any]:
            """Dynamically activate a Blender toolset (e.g. 'nodes', 'animation', 'render') and emit tools/list_changed."""
            added = mgr.enable_sync(name)
            if mgr.bus is not None:
                await mgr.bus.publish(ToolsListChanged())
            if ctx is not None:
                with contextlib.suppress(Exception):
                    await ctx.notify_tools_changed()
            return {
                "toolset": name.strip().lower(),
                "enabled": True,
                "tools_added": added,
                "total_active_tools": len(mgr._current_tool_names()),
            }

        @mcp.tool(annotations=_MUTATE)
        async def disable_toolset(name: str, ctx: Context | None = None) -> dict[str, Any]:
            """Dynamically unload a Blender toolset to reduce context usage and emit tools/list_changed."""
            removed = mgr.disable_sync(name)
            if mgr.bus is not None:
                await mgr.bus.publish(ToolsListChanged())
            if ctx is not None:
                with contextlib.suppress(Exception):
                    await ctx.notify_tools_changed()
            return {
                "toolset": name.strip().lower(),
                "enabled": False,
                "tools_removed": removed,
                "total_active_tools": len(mgr._current_tool_names()),
            }

        @mcp.tool(annotations=_READ_ONLY)
        async def list_blender_instances() -> dict[str, Any]:
            """Discover all running Blender instances with active MCP bridges and show which one is selected."""
            if rt.pool is None:
                hs = rt.bridge.handshake
                return {
                    "active_instance_id": hs.instance_id if hs else None,
                    "instances": [],
                }
            instances = rt.pool.discover_instances()
            return {
                "active_instance_id": rt.pool.active_instance_id,
                "instances": instances,
            }

        @mcp.tool(annotations=_MUTATE)
        async def select_blender_instance(instance_id: str) -> dict[str, Any]:
            """Switch the active target Blender instance when controlling multiple Blender sessions."""
            if rt.pool is None:
                raise ToolError("Multi-instance pool is not configured on this server.")
            try:
                return rt.pool.select_instance(instance_id)
            except BridgeError as err:
                raise ToolError(err.format_for_agent()) from err
