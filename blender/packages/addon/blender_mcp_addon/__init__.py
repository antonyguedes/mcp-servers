# SPDX-License-Identifier: GPL-3.0-or-later
"""Blender MCP Bridge add-on entry point, preferences, and 3D Viewport N-panel."""

from __future__ import annotations

import os
from typing import Any

import bpy  # type: ignore[import-not-found]
from bpy.props import BoolProperty, IntProperty, StringProperty  # type: ignore[import-not-found]

from .dispatcher import Dispatcher
from .handlers import register_all_handlers
from .server import BridgeTCPServer
from .wire import DEFAULT_HOST, DEFAULT_PORT

_DISPATCHER: Dispatcher | None = None
_SERVER: BridgeTCPServer | None = None


def _get_prefs(context: Any) -> Any | None:
    addon = context.preferences.addons.get(__package__ or __name__)
    return addon.preferences if addon else None


def start_bridge(*, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT, allow_python: bool = False) -> BridgeTCPServer:
    global _DISPATCHER, _SERVER
    if _SERVER is not None and _SERVER.is_running:
        return _SERVER
    _DISPATCHER = Dispatcher()
    register_all_handlers(_DISPATCHER)
    _SERVER = BridgeTCPServer(
        dispatcher=_DISPATCHER,
        host=host,
        port=port,
        token=os.environ.get("BLENDER_MCP_TOKEN") or None,
        allow_python=allow_python,
    )
    _SERVER.start()
    _DISPATCHER.start_gui_timer()
    return _SERVER


def stop_bridge() -> None:
    global _DISPATCHER, _SERVER
    if _DISPATCHER is not None:
        _DISPATCHER.request_stop()
    if _SERVER is not None:
        _SERVER.stop()
    _DISPATCHER = None
    _SERVER = None


class BlenderMCPPreferences(bpy.types.AddonPreferences):
    bl_idname = __package__ or __name__

    host: StringProperty(  # type: ignore[valid-type]
        name="Host",
        description="Localhost interface to bind (must stay local for security)",
        default=DEFAULT_HOST,
    )
    port: IntProperty(  # type: ignore[valid-type]
        name="Port",
        description="TCP port for the MCP bridge",
        default=DEFAULT_PORT,
        min=1024,
        max=65535,
    )
    allow_python: BoolProperty(  # type: ignore[valid-type]
        name="Allow Python Execution",
        description="Permit execute_python calls when also enabled by BLENDER_MCP_ALLOW_PYTHON",
        default=False,
    )
    auto_start: BoolProperty(  # type: ignore[valid-type]
        name="Auto-Start Bridge",
        description="Start the bridge automatically when Blender opens",
        default=True,
    )

    def draw(self, _context: Any) -> None:
        layout = self.layout
        layout.prop(self, "host")
        layout.prop(self, "port")
        layout.prop(self, "allow_python")
        layout.prop(self, "auto_start")


class BLENDER_MCP_OT_start(bpy.types.Operator):
    bl_idname = "blender_mcp.start_server"
    bl_label = "Start MCP Bridge"
    bl_description = "Start the local authenticated JSON-RPC bridge for AI agents"

    def execute(self, context: Any) -> set[str]:
        prefs = _get_prefs(context)
        host = prefs.host if prefs else DEFAULT_HOST
        port = prefs.port if prefs else DEFAULT_PORT
        allow_py = prefs.allow_python if prefs else False
        try:
            srv = start_bridge(host=host, port=port, allow_python=allow_py)
        except Exception as exc:
            self.report({"ERROR"}, f"Failed to start MCP bridge: {exc}")
            return {"CANCELLED"}
        self.report({"INFO"}, f"MCP bridge listening on {srv.host}:{srv.port}")
        return {"FINISHED"}


class BLENDER_MCP_OT_stop(bpy.types.Operator):
    bl_idname = "blender_mcp.stop_server"
    bl_label = "Stop MCP Bridge"
    bl_description = "Stop the local JSON-RPC bridge"

    def execute(self, _context: Any) -> set[str]:
        stop_bridge()
        self.report({"INFO"}, "MCP bridge stopped")
        return {"FINISHED"}


class BLENDER_MCP_PT_panel(bpy.types.Panel):
    bl_label = "Blender MCP"
    bl_idname = "VIEW3D_PT_blender_mcp"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "MCP"

    def draw(self, context: Any) -> None:
        layout = self.layout
        prefs = _get_prefs(context)
        running = _SERVER is not None and _SERVER.is_running

        box = layout.box()
        if running and _SERVER is not None:
            box.label(text=f"Status: Running ({_SERVER.host}:{_SERVER.port})", icon="CHECKMARK")
            box.label(text=f"Clients: {_SERVER.active_clients}")
            box.label(text=f"Python Exec: {'Allowed' if _SERVER.allow_python else 'Blocked'}")
            layout.operator("blender_mcp.stop_server", icon="PAUSE")
        else:
            box.label(text="Status: Stopped", icon="X")
            if prefs is not None:
                layout.prop(prefs, "port")
                layout.prop(prefs, "allow_python")
            layout.operator("blender_mcp.start_server", icon="PLAY")


_CLASSES = (
    BlenderMCPPreferences,
    BLENDER_MCP_OT_start,
    BLENDER_MCP_OT_stop,
    BLENDER_MCP_PT_panel,
)


def register() -> None:
    for cls in _CLASSES:
        bpy.utils.register_class(cls)
    prefs = _get_prefs(bpy.context)
    if prefs is None or prefs.auto_start:
        try:
            start_bridge(
                host=prefs.host if prefs else DEFAULT_HOST,
                port=prefs.port if prefs else DEFAULT_PORT,
                allow_python=prefs.allow_python if prefs else False,
            )
        except Exception as exc:
            print(f"[blender-mcp] Auto-start skipped: {exc}")


def unregister() -> None:
    stop_bridge()
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
