# SPDX-License-Identifier: GPL-3.0-or-later
"""Armature creation, auto-weights binding, posing, and IK setup handlers."""

from __future__ import annotations

import difflib
import math
from typing import Any

import bpy  # type: ignore[import-not-found]
from mathutils import Euler, Vector  # type: ignore[import-not-found]

from ..dispatcher import Dispatcher, ExecutionContext
from ..state import ensure_object_uid, resolve_collection, resolve_object
from ..wire import AddonError, BridgeErrorCode


def create_armature(params: dict[str, Any], _ctx: ExecutionContext) -> dict[str, Any]:
    name = str(params.get("name", "Armature")).strip() or "Armature"
    bones_spec = params.get("bones") or []
    if not bones_spec:
        raise AddonError(BridgeErrorCode.INVALID_PARAMS, "'bones' must be a non-empty list of bone specs.")

    arm_data = bpy.data.armatures.new(name=name)
    arm_obj = bpy.data.objects.new(name=name, object_data=arm_data)
    col = resolve_collection(str(params["collection"])) if params.get("collection") else bpy.context.scene.collection
    assert col is not None
    col.objects.link(arm_obj)

    loc = params.get("location")
    if loc is not None:
        arm_obj.location = Vector((float(loc[0]), float(loc[1]), float(loc[2])))

    # Ensure clean OBJECT mode first, then switch active armature to EDIT mode to author bones
    prev_active = bpy.context.view_layer.objects.active
    if prev_active is not None and prev_active.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")

    bpy.context.view_layer.objects.active = arm_obj
    arm_obj.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")

    created_bones: list[str] = []
    try:
        edit_bones = arm_data.edit_bones
        bone_map: dict[str, Any] = {}
        for bspec in bones_spec:
            bname = str(bspec["name"])
            eb = edit_bones.new(bname)
            head = bspec.get("head") or [0.0, 0.0, 0.0]
            tail = bspec.get("tail") or [0.0, 0.0, 0.5]
            eb.head = Vector((float(head[0]), float(head[1]), float(head[2])))
            eb.tail = Vector((float(tail[0]), float(tail[1]), float(tail[2])))
            if bspec.get("roll_degrees") is not None:
                eb.roll = math.radians(float(bspec["roll_degrees"]))
            bone_map[bname] = eb
            created_bones.append(eb.name)

        # Resolve parents in second pass so order in spec doesn't break hierarchy
        for bspec in bones_spec:
            parent_name = bspec.get("parent")
            if parent_name:
                child_eb = bone_map[str(bspec["name"])]
                parent_eb = bone_map.get(str(parent_name))
                if parent_eb is None:
                    raise AddonError(
                        BridgeErrorCode.NOT_FOUND,
                        f"Parent bone {parent_name!r} not found in spec.",
                        suggestions=list(bone_map.keys()),
                    )
                child_eb.parent = parent_eb
                child_eb.use_connect = bool(bspec.get("use_connect", False))
    finally:
        bpy.ops.object.mode_set(mode="OBJECT")

    uid = ensure_object_uid(arm_obj)
    return {
        "uid": uid,
        "name": arm_obj.name,
        "bones": created_bones,
    }


def _assign_distance_weights(mesh_obj: Any, arm_obj: Any) -> str:
    """Deterministic pure-math inverse-distance bone skinning fallback."""
    bpy.context.view_layer.update()
    mesh_world = mesh_obj.matrix_world
    arm_world = arm_obj.matrix_world

    bone_segments: list[tuple[str, Vector, Vector]] = []
    for bone in arm_obj.data.bones:
        if not bone.use_deform:
            continue
        h = arm_world @ bone.head_local
        t = arm_world @ bone.tail_local
        bone_segments.append((bone.name, h, t))
        if mesh_obj.vertex_groups.get(bone.name) is None:
            mesh_obj.vertex_groups.new(name=bone.name)

    if not bone_segments:
        return "no_deform_bones"

    for v in mesh_obj.data.vertices:
        p = mesh_world @ v.co
        weights: list[tuple[str, float]] = []
        for bname, h, t in bone_segments:
            ab = t - h
            ab_len_sq = max(ab.length_squared, 1e-8)
            proj = max(0.0, min(1.0, (p - h).dot(ab) / ab_len_sq))
            closest = h + ab * proj
            dist = (p - closest).length
            w = 1.0 / ((dist + 0.05) ** 2)
            weights.append((bname, w))
        total = sum(w for _, w in weights) or 1.0
        for bname, w in weights:
            norm_w = w / total
            if norm_w >= 0.01:
                mesh_obj.vertex_groups[bname].add([v.index], norm_w, "REPLACE")

    return "distance_fallback"


def bind_auto_weights(params: dict[str, Any], _ctx: ExecutionContext) -> dict[str, Any]:
    mesh_obj = resolve_object(str(params.get("mesh", "")))
    arm_obj = resolve_object(str(params.get("armature", "")))
    assert mesh_obj is not None and arm_obj is not None
    if mesh_obj.type != "MESH":
        raise AddonError(BridgeErrorCode.INVALID_PARAMS, f"{mesh_obj.name!r} must be a MESH.")
    if arm_obj.type != "ARMATURE":
        raise AddonError(BridgeErrorCode.INVALID_PARAMS, f"{arm_obj.name!r} must be an ARMATURE.")

    method = "automatic_heat"
    try:
        for o in bpy.context.scene.objects:
            o.select_set(False)
        mesh_obj.select_set(True)
        arm_obj.select_set(True)
        bpy.context.view_layer.objects.active = arm_obj
        res = bpy.ops.object.parent_set(type="ARMATURE_AUTO")
        if "FINISHED" not in res or len(mesh_obj.vertex_groups) == 0:
            raise RuntimeError("ARMATURE_AUTO did not produce weights")
    except Exception:
        # Clean deterministic fallback (works headless even on open/non-manifold meshes)
        mesh_obj.parent = arm_obj
        mesh_obj.matrix_parent_inverse = arm_obj.matrix_world.inverted()
        mod = next((m for m in mesh_obj.modifiers if m.type == "ARMATURE"), None)
        if mod is None:
            mod = mesh_obj.modifiers.new(name="Armature", type="ARMATURE")
        mod.object = arm_obj
        method = _assign_distance_weights(mesh_obj, arm_obj)

    return {
        "mesh": mesh_obj.name,
        "armature": arm_obj.name,
        "method": method,
        "vertex_groups": [vg.name for vg in mesh_obj.vertex_groups],
    }


def pose_bone(params: dict[str, Any], _ctx: ExecutionContext) -> dict[str, Any]:
    arm_obj = resolve_object(str(params.get("armature", "")))
    assert arm_obj is not None
    if arm_obj.type != "ARMATURE":
        raise AddonError(BridgeErrorCode.INVALID_PARAMS, f"{arm_obj.name!r} must be an ARMATURE.")
    bone_name = str(params.get("bone", ""))
    pbone = arm_obj.pose.bones.get(bone_name)
    if pbone is None:
        raise AddonError(
            BridgeErrorCode.NOT_FOUND,
            f"Pose bone {bone_name!r} not found on {arm_obj.name!r}.",
            suggestions=difflib.get_close_matches(bone_name, [b.name for b in arm_obj.pose.bones], n=5, cutoff=0.35),
        )

    loc = params.get("location")
    rot = params.get("rotation_degrees")
    scl = params.get("scale")
    frame = params.get("keyframe_frame")

    if loc is not None:
        pbone.location = Vector((float(loc[0]), float(loc[1]), float(loc[2])))
        if frame is not None:
            pbone.keyframe_insert(data_path="location", frame=int(frame))
    if rot is not None:
        pbone.rotation_mode = "XYZ"
        pbone.rotation_euler = Euler(
            (math.radians(float(rot[0])), math.radians(float(rot[1])), math.radians(float(rot[2]))),
            "XYZ",
        )
        if frame is not None:
            pbone.keyframe_insert(data_path="rotation_euler", frame=int(frame))
    if scl is not None:
        sv = Vector((float(scl), float(scl), float(scl))) if isinstance(scl, (int, float)) else Vector(
            (float(scl[0]), float(scl[1]), float(scl[2]))
        )
        pbone.scale = sv
        if frame is not None:
            pbone.keyframe_insert(data_path="scale", frame=int(frame))

    bpy.context.view_layer.update()
    return {
        "armature": arm_obj.name,
        "bone": pbone.name,
        "location": [round(float(v), 4) for v in pbone.location],
        "rotation_degrees": [round(math.degrees(float(a)), 3) for a in pbone.rotation_euler],
        "keyframed": frame is not None,
    }


def setup_ik(params: dict[str, Any], _ctx: ExecutionContext) -> dict[str, Any]:
    arm_obj = resolve_object(str(params.get("armature", "")))
    assert arm_obj is not None
    if arm_obj.type != "ARMATURE":
        raise AddonError(BridgeErrorCode.INVALID_PARAMS, f"{arm_obj.name!r} must be an ARMATURE.")
    bone_name = str(params.get("bone", ""))
    pbone = arm_obj.pose.bones.get(bone_name)
    if pbone is None:
        raise AddonError(
            BridgeErrorCode.NOT_FOUND,
            f"Bone {bone_name!r} not found on {arm_obj.name!r}.",
            suggestions=[b.name for b in arm_obj.pose.bones],
        )

    chain_count = max(0, int(params.get("chain_count", 2)))
    target_ref = params.get("target")
    if target_ref:
        target_obj = resolve_object(str(target_ref))
    else:
        # Auto-create an Empty IK target positioned cleanly at the bone's world tail
        target_obj = bpy.data.objects.new(f"IK_{bone_name}_Target", None)
        target_obj.empty_display_type = "SPHERE"
        target_obj.empty_display_size = 0.15
        bpy.context.scene.collection.objects.link(target_obj)
        target_obj.location = arm_obj.matrix_world @ pbone.tail
        ensure_object_uid(target_obj)

    con = pbone.constraints.new(type="IK")
    con.name = str(params.get("name") or f"IK_{bone_name}")
    con.target = target_obj
    con.chain_count = chain_count

    if params.get("pole_target"):
        con.pole_target = resolve_object(str(params["pole_target"]))
        con.pole_angle = math.radians(float(params.get("pole_angle_degrees", 0.0)))

    return {
        "armature": arm_obj.name,
        "bone": pbone.name,
        "constraint": con.name,
        "target": target_obj.name,
        "chain_count": chain_count,
    }


def register(dispatcher: Dispatcher) -> None:
    dispatcher.register("rigging.create_armature", create_armature)
    dispatcher.register("rigging.bind_auto_weights", bind_auto_weights)
    dispatcher.register("rigging.pose_bone", pose_bone)
    dispatcher.register("rigging.setup_ik", setup_ik)
