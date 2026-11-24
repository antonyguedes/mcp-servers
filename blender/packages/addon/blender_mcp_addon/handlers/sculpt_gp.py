# SPDX-License-Identifier: GPL-3.0-or-later
"""Headless-safe Sculpt (voxel remesh & procedural brush strokes) and Grease Pencil (v2/v3) handlers."""

from __future__ import annotations

from typing import Any

import bmesh  # type: ignore[import-not-found]
import bpy  # type: ignore[import-not-found]
from mathutils import Vector  # type: ignore[import-not-found]

from ..compat import add_grease_pencil_stroke
from ..dispatcher import Dispatcher, ExecutionContext
from ..state import ensure_object_uid, resolve_collection, resolve_object
from ..wire import AddonError, BridgeErrorCode


def sculpt_remesh(params: dict[str, Any], _ctx: ExecutionContext) -> dict[str, Any]:
    """Perform voxel remeshing cleanly in both GUI and headless modes."""
    obj = resolve_object(str(params.get("object", "")))
    assert obj is not None
    if obj.type != "MESH" or obj.data is None:
        raise AddonError(BridgeErrorCode.INVALID_PARAMS, f"Object {obj.name!r} must be a MESH.")

    voxel_size = max(0.002, float(params.get("voxel_size", 0.08)))
    smooth_shade = bool(params.get("smooth_shading", True))

    mod = obj.modifiers.new(name="_mcp_voxel_remesh", type="REMESH")
    mod.mode = "VOXEL"
    mod.voxel_size = voxel_size
    mod.use_smooth_shade = smooth_shade

    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    eval_obj = obj.evaluated_get(depsgraph)
    new_mesh = bpy.data.meshes.new_from_object(eval_obj)

    obj.modifiers.remove(mod)
    old_mesh = obj.data
    obj.data = new_mesh
    new_mesh.name = old_mesh.name
    if old_mesh.users == 0:
        bpy.data.meshes.remove(old_mesh)

    return {
        "object": obj.name,
        "voxel_size": voxel_size,
        "vertices": len(obj.data.vertices),
        "faces": len(obj.data.polygons),
    }


def _smoothstep_falloff(dist: float, radius: float) -> float:
    if dist >= radius or radius <= 1e-6:
        return 0.0
    t = 1.0 - (dist / radius)
    return t * t * (3.0 - 2.0 * t)


def sculpt_stroke(params: dict[str, Any], _ctx: ExecutionContext) -> dict[str, Any]:
    """Apply a procedural sculpt brush stroke along 3D world-space stroke points (headless-safe)."""
    obj = resolve_object(str(params.get("object", "")))
    assert obj is not None
    if obj.type != "MESH" or obj.data is None:
        raise AddonError(BridgeErrorCode.INVALID_PARAMS, f"Object {obj.name!r} must be a MESH.")

    brush = str(params.get("brush", "DRAW")).strip().upper()
    if brush not in ("DRAW", "INFLATE", "SMOOTH", "FLATTEN", "PINCH", "GRAB"):
        raise AddonError(
            BridgeErrorCode.INVALID_PARAMS,
            f"Unsupported brush {brush!r}.",
            suggestions=["DRAW", "INFLATE", "SMOOTH", "FLATTEN", "PINCH", "GRAB"],
        )

    points_raw = params.get("points") or []
    if not points_raw:
        raise AddonError(BridgeErrorCode.INVALID_PARAMS, "'points' must be a non-empty list of [x, y, z] coordinates.")
    radius = max(0.001, float(params.get("radius", 0.3)))
    strength = float(params.get("strength", 0.15))
    symmetry_x = bool(params.get("symmetry_x", False))

    inv_world = obj.matrix_world.inverted()
    local_pts = [inv_world @ Vector((float(p[0]), float(p[1]), float(p[2]))) for p in points_raw]
    if symmetry_x:
        mirrored = [Vector((-p.x, p.y, p.z)) for p in local_pts]
        stroke_sets = [local_pts, mirrored]
    else:
        stroke_sets = [local_pts]

    bm = bmesh.new()
    affected: set[int] = set()
    try:
        bm.from_mesh(obj.data)
        bm.normal_update()
        bm.verts.ensure_lookup_table()
        bm.verts.index_update()

        for pts in stroke_sets:
            if brush == "GRAB" and len(pts) >= 2:
                origin = pts[0]
                delta = pts[-1] - origin
                for v in bm.verts:
                    w = _smoothstep_falloff((v.co - origin).length, radius) * strength
                    if w > 0.0:
                        v.co += delta * w
                        affected.add(v.index)
                continue

            for center in pts:
                if brush == "SMOOTH":
                    updates: list[tuple[Any, Vector]] = []
                    for v in bm.verts:
                        w = _smoothstep_falloff((v.co - center).length, radius) * abs(strength)
                        if w > 0.0 and v.link_edges:
                            neighbors = [e.other_vert(v).co for e in v.link_edges]
                            avg = sum(neighbors, Vector((0.0, 0.0, 0.0))) / len(neighbors)
                            updates.append((v, v.co.lerp(avg, min(1.0, w))))
                            affected.add(v.index)
                    for v, new_co in updates:
                        v.co = new_co
                elif brush == "FLATTEN":
                    in_range = [v for v in bm.verts if (v.co - center).length < radius]
                    if not in_range:
                        continue
                    avg_pos = sum((v.co for v in in_range), Vector((0.0, 0.0, 0.0))) / len(in_range)
                    avg_n = sum((v.normal for v in in_range), Vector((0.0, 0.0, 0.0)))
                    if avg_n.length < 1e-6:
                        continue
                    avg_n.normalize()
                    for v in in_range:
                        w = _smoothstep_falloff((v.co - center).length, radius) * min(1.0, abs(strength))
                        proj_dist = (v.co - avg_pos).dot(avg_n)
                        v.co -= avg_n * (proj_dist * w)
                        affected.add(v.index)
                elif brush == "PINCH":
                    for v in bm.verts:
                        w = _smoothstep_falloff((v.co - center).length, radius) * strength
                        if w != 0.0:
                            v.co = v.co.lerp(center, max(-1.0, min(1.0, w)))
                            affected.add(v.index)
                else:
                    # DRAW / INFLATE push along vertex normal
                    for v in bm.verts:
                        w = _smoothstep_falloff((v.co - center).length, radius) * strength
                        if w != 0.0:
                            v.co += v.normal * w
                            affected.add(v.index)
            bm.normal_update()

        bm.to_mesh(obj.data)
        obj.data.update()
    finally:
        bm.free()

    return {
        "object": obj.name,
        "brush": brush,
        "affected_vertices": len(affected),
    }


def gp_create_object(params: dict[str, Any], _ctx: ExecutionContext) -> dict[str, Any]:
    """Create a Grease Pencil object (GPv3 on 4.3+/5.x, GPv2 on 3.6-4.2)."""
    name = str(params.get("name", "GreasePencil")).strip() or "GreasePencil"
    layer_name = str(params.get("layer_name", "Lines"))

    if hasattr(bpy.data, "grease_pencils_v3"):
        gp_data = bpy.data.grease_pencils_v3.new(name)
    else:
        gp_data = bpy.data.grease_pencils.new(name)

    gp_obj = bpy.data.objects.new(name, gp_data)
    col = resolve_collection(str(params["collection"])) if params.get("collection") else bpy.context.scene.collection
    assert col is not None
    col.objects.link(gp_obj)

    if params.get("location") is not None:
        loc = params["location"]
        gp_obj.location = Vector((float(loc[0]), float(loc[1]), float(loc[2])))

    layer = gp_data.layers.new(layer_name)
    layer.frames.new(int(params.get("frame", 1)))

    # Attach a default stroke material so strokes render immediately
    mat = bpy.data.materials.new(name=f"{name}_StrokeMat")
    bpy.data.materials.create_gpencil_data(mat)
    color = params.get("color") or [0.05, 0.05, 0.05, 1.0]
    if len(color) == 3:
        color = [*color, 1.0]
    mat.grease_pencil.color = tuple(float(c) for c in color[:4])
    gp_data.materials.append(mat)

    uid = ensure_object_uid(gp_obj)
    return {
        "uid": uid,
        "name": gp_obj.name,
        "type": gp_obj.type,
        "layer": layer_name,
        "material": mat.name,
    }


def gp_draw_stroke(params: dict[str, Any], _ctx: ExecutionContext) -> dict[str, Any]:
    obj = resolve_object(str(params.get("object", "")))
    assert obj is not None
    if obj.type not in ("GREASEPENCIL", "GPENCIL") or obj.data is None:
        raise AddonError(
            BridgeErrorCode.INVALID_PARAMS,
            f"Object {obj.name!r} must be a Grease Pencil object (got {obj.type}).",
        )
    points = params.get("points") or []
    if len(points) < 2:
        raise AddonError(BridgeErrorCode.INVALID_PARAMS, "'points' must contain at least 2 [x, y, z] coordinates.")
    layer_name = str(params.get("layer", "Lines"))
    frame_number = int(params.get("frame", bpy.context.scene.frame_current))
    radius = float(params.get("radius", 0.02))
    opacity = float(params.get("opacity", 1.0))
    cyclic = bool(params.get("cyclic", False))

    info = add_grease_pencil_stroke(
        obj.data,
        layer_name,
        frame_number,
        points,
        radius=radius,
        opacity=opacity,
        cyclic=cyclic,
    )
    return {"object": obj.name, "layer": layer_name, "frame": frame_number, **info}


def register(dispatcher: Dispatcher) -> None:
    dispatcher.register("sculpt.remesh", sculpt_remesh)
    dispatcher.register("sculpt.brush_stroke", sculpt_stroke)
    dispatcher.register("gp.create_object", gp_create_object)
    dispatcher.register("gp.draw_stroke", gp_draw_stroke)
