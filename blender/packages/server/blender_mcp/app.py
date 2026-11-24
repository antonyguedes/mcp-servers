# SPDX-License-Identifier: MIT
"""MCPServer assembly: subscriptions, resources, prompts, completions, toolsets, integrations, plugins."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.subscriptions import InMemorySubscriptionBus, ResourceUpdated

from blender_mcp.bridge.client import BridgeClient
from blender_mcp.bridge.pool import BridgePool
from blender_mcp.completions import register_completions
from blender_mcp.config import ServerSettings
from blender_mcp.integrations import IntegrationsHub
from blender_mcp.plugins import PluginCallback, PluginContext, load_plugins
from blender_mcp.prompts import register_prompts
from blender_mcp.resources import register_resources
from blender_mcp.security import PathGuard
from blender_mcp.tools import ToolRuntime
from blender_mcp.toolsets import ToolsetManager

SERVER_INSTRUCTIONS = """\
You are connected to Blender 3D via `blender-mcp`.

Conventions & best practices:
- Coordinate system: right-handed Z-up, units in meters, Euler rotations in degrees (XYZ).
- Prefer semantic tools (`create_primitive`, `mesh_bevel`, `add_modifier`, `create_pbr_material`, `setup_lighting_preset`, `align_to_ground`) over raw scripting.
- For procedural materials, Geometry Nodes, World shaders, and Compositor graphs, use the declarative Nodes DSL (`build_node_tree`, `patch_node_tree`, `get_node_tree`, `list_node_types`).
- For real-world HDRIs, PBR textures, and models, enable or use the `integrations` toolset (Poly Haven & ambientCG work without API keys; Sketchfab and AI 3D providers activate via env vars).
- Use `list_toolsets` / `enable_toolset` / `disable_toolset` to load only the toolsets needed for the task.
- Read live scene state via MCP Resources (`blender://scene`, `blender://object/{ref}`, `blender://material/{name}`, `blender://node-tree/{kind}/{name}`, `docs://bpy/{query}`).
- Every mutating tool returns a persistent `uid` and a compact scene `diff` (`created`, `modified`, `deleted`).
- Use `create_checkpoint` before risky or bulk edits so you can roll back cleanly via `restore_checkpoint`.
- Always close the visual feedback loop: call `capture_multiview` (fast `workbench` shading) to verify geometry/proportions and `capture_viewport` (`eevee`/`cycles`) to verify materials and lighting.
"""


def create_server(
    settings: ServerSettings | None = None,
    bridge: BridgeClient | BridgePool | None = None,
    *,
    extra_plugins: Sequence[PluginCallback] | None = None,
    discover_plugins: bool = True,
) -> MCPServer:
    """Create and configure the `blender-mcp` MCPServer instance."""
    cfg = settings or ServerSettings.from_env()
    if isinstance(bridge, BridgePool):
        pool: BridgePool | None = bridge
        active_bridge: BridgeClient | BridgePool = bridge
    elif isinstance(bridge, BridgeClient):
        pool = BridgePool(cfg, default_bridge=bridge)
        active_bridge = pool
    else:
        pool = BridgePool(cfg)
        active_bridge = pool

    integrations = IntegrationsHub(cfg)
    allowed = list(cfg.allowed_dirs)
    if allowed:
        # Always permit importing downloaded assets from the managed local cache
        allowed.append(integrations.cache.root)

    bus = InMemorySubscriptionBus()
    runtime = ToolRuntime(
        bridge=active_bridge,
        settings=cfg,
        path_guard=PathGuard(allowed),
        pool=pool,
        integrations=integrations,
    )

    async def _on_bridge_notification(method: str, params: dict[str, Any]) -> None:
        if method == "event.scene_changed":
            runtime.last_scene_event = params
            await bus.publish(ResourceUpdated(uri="blender://scene"))

    active_bridge.add_notification_listener(_on_bridge_notification)

    @asynccontextmanager
    async def lifespan(_server: MCPServer) -> AsyncIterator[dict[str, object]]:
        try:
            yield {"runtime": runtime, "bus": bus, "integrations": integrations}
        finally:
            await active_bridge.close()

    mcp = MCPServer(
        name="blender-mcp",
        title="Blender MCP Server",
        description="Production-grade MCP server connecting AI agents to Blender 3D (3.6 LTS - 5.3+)",
        instructions=SERVER_INSTRUCTIONS,
        lifespan=lifespan,
        subscriptions=bus,
    )

    toolset_mgr = ToolsetManager(mcp, runtime, bus=bus)
    toolset_mgr.apply_initial_profile(cfg.profile)
    toolset_mgr.register_management_tools()

    register_resources(mcp, runtime)
    register_prompts(mcp)
    register_completions(mcp, runtime)

    loaded_plugins = load_plugins(
        PluginContext(mcp=mcp, runtime=runtime, integrations=integrations, toolsets=toolset_mgr),
        extra_plugins=extra_plugins,
        discover_entry_points=discover_plugins,
    )

    mcp._blender_runtime = runtime  # type: ignore[attr-defined]
    mcp._blender_bus = bus  # type: ignore[attr-defined]
    mcp._blender_toolsets = toolset_mgr  # type: ignore[attr-defined]
    mcp._blender_integrations = integrations  # type: ignore[attr-defined]
    mcp._blender_plugins = loaded_plugins  # type: ignore[attr-defined]
    return mcp
