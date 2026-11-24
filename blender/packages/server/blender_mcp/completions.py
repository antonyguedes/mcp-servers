# SPDX-License-Identifier: MIT
"""MCP Completions handler for Resource Templates and Prompt arguments."""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer
from mcp.types import (
    Completion,
    CompletionArgument,
    CompletionContext,
    PromptReference,
    ResourceTemplateReference,
)

from blender_mcp.tools import ToolRuntime

_PROMPT_STATIC_CHOICES: dict[str, list[str]] = {
    "lighting_preset": ["three_point", "studio", "dramatic", "outdoor"],
    "engine": ["eevee", "cycles", "workbench"],
    "target_format": ["glb", "gltf", "fbx", "obj", "usd"],
    "style": ["stylized robot", "low-poly adventurer", "chibi creature", "humanoid blockout"],
}


def _filter_prefix(candidates: list[str], partial: str) -> Completion:
    q = partial.strip().lower()
    matched = [c for c in candidates if not q or q in c.lower()]
    truncated = len(matched) > 50
    return Completion(values=matched[:50], total=len(matched), has_more=truncated)


def register_completions(mcp: MCPServer, rt: ToolRuntime) -> None:
    @mcp.completion()
    async def handle_completion(
        ref: PromptReference | ResourceTemplateReference,
        argument: CompletionArgument,
        _context: CompletionContext | None,
    ) -> Completion:
        arg_name = argument.name
        partial = argument.value or ""

        if isinstance(ref, ResourceTemplateReference):
            uri = ref.uri
            if uri == "blender://object/{ref}" and arg_name == "ref":
                try:
                    data = await rt.bridge.call("core.list_objects", {"limit": 100})
                    names = [o["name"] for o in data.get("objects", [])]
                    return _filter_prefix(names, partial)
                except Exception:
                    return Completion(values=[])

            if uri == "blender://material/{name}" and arg_name == "name":
                try:
                    data = await rt.bridge.call("materials.list_materials", {})
                    names = [m["name"] for m in data.get("materials", [])]
                    return _filter_prefix(names, partial)
                except Exception:
                    return Completion(values=[])

            if uri == "blender://node-tree/{kind}/{name}":
                if arg_name == "kind":
                    return _filter_prefix(["material", "geonodes", "world", "compositor"], partial)
                if arg_name == "name":
                    try:
                        data = await rt.bridge.call("materials.list_materials", {})
                        names = [m["name"] for m in data.get("materials", [])]
                        return _filter_prefix(names, partial)
                    except Exception:
                        return Completion(values=[])

            if uri == "docs://bpy/{query}" and arg_name == "query":
                return _filter_prefix(
                    ["Principled", "GeometryNode", "ShaderNode", "Modifier", "Camera", "Light", "Action"],
                    partial,
                )

        if isinstance(ref, PromptReference):
            if arg_name in _PROMPT_STATIC_CHOICES:
                return _filter_prefix(_PROMPT_STATIC_CHOICES[arg_name], partial)
            if arg_name in ("subject", "target", "object_name"):
                try:
                    data = await rt.bridge.call("core.list_objects", {"limit": 100})
                    names = [o["name"] for o in data.get("objects", [])]
                    return _filter_prefix(names, partial)
                except Exception:
                    return Completion(values=[])
            if arg_name == "material_name":
                try:
                    data = await rt.bridge.call("materials.list_materials", {})
                    names = [m["name"] for m in data.get("materials", [])]
                    return _filter_prefix(names, partial)
                except Exception:
                    return Completion(values=[])

        return Completion(values=[])
