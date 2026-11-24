# SPDX-License-Identifier: MIT
"""MCP Resources and Resource Templates exposing live Blender scene state and bpy docs."""

from __future__ import annotations

import json

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ResourceError

from blender_mcp.tools import ToolRuntime
from blender_mcp_protocol import BridgeError

AGENT_GUIDE_MARKDOWN = """\
# Blender MCP Agent Guide

## Conventions
- **Axes:** Right-handed **Z-up** (X right, Y depth/back, Z up).
- **Units:** Meters.
- **Rotations:** Euler XYZ in **degrees** across all semantic tools.

## Recommended Workflow
1. Inspect the scene (`blender://scene` or `get_scene_summary`).
2. Save a checkpoint (`create_checkpoint`) before bulk or destructive edits.
3. Build geometry using semantic tools (`create_primitive`, `mesh_bevel`, `mesh_boolean`, `add_modifier`, `align_to_ground`).
4. Author procedural shaders, Geometry Nodes, World shaders, and Compositor graphs via the **Nodes DSL** (`build_node_tree`, `patch_node_tree`, `get_node_tree`, `list_node_types`).
5. Inspect visually with `capture_multiview` (fast `workbench`) and `capture_viewport` (`eevee`/`cycles`).
6. Keep context lean by using `list_toolsets` / `enable_toolset` / `disable_toolset`.
"""


def register_resources(mcp: MCPServer, rt: ToolRuntime) -> None:
    @mcp.resource(
        "blender://guide",
        name="blender_guide",
        title="Blender MCP Agent Guide",
        description="Conventions, Nodes DSL quick reference, and best practices for AI agents using Blender.",
        mime_type="text/markdown",
    )
    async def read_guide() -> str:
        return AGENT_GUIDE_MARKDOWN

    @mcp.resource(
        "blender://scene",
        name="blender_scene",
        title="Active Blender Scene Summary",
        description="Live JSON summary of the active Blender scene (objects, collections, render, timeline). Supports real-time subscriptions.",
        mime_type="application/json",
    )
    async def read_scene() -> str:
        try:
            data = await rt.bridge.call("core.get_scene_summary", {})
        except BridgeError as err:
            raise ResourceError(err.format_for_agent()) from err
        return json.dumps(data, indent=2)

    @mcp.resource(
        "blender://instances",
        name="blender_instances",
        title="Running Blender Instances",
        description="List of all discovered running Blender MCP bridge instances and the active selection.",
        mime_type="application/json",
    )
    async def read_instances() -> str:
        if rt.pool is None:
            hs = rt.bridge.handshake
            payload = {"active_instance_id": hs.instance_id if hs else None, "instances": []}
        else:
            payload = {
                "active_instance_id": rt.pool.active_instance_id,
                "instances": rt.pool.discover_instances(),
            }
        return json.dumps(payload, indent=2)

    @mcp.resource(
        "blender://object/{ref}",
        name="blender_object",
        title="Blender Object Details",
        description="Detailed geometry, world bounding box, transforms, materials, and modifiers for an object (by name or uid).",
        mime_type="application/json",
    )
    async def read_object(ref: str) -> str:
        try:
            data = await rt.bridge.call("core.get_object_details", {"object": ref})
        except BridgeError as err:
            raise ResourceError(err.format_for_agent()) from err
        return json.dumps(data, indent=2)

    @mcp.resource(
        "blender://material/{name}",
        name="blender_material",
        title="Blender Material Details",
        description="Nodes and Principled BSDF parameters of a Blender material.",
        mime_type="application/json",
    )
    async def read_material(name: str) -> str:
        try:
            data = await rt.bridge.call("materials.get_material_details", {"material": name})
        except BridgeError as err:
            raise ResourceError(err.format_for_agent()) from err
        return json.dumps(data, indent=2)

    @mcp.resource(
        "blender://node-tree/{kind}/{name}",
        name="blender_node_tree",
        title="Blender Node Tree DSL",
        description="Declarative DSL JSON serialization of a node tree (kind: material, geonodes, world, compositor).",
        mime_type="application/json",
    )
    async def read_node_tree(kind: str, name: str) -> str:
        spec = "compositor" if kind.lower() == "compositor" else f"{kind}:{name}"
        try:
            data = await rt.bridge.call("nodes.get_node_tree", {"tree": spec})
        except BridgeError as err:
            raise ResourceError(err.format_for_agent()) from err
        return json.dumps(data, indent=2)

    @mcp.resource(
        "docs://bpy/{query}",
        name="bpy_api_docs",
        title="Live Blender bpy.types Reference",
        description="Live RNA classes and properties matching `query` on the connected Blender version.",
        mime_type="application/json",
    )
    async def read_bpy_docs(query: str) -> str:
        try:
            data = await rt.bridge.call("introspection.search_bpy_api", {"query": query, "limit": 20})
        except BridgeError as err:
            raise ResourceError(err.format_for_agent()) from err
        return json.dumps(data, indent=2)
