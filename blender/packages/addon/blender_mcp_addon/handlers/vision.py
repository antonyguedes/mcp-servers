# SPDX-License-Identifier: GPL-3.0-or-later
"""Visual feedback handlers: auto-framed viewport capture, multiview, and render preview.

Works reliably in both GUI and headless (`--background`) Blender by rendering
via a cleanly managed temporary camera and restoring all scene settings afterward.
"""

from __future__ import annotations

import base64
import math
import os
import tempfile
from typing import Any

import bpy  # type: ignore[import-not-found]
from mathutils import Vector  # type: ignore[import-not-found]

from ..compat import get_object_bbox_world, resolve_render_engine
from ..dispatcher import Dispatcher, ExecutionContext
from ..state import resolve_object
from ..wire import AddonError, BridgeErrorCode

# Unit direction vectors from target center toward camera
VIEW_DIRECTIONS: dict[str, tuple[float, float, float]] = {
    "iso": (1.0, -1.0, 0.75),
    "iso_back": (-1.0, 1.0, 0.75),
    "front": (0.0, -1.0, 0.0),
    "back": (0.0, 1.0, 0.0),
    "right": (1.0, 0.0, 0.0),
    "left": (-1.0, 0.0, 0.0),
    "top": (0.0, -0.001, 1.0),
    "bottom": (0.0, -0.001, -1.0),
}


def _compute_framing(target_refs: list[str] | None) -> tuple[Vector, float]:
    """Compute (center, bounding_radius) for target objects or all visible geometry."""
    objs: list[Any] = []
    if target_refs:
        for ref in target_refs:
            obj = resolve_object(str(ref))
            assert obj is not None
            objs.append(obj)
    else:
        for obj in bpy.context.scene.objects:
            if obj.hide_viewport or obj.hide_render:
                continue
            if obj.type in ("MESH", "CURVE", "SURFACE", "META", "FONT", "GPENCIL", "GREASEPENCIL"):
                objs.append(obj)

    if not objs:
        return Vector((0.0, 0.0, 0.0)), 2.0

    mins = [float("inf"), float("inf"), float("inf")]
    maxs = [float("-inf"), float("-inf"), float("-inf")]
    for obj in objs:
        bb = get_object_bbox_world(obj)
        for i in range(3):
            mins[i] = min(mins[i], bb["min"][i])
            maxs[i] = max(maxs[i], bb["max"][i])

    center = Vector((mins[i] + maxs[i]) * 0.5 for i in range(3))
    extents = Vector(maxs[i] - mins[i] for i in range(3))
    radius = max(0.25, extents.length * 0.5)
    return center, radius


def _point_camera_at(cam_obj: Any, target: Vector) -> None:
    direction = target - cam_obj.location
    if direction.length < 1e-6:
        direction = Vector((0.0, 1.0, 0.0))
    cam_obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


def _render_single_view(
    *,
    view: str,
    width: int,
    height: int,
    shading: str,
    samples: int,
    target_objects: list[str] | None,
    camera_location: list[float] | None,
    look_at: list[float] | None,
    lens: float,
    margin: float,
) -> dict[str, Any]:
    scene = bpy.context.scene
    render = scene.render

    # Save scene state to restore cleanly
    saved_camera = scene.camera
    saved_engine = render.engine
    saved_res_x = render.resolution_x
    saved_res_y = render.resolution_y
    saved_res_pct = render.resolution_percentage
    saved_filepath = render.filepath
    saved_format = render.image_settings.file_format
    saved_cycles_samples = getattr(scene.cycles, "samples", None) if hasattr(scene, "cycles") else None
    saved_cycles_device = getattr(scene.cycles, "device", None) if hasattr(scene, "cycles") else None

    tmp_cam_data = None
    tmp_cam_obj = None
    fd, tmp_path = tempfile.mkstemp(prefix="blender_mcp_view_", suffix=".png")
    os.close(fd)

    try:
        use_active = view == "active_camera" and scene.camera is not None
        if use_active:
            cam_obj = scene.camera
            cam_loc = [round(float(v), 4) for v in cam_obj.location]
            cam_target = None
        else:
            center, radius = _compute_framing(target_objects)
            target_pt = (
                Vector((float(look_at[0]), float(look_at[1]), float(look_at[2])))
                if look_at is not None
                else center
            )

            tmp_cam_data = bpy.data.cameras.new("_blender_mcp_tmp_cam")
            tmp_cam_data.lens = lens
            tmp_cam_data.clip_start = 0.01
            tmp_cam_data.clip_end = max(1000.0, radius * 50.0)
            tmp_cam_obj = bpy.data.objects.new("_blender_mcp_tmp_cam", tmp_cam_data)
            scene.collection.objects.link(tmp_cam_obj)

            if camera_location is not None:
                tmp_cam_obj.location = Vector(
                    (float(camera_location[0]), float(camera_location[1]), float(camera_location[2]))
                )
            else:
                dir_tuple = VIEW_DIRECTIONS.get(view, VIEW_DIRECTIONS["iso"])
                direction = Vector(dir_tuple).normalized()
                fov = 2.0 * math.atan(tmp_cam_data.sensor_width / (2.0 * tmp_cam_data.lens))
                dist = (radius / max(0.1, math.sin(fov * 0.5))) * margin
                tmp_cam_obj.location = target_pt + direction * dist

            _point_camera_at(tmp_cam_obj, target_pt)
            scene.camera = tmp_cam_obj
            cam_loc = [round(float(v), 4) for v in tmp_cam_obj.location]
            cam_target = [round(float(v), 4) for v in target_pt]

        # Select render engine
        shading_key = shading.strip().lower()
        if shading_key in ("solid", "workbench"):
            engine_id = resolve_render_engine("workbench")
        elif shading_key == "cycles":
            engine_id = resolve_render_engine("cycles")
        else:
            engine_id = resolve_render_engine("eevee")

        render.engine = engine_id
        render.resolution_x = width
        render.resolution_y = height
        render.resolution_percentage = 100
        render.image_settings.file_format = "PNG"
        render.filepath = tmp_path

        if engine_id == "CYCLES" and hasattr(scene, "cycles"):
            scene.cycles.samples = max(1, samples)
            scene.cycles.device = "CPU"
        elif engine_id == "BLENDER_WORKBENCH" and hasattr(scene, "display"):
            try:
                scene.display.shading.light = "STUDIO"
                scene.display.shading.color_type = "MATERIAL"
            except Exception:
                pass

        bpy.ops.render.render(write_still=True)

        with open(tmp_path, "rb") as fh:
            img_bytes = fh.read()

        return {
            "view": view,
            "engine": engine_id,
            "width": width,
            "height": height,
            "mime_type": "image/png",
            "camera_location": cam_loc,
            "look_at": cam_target,
            "image_base64": base64.b64encode(img_bytes).decode("ascii"),
        }
    finally:
        scene.camera = saved_camera
        render.engine = saved_engine
        render.resolution_x = saved_res_x
        render.resolution_y = saved_res_y
        render.resolution_percentage = saved_res_pct
        render.filepath = saved_filepath
        render.image_settings.file_format = saved_format
        if saved_cycles_samples is not None and hasattr(scene, "cycles"):
            scene.cycles.samples = saved_cycles_samples
        if saved_cycles_device is not None and hasattr(scene, "cycles"):
            scene.cycles.device = saved_cycles_device
        if tmp_cam_obj is not None:
            bpy.data.objects.remove(tmp_cam_obj, do_unlink=True)
        if tmp_cam_data is not None and tmp_cam_data.users == 0:
            bpy.data.cameras.remove(tmp_cam_data)
        try:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
        except OSError:
            pass


def capture_viewport(params: dict[str, Any], _ctx: ExecutionContext) -> dict[str, Any]:
    view = str(params.get("view", "iso")).strip().lower()
    if view != "active_camera" and view not in VIEW_DIRECTIONS:
        raise AddonError(
            BridgeErrorCode.INVALID_PARAMS,
            f"Unsupported view preset {view!r}.",
            suggestions=[*sorted(VIEW_DIRECTIONS.keys()), "active_camera"],
        )
    width = max(64, min(2048, int(params.get("width", 768))))
    height = max(64, min(2048, int(params.get("height", 512))))
    shading = str(params.get("shading", "eevee"))
    samples = max(1, min(128, int(params.get("samples", 16))))
    lens = float(params.get("lens", 50.0))
    margin = float(params.get("margin", 1.25))

    return _render_single_view(
        view=view,
        width=width,
        height=height,
        shading=shading,
        samples=samples,
        target_objects=params.get("target_objects"),
        camera_location=params.get("camera_location"),
        look_at=params.get("look_at"),
        lens=lens,
        margin=margin,
    )


def capture_multiview(params: dict[str, Any], _ctx: ExecutionContext) -> dict[str, Any]:
    views = params.get("views") or ["iso", "front", "right", "top"]
    if not isinstance(views, list) or not (1 <= len(views) <= 4):
        raise AddonError(BridgeErrorCode.INVALID_PARAMS, "'views' must be a list of 1 to 4 view names.")
    tile_size = max(64, min(1024, int(params.get("tile_size", 384))))
    shading = str(params.get("shading", "workbench"))
    samples = max(1, min(64, int(params.get("samples", 8))))
    target_objects = params.get("target_objects")

    rendered: list[dict[str, Any]] = []
    for v in views:
        v_key = str(v).strip().lower()
        if v_key != "active_camera" and v_key not in VIEW_DIRECTIONS:
            raise AddonError(
                BridgeErrorCode.INVALID_PARAMS,
                f"Unsupported view preset {v_key!r}.",
                suggestions=[*sorted(VIEW_DIRECTIONS.keys()), "active_camera"],
            )
        rendered.append(
            _render_single_view(
                view=v_key,
                width=tile_size,
                height=tile_size,
                shading=shading,
                samples=samples,
                target_objects=target_objects,
                camera_location=None,
                look_at=None,
                lens=50.0,
                margin=1.25,
            )
        )

    return {"tile_size": tile_size, "views": rendered}


def render_preview(params: dict[str, Any], _ctx: ExecutionContext) -> dict[str, Any]:
    width = max(64, min(2048, int(params.get("width", 640))))
    height = max(64, min(2048, int(params.get("height", 360))))
    engine = str(params.get("engine", "eevee"))
    samples = max(1, min(128, int(params.get("samples", 16))))
    view = "active_camera" if bpy.context.scene.camera is not None else "iso"
    return _render_single_view(
        view=view,
        width=width,
        height=height,
        shading=engine,
        samples=samples,
        target_objects=None,
        camera_location=None,
        look_at=None,
        lens=50.0,
        margin=1.25,
    )


def register(dispatcher: Dispatcher) -> None:
    dispatcher.register("vision.capture_viewport", capture_viewport, mutating=False)
    dispatcher.register("vision.capture_multiview", capture_multiview, mutating=False)
    dispatcher.register("vision.render_preview", render_preview, mutating=False)
