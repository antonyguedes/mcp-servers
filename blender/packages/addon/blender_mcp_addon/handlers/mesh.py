# SPDX-License-Identifier: GPL-3.0-or-later
"""Headless-safe bmesh modeling, boolean, shading, and UV unwrap handlers."""

from __future__ import annotations

import math
from typing import Any

import bmesh  # type: ignore[import-not-found]
import bpy  # type: ignore[import-not-found]
from mathutils import Matrix, Vector  # type: ignore[import-not-found]

from ..compat import get_object_bbox_world, set_mesh_shading
from ..dispatcher import Dispatcher, ExecutionContext
from ..state import resolve_object
from ..wire import AddonError, BridgeErrorCode

_FACE_DIRECTION_VECTORS: dict[str, Vector] = {
    "top": Vector((0.0, 0.0, 1.0)),
    "bottom": Vector((0.0, 0.0, -1.0)),
    "front": Vector((0.0, -1.0, 0.0)),
    "back": Vector((0.0, 1.0, 0.0)),
    "right": Vector((1.0, 0.0, 0.0)),
    "left": Vector((-1.0, 0.0, 0.0)),
}


def _require_mesh(ref: str) -> Any:
    obj = resolve_object(ref)
    assert obj is not None
    if obj.type != "MESH" or obj.data is None:
        raise AddonError(
            BridgeErrorCode.INVALID_PARAMS,
            f"Object {obj.name!r} must be a MESH (got {obj.type}).",
        )
    return obj


def _select_bm_faces(
    bm: Any,
    face_indices: list[int] | None,
    direction: str | None,
    normal_threshold: float = 0.7,
) -> list[Any]:
    bm.faces.ensure_lookup_table()
    if face_indices is not None and len(face_indices) > 0:
        selected: list[Any] = []
        for idx in face_indices:
            if 0 <= int(idx) < len(bm.faces):
                selected.append(bm.faces[int(idx)])
        if not selected:
            raise AddonError(BridgeErrorCode.INVALID_PARAMS, "No valid face indices matched mesh.")
        return selected

    if direction and direction.lower() != "all":
        dir_key = direction.strip().lower()
        target_vec = _FACE_DIRECTION_VECTORS.get(dir_key)
        if target_vec is None:
            raise AddonError(
                BridgeErrorCode.INVALID_PARAMS,
                f"Unknown face direction {direction!r}.",
                suggestions=["all", *sorted(_FACE_DIRECTION_VECTORS.keys())],
            )
        bm.normal_update()
        matched = [f for f in bm.faces if f.normal.dot(target_vec) >= normal_threshold]
        if not matched:
            raise AddonError(
                BridgeErrorCode.INVALID_STATE,
                f"No faces matched direction {direction!r} (threshold={normal_threshold}).",
            )
        return matched

    return list(bm.faces)


def mesh_stats(params: dict[str, Any], _ctx: ExecutionContext) -> dict[str, Any]:
    obj = _require_mesh(str(params.get("object", "")))
    bm = bmesh.new()
    try:
        bm.from_mesh(obj.data)
        bm.normal_update()
        tris = sum(1 for f in bm.faces if len(f.verts) == 3)
        quads = sum(1 for f in bm.faces if len(f.verts) == 4)
        ngons = sum(1 for f in bm.faces if len(f.verts) > 4)
        non_manifold_edges = sum(1 for e in bm.edges if not e.is_manifold)
        loose_verts = sum(1 for v in bm.verts if len(v.link_edges) == 0)
        area = sum(f.calc_area() for f in bm.faces)
        volume = abs(bm.calc_volume(signed=True)) if non_manifold_edges == 0 and len(bm.faces) > 0 else 0.0
        result = {
            "object": obj.name,
            "vertices": len(bm.verts),
            "edges": len(bm.edges),
            "faces": len(bm.faces),
            "tris": tris,
            "quads": quads,
            "ngons": ngons,
            "is_manifold": non_manifold_edges == 0 and loose_verts == 0 and len(bm.faces) > 0,
            "non_manifold_edges": non_manifold_edges,
            "loose_vertices": loose_verts,
            "surface_area": round(float(area), 5),
            "volume": round(float(volume), 5),
            "uv_layers": [uv.name for uv in obj.data.uv_layers],
            "vertex_groups": [vg.name for vg in obj.vertex_groups],
            "bbox_world": get_object_bbox_world(obj),
        }
    finally:
        bm.free()
    return result


def mesh_extrude(params: dict[str, Any], _ctx: ExecutionContext) -> dict[str, Any]:
    obj = _require_mesh(str(params.get("object", "")))
    distance = float(params.get("distance", 0.2))
    offset = params.get("offset")
    scale_factor = params.get("scale")
    face_indices = params.get("face_indices")
    direction = params.get("direction", "top")

    bm = bmesh.new()
    try:
        bm.from_mesh(obj.data)
        bm.normal_update()
        faces = _select_bm_faces(bm, face_indices, direction)
        avg_normal = sum((f.normal for f in faces), Vector((0.0, 0.0, 0.0)))
        if avg_normal.length > 1e-6:
            avg_normal.normalize()
        else:
            avg_normal = Vector((0.0, 0.0, 1.0))

        delta = (
            Vector((float(offset[0]), float(offset[1]), float(offset[2])))
            if offset is not None
            else avg_normal * distance
        )

        res = bmesh.ops.extrude_face_region(bm, geom=faces)
        extruded_verts = [g for g in res["geom"] if isinstance(g, bmesh.types.BMVert)]
        bmesh.ops.translate(bm, verts=extruded_verts, vec=delta)

        if scale_factor is not None:
            s = float(scale_factor)
            pivot = sum((v.co for v in extruded_verts), Vector((0.0, 0.0, 0.0))) / max(1, len(extruded_verts))
            bmesh.ops.scale(
                bm,
                vec=Vector((s, s, s)),
                verts=extruded_verts,
                space=Matrix.Translation(-pivot),
            )

        bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
        bm.to_mesh(obj.data)
        obj.data.update()
        v_cnt, f_cnt = len(bm.verts), len(bm.faces)
    finally:
        bm.free()

    return {
        "object": obj.name,
        "extruded_faces": len(faces),
        "vertices": v_cnt,
        "faces": f_cnt,
        "bbox_world": get_object_bbox_world(obj),
    }


def mesh_bevel(params: dict[str, Any], _ctx: ExecutionContext) -> dict[str, Any]:
    obj = _require_mesh(str(params.get("object", "")))
    offset = max(0.0001, float(params.get("offset", 0.05)))
    segments = max(1, min(16, int(params.get("segments", 2))))
    affect = str(params.get("affect", "EDGES")).upper()
    if affect not in ("EDGES", "VERTICES"):
        raise AddonError(BridgeErrorCode.INVALID_PARAMS, f"affect must be EDGES or VERTICES, got {affect!r}.")
    clamp_overlap = bool(params.get("clamp_overlap", True))
    profile = max(0.0, min(1.0, float(params.get("profile", 0.5))))
    angle_limit = params.get("angle_limit_degrees")

    bm = bmesh.new()
    try:
        bm.from_mesh(obj.data)
        bm.normal_update()
        if affect == "VERTICES":
            geom = list(bm.verts)
        elif angle_limit is not None:
            thresh = math.radians(float(angle_limit))
            geom = [e for e in bm.edges if len(e.link_faces) == 2 and e.calc_face_angle(0.0) >= thresh]
            if not geom:
                geom = list(bm.edges)
        else:
            geom = list(bm.edges)

        bmesh.ops.bevel(
            bm,
            geom=geom,
            offset=offset,
            offset_type="OFFSET",
            segments=segments,
            profile=profile,
            affect=affect,
            clamp_overlap=clamp_overlap,
        )
        bm.to_mesh(obj.data)
        obj.data.update()
        v_cnt, f_cnt = len(bm.verts), len(bm.faces)
    finally:
        bm.free()

    return {"object": obj.name, "vertices": v_cnt, "faces": f_cnt, "segments": segments, "offset": offset}


def mesh_inset(params: dict[str, Any], _ctx: ExecutionContext) -> dict[str, Any]:
    obj = _require_mesh(str(params.get("object", "")))
    thickness = max(0.0001, float(params.get("thickness", 0.05)))
    depth = float(params.get("depth", 0.0))
    individual = bool(params.get("individual", True))
    face_indices = params.get("face_indices")
    direction = params.get("direction", "all")

    bm = bmesh.new()
    try:
        bm.from_mesh(obj.data)
        faces = _select_bm_faces(bm, face_indices, direction)
        if individual:
            bmesh.ops.inset_individual(bm, faces=faces, thickness=thickness, depth=depth)
        else:
            bmesh.ops.inset_region(bm, faces=faces, thickness=thickness, depth=depth)
        bm.to_mesh(obj.data)
        obj.data.update()
        v_cnt, f_cnt = len(bm.verts), len(bm.faces)
    finally:
        bm.free()

    return {"object": obj.name, "inset_faces": len(faces), "vertices": v_cnt, "faces": f_cnt}


def mesh_subdivide(params: dict[str, Any], _ctx: ExecutionContext) -> dict[str, Any]:
    obj = _require_mesh(str(params.get("object", "")))
    cuts = max(1, min(10, int(params.get("cuts", 1))))
    smoothness = max(0.0, min(1.0, float(params.get("smoothness", 0.0))))
    fractal = max(0.0, float(params.get("fractal", 0.0)))

    bm = bmesh.new()
    try:
        bm.from_mesh(obj.data)
        bmesh.ops.subdivide_edges(
            bm,
            edges=list(bm.edges),
            cuts=cuts,
            smooth=smoothness,
            fractal=fractal,
            use_grid_fill=True,
        )
        bm.to_mesh(obj.data)
        obj.data.update()
        v_cnt, f_cnt = len(bm.verts), len(bm.faces)
    finally:
        bm.free()

    return {"object": obj.name, "cuts": cuts, "vertices": v_cnt, "faces": f_cnt}


def mesh_boolean(params: dict[str, Any], _ctx: ExecutionContext) -> dict[str, Any]:
    target = _require_mesh(str(params.get("target", "")))
    cutter = _require_mesh(str(params.get("cutter", "")))
    if target == cutter:
        raise AddonError(BridgeErrorCode.INVALID_PARAMS, "Target and cutter must be different objects.")

    operation = str(params.get("operation", "DIFFERENCE")).upper()
    if operation not in ("DIFFERENCE", "UNION", "INTERSECT"):
        raise AddonError(
            BridgeErrorCode.INVALID_PARAMS,
            f"Unsupported boolean operation {operation!r}.",
            suggestions=["DIFFERENCE", "UNION", "INTERSECT"],
        )
    solver = str(params.get("solver", "EXACT")).upper()
    delete_cutter = bool(params.get("delete_cutter", False))
    hide_cutter = bool(params.get("hide_cutter", True))

    mod = target.modifiers.new(name="_mcp_boolean", type="BOOLEAN")
    mod.operation = operation
    mod.object = cutter
    if hasattr(mod, "solver"):
        valid_solvers = [i.identifier for i in mod.bl_rna.properties["solver"].enum_items]
        if solver in valid_solvers:
            mod.solver = solver

    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    eval_obj = target.evaluated_get(depsgraph)
    new_mesh = bpy.data.meshes.new_from_object(eval_obj)

    old_mesh = target.data
    target.modifiers.remove(mod)
    target.data = new_mesh
    new_mesh.name = old_mesh.name
    if old_mesh.users == 0:
        bpy.data.meshes.remove(old_mesh)

    if delete_cutter:
        c_data = cutter.data
        bpy.data.objects.remove(cutter, do_unlink=True)
        if c_data is not None and c_data.users == 0:
            bpy.data.meshes.remove(c_data)
    elif hide_cutter:
        cutter.hide_viewport = True
        cutter.hide_render = True

    return {
        "target": target.name,
        "operation": operation,
        "vertices": len(target.data.vertices),
        "faces": len(target.data.polygons),
        "cutter_deleted": delete_cutter,
    }


def mesh_loop_cut(params: dict[str, Any], _ctx: ExecutionContext) -> dict[str, Any]:
    obj = _require_mesh(str(params.get("object", "")))
    axis = str(params.get("axis", "Z")).strip().upper()
    if axis not in ("X", "Y", "Z"):
        raise AddonError(BridgeErrorCode.INVALID_PARAMS, f"axis must be X, Y, or Z (got {axis!r}).")
    cuts = max(1, min(32, int(params.get("cuts", 1))))

    axis_idx = {"X": 0, "Y": 1, "Z": 2}[axis]
    normal = Vector((1.0 if axis == "X" else 0.0, 1.0 if axis == "Y" else 0.0, 1.0 if axis == "Z" else 0.0))

    bm = bmesh.new()
    try:
        bm.from_mesh(obj.data)
        coords = [v.co[axis_idx] for v in bm.verts]
        if not coords:
            raise AddonError(BridgeErrorCode.INVALID_STATE, f"Mesh {obj.name!r} has no vertices.")
        lo, hi = min(coords), max(coords)
        span = hi - lo
        if span < 1e-6:
            raise AddonError(BridgeErrorCode.INVALID_STATE, f"Mesh has zero extent along {axis}.")

        for i in range(1, cuts + 1):
            t = lo + span * (i / (cuts + 1))
            plane_co = Vector((t if axis == "X" else 0.0, t if axis == "Y" else 0.0, t if axis == "Z" else 0.0))
            geom = list(bm.verts) + list(bm.edges) + list(bm.faces)
            bmesh.ops.bisect_plane(bm, geom=geom, plane_co=plane_co, plane_no=normal)

        bm.to_mesh(obj.data)
        obj.data.update()
        v_cnt, f_cnt = len(bm.verts), len(bm.faces)
    finally:
        bm.free()

    return {"object": obj.name, "axis": axis, "cuts": cuts, "vertices": v_cnt, "faces": f_cnt}


def mesh_merge_by_distance(params: dict[str, Any], _ctx: ExecutionContext) -> dict[str, Any]:
    obj = _require_mesh(str(params.get("object", "")))
    distance = max(0.0, float(params.get("distance", 0.001)))

    bm = bmesh.new()
    try:
        bm.from_mesh(obj.data)
        before_verts = len(bm.verts)
        bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=distance)
        after_verts = len(bm.verts)
        bm.to_mesh(obj.data)
        obj.data.update()
    finally:
        bm.free()

    return {
        "object": obj.name,
        "removed_vertices": before_verts - after_verts,
        "vertices": after_verts,
    }


def mesh_recalc_normals(params: dict[str, Any], _ctx: ExecutionContext) -> dict[str, Any]:
    obj = _require_mesh(str(params.get("object", "")))
    inside = bool(params.get("inside", False))

    bm = bmesh.new()
    try:
        bm.from_mesh(obj.data)
        bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
        if inside:
            bmesh.ops.reverse_faces(bm, faces=list(bm.faces))
        bm.to_mesh(obj.data)
        obj.data.update()
    finally:
        bm.free()

    return {"object": obj.name, "inside": inside, "faces": len(obj.data.polygons)}


def mesh_set_shading(params: dict[str, Any], _ctx: ExecutionContext) -> dict[str, Any]:
    obj = _require_mesh(str(params.get("object", "")))
    mode = str(params.get("mode", "smooth")).strip().lower()
    if mode not in ("flat", "smooth", "auto"):
        raise AddonError(
            BridgeErrorCode.INVALID_PARAMS,
            f"Unsupported shading mode {mode!r}.",
            suggestions=["flat", "smooth", "auto"],
        )
    angle_degrees = float(params.get("angle_degrees", 30.0))
    info = set_mesh_shading(obj, mode, angle_degrees=angle_degrees)
    return {"object": obj.name, **info}


def mesh_uv_unwrap(params: dict[str, Any], _ctx: ExecutionContext) -> dict[str, Any]:
    """Deterministic headless-safe UV unwrapping (box, planar, spherical, or smart)."""
    obj = _require_mesh(str(params.get("object", "")))
    method = str(params.get("method", "box")).strip().lower()
    scale = float(params.get("scale", 1.0))
    uv_layer_name = str(params.get("uv_layer", "UVMap"))

    if method not in ("box", "cube", "planar_z", "planar_x", "planar_y", "spherical", "smart"):
        raise AddonError(
            BridgeErrorCode.INVALID_PARAMS,
            f"Unsupported UV unwrap method {method!r}.",
            suggestions=["box", "planar_z", "planar_x", "planar_y", "spherical", "smart"],
        )

    bm = bmesh.new()
    try:
        bm.from_mesh(obj.data)
        bm.normal_update()
        uv_layer = bm.loops.layers.uv.get(uv_layer_name)
        if uv_layer is None:
            uv_layer = bm.loops.layers.uv.new(uv_layer_name)

        # Compute local bounds for normalized projection
        xs = [v.co.x for v in bm.verts] or [0.0]
        ys = [v.co.y for v in bm.verts] or [0.0]
        zs = [v.co.z for v in bm.verts] or [0.0]
        min_v = Vector((min(xs), min(ys), min(zs)))
        span = max(max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs), 1e-5)

        for face in bm.faces:
            n = face.normal
            ax, ay, az = abs(n.x), abs(n.y), abs(n.z)
            for loop in face.loops:
                p = (loop.vert.co - min_v) / span
                if method == "planar_z":
                    u, v = p.x, p.y
                elif method == "planar_x":
                    u, v = p.y, p.z
                elif method == "planar_y":
                    u, v = p.x, p.z
                elif method == "spherical":
                    c = loop.vert.co
                    r = max(c.length, 1e-6)
                    u = 0.5 + math.atan2(c.y, c.x) / (2.0 * math.pi)
                    v = 0.5 - math.asin(max(-1.0, min(1.0, c.z / r))) / math.pi
                else:
                    # Tri-planar box/cube projection (also used as deterministic fallback for 'smart')
                    if az >= ax and az >= ay:
                        u, v = p.x, p.y
                    elif ax >= ay and ax >= az:
                        u, v = p.y, p.z
                    else:
                        u, v = p.x, p.z
                loop[uv_layer].uv = (u * scale, v * scale)

        bm.to_mesh(obj.data)
        obj.data.update()
        loop_count = sum(len(f.loops) for f in bm.faces)
    finally:
        bm.free()

    return {
        "object": obj.name,
        "method": method,
        "uv_layer": uv_layer_name,
        "uv_loops": loop_count,
    }


def register(dispatcher: Dispatcher) -> None:
    dispatcher.register("mesh.stats", mesh_stats, mutating=False)
    dispatcher.register("mesh.extrude", mesh_extrude)
    dispatcher.register("mesh.bevel", mesh_bevel)
    dispatcher.register("mesh.inset", mesh_inset)
    dispatcher.register("mesh.subdivide", mesh_subdivide)
    dispatcher.register("mesh.boolean", mesh_boolean)
    dispatcher.register("mesh.loop_cut", mesh_loop_cut)
    dispatcher.register("mesh.merge_by_distance", mesh_merge_by_distance)
    dispatcher.register("mesh.recalc_normals", mesh_recalc_normals)
    dispatcher.register("mesh.set_shading", mesh_set_shading)
    dispatcher.register("mesh.uv_unwrap", mesh_uv_unwrap)
