# SPDX-License-Identifier: MIT
"""Visual feedback MCP tools returning inline PNG images for multimodal inspection."""

from __future__ import annotations

import base64
import json
from typing import Literal

from mcp.server.mcpserver import MCPServer
from mcp.types import ImageContent, TextContent, ToolAnnotations

from blender_mcp.tools import ToolRuntime
from blender_mcp.vision_utils import stitch_multiview_grid

_READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True)


def register(mcp: MCPServer, rt: ToolRuntime) -> None:
    @mcp.tool(annotations=_READ_ONLY)
    async def capture_viewport(
        view: Literal[
            "iso",
            "iso_back",
            "front",
            "back",
            "right",
            "left",
            "top",
            "bottom",
            "active_camera",
        ] = "iso",
        target_objects: list[str] | None = None,
        width: int = 768,
        height: int = 512,
        shading: Literal["workbench", "solid", "eevee", "cycles"] = "workbench",
        samples: int = 16,
        camera_location: list[float] | None = None,
        look_at: list[float] | None = None,
        lens: float = 50.0,
        margin: float = 1.25,
    ) -> list[TextContent | ImageContent]:
        """Capture an auto-framed image of the scene or target objects so you can visually inspect your work.

        Use `shading="workbench"` for fast geometry inspection (lit even with no lights in scene)
        or `shading="eevee"` / `"cycles"` to inspect materials and lighting.
        """
        res = await rt.invoke(
            "vision.capture_viewport",
            {
                "view": view,
                "target_objects": target_objects,
                "width": width,
                "height": height,
                "shading": shading,
                "samples": samples,
                "camera_location": camera_location,
                "look_at": look_at,
                "lens": lens,
                "margin": margin,
            },
        )
        b64 = res.pop("image_base64")
        return [
            TextContent(type="text", text=json.dumps(res)),
            ImageContent(type="image", data=b64, mime_type="image/png"),
        ]

    @mcp.tool(annotations=_READ_ONLY)
    async def capture_multiview(
        views: list[str] | None = None,
        target_objects: list[str] | None = None,
        tile_size: int = 384,
        shading: Literal["workbench", "solid", "eevee", "cycles"] = "workbench",
        samples: int = 8,
    ) -> list[TextContent | ImageContent]:
        """Capture a labeled 2x2 contact sheet (default: ISO, FRONT, RIGHT, TOP) for 3D spatial verification."""
        res = await rt.invoke(
            "vision.capture_multiview",
            {
                "views": views or ["iso", "front", "right", "top"],
                "target_objects": target_objects,
                "tile_size": tile_size,
                "shading": shading,
                "samples": samples,
            },
        )
        grid_bytes = stitch_multiview_grid(res["views"], tile_size=int(res["tile_size"]))
        grid_b64 = base64.b64encode(grid_bytes).decode("ascii")
        meta = {
            "views": [v["view"] for v in res["views"]],
            "tile_size": res["tile_size"],
            "engine": res["views"][0]["engine"] if res["views"] else None,
        }
        return [
            TextContent(type="text", text=json.dumps(meta)),
            ImageContent(type="image", data=grid_b64, mime_type="image/png"),
        ]

    @mcp.tool(annotations=_READ_ONLY)
    async def render_preview(
        width: int = 640,
        height: int = 360,
        engine: Literal["eevee", "cycles", "workbench"] = "eevee",
        samples: int = 16,
    ) -> list[TextContent | ImageContent]:
        """Render a quick preview from the active scene camera (or an auto-framed ISO angle if none exists)."""
        res = await rt.invoke(
            "vision.render_preview",
            {
                "width": width,
                "height": height,
                "engine": engine,
                "samples": samples,
            },
        )
        b64 = res.pop("image_base64")
        return [
            TextContent(type="text", text=json.dumps(res)),
            ImageContent(type="image", data=b64, mime_type="image/png"),
        ]
