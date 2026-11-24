# SPDX-License-Identifier: GPL-3.0-or-later
"""Lighting presets, physical sky/HDRI world setup, and camera framing/DOF handlers."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import bpy  # type: ignore[import-not-found]
from mathutils import Euler, Vector  # type: ignore[import-not-found]

from ..compat import get_object_bbox_world, get_or_create_world_tree, resolve_sky_type
from ..dispatcher import Dispatcher, ExecutionContext
from ..state import ensure_object_uid, resolve_collection, resolve_object
from ..wire import AddonError, BridgeErrorCode


def _point_at(obj: Any, target: Vector) -> None:
    direction = target - obj.location
    if direction.length < 1e-6:
        direction = Vector((0.0, 1.0, 0.0))
    obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


def _subject_bounds(target_refs: list[str] | None) -> tuple[Vector, float]:
    objs: list[Any] = []
    if target_refs:
        for ref in target_refs:
            obj = resolve_object(str(ref))
            assert obj is not None
            objs.append(obj)
    else:
        for obj in bpy.context.scene.objects:
            if not obj.hide_viewport and obj.type in ("MESH", "CURVE", "SURFACE", "FONT", "META"):
                objs.append(obj)
    if not objs:
        return Vector((0.0, 0.0, 0.0)), 2.0
    mins = [float("inf")] * 3
    maxs = [float("-inf")] * 3
    for obj in objs:
        bb = get_object_bbox_world(obj)
        for i in range(3):
            mins[i] = min(mins[i], bb["min"][i])
            maxs[i] = max(maxs[i], bb["max"][i])
    center = Vector((mins[i] + maxs[i]) * 0.5 for i in range(3))
    extents = Vector(maxs[i] - mins[i] for i in range(3))
    return center, max(0.5, extents.length * 0.5)


def add_light(params: dict[str, Any], _ctx: ExecutionContext) -> dict[str, Any]:
    light_type = str(params.get("light_type", "AREA")).strip().upper()
    if light_type not in ("POINT", "SUN", "SPOT", "AREA"):
        raise AddonError(
            BridgeErrorCode.INVALID_PARAMS,
            f"Unsupported light_type {light_type!r}.",
            suggestions=["POINT", "SUN", "SPOT", "AREA"],
        )
    name = str(params.get("name") or f"{light_type.title()}Light")
    energy = float(params.get("energy", 250.0 if light_type != "SUN" else 3.0))
    color = params.get("color") or [1.0, 1.0, 1.0]
    location = params.get("location") or [3.0, -3.0, 4.0]
    size = float(params.get("size", 1.0))

    light_data = bpy.data.lights.new(name=name, type=light_type)
    light_data.energy = energy
    light_data.color = (float(color[0]), float(color[1]), float(color[2]))

    if light_type == "AREA":
        light_data.size = size
    elif light_type == "POINT":
        light_data.shadow_soft_size = size * 0.25
    elif light_type == "SPOT":
        light_data.shadow_soft_size = size * 0.2
        light_data.spot_size = math.radians(float(params.get("spot_angle_degrees", 45.0)))
        light_data.spot_blend = float(params.get("spot_blend", 0.25))
    elif light_type == "SUN":
        light_data.angle = math.radians(float(params.get("sun_angle_degrees", 0.53)))

    obj = bpy.data.objects.new(name=name, object_data=light_data)
    col = resolve_collection(str(params["collection"])) if params.get("collection") else bpy.context.scene.collection
    assert col is not None
    col.objects.link(obj)
    obj.location = Vector((float(location[0]), float(location[1]), float(location[2])))

    if params.get("look_at") is not None:
        la = params["look_at"]
        target = resolve_object(la).matrix_world.translation if isinstance(la, str) else Vector(
            (float(la[0]), float(la[1]), float(la[2]))
        )
        _point_at(obj, target)
    elif params.get("rotation_degrees") is not None:
        r = params["rotation_degrees"]
        obj.rotation_euler = Euler(
            (math.radians(float(r[0])), math.radians(float(r[1])), math.radians(float(r[2]))), "XYZ"
        )

    uid = ensure_object_uid(obj)
    return {
        "uid": uid,
        "name": obj.name,
        "light_type": light_type,
        "energy": light_data.energy,
        "location": [round(float(v), 4) for v in obj.location],
    }


def setup_lighting_preset(params: dict[str, Any], _ctx: ExecutionContext) -> dict[str, Any]:
    preset = str(params.get("preset", "three_point")).strip().lower()
    if preset not in ("three_point", "studio", "dramatic", "outdoor"):
        raise AddonError(
            BridgeErrorCode.INVALID_PARAMS,
            f"Unsupported lighting preset {preset!r}.",
            suggestions=["three_point", "studio", "dramatic", "outdoor"],
        )
    clear_existing = bool(params.get("clear_existing_lights", True))
    intensity = float(params.get("intensity", 1.0))
    center, radius = _subject_bounds(params.get("target_objects"))
    dist = radius * 3.0

    if clear_existing:
        for obj in list(bpy.context.scene.objects):
            if obj.type == "LIGHT":
                ld = obj.data
                bpy.data.objects.remove(obj, do_unlink=True)
                if ld is not None and ld.users == 0:
                    bpy.data.lights.remove(ld)

    col_name = "Lighting"
    col = bpy.data.collections.get(col_name)
    if col is None:
        col = bpy.data.collections.new(col_name)
        bpy.context.scene.collection.children.link(col)

    created: list[str] = []

    def _spawn(name: str, ltype: str, loc: Vector, energy: float, color: tuple[float, float, float], size: float) -> None:
        ld = bpy.data.lights.new(name=name, type=ltype)
        ld.energy = energy * intensity
        ld.color = color
        if ltype == "AREA":
            ld.size = size
        obj = bpy.data.objects.new(name=name, object_data=ld)
        col.objects.link(obj)
        obj.location = loc
        _point_at(obj, center)
        ensure_object_uid(obj)
        created.append(obj.name)

    scale_e = max(1.0, (dist / 3.0) ** 2)

    if preset == "three_point":
        _spawn("Key_Light", "AREA", center + Vector((dist, -dist, dist * 0.9)), 350.0 * scale_e, (1.0, 0.96, 0.9), radius * 1.2)
        _spawn("Fill_Light", "AREA", center + Vector((-dist * 1.1, -dist * 0.7, dist * 0.5)), 120.0 * scale_e, (0.85, 0.92, 1.0), radius * 1.8)
        _spawn("Rim_Light", "AREA", center + Vector((-dist * 0.4, dist * 1.1, dist * 0.8)), 220.0 * scale_e, (1.0, 0.98, 0.95), radius * 0.8)
    elif preset == "studio":
        _spawn("Studio_Overhead", "AREA", center + Vector((0.0, 0.0, dist * 1.2)), 400.0 * scale_e, (1.0, 1.0, 1.0), radius * 2.5)
        _spawn("Studio_Left", "AREA", center + Vector((-dist * 1.2, -dist * 0.4, dist * 0.4)), 220.0 * scale_e, (0.95, 0.97, 1.0), radius * 1.6)
        _spawn("Studio_Right", "AREA", center + Vector((dist * 1.2, -dist * 0.4, dist * 0.4)), 220.0 * scale_e, (1.0, 0.97, 0.94), radius * 1.6)
    elif preset == "dramatic":
        _spawn("Dramatic_Key", "SPOT", center + Vector((dist * 0.9, -dist * 0.8, dist * 1.0)), 600.0 * scale_e, (1.0, 0.88, 0.75), radius * 0.5)
        _spawn("Dramatic_Rim", "AREA", center + Vector((-dist * 0.7, dist * 1.0, dist * 0.7)), 320.0 * scale_e, (0.65, 0.82, 1.0), radius * 0.6)
    elif preset == "outdoor":
        set_world_sky({"sun_elevation": 35.0, "sun_rotation": 45.0, "strength": 1.0 * intensity}, _ctx)
        _spawn("Outdoor_Sun", "SUN", center + Vector((dist, -dist, dist)), 3.0, (1.0, 0.97, 0.92), 1.0)

    return {"preset": preset, "lights_created": created, "subject_center": [round(float(c), 4) for c in center]}


def set_world_sky(params: dict[str, Any], _ctx: ExecutionContext) -> dict[str, Any]:
    world, tree = get_or_create_world_tree(bpy.context.scene)
    tree.nodes.clear()

    sky = tree.nodes.new("ShaderNodeTexSky")
    sky.location = (-300, 0)
    resolved_type = resolve_sky_type(sky, str(params.get("sky_type", "nishita")))
    sky.sky_type = resolved_type

    if hasattr(sky, "sun_elevation"):
        sky.sun_elevation = math.radians(float(params.get("sun_elevation", 25.0)))
    if hasattr(sky, "sun_rotation"):
        sky.sun_rotation = math.radians(float(params.get("sun_rotation", 0.0)))
    if hasattr(sky, "air_density") and "air_density" in params:
        sky.air_density = float(params["air_density"])
    if hasattr(sky, "dust_density") and "dust_density" in params:
        sky.dust_density = float(params["dust_density"])

    bg = tree.nodes.new("ShaderNodeBackground")
    bg.location = (0, 0)
    bg.inputs["Strength"].default_value = float(params.get("strength", 1.0))

    out = tree.nodes.new("ShaderNodeOutputWorld")
    out.location = (250, 0)

    tree.links.new(sky.outputs["Color"], bg.inputs["Color"])
    tree.links.new(bg.outputs["Background"], out.inputs["Surface"])

    return {"world": world.name, "sky_type": resolved_type, "strength": bg.inputs["Strength"].default_value}


def set_world_hdri(params: dict[str, Any], _ctx: ExecutionContext) -> dict[str, Any]:
    filepath = str(params.get("filepath", "")).strip()
    if not filepath or not Path(filepath).is_file():
        raise AddonError(BridgeErrorCode.NOT_FOUND, f"HDRI image not found: {filepath!r}")
    strength = float(params.get("strength", 1.0))
    rotation_z = math.radians(float(params.get("rotation_degrees", 0.0)))

    world, tree = get_or_create_world_tree(bpy.context.scene)
    tree.nodes.clear()

    tex_coord = tree.nodes.new("ShaderNodeTexCoord")
    tex_coord.location = (-750, 0)
    mapping = tree.nodes.new("ShaderNodeMapping")
    mapping.location = (-550, 0)
    mapping.inputs["Rotation"].default_value = (0.0, 0.0, rotation_z)

    env_tex = tree.nodes.new("ShaderNodeTexEnvironment")
    env_tex.location = (-300, 0)
    img = bpy.data.images.load(filepath, check_existing=True)
    env_tex.image = img

    bg = tree.nodes.new("ShaderNodeBackground")
    bg.location = (0, 0)
    bg.inputs["Strength"].default_value = strength

    out = tree.nodes.new("ShaderNodeOutputWorld")
    out.location = (250, 0)

    tree.links.new(tex_coord.outputs["Generated"], mapping.inputs["Vector"])
    tree.links.new(mapping.outputs["Vector"], env_tex.inputs["Vector"])
    tree.links.new(env_tex.outputs["Color"], bg.inputs["Color"])
    tree.links.new(bg.outputs["Background"], out.inputs["Surface"])

    return {
        "world": world.name,
        "image": img.name,
        "strength": strength,
        "rotation_degrees": float(params.get("rotation_degrees", 0.0)),
    }


def add_camera(params: dict[str, Any], _ctx: ExecutionContext) -> dict[str, Any]:
    name = str(params.get("name") or "Camera")
    location = params.get("location") or [4.0, -4.0, 3.0]
    lens = float(params.get("lens", 50.0))
    sensor_width = float(params.get("sensor_width", 36.0))
    set_active = bool(params.get("set_active", True))

    cam_data = bpy.data.cameras.new(name=name)
    cam_data.lens = lens
    cam_data.sensor_width = sensor_width

    cam_obj = bpy.data.objects.new(name=name, object_data=cam_data)
    col = resolve_collection(str(params["collection"])) if params.get("collection") else bpy.context.scene.collection
    assert col is not None
    col.objects.link(cam_obj)
    cam_obj.location = Vector((float(location[0]), float(location[1]), float(location[2])))

    if params.get("look_at") is not None:
        la = params["look_at"]
        target = (
            Vector(get_object_bbox_world(resolve_object(la))["center"])
            if isinstance(la, str)
            else Vector((float(la[0]), float(la[1]), float(la[2])))
        )
        _point_at(cam_obj, target)
    elif params.get("rotation_degrees") is not None:
        r = params["rotation_degrees"]
        cam_obj.rotation_euler = Euler(
            (math.radians(float(r[0])), math.radians(float(r[1])), math.radians(float(r[2]))), "XYZ"
        )

    if set_active:
        bpy.context.scene.camera = cam_obj

    uid = ensure_object_uid(cam_obj)
    return {
        "uid": uid,
        "name": cam_obj.name,
        "lens": cam_data.lens,
        "is_active": bpy.context.scene.camera == cam_obj,
        "location": [round(float(v), 4) for v in cam_obj.location],
    }


def _resolve_camera(ref: str | None) -> Any:
    if ref:
        cam = resolve_object(ref)
        assert cam is not None
        if cam.type != "CAMERA":
            raise AddonError(BridgeErrorCode.INVALID_PARAMS, f"Object {cam.name!r} is not a CAMERA.")
        return cam
    cam = bpy.context.scene.camera
    if cam is None:
        raise AddonError(BridgeErrorCode.NOT_FOUND, "No active camera in scene. Specify 'camera' or add one first.")
    return cam


def camera_look_at(params: dict[str, Any], _ctx: ExecutionContext) -> dict[str, Any]:
    cam = _resolve_camera(params.get("camera"))
    target_val = params.get("target")
    if target_val is None:
        raise AddonError(BridgeErrorCode.INVALID_PARAMS, "'target' (object name or [x, y, z]) is required.")
    target = (
        Vector(get_object_bbox_world(resolve_object(target_val))["center"])
        if isinstance(target_val, str)
        else Vector((float(target_val[0]), float(target_val[1]), float(target_val[2])))
    )
    _point_at(cam, target)
    return {
        "camera": cam.name,
        "target": [round(float(c), 4) for c in target],
        "rotation_degrees": [round(math.degrees(float(a)), 3) for a in cam.rotation_euler],
    }


def camera_frame_objects(params: dict[str, Any], _ctx: ExecutionContext) -> dict[str, Any]:
    cam = _resolve_camera(params.get("camera"))
    center, radius = _subject_bounds(params.get("objects"))
    margin = float(params.get("margin", 1.3))

    dir_param = params.get("direction")
    if dir_param is not None:
        direction = Vector((float(dir_param[0]), float(dir_param[1]), float(dir_param[2]))).normalized()
    else:
        cur = cam.location - center
        direction = cur.normalized() if cur.length > 1e-4 else Vector((1.0, -1.0, 0.7)).normalized()

    fov = 2.0 * math.atan(cam.data.sensor_width / (2.0 * max(1.0, cam.data.lens)))
    dist = (radius / max(0.1, math.sin(fov * 0.5))) * margin
    cam.location = center + direction * dist
    _point_at(cam, center)

    return {
        "camera": cam.name,
        "location": [round(float(v), 4) for v in cam.location],
        "look_at": [round(float(c), 4) for c in center],
        "distance": round(float(dist), 4),
    }


def set_camera_lens_dof(params: dict[str, Any], _ctx: ExecutionContext) -> dict[str, Any]:
    cam = _resolve_camera(params.get("camera"))
    cd = cam.data
    if params.get("lens") is not None:
        cd.lens = float(params["lens"])
    if params.get("camera_type") is not None:
        cd.type = str(params["camera_type"]).upper()
    if params.get("clip_start") is not None:
        cd.clip_start = float(params["clip_start"])
    if params.get("clip_end") is not None:
        cd.clip_end = float(params["clip_end"])
    if params.get("use_dof") is not None:
        cd.dof.use_dof = bool(params["use_dof"])
    if params.get("focus_object") is not None:
        cd.dof.use_dof = True
        cd.dof.focus_object = resolve_object(str(params["focus_object"]))
    elif params.get("focus_distance") is not None:
        cd.dof.use_dof = True
        cd.dof.focus_object = None
        cd.dof.focus_distance = float(params["focus_distance"])
    if params.get("fstop") is not None:
        cd.dof.aperture_fstop = float(params["fstop"])

    return {
        "camera": cam.name,
        "lens": round(float(cd.lens), 3),
        "type": cd.type,
        "use_dof": bool(cd.dof.use_dof),
        "focus_object": cd.dof.focus_object.name if cd.dof.focus_object else None,
        "focus_distance": round(float(cd.dof.focus_distance), 4),
        "fstop": round(float(cd.dof.aperture_fstop), 3),
    }


def register(dispatcher: Dispatcher) -> None:
    dispatcher.register("lighting.add_light", add_light)
    dispatcher.register("lighting.setup_preset", setup_lighting_preset)
    dispatcher.register("lighting.set_world_sky", set_world_sky)
    dispatcher.register("lighting.set_world_hdri", set_world_hdri)
    dispatcher.register("camera.add_camera", add_camera)
    dispatcher.register("camera.look_at", camera_look_at)
    dispatcher.register("camera.frame_objects", camera_frame_objects)
    dispatcher.register("camera.set_lens_dof", set_camera_lens_dof)
