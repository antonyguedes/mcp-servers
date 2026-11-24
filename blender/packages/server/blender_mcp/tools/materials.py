# SPDX-License-Identifier: MIT
"""PBR material and image texture MCP tools."""

from __future__ import annotations

from typing import Any, Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from blender_mcp.tools import ToolRuntime
from blender_mcp_protocol import BridgeError

_READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True)
_MUTATE = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=True)


def register(mcp: MCPServer, rt: ToolRuntime) -> None:
    @mcp.tool(annotations=_READ_ONLY)
    async def list_materials() -> dict[str, Any]:
        """List all materials in the Blender file with their current Principled BSDF parameters."""
        return await rt.invoke("materials.list_materials")

    @mcp.tool(annotations=_READ_ONLY)
    async def get_material_details(material: str) -> dict[str, Any]:
        """Inspect a material's nodes and Principled BSDF parameters."""
        return await rt.invoke("materials.get_material_details", {"material": material})

    @mcp.tool(annotations=_MUTATE)
    async def create_pbr_material(
        name: str,
        base_color: list[float] | None = None,
        metallic: float | None = None,
        roughness: float | None = None,
        ior: float | None = None,
        alpha: float | None = None,
        specular: float | None = None,
        subsurface: float | None = None,
        transmission: float | None = None,
        coat_weight: float | None = None,
        coat_roughness: float | None = None,
        emission_color: list[float] | None = None,
        emission_strength: float | None = None,
        assign_to: list[str] | None = None,
        overwrite: bool = False,
    ) -> dict[str, Any]:
        """Create a Principled BSDF PBR material (compatible with Blender 3.6-5.3+) and optionally assign it.

        Colors are linear RGB or RGBA floats in [0.0, 1.0].
        """
        params: dict[str, Any] = {
            "name": name,
            "overwrite": overwrite,
            "assign_to": assign_to or [],
        }
        for key, val in (
            ("base_color", base_color),
            ("metallic", metallic),
            ("roughness", roughness),
            ("ior", ior),
            ("alpha", alpha),
            ("specular", specular),
            ("subsurface", subsurface),
            ("transmission", transmission),
            ("coat_weight", coat_weight),
            ("coat_roughness", coat_roughness),
            ("emission_color", emission_color),
            ("emission_strength", emission_strength),
        ):
            if val is not None:
                params[key] = val
        return await rt.invoke("materials.create_pbr_material", params, audit=True)

    @mcp.tool(annotations=_MUTATE)
    async def assign_material(
        material: str,
        objects: list[str],
        slot_index: int | None = None,
    ) -> dict[str, Any]:
        """Assign an existing material to one or more objects."""
        return await rt.invoke(
            "materials.assign_material",
            {"material": material, "objects": objects, "slot_index": slot_index},
            audit=True,
        )

    @mcp.tool(annotations=_MUTATE)
    async def set_material_params(
        material: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        """Update Principled BSDF parameters on an existing material (e.g. roughness, base_color, metallic)."""
        return await rt.invoke(
            "materials.set_material_params",
            {"material": material, "params": params},
            audit=True,
        )

    @mcp.tool(annotations=_MUTATE)
    async def create_texture_from_image(
        material: str,
        filepath: str,
        channel: Literal[
            "base_color",
            "roughness",
            "metallic",
            "normal",
            "emission_color",
            "alpha",
        ] = "base_color",
        colorspace: str | None = None,
        normal_strength: float = 1.0,
    ) -> dict[str, Any]:
        """Load an image texture from disk and connect it to a material's Principled BSDF channel."""
        try:
            resolved = rt.path_guard.validate(filepath, must_exist=True)
        except BridgeError as err:
            raise ToolError(err.format_for_agent()) from err
        return await rt.invoke(
            "materials.create_texture_from_image",
            {
                "material": material,
                "filepath": str(resolved),
                "channel": channel,
                "colorspace": colorspace,
                "normal_strength": normal_strength,
            },
            audit=True,
        )
