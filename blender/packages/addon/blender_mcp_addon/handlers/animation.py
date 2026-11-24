# SPDX-License-Identifier: GPL-3.0-or-later
"""Animation handlers (Slotted Actions 4.4+/5.x and classic Actions 3.6-4.3)."""

from __future__ import annotations

import math
from typing import Any

import bpy  # type: ignore[import-not-found]
from mathutils import Euler, Vector  # type: ignore[import-not-found]

from ..compat import iter_fcurves
from ..dispatcher import Dispatcher, ExecutionContext
from ..state import resolve_object
from ..wire import AddonError, BridgeErrorCode


def set_frame_range(params: dict[str, Any], _ctx: ExecutionContext) -> dict[str, Any]:
    scene = bpy.context.scene
    if params.get("frame_start") is not None:
        scene.frame_start = int(params["frame_start"])
    if params.get("frame_end") is not None:
        scene.frame_end = int(params["frame_end"])
    if params.get("fps") is not None:
        scene.render.fps = max(1, int(params["fps"]))
    if params.get("frame_current") is not None:
        scene.frame_set(int(params["frame_current"]))
    return {
        "frame_start": scene.frame_start,
        "frame_end": scene.frame_end,
        "frame_current": scene.frame_current,
        "fps": scene.render.fps,
    }


def set_current_frame(params: dict[str, Any], _ctx: ExecutionContext) -> dict[str, Any]:
    frame = int(params.get("frame", 1))
    bpy.context.scene.frame_set(frame)
    return {"frame_current": bpy.context.scene.frame_current}


def _set_property_value(obj: Any, data_path: str, value: Any, *, degrees: bool) -> None:
    if data_path == "location":
        obj.location = Vector((float(value[0]), float(value[1]), float(value[2])))
    elif data_path == "rotation_euler":
        if degrees:
            obj.rotation_euler = Euler(
                (math.radians(float(value[0])), math.radians(float(value[1])), math.radians(float(value[2]))),
                "XYZ",
            )
        else:
            obj.rotation_euler = Euler((float(value[0]), float(value[1]), float(value[2])), "XYZ")
    elif data_path == "scale":
        if isinstance(value, (int, float)):
            s = float(value)
            obj.scale = Vector((s, s, s))
        else:
            obj.scale = Vector((float(value[0]), float(value[1]), float(value[2])))
    else:
        parts = data_path.split(".")
        curr = obj
        for attr in parts[:-1]:
            curr = getattr(curr, attr)
        setattr(curr, parts[-1], value)


def insert_keyframes(params: dict[str, Any], _ctx: ExecutionContext) -> dict[str, Any]:
    obj = resolve_object(str(params.get("object", "")))
    assert obj is not None
    data_path = str(params.get("data_path", "location")).strip()
    keyframes = params.get("keyframes") or []
    degrees = bool(params.get("degrees", True))
    interpolation = params.get("interpolation")
    easing = params.get("easing")

    if not keyframes:
        raise AddonError(BridgeErrorCode.INVALID_PARAMS, "'keyframes' must be a non-empty list of {frame, value}.")

    inserted_frames: list[int] = []
    for kf in keyframes:
        frame = int(kf["frame"])
        if "value" in kf and kf["value"] is not None:
            _set_property_value(obj, data_path, kf["value"], degrees=degrees)
        index = int(kf["index"]) if kf.get("index") is not None else -1
        obj.keyframe_insert(data_path=data_path, index=index, frame=frame)
        inserted_frames.append(frame)

    if interpolation or easing:
        interp_upper = str(interpolation).upper() if interpolation else None
        easing_upper = str(easing).upper() if easing else None
        for fc in iter_fcurves(obj):
            if fc.data_path != data_path:
                continue
            for kp in fc.keyframe_points:
                if round(kp.co.x) in inserted_frames:
                    if interp_upper:
                        kp.interpolation = interp_upper
                    if easing_upper:
                        kp.easing = easing_upper
            fc.update()

    return {
        "object": obj.name,
        "data_path": data_path,
        "frames": inserted_frames,
        "action": obj.animation_data.action.name if (obj.animation_data and obj.animation_data.action) else None,
    }


def delete_keyframes(params: dict[str, Any], _ctx: ExecutionContext) -> dict[str, Any]:
    obj = resolve_object(str(params.get("object", "")))
    assert obj is not None
    data_path = str(params.get("data_path", "location")).strip()
    frames = params.get("frames") or []

    deleted = 0
    if frames:
        for fr in frames:
            try:
                if obj.keyframe_delete(data_path=data_path, frame=int(fr)):
                    deleted += 1
            except RuntimeError:
                pass
    else:
        for fc in iter_fcurves(obj):
            if fc.data_path == data_path:
                for kp in list(fc.keyframe_points):
                    try:
                        if obj.keyframe_delete(data_path=data_path, frame=kp.co.x):
                            deleted += 1
                    except RuntimeError:
                        pass

    return {"object": obj.name, "data_path": data_path, "deleted": deleted}


def set_interpolation(params: dict[str, Any], _ctx: ExecutionContext) -> dict[str, Any]:
    obj = resolve_object(str(params.get("object", "")))
    assert obj is not None
    interpolation = str(params.get("interpolation", "BEZIER")).strip().upper()
    easing = params.get("easing")
    data_path = params.get("data_path")

    updated = 0
    for fc in iter_fcurves(obj):
        if data_path and fc.data_path != str(data_path):
            continue
        for kp in fc.keyframe_points:
            kp.interpolation = interpolation
            if easing:
                kp.easing = str(easing).upper()
            updated += 1
        fc.update()

    return {
        "object": obj.name,
        "interpolation": interpolation,
        "updated_keyframes": updated,
    }


def list_keyframes(params: dict[str, Any], _ctx: ExecutionContext) -> dict[str, Any]:
    obj = resolve_object(str(params.get("object", "")))
    assert obj is not None
    curves = []
    for fc in iter_fcurves(obj):
        curves.append(
            {
                "data_path": fc.data_path,
                "array_index": fc.array_index,
                "keyframes": [
                    {
                        "frame": round(float(kp.co.x), 3),
                        "value": round(float(kp.co.y), 5),
                        "interpolation": kp.interpolation,
                    }
                    for kp in fc.keyframe_points
                ],
            }
        )
    return {
        "object": obj.name,
        "action": obj.animation_data.action.name if (obj.animation_data and obj.animation_data.action) else None,
        "fcurves": curves,
    }


def add_constraint(params: dict[str, Any], _ctx: ExecutionContext) -> dict[str, Any]:
    obj = resolve_object(str(params.get("object", "")))
    assert obj is not None
    ctype = str(params.get("constraint_type", "TRACK_TO")).strip().upper()
    name = str(params.get("name") or ctype.title())
    settings = dict(params.get("settings") or {})
    if params.get("target") is not None:
        settings["target"] = params["target"]

    try:
        con = obj.constraints.new(type=ctype)
    except Exception as exc:
        raise AddonError(BridgeErrorCode.INVALID_PARAMS, f"Unsupported constraint {ctype!r}: {exc}") from exc
    con.name = name

    applied: list[str] = []
    for k, v in settings.items():
        if not hasattr(con, k):
            continue
        if k == "target" and isinstance(v, str):
            setattr(con, k, resolve_object(v))
        else:
            setattr(con, k, v)
        applied.append(k)

    return {"object": obj.name, "constraint": con.name, "type": con.type, "applied": applied}


def add_driver(params: dict[str, Any], _ctx: ExecutionContext) -> dict[str, Any]:
    obj = resolve_object(str(params.get("object", "")))
    assert obj is not None
    data_path = str(params.get("data_path", "")).strip()
    expression = str(params.get("expression", "")).strip()
    if not data_path or not expression:
        raise AddonError(BridgeErrorCode.INVALID_PARAMS, "'data_path' and 'expression' are required.")
    index = int(params.get("index", -1))

    fc_or_list = obj.driver_add(data_path, index) if index >= 0 else obj.driver_add(data_path)
    fcurves = fc_or_list if isinstance(fc_or_list, list) else [fc_or_list]

    variables = params.get("variables") or []
    for fc in fcurves:
        drv = fc.driver
        drv.type = "SCRIPTED"
        drv.expression = expression
        for vdef in variables:
            var = drv.variables.new()
            var.name = str(vdef["name"])
            var.type = str(vdef.get("type", "SINGLE_PROP")).upper()
            if var.targets:
                tgt = var.targets[0]
                if vdef.get("target_object"):
                    tgt.id = resolve_object(str(vdef["target_object"]))
                if vdef.get("data_path"):
                    tgt.data_path = str(vdef["data_path"])

    return {
        "object": obj.name,
        "data_path": data_path,
        "expression": expression,
        "drivers_created": len(fcurves),
    }


def nla_push_down(params: dict[str, Any], _ctx: ExecutionContext) -> dict[str, Any]:
    obj = resolve_object(str(params.get("object", "")))
    assert obj is not None
    if obj.animation_data is None or obj.animation_data.action is None:
        raise AddonError(BridgeErrorCode.INVALID_STATE, f"Object {obj.name!r} has no active action to push to NLA.")

    anim = obj.animation_data
    action = anim.action
    track_name = str(params.get("track_name") or action.name)
    start_frame = int(params.get("start_frame", bpy.context.scene.frame_start))

    track = anim.nla_tracks.new()
    track.name = track_name
    strip = track.strips.new(action.name, start_frame, action)
    if params.get("clear_active_action", True):
        anim.action = None

    return {
        "object": obj.name,
        "track": track.name,
        "strip": strip.name,
        "frame_start": strip.frame_start,
        "frame_end": strip.frame_end,
    }


def shape_key_add(params: dict[str, Any], _ctx: ExecutionContext) -> dict[str, Any]:
    obj = resolve_object(str(params.get("object", "")))
    assert obj is not None
    if obj.type != "MESH" or obj.data is None:
        raise AddonError(BridgeErrorCode.INVALID_PARAMS, f"Object {obj.name!r} must be a MESH for shape keys.")

    if obj.data.shape_keys is None:
        obj.shape_key_add(name="Basis", from_mix=False)

    name = str(params.get("name", "Key")).strip() or "Key"
    sk = obj.shape_key_add(name=name, from_mix=bool(params.get("from_mix", False)))

    # Optional vertex deltas: [[idx, dx, dy, dz], ...] or uniform scale_offset [sx, sy, sz]
    deltas = params.get("vertex_deltas") or []
    for entry in deltas:
        idx = int(entry[0])
        if 0 <= idx < len(sk.data):
            sk.data[idx].co.x += float(entry[1])
            sk.data[idx].co.y += float(entry[2])
            sk.data[idx].co.z += float(entry[3])

    scale_offset = params.get("scale_offset")
    if scale_offset is not None and len(scale_offset) == 3:
        sx, sy, sz = float(scale_offset[0]), float(scale_offset[1]), float(scale_offset[2])
        for pt in sk.data:
            pt.co.x *= sx
            pt.co.y *= sy
            pt.co.z *= sz

    if params.get("value") is not None:
        sk.value = float(params["value"])

    return {
        "object": obj.name,
        "shape_key": sk.name,
        "value": round(float(sk.value), 4),
        "all_keys": [k.name for k in obj.data.shape_keys.key_blocks],
    }


def shape_key_set(params: dict[str, Any], _ctx: ExecutionContext) -> dict[str, Any]:
    obj = resolve_object(str(params.get("object", "")))
    assert obj is not None
    if obj.type != "MESH" or obj.data is None or obj.data.shape_keys is None:
        raise AddonError(BridgeErrorCode.NOT_FOUND, f"Object {obj.name!r} has no shape keys.")
    key_name = str(params.get("shape_key", ""))
    sk = obj.data.shape_keys.key_blocks.get(key_name)
    if sk is None:
        raise AddonError(
            BridgeErrorCode.NOT_FOUND,
            f"Shape key {key_name!r} not found on {obj.name!r}.",
            suggestions=[k.name for k in obj.data.shape_keys.key_blocks],
        )
    sk.value = float(params.get("value", 1.0))
    frame = params.get("keyframe_frame")
    if frame is not None:
        sk.keyframe_insert(data_path="value", frame=int(frame))
    return {"object": obj.name, "shape_key": sk.name, "value": round(float(sk.value), 4), "keyframed": frame is not None}


def register(dispatcher: Dispatcher) -> None:
    dispatcher.register("animation.set_frame_range", set_frame_range)
    dispatcher.register("animation.set_current_frame", set_current_frame, mutating=False)
    dispatcher.register("animation.insert_keyframes", insert_keyframes)
    dispatcher.register("animation.delete_keyframes", delete_keyframes)
    dispatcher.register("animation.set_interpolation", set_interpolation)
    dispatcher.register("animation.list_keyframes", list_keyframes, mutating=False)
    dispatcher.register("animation.add_constraint", add_constraint)
    dispatcher.register("animation.add_driver", add_driver)
    dispatcher.register("animation.nla_push_down", nla_push_down)
    dispatcher.register("animation.shape_key_add", shape_key_add)
    dispatcher.register("animation.shape_key_set", shape_key_set)
