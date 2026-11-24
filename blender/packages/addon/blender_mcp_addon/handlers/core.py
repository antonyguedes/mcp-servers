# SPDX-License-Identifier: GPL-3.0-or-later
"""Core scene inspection and selection handlers."""

from __future__ import annotations

import math
import sys
from typing import Any

import bpy  # type: ignore[import-not-found]

from ..compat import detect_capabilities, get_object_bbox_world
from ..dispatcher import Dispatcher, ExecutionContext
from ..state import ensure_object_uid, resolve_collection, resolve_object
from ..wire import ADDON_VERSION, PROTOCOL_VERSION, AddonError, BridgeErrorCode


def _vec_round(vec: Any, ndigits: int = 4) -> list[float]:
    return [round(float(v), ndigits) for v in vec]


def _euler_deg(euler: Any) -> list[float]:
    return [round(math.degrees(float(a)), 3) for a in euler]


def get_blender_info(_params: dict[str, Any], ctx: ExecutionContext) -> dict[str, Any]:
    scene = bpy.context.scene
    return {
        "protocol_version": PROTOCOL_VERSION,
        "addon_version": ADDON_VERSION,
        "blender_version": list(bpy.app.version),
        "blender_version_string": bpy.app.version_string,
        "python_version": sys.version.split()[0],
        "filepath": bpy.data.filepath,
        "scene_name": scene.name,
        "object_count": len(bpy.data.objects),
        "capabilities": detect_capabilities(allow_python=ctx.allow_python),
    }


def _collection_tree(col: Any, depth: int = 0) -> dict[str, Any]:
    return {
        "name": col.name,
        "object_count": len(col.objects),
        "children": [_collection_tree(c, depth + 1) for c in col.children] if depth < 6 else [],
    }


def get_scene_summary(_params: dict[str, Any], _ctx: ExecutionContext) -> dict[str, Any]:
    scene = bpy.context.scene
    type_counts: dict[str, int] = {}
    for obj in scene.objects:
        type_counts[obj.type] = type_counts.get(obj.type, 0) + 1

    active_obj = bpy.context.view_layer.objects.active
    selected = [o.name for o in bpy.context.selected_objects]

    return {
        "scene_name": scene.name,
        "filepath": bpy.data.filepath,
        "unit_system": scene.unit_settings.system,
        "scale_length": scene.unit_settings.scale_length,
        "render_engine": scene.render.engine,
        "resolution": [scene.render.resolution_x, scene.render.resolution_y],
        "frame_current": scene.frame_current,
        "frame_start": scene.frame_start,
        "frame_end": scene.frame_end,
        "fps": scene.render.fps,
        "active_camera": scene.camera.name if scene.camera else None,
        "active_object": active_obj.name if active_obj else None,
        "selected_objects": selected,
        "object_count": len(scene.objects),
        "objects_by_type": type_counts,
        "material_count": len(bpy.data.materials),
        "collection_tree": _collection_tree(scene.collection),
        "world": scene.world.name if scene.world else None,
    }


def list_objects(params: dict[str, Any], _ctx: ExecutionContext) -> dict[str, Any]:
    object_type = params.get("object_type")
    collection_name = params.get("collection")
    name_contains = params.get("name_contains")
    offset = max(0, int(params.get("offset", 0)))
    limit = min(500, max(1, int(params.get("limit", 100))))

    if collection_name:
        col = resolve_collection(str(collection_name))
        pool = list(col.all_objects)
    else:
        pool = list(bpy.context.scene.objects)

    filtered: list[Any] = []
    for obj in pool:
        if object_type and obj.type != str(object_type).upper():
            continue
        if name_contains and str(name_contains).lower() not in obj.name.lower():
            continue
        filtered.append(obj)

    total = len(filtered)
    page = filtered[offset : offset + limit]

    items: list[dict[str, Any]] = []
    for obj in page:
        uid = ensure_object_uid(obj)
        items.append(
            {
                "uid": uid,
                "name": obj.name,
                "type": obj.type,
                "location": _vec_round(obj.location),
                "rotation_degrees": _euler_deg(obj.rotation_euler),
                "scale": _vec_round(obj.scale),
                "dimensions": _vec_round(obj.dimensions),
                "visible": not obj.hide_viewport,
                "parent": obj.parent.name if obj.parent else None,
                "materials": [s.material.name for s in obj.material_slots if s.material],
            }
        )

    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "has_more": (offset + len(items)) < total,
        "objects": items,
    }


def get_object_details(params: dict[str, Any], _ctx: ExecutionContext) -> dict[str, Any]:
    ref = str(params.get("object", ""))
    obj = resolve_object(ref)
    assert obj is not None
    uid = ensure_object_uid(obj)

    details: dict[str, Any] = {
        "uid": uid,
        "name": obj.name,
        "type": obj.type,
        "location": _vec_round(obj.location),
        "rotation_degrees": _euler_deg(obj.rotation_euler),
        "scale": _vec_round(obj.scale),
        "dimensions": _vec_round(obj.dimensions),
        "bbox_world": get_object_bbox_world(obj),
        "visible_viewport": not obj.hide_viewport,
        "visible_render": not obj.hide_render,
        "parent": obj.parent.name if obj.parent else None,
        "children": [c.name for c in obj.children],
        "collections": [c.name for c in obj.users_collection],
        "materials": [
            {"slot": idx, "name": s.material.name if s.material else None}
            for idx, s in enumerate(obj.material_slots)
        ],
        "modifiers": [
            {"name": m.name, "type": m.type, "show_viewport": m.show_viewport}
            for m in obj.modifiers
        ],
    }

    if obj.type == "MESH" and obj.data is not None:
        mesh = obj.data
        details["mesh"] = {
            "name": mesh.name,
            "vertices": len(mesh.vertices),
            "edges": len(mesh.edges),
            "polygons": len(mesh.polygons),
            "uv_layers": [uv.name for uv in mesh.uv_layers],
        }
    elif obj.type == "LIGHT" and obj.data is not None:
        light = obj.data
        details["light"] = {
            "type": light.type,
            "energy": round(float(light.energy), 4),
            "color": _vec_round(light.color),
        }
    elif obj.type == "CAMERA" and obj.data is not None:
        cam = obj.data
        details["camera"] = {
            "type": cam.type,
            "lens": round(float(cam.lens), 3),
            "clip_start": round(float(cam.clip_start), 4),
            "clip_end": round(float(cam.clip_end), 2),
        }

    custom_props: dict[str, Any] = {}
    for k in obj.keys():  # noqa: SIM118  # Blender ID objects require .keys()
        if k.startswith("_") or k == "blender_mcp_uid":
            continue
        v = obj[k]
        if isinstance(v, (int, float, str, bool)):
            custom_props[k] = v
    if custom_props:
        details["custom_properties"] = custom_props

    return details


def select_objects(params: dict[str, Any], _ctx: ExecutionContext) -> dict[str, Any]:
    names = params.get("objects") or []
    extend = bool(params.get("extend", False))
    select_all = bool(params.get("select_all", False))
    deselect_all = bool(params.get("deselect_all", False))

    if deselect_all or (not extend and not select_all):
        for o in bpy.context.scene.objects:
            o.select_set(False)

    if select_all:
        for o in bpy.context.scene.objects:
            if not o.hide_viewport:
                o.select_set(True)
    else:
        last = None
        for ref in names:
            obj = resolve_object(str(ref))
            assert obj is not None
            obj.select_set(True)
            last = obj
        if last is not None and not extend:
            bpy.context.view_layer.objects.active = last

    selected = [o.name for o in bpy.context.selected_objects]
    active = bpy.context.view_layer.objects.active
    return {
        "selected": selected,
        "active": active.name if active else None,
    }


def set_active(params: dict[str, Any], _ctx: ExecutionContext) -> dict[str, Any]:
    ref = str(params.get("object", ""))
    obj = resolve_object(ref)
    assert obj is not None
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    return {"active": obj.name, "uid": ensure_object_uid(obj)}


def set_mode(params: dict[str, Any], _ctx: ExecutionContext) -> dict[str, Any]:
    mode = str(params.get("mode", "OBJECT")).upper()
    valid_modes = {
        "OBJECT",
        "EDIT",
        "SCULPT",
        "VERTEX_PAINT",
        "WEIGHT_PAINT",
        "TEXTURE_PAINT",
        "POSE",
    }
    if mode not in valid_modes:
        raise AddonError(
            BridgeErrorCode.INVALID_PARAMS,
            f"Unsupported mode {mode!r}.",
            suggestions=sorted(valid_modes),
        )
    obj_ref = params.get("object")
    if obj_ref:
        obj = resolve_object(str(obj_ref))
        assert obj is not None
        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)

    active = bpy.context.view_layer.objects.active
    if active is None and mode != "OBJECT":
        raise AddonError(
            BridgeErrorCode.INVALID_STATE,
            f"Cannot enter {mode} mode without an active object.",
        )

    if active is not None and active.mode != mode:
        bpy.ops.object.mode_set(mode=mode)

    current = active.mode if active else "OBJECT"
    return {"mode": current, "active": active.name if active else None}


def register(dispatcher: Dispatcher) -> None:
    dispatcher.register("core.get_blender_info", get_blender_info, mutating=False)
    dispatcher.register("core.get_scene_summary", get_scene_summary, mutating=False)
    dispatcher.register("core.list_objects", list_objects, mutating=False)
    dispatcher.register("core.get_object_details", get_object_details, mutating=False)
    dispatcher.register("core.select", select_objects, mutating=False)
    dispatcher.register("core.set_active", set_active, mutating=False)
    dispatcher.register("core.set_mode", set_mode, mutating=False)
