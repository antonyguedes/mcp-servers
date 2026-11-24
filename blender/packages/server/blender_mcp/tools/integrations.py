# SPDX-License-Identifier: MIT
"""External asset library and AI 3D generation MCP tools (Poly Haven, ambientCG, Sketchfab, AI 3D)."""

from __future__ import annotations

import contextlib
from pathlib import Path
from typing import Any, Literal

from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from blender_mcp.tools import ToolRuntime
from blender_mcp_protocol import BridgeError

_READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True)
_MUTATE = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False)
_DESTRUCTIVE = ToolAnnotations(read_only_hint=False, destructive_hint=True, idempotent_hint=False)


async def _wire_pbr_maps(
    rt: ToolRuntime,
    *,
    material_name: str,
    maps: dict[str, Path],
    assign_to: list[str] | None,
) -> dict[str, Any]:
    mat = await rt.invoke(
        "materials.create_pbr_material",
        {
            "name": material_name,
            "overwrite": True,
            "assign_to": assign_to or [],
        },
        audit=True,
    )
    wired: list[str] = []
    for channel, path in maps.items():
        await rt.invoke(
            "materials.create_texture_from_image",
            {
                "material": mat["name"],
                "filepath": str(path),
                "channel": channel,
            },
            audit=True,
        )
        wired.append(channel)
    return {
        "material": mat["name"],
        "channels_wired": wired,
        "assigned_to": mat.get("assigned_to", []),
    }


async def _import_and_normalize_model(
    rt: ToolRuntime,
    model_path: Path,
    *,
    collection: str | None,
    align_ground: bool,
) -> dict[str, Any]:
    imp = await rt.invoke("io.import_file", {"filepath": str(model_path)}, audit=True)
    names = [o["name"] for o in imp.get("imported_objects", [])]
    if collection and names:
        with contextlib.suppress(ToolError):
            await rt.invoke("collections.create_collection", {"name": collection}, audit=True)
        await rt.invoke(
            "collections.move_to_collection",
            {"objects": names, "collection": collection},
            audit=True,
        )
    if align_ground and names:
        await rt.invoke("objects.align_to_ground", {"objects": names, "target_z": 0.0}, audit=True)
    return {"filepath": str(model_path), "imported_objects": imp.get("imported_objects", [])}


def register(mcp: MCPServer, rt: ToolRuntime) -> None:
    hub = rt.integrations
    assert hub is not None

    # ---- Poly Haven (CC0, no key needed) ----
    @mcp.tool(annotations=_READ_ONLY)
    async def polyhaven_search(
        asset_type: Literal["all", "hdris", "textures", "models"] = "all",
        query: str = "",
        categories: list[str] | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        """Search Poly Haven's free CC0 catalog of HDRIs, PBR textures, and 3D models (no API key required)."""
        try:
            return await hub.polyhaven.search(
                asset_type=asset_type,
                query=query,
                categories=categories,
                limit=limit,
            )
        except Exception as exc:
            raise ToolError(f"Poly Haven search failed: {exc}") from exc

    @mcp.tool(annotations=_MUTATE)
    async def polyhaven_apply_hdri(
        asset_id: str,
        resolution: Literal["1k", "2k", "4k", "8k"] = "2k",
        file_format: Literal["hdr", "exr"] = "hdr",
        strength: float = 1.0,
        rotation_degrees: float = 0.0,
    ) -> dict[str, Any]:
        """Download (and cache) a Poly Haven HDRI and configure the Blender World shader automatically."""
        try:
            hdri_path = await hub.polyhaven.download_hdri(asset_id, resolution=resolution, file_format=file_format)
        except Exception as exc:
            raise ToolError(f"Failed downloading Poly Haven HDRI {asset_id!r}: {exc}") from exc
        world_res = await rt.invoke(
            "lighting.set_world_hdri",
            {
                "filepath": str(hdri_path),
                "strength": strength,
                "rotation_degrees": rotation_degrees,
            },
            audit=True,
        )
        return {"provider": "polyhaven", "asset_id": asset_id, "cached_path": str(hdri_path), **world_res}

    @mcp.tool(annotations=_MUTATE)
    async def polyhaven_apply_texture(
        asset_id: str,
        resolution: Literal["1k", "2k", "4k"] = "2k",
        material_name: str | None = None,
        assign_to: list[str] | None = None,
    ) -> dict[str, Any]:
        """Download a Poly Haven CC0 PBR texture set, wire albedo/roughness/normal/metallic maps, and optionally assign it."""
        try:
            maps = await hub.polyhaven.download_texture_maps(asset_id, resolution=resolution)
        except Exception as exc:
            raise ToolError(f"Failed downloading Poly Haven texture {asset_id!r}: {exc}") from exc
        wired = await _wire_pbr_maps(
            rt,
            material_name=material_name or f"PH_{asset_id}",
            maps=maps,
            assign_to=assign_to,
        )
        return {"provider": "polyhaven", "asset_id": asset_id, **wired}

    @mcp.tool(annotations=_MUTATE)
    async def polyhaven_import_model(
        asset_id: str,
        resolution: Literal["1k", "2k", "4k"] = "2k",
        collection: str | None = None,
        align_ground: bool = True,
    ) -> dict[str, Any]:
        """Download a Poly Haven CC0 glTF 3D model into the local cache and import it into Blender."""
        try:
            model_path = await hub.polyhaven.download_model(asset_id, resolution=resolution)
        except Exception as exc:
            raise ToolError(f"Failed downloading Poly Haven model {asset_id!r}: {exc}") from exc
        imp = await _import_and_normalize_model(rt, model_path, collection=collection, align_ground=align_ground)
        return {"provider": "polyhaven", "asset_id": asset_id, **imp}

    # ---- ambientCG (CC0, no key needed) ----
    @mcp.tool(annotations=_READ_ONLY)
    async def ambientcg_search(query: str = "", limit: int = 20) -> dict[str, Any]:
        """Search ambientCG's free CC0 PBR material library (no API key required)."""
        try:
            return await hub.ambientcg.search(query=query, limit=limit)
        except Exception as exc:
            raise ToolError(f"ambientCG search failed: {exc}") from exc

    @mcp.tool(annotations=_MUTATE)
    async def ambientcg_apply_material(
        asset_id: str,
        resolution: str = "2K-PNG",
        material_name: str | None = None,
        assign_to: list[str] | None = None,
    ) -> dict[str, Any]:
        """Download an ambientCG CC0 material pack, wire its PBR maps into Principled BSDF, and optionally assign it."""
        try:
            maps = await hub.ambientcg.download_material_maps(asset_id, resolution=resolution)
        except Exception as exc:
            raise ToolError(f"Failed downloading ambientCG material {asset_id!r}: {exc}") from exc
        wired = await _wire_pbr_maps(
            rt,
            material_name=material_name or f"ACG_{asset_id}",
            maps=maps,
            assign_to=assign_to,
        )
        return {"provider": "ambientcg", "asset_id": asset_id, **wired}

    # ---- Sketchfab ----
    @mcp.tool(annotations=_READ_ONLY)
    async def sketchfab_search(
        query: str,
        max_face_count: int | None = None,
        animated: bool | None = None,
        categories: list[str] | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        """Search downloadable 3D models on Sketchfab (downloads require `SKETCHFAB_API_KEY`)."""
        try:
            return await hub.sketchfab.search(
                query,
                max_face_count=max_face_count,
                animated=animated,
                categories=categories,
                limit=limit,
            )
        except Exception as exc:
            raise ToolError(f"Sketchfab search failed: {exc}") from exc

    @mcp.tool(annotations=_MUTATE)
    async def sketchfab_import(
        uid: str,
        collection: str | None = None,
        align_ground: bool = True,
    ) -> dict[str, Any]:
        """Download a Sketchfab glTF model (requires `SKETCHFAB_API_KEY`), cache it, and import it into Blender."""
        try:
            model_path = await hub.sketchfab.download_model(uid)
        except Exception as exc:
            raise ToolError(f"Sketchfab download failed for {uid!r}: {exc}") from exc
        imp = await _import_and_normalize_model(rt, model_path, collection=collection, align_ground=align_ground)
        return {"provider": "sketchfab", "uid": uid, **imp}

    # ---- Unified AI 3D Generators ----
    @mcp.tool(annotations=_READ_ONLY)
    async def ai3d_list_providers() -> dict[str, Any]:
        """List all registered AI 3D generation providers and show which ones are currently configured."""
        return {"providers": hub.ai3d.list_providers()}

    @mcp.tool(annotations=_MUTATE)
    async def ai3d_generate(
        prompt: str | None = None,
        image_path: str | None = None,
        provider: str | None = None,
        collection: str | None = None,
        align_ground: bool = True,
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        """Generate a 3D GLB model from text or an image using a configured AI 3D provider and import it into Blender.

        Supports Hyper3D Rodin, Hunyuan3D (cloud or local self-hosted), Tripo3D, Meshy, TRELLIS, and custom plugins.
        """
        validated_img: Path | None = None
        if image_path:
            try:
                validated_img = rt.path_guard.validate(image_path, must_exist=True)
            except BridgeError as err:
                raise ToolError(err.format_for_agent()) from err

        async def _progress(fraction: float, message: str) -> None:
            if ctx is not None:
                with contextlib.suppress(Exception):
                    await ctx.report_progress(progress=fraction * 100.0, total=100.0, message=message)

        try:
            prov, glb_path = await hub.ai3d.generate(
                prompt=prompt,
                image_path=validated_img,
                provider_name=provider,
                on_progress=_progress,
            )
        except Exception as exc:
            raise ToolError(f"AI 3D generation failed: {exc}") from exc

        imp = await _import_and_normalize_model(rt, glb_path, collection=collection, align_ground=align_ground)
        return {"provider": prov.name, "prompt": prompt, **imp}

    # ---- Local Asset Cache ----
    @mcp.tool(annotations=_READ_ONLY)
    async def asset_cache_status() -> dict[str, Any]:
        """Inspect local asset cache location, total size, and cached file counts by provider."""
        return hub.cache.status()

    @mcp.tool(annotations=_DESTRUCTIVE)
    async def asset_cache_clear(provider: str | None = None) -> dict[str, Any]:
        """Clear cached downloaded assets (all providers or a specific provider like 'polyhaven')."""
        return hub.cache.clear(provider)
