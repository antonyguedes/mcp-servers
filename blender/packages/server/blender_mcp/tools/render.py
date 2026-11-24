# SPDX-License-Identifier: MIT
"""Render configuration and asynchronous render/job MCP tools with progress & cancellation."""

from __future__ import annotations

import json
from typing import Any, Literal

from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ImageContent, TextContent, ToolAnnotations

from blender_mcp.tools import ToolRuntime, wait_for_job
from blender_mcp_protocol import BridgeError

_READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True)
_MUTATE = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=True)


def _guard_path(rt: ToolRuntime, filepath: str) -> str:
    try:
        return str(rt.path_guard.validate(filepath, must_exist=False))
    except BridgeError as err:
        raise ToolError(err.format_for_agent()) from err


def register(mcp: MCPServer, rt: ToolRuntime) -> None:
    @mcp.tool(annotations=_MUTATE)
    async def configure_render(
        engine: Literal["cycles", "eevee", "workbench"] | None = None,
        resolution_x: int | None = None,
        resolution_y: int | None = None,
        resolution_percentage: int | None = None,
        samples: int | None = None,
        device: Literal["CPU", "GPU"] | None = None,
        use_denoising: bool | None = None,
        film_transparent: bool | None = None,
        file_format: Literal["PNG", "JPEG", "OPEN_EXR", "WEBP"] | None = None,
        output_path: str | None = None,
    ) -> dict[str, Any]:
        """Configure scene render engine (Cycles/EEVEE/Workbench), resolution, samples, device, and output settings."""
        safe_out = _guard_path(rt, output_path) if output_path else None
        return await rt.invoke(
            "render.configure",
            {
                "engine": engine,
                "resolution_x": resolution_x,
                "resolution_y": resolution_y,
                "resolution_percentage": resolution_percentage,
                "samples": samples,
                "device": device,
                "use_denoising": use_denoising,
                "film_transparent": film_transparent,
                "file_format": file_format,
                "output_path": safe_out,
            },
            audit=True,
        )

    @mcp.tool(annotations=_MUTATE)
    async def render_still(
        output_path: str,
        frame: int | None = None,
        engine: Literal["cycles", "eevee", "workbench"] | None = None,
        samples: int | None = None,
        width: int | None = None,
        height: int | None = None,
        wait: bool = True,
        return_image: bool = False,
        ctx: Context | None = None,
    ) -> list[TextContent | ImageContent] | dict[str, Any]:
        """Render a single frame to `output_path` via the cooperative JobManager.

        Set `wait=False` to return the `job_id` immediately for async tracking.
        Set `return_image=True` (with `wait=True`) to include the rendered PNG inline for visual inspection.
        """
        safe_out = _guard_path(rt, output_path)
        job = await rt.invoke(
            "render.render_still",
            {
                "output_path": safe_out,
                "frame": frame,
                "engine": engine,
                "samples": samples,
                "width": width,
                "height": height,
                "return_image": return_image and wait,
            },
            audit=True,
        )
        if not wait:
            return job
        done = await wait_for_job(rt, job["job_id"], ctx)
        res = done.get("result") or {}
        if return_image and isinstance(res, dict) and "image_base64" in res:
            b64 = res.pop("image_base64")
            return [
                TextContent(type="text", text=json.dumps(done)),
                ImageContent(type="image", data=b64, mime_type="image/png"),
            ]
        return done

    @mcp.tool(annotations=_MUTATE)
    async def render_animation(
        output_dir: str,
        frame_start: int | None = None,
        frame_end: int | None = None,
        frame_step: int = 1,
        filename_prefix: str = "frame_",
        engine: Literal["cycles", "eevee", "workbench"] | None = None,
        samples: int | None = None,
        width: int | None = None,
        height: int | None = None,
        wait: bool = True,
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        """Render an animation frame-by-frame to `output_dir` with real-time progress and cancellation support.

        When `wait=False`, returns `job_id` immediately so you can poll `get_job_status` or stop early with `cancel_job`.
        """
        safe_dir = _guard_path(rt, output_dir)
        params: dict[str, Any] = {
            "output_dir": safe_dir,
            "frame_step": frame_step,
            "filename_prefix": filename_prefix,
            "engine": engine,
            "samples": samples,
            "width": width,
            "height": height,
        }
        if frame_start is not None:
            params["frame_start"] = frame_start
        if frame_end is not None:
            params["frame_end"] = frame_end
        job = await rt.invoke("render.render_animation", params, audit=True)
        if not wait:
            return job
        return await wait_for_job(rt, job["job_id"], ctx)

    @mcp.tool(annotations=_READ_ONLY)
    async def get_job_status(job_id: str) -> dict[str, Any]:
        """Query the live status, progress (0..1), and result of an async render or physics bake job."""
        return await rt.invoke("jobs.get_status", {"job_id": job_id})

    @mcp.tool(annotations=_READ_ONLY)
    async def list_jobs(limit: int = 30) -> dict[str, Any]:
        """List recent and currently active background Blender jobs."""
        return await rt.invoke("jobs.list_jobs", {"limit": limit})

    @mcp.tool(annotations=_MUTATE)
    async def cancel_job(job_id: str) -> dict[str, Any]:
        """Cancel a queued or running render/bake job immediately between frames."""
        return await rt.invoke("jobs.cancel", {"job_id": job_id}, audit=True)
