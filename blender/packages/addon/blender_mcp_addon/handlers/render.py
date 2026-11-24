# SPDX-License-Identifier: GPL-3.0-or-later
"""Render configuration and cooperative asynchronous still/animation render jobs."""

from __future__ import annotations

import base64
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import bpy  # type: ignore[import-not-found]

from ..compat import resolve_render_engine
from ..dispatcher import Dispatcher, ExecutionContext
from ..jobs import JobRecord
from ..wire import AddonError, BridgeErrorCode


def configure_render(params: dict[str, Any], _ctx: ExecutionContext) -> dict[str, Any]:
    scene = bpy.context.scene
    render = scene.render

    if params.get("engine") is not None:
        render.engine = resolve_render_engine(str(params["engine"]))
    if params.get("resolution_x") is not None:
        render.resolution_x = max(16, min(8192, int(params["resolution_x"])))
    if params.get("resolution_y") is not None:
        render.resolution_y = max(16, min(8192, int(params["resolution_y"])))
    if params.get("resolution_percentage") is not None:
        render.resolution_percentage = max(10, min(200, int(params["resolution_percentage"])))
    if params.get("film_transparent") is not None:
        render.film_transparent = bool(params["film_transparent"])
    if params.get("file_format") is not None:
        render.image_settings.file_format = str(params["file_format"]).upper()
    if params.get("output_path") is not None:
        render.filepath = str(params["output_path"])

    samples = params.get("samples")
    if samples is not None:
        s_int = max(1, int(samples))
        if render.engine == "CYCLES" and hasattr(scene, "cycles"):
            scene.cycles.samples = s_int
        elif hasattr(scene, "eevee"):
            if hasattr(scene.eevee, "taa_render_samples"):
                scene.eevee.taa_render_samples = s_int
            elif hasattr(scene.eevee, "samples"):
                scene.eevee.samples = s_int

    if render.engine == "CYCLES" and hasattr(scene, "cycles"):
        if params.get("device") is not None:
            scene.cycles.device = str(params["device"]).upper()
        if params.get("use_denoising") is not None:
            scene.cycles.use_denoising = bool(params["use_denoising"])

    return {
        "engine": render.engine,
        "resolution": [render.resolution_x, render.resolution_y],
        "resolution_percentage": render.resolution_percentage,
        "film_transparent": render.film_transparent,
        "file_format": render.image_settings.file_format,
        "filepath": render.filepath,
        "cycles_samples": getattr(scene.cycles, "samples", None) if hasattr(scene, "cycles") else None,
        "cycles_device": getattr(scene.cycles, "device", None) if hasattr(scene, "cycles") else None,
    }


def render_still_job(params: dict[str, Any], ctx: ExecutionContext) -> dict[str, Any]:
    """Submit a tracked Job rendering a single frame to disk."""
    raw_out = str(params.get("output_path", "")).strip()
    if not raw_out:
        raise AddonError(BridgeErrorCode.INVALID_PARAMS, "'output_path' is required.")
    out_path = Path(raw_out).expanduser().resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    frame = params.get("frame")
    engine = params.get("engine")
    samples = params.get("samples")
    width = params.get("width")
    height = params.get("height")
    return_image = bool(params.get("return_image", False))

    def _stepper(job: JobRecord) -> Iterator[None]:
        scene = bpy.context.scene
        render = scene.render
        saved = {
            "engine": render.engine,
            "res_x": render.resolution_x,
            "res_y": render.resolution_y,
            "filepath": render.filepath,
            "frame": scene.frame_current,
            "cycles_samples": getattr(scene.cycles, "samples", None) if hasattr(scene, "cycles") else None,
        }
        try:
            job.update_progress(0, 1, f"Rendering still to {out_path.name}")
            yield
            if job.is_cancelled:
                return
            if engine:
                render.engine = resolve_render_engine(str(engine))
            if width:
                render.resolution_x = max(16, min(8192, int(width)))
            if height:
                render.resolution_y = max(16, min(8192, int(height)))
            if samples and render.engine == "CYCLES" and hasattr(scene, "cycles"):
                scene.cycles.samples = max(1, int(samples))
            if frame is not None:
                scene.frame_set(int(frame))
            render.filepath = str(out_path)

            t0 = time.perf_counter()
            bpy.ops.render.render(write_still=True)
            elapsed = time.perf_counter() - t0

            res: dict[str, Any] = {
                "filepath": str(out_path),
                "exists": out_path.is_file(),
                "size_bytes": out_path.stat().st_size if out_path.is_file() else 0,
                "width": render.resolution_x,
                "height": render.resolution_y,
                "engine": render.engine,
                "frame": scene.frame_current,
                "render_time_sec": round(elapsed, 3),
            }
            if return_image and out_path.is_file():
                res["image_base64"] = base64.b64encode(out_path.read_bytes()).decode("ascii")
            job.result = res
            job.update_progress(1, 1, f"Rendered still ({elapsed:.2f}s)")
        finally:
            render.engine = saved["engine"]
            render.resolution_x = saved["res_x"]
            render.resolution_y = saved["res_y"]
            render.filepath = saved["filepath"]
            scene.frame_set(saved["frame"])
            if saved["cycles_samples"] is not None and hasattr(scene, "cycles"):
                scene.cycles.samples = saved["cycles_samples"]

    rec = ctx.jobs.submit(
        "render.still",
        _stepper,
        total_steps=1,
        message=f"Queued still render -> {out_path.name}",
    )
    return rec.to_dict()


def render_animation_job(params: dict[str, Any], ctx: ExecutionContext) -> dict[str, Any]:
    """Submit a cancellable frame-by-frame animation render job."""
    raw_dir = str(params.get("output_dir", "")).strip()
    if not raw_dir:
        raise AddonError(BridgeErrorCode.INVALID_PARAMS, "'output_dir' is required.")
    out_dir = Path(raw_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    scene = bpy.context.scene
    start = int(params.get("frame_start", scene.frame_start))
    end = int(params.get("frame_end", scene.frame_end))
    step = max(1, int(params.get("frame_step", 1)))
    prefix = str(params.get("filename_prefix", "frame_"))
    engine = params.get("engine")
    samples = params.get("samples")
    width = params.get("width")
    height = params.get("height")

    if end < start:
        raise AddonError(BridgeErrorCode.INVALID_PARAMS, "frame_end must be >= frame_start.")

    frames = list(range(start, end + 1, step))

    def _stepper(job: JobRecord) -> Iterator[None]:
        render = scene.render
        saved = {
            "engine": render.engine,
            "res_x": render.resolution_x,
            "res_y": render.resolution_y,
            "filepath": render.filepath,
            "format": render.image_settings.file_format,
            "frame": scene.frame_current,
            "cycles_samples": getattr(scene.cycles, "samples", None) if hasattr(scene, "cycles") else None,
        }
        rendered_files: list[str] = []
        t0 = time.perf_counter()
        try:
            if engine:
                render.engine = resolve_render_engine(str(engine))
            if width:
                render.resolution_x = max(16, min(8192, int(width)))
            if height:
                render.resolution_y = max(16, min(8192, int(height)))
            if samples and render.engine == "CYCLES" and hasattr(scene, "cycles"):
                scene.cycles.samples = max(1, int(samples))
            render.image_settings.file_format = "PNG"

            for idx, fr in enumerate(frames):
                if job.is_cancelled:
                    break
                scene.frame_set(fr)
                frame_path = out_dir / f"{prefix}{fr:04d}.png"
                render.filepath = str(frame_path)
                bpy.ops.render.render(write_still=True)
                rendered_files.append(str(frame_path))
                job.update_progress(idx + 1, len(frames), f"Rendered frame {fr} ({idx + 1}/{len(frames)})")
                job.result = {
                    "output_dir": str(out_dir),
                    "rendered_count": len(rendered_files),
                    "total_frames": len(frames),
                    "frames": rendered_files,
                    "elapsed_sec": round(time.perf_counter() - t0, 3),
                }
                yield
        finally:
            render.engine = saved["engine"]
            render.resolution_x = saved["res_x"]
            render.resolution_y = saved["res_y"]
            render.filepath = saved["filepath"]
            render.image_settings.file_format = saved["format"]
            scene.frame_set(saved["frame"])
            if saved["cycles_samples"] is not None and hasattr(scene, "cycles"):
                scene.cycles.samples = saved["cycles_samples"]

    rec = ctx.jobs.submit(
        "render.animation",
        _stepper,
        total_steps=len(frames),
        message=f"Queued animation render ({len(frames)} frames)",
    )
    return rec.to_dict()


def register(dispatcher: Dispatcher) -> None:
    dispatcher.register("render.configure", configure_render)
    dispatcher.register("render.render_still", render_still_job, mutating=False)
    dispatcher.register("render.render_animation", render_animation_job, mutating=False)
