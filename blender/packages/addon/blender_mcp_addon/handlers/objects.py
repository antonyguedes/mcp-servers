# SPDX-License-Identifier: GPL-3.0-or-later
"""Object creation, transformation, hierarchy, and geometry utility handlers.

Implemented primarily via `bmesh` and `bpy.data` so every operation works
reliably in both GUI and headless (`--background`) Blender sessions.
"""

from __future__ import annotations

import math
from typing import Any

import bmesh  # type: ignore[import-not-found]
import bpy  # type: ignore[import-not-found]
from mathutils import Euler, Matrix, Vector  # type: ignore[import-not-found]

from ..compat import get_object_bbox_world
from ..dispatcher import Dispatcher, ExecutionContext
from ..state import ensure_object_uid, resolve_collection, resolve_object
from ..wire import AddonError, BridgeErrorCode


def _link_to_collection(obj: Any, collection_name: str | None) -> None:
    target = resolve_collection(collection_name) if collection_name else bpy.context.scene.collection
    assert target is not None
    if obj.name not in target.objects:
        target.objects.link(obj)


def _apply_initial_trs(obj: Any, params: dict[str, Any]) -> None:
    loc = params.get("location")
    rot = params.get("rotation_degrees")
    scl = params.get("scale")
    if loc is not None:
        obj.location = Vector((float(loc[0]), float(loc[1]), float(loc[2])))
    if rot is not None:
        obj.rotation_euler = Euler(
            (math.radians(float(rot[0])), math.radians(float(rot[1])), math.radians(float(rot[2]))),
            "XYZ",
        )
    if scl is not None:
        if isinstance(scl, (int, float)):
            s = float(scl)
            obj.scale = Vector((s, s, s))
        else:
            obj.scale = Vector((float(scl[0]), float(scl[1]), float(scl[2])))


def _build_torus_bmesh(
    bm: Any,
    major_radius: float,
    minor_radius: float,
    major_segments: int,
    minor_segments: int,
) -> None:
    rings: list[list[Any]] = []
    for i in range(major_segments):
        theta = 2.0 * math.pi * i / major_segments
        cos_t, sin_t = math.cos(theta), math.sin(theta)
        ring: list[Any] = []
        for j in range(minor_segments):
            phi = 2.0 * math.pi * j / minor_segments
            r = major_radius + minor_radius * math.cos(phi)
            x = r * cos_t
            y = r * sin_t
            z = minor_radius * math.sin(phi)
            ring.append(bm.verts.new((x, y, z)))
        rings.append(ring)
    for i in range(major_segments):
        next_i = (i + 1) % major_segments
        for j in range(minor_segments):
            next_j = (j + 1) % minor_segments
            bm.faces.new(
                (
                    rings[i][j],
                    rings[next_i][j],
                    rings[next_i][next_j],
                    rings[i][next_j],
                )
            )


def create_primitive(params: dict[str, Any], _ctx: ExecutionContext) -> dict[str, Any]:
    prim = str(params.get("primitive", "cube")).strip().lower()
    name = str(params.get("name") or prim.capitalize())
    collection_name = params.get("collection")
    size = float(params.get("size", 2.0))
    radius = float(params.get("radius", size * 0.5))
    depth = float(params.get("depth", size))
    segments = max(3, int(params.get("segments", 32)))
    rings = max(3, int(params.get("rings", 16)))
    subdivisions = max(1, min(6, int(params.get("subdivisions", 2))))

    if prim == "empty":
        obj = bpy.data.objects.new(name, None)
        obj.empty_display_type = str(params.get("empty_type", "PLAIN_AXES")).upper()
        obj.empty_display_size = size * 0.5
        _link_to_collection(obj, collection_name)
        _apply_initial_trs(obj, params)
    elif prim == "text":
        curve = bpy.data.curves.new(name=name, type="FONT")
        curve.body = str(params.get("text", "Text"))
        curve.size = size * 0.5
        obj = bpy.data.objects.new(name, curve)
        _link_to_collection(obj, collection_name)
        _apply_initial_trs(obj, params)
    else:
        bm = bmesh.new()
        try:
            if prim == "cube":
                bmesh.ops.create_cube(bm, size=size)
            elif prim in ("uv_sphere", "sphere"):
                bmesh.ops.create_uvsphere(bm, u_segments=segments, v_segments=rings, radius=radius)
            elif prim == "ico_sphere":
                bmesh.ops.create_icosphere(bm, subdivisions=subdivisions, radius=radius)
            elif prim == "cylinder":
                bmesh.ops.create_cone(
                    bm,
                    cap_ends=True,
                    cap_tris=False,
                    segments=segments,
                    radius1=radius,
                    radius2=radius,
                    depth=depth,
                )
            elif prim == "cone":
                radius2 = float(params.get("radius2", 0.0))
                bmesh.ops.create_cone(
                    bm,
                    cap_ends=True,
                    cap_tris=False,
                    segments=segments,
                    radius1=radius,
                    radius2=radius2,
                    depth=depth,
                )
            elif prim == "plane":
                bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=size * 0.5)
            elif prim == "grid":
                x_seg = max(1, int(params.get("x_segments", 10)))
                y_seg = max(1, int(params.get("y_segments", 10)))
                bmesh.ops.create_grid(bm, x_segments=x_seg, y_segments=y_seg, size=size * 0.5)
            elif prim == "torus":
                major_r = float(params.get("major_radius", radius))
                minor_r = float(params.get("minor_radius", radius * 0.25))
                _build_torus_bmesh(bm, major_r, minor_r, segments, max(3, int(params.get("minor_segments", 16))))
            elif prim in ("monkey", "suzanne"):
                bmesh.ops.create_monkey(bm)
            else:
                raise AddonError(
                    BridgeErrorCode.INVALID_PARAMS,
                    f"Unsupported primitive type {prim!r}.",
                    suggestions=[
                        "cube",
                        "uv_sphere",
                        "ico_sphere",
                        "cylinder",
                        "cone",
                        "torus",
                        "plane",
                        "grid",
                        "monkey",
                        "empty",
                        "text",
                    ],
                )

            mesh = bpy.data.meshes.new(name)
            bm.to_mesh(mesh)
            mesh.update()
        finally:
            bm.free()

        if params.get("smooth", False):
            mesh.polygons.foreach_set("use_smooth", [True] * len(mesh.polygons))
            mesh.update()

        obj = bpy.data.objects.new(name, mesh)
        _link_to_collection(obj, collection_name)
        _apply_initial_trs(obj, params)

    uid = ensure_object_uid(obj)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    return {
        "uid": uid,
        "name": obj.name,
        "type": obj.type,
        "location": [round(float(v), 4) for v in obj.location],
        "bbox_world": get_object_bbox_world(obj),
    }


def create_mesh_object(params: dict[str, Any], _ctx: ExecutionContext) -> dict[str, Any]:
    name = str(params.get("name", "CustomMesh"))
    vertices = params.get("vertices") or []
    edges = params.get("edges") or []
    faces = params.get("faces") or []
    collection_name = params.get("collection")

    if not vertices:
        raise AddonError(BridgeErrorCode.INVALID_PARAMS, "'vertices' must contain at least one vertex.")

    verts_tuples = [(float(v[0]), float(v[1]), float(v[2])) for v in vertices]
    edges_tuples = [(int(e[0]), int(e[1])) for e in edges]
    faces_tuples = [tuple(int(i) for i in f) for f in faces]

    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts_tuples, edges_tuples, faces_tuples)
    mesh.validate(verbose=False)
    mesh.update()

    if params.get("smooth", False) and len(mesh.polygons) > 0:
        mesh.polygons.foreach_set("use_smooth", [True] * len(mesh.polygons))
        mesh.update()

    obj = bpy.data.objects.new(name, mesh)
    _link_to_collection(obj, collection_name)
    _apply_initial_trs(obj, params)

    uid = ensure_object_uid(obj)
    bpy.context.view_layer.objects.active = obj
    return {
        "uid": uid,
        "name": obj.name,
        "vertices": len(mesh.vertices),
        "edges": len(mesh.edges),
        "polygons": len(mesh.polygons),
        "bbox_world": get_object_bbox_world(obj),
    }


def transform_object(params: dict[str, Any], _ctx: ExecutionContext) -> dict[str, Any]:
    obj = resolve_object(str(params.get("object", "")))
    assert obj is not None
    relative = bool(params.get("relative", False))
    space = str(params.get("space", "world")).lower()

    loc = params.get("location")
    rot = params.get("rotation_degrees")
    scl = params.get("scale")

    if space == "local" and relative:
        if loc is not None:
            delta = Vector((float(loc[0]), float(loc[1]), float(loc[2])))
            obj.location = obj.location + (obj.rotation_euler.to_matrix() @ delta)
        if rot is not None:
            delta_rot = Euler(
                (math.radians(float(rot[0])), math.radians(float(rot[1])), math.radians(float(rot[2]))),
                "XYZ",
            )
            obj.rotation_euler = (obj.rotation_euler.to_matrix() @ delta_rot.to_matrix()).to_euler()
        if scl is not None:
            sv = Vector((float(scl), float(scl), float(scl))) if isinstance(scl, (int, float)) else Vector(
                (float(scl[0]), float(scl[1]), float(scl[2]))
            )
            obj.scale = Vector((obj.scale.x * sv.x, obj.scale.y * sv.y, obj.scale.z * sv.z))
    else:
        if loc is not None:
            v = Vector((float(loc[0]), float(loc[1]), float(loc[2])))
            obj.location = (obj.location + v) if relative else v
        if rot is not None:
            r = Euler(
                (math.radians(float(rot[0])), math.radians(float(rot[1])), math.radians(float(rot[2]))),
                "XYZ",
            )
            if relative:
                obj.rotation_euler = Euler(
                    (
                        obj.rotation_euler.x + r.x,
                        obj.rotation_euler.y + r.y,
                        obj.rotation_euler.z + r.z,
                    ),
                    "XYZ",
                )
            else:
                obj.rotation_euler = r
        if scl is not None:
            sv = Vector((float(scl), float(scl), float(scl))) if isinstance(scl, (int, float)) else Vector(
                (float(scl[0]), float(scl[1]), float(scl[2]))
            )
            if relative:
                obj.scale = Vector((obj.scale.x * sv.x, obj.scale.y * sv.y, obj.scale.z * sv.z))
            else:
                obj.scale = sv

    bpy.context.view_layer.update()
    return {
        "uid": ensure_object_uid(obj),
        "name": obj.name,
        "location": [round(float(v), 4) for v in obj.location],
        "rotation_degrees": [round(math.degrees(float(a)), 3) for a in obj.rotation_euler],
        "scale": [round(float(v), 4) for v in obj.scale],
        "bbox_world": get_object_bbox_world(obj),
    }


def duplicate_object(params: dict[str, Any], _ctx: ExecutionContext) -> dict[str, Any]:
    src = resolve_object(str(params.get("object", "")))
    assert src is not None
    linked = bool(params.get("linked", False))
    new_name = params.get("new_name")
    offset = params.get("offset")
    count = max(1, min(100, int(params.get("count", 1))))

    created: list[dict[str, Any]] = []
    for idx in range(count):
        dup = src.copy()
        if not linked and src.data is not None:
            dup.data = src.data.copy()
        # Reset UID so duplicate receives a fresh persistent UID
        if "blender_mcp_uid" in dup:
            del dup["blender_mcp_uid"]
        if new_name:
            dup.name = f"{new_name}_{idx + 1}" if count > 1 else str(new_name)
        for col in src.users_collection:
            col.objects.link(dup)
        if not src.users_collection:
            bpy.context.scene.collection.objects.link(dup)
        if offset is not None:
            step = idx + 1
            dup.location = src.location + Vector(
                (float(offset[0]) * step, float(offset[1]) * step, float(offset[2]) * step)
            )
        uid = ensure_object_uid(dup)
        created.append(
            {
                "uid": uid,
                "name": dup.name,
                "location": [round(float(v), 4) for v in dup.location],
            }
        )

    bpy.context.view_layer.update()
    return {"duplicated_from": src.name, "created": created}


def delete_objects(params: dict[str, Any], _ctx: ExecutionContext) -> dict[str, Any]:
    refs = params.get("objects") or []
    include_children = bool(params.get("include_children", False))
    if not refs:
        raise AddonError(BridgeErrorCode.INVALID_PARAMS, "Provide at least one object to delete.")

    to_delete: list[Any] = []
    seen: set[int] = set()

    def _collect(obj: Any) -> None:
        key = obj.as_pointer()
        if key in seen:
            return
        seen.add(key)
        to_delete.append(obj)
        if include_children:
            for child in list(obj.children):
                _collect(child)

    for ref in refs:
        obj = resolve_object(str(ref))
        assert obj is not None
        _collect(obj)

    deleted_names: list[str] = []
    for obj in to_delete:
        name = obj.name
        data = obj.data
        bpy.data.objects.remove(obj, do_unlink=True)
        if data is not None and data.users == 0:
            try:
                if isinstance(data, bpy.types.Mesh):
                    bpy.data.meshes.remove(data)
                elif isinstance(data, bpy.types.Light):
                    bpy.data.lights.remove(data)
                elif isinstance(data, bpy.types.Camera):
                    bpy.data.cameras.remove(data)
                elif isinstance(data, bpy.types.Curve):
                    bpy.data.curves.remove(data)
            except Exception:
                pass
        deleted_names.append(name)

    return {"deleted": deleted_names}


def parent_objects(params: dict[str, Any], _ctx: ExecutionContext) -> dict[str, Any]:
    child_refs = params.get("children") or []
    if params.get("child"):
        child_refs = [params["child"], *child_refs]
    if not child_refs:
        raise AddonError(BridgeErrorCode.INVALID_PARAMS, "Provide 'child' or 'children'.")

    parent_ref = params.get("parent")
    keep_transform = bool(params.get("keep_transform", True))
    parent_obj = resolve_object(str(parent_ref)) if parent_ref else None

    bpy.context.view_layer.update()
    updated: list[str] = []
    for ref in child_refs:
        child = resolve_object(str(ref))
        assert child is not None
        if parent_obj is not None and child == parent_obj:
            raise AddonError(BridgeErrorCode.INVALID_PARAMS, "An object cannot be parented to itself.")
        saved_world = child.matrix_world.copy()
        if parent_obj is None:
            child.parent = None
            if keep_transform:
                child.matrix_world = saved_world
        else:
            child.parent = parent_obj
            if keep_transform:
                child.matrix_parent_inverse = parent_obj.matrix_world.inverted()
                child.matrix_world = saved_world
        updated.append(child.name)

    bpy.context.view_layer.update()
    return {"parent": parent_obj.name if parent_obj else None, "children": updated}


def join_objects(params: dict[str, Any], _ctx: ExecutionContext) -> dict[str, Any]:
    target = resolve_object(str(params.get("target", "")))
    assert target is not None
    if target.type != "MESH" or target.data is None:
        raise AddonError(BridgeErrorCode.INVALID_PARAMS, f"Target {target.name!r} must be a MESH object.")

    source_refs = params.get("sources") or []
    if not source_refs:
        raise AddonError(BridgeErrorCode.INVALID_PARAMS, "Provide at least one source mesh to join.")

    sources: list[Any] = []
    for ref in source_refs:
        src = resolve_object(str(ref))
        assert src is not None
        if src == target:
            continue
        if src.type != "MESH" or src.data is None:
            raise AddonError(BridgeErrorCode.INVALID_PARAMS, f"Source {src.name!r} must be a MESH object.")
        sources.append(src)

    bpy.context.view_layer.update()
    target_inv = target.matrix_world.inverted()
    target_bm = bmesh.new()
    try:
        target_bm.from_mesh(target.data)
        target_mats = [s.material for s in target.material_slots]

        joined_names: list[str] = []
        for src in sources:
            rel_mat = target_inv @ src.matrix_world
            src_bm = bmesh.new()
            try:
                src_bm.from_mesh(src.data)
                bmesh.ops.transform(src_bm, matrix=rel_mat, verts=src_bm.verts)
                src_bm.verts.ensure_lookup_table()
                src_bm.verts.index_update()

                # Remap material indices cleanly
                mat_remap: dict[int, int] = {}
                for idx, slot in enumerate(src.material_slots):
                    mat = slot.material
                    if mat not in target_mats:
                        target.data.materials.append(mat)
                        target_mats.append(mat)
                    mat_remap[idx] = target_mats.index(mat)

                vert_map = {}
                for v in src_bm.verts:
                    vert_map[v.index] = target_bm.verts.new(v.co)
                for e in src_bm.edges:
                    v1, v2 = vert_map[e.verts[0].index], vert_map[e.verts[1].index]
                    try:
                        target_bm.edges.new((v1, v2))
                    except ValueError:
                        pass
                for f in src_bm.faces:
                    try:
                        nf = target_bm.faces.new([vert_map[v.index] for v in f.verts])
                        nf.smooth = f.smooth
                        if f.material_index in mat_remap:
                            nf.material_index = mat_remap[f.material_index]
                    except ValueError:
                        pass
            finally:
                src_bm.free()

            joined_names.append(src.name)
            src_data = src.data
            bpy.data.objects.remove(src, do_unlink=True)
            if src_data.users == 0:
                bpy.data.meshes.remove(src_data)

        target_bm.to_mesh(target.data)
        target.data.update()
    finally:
        target_bm.free()

    return {
        "target": target.name,
        "joined": joined_names,
        "vertices": len(target.data.vertices),
        "polygons": len(target.data.polygons),
    }


def apply_transforms(params: dict[str, Any], _ctx: ExecutionContext) -> dict[str, Any]:
    obj = resolve_object(str(params.get("object", "")))
    assert obj is not None
    apply_loc = bool(params.get("location", False))
    apply_rot = bool(params.get("rotation", True))
    apply_scl = bool(params.get("scale", True))

    if obj.type != "MESH" or obj.data is None:
        raise AddonError(
            BridgeErrorCode.INVALID_PARAMS,
            f"apply_transforms currently supports MESH objects; {obj.name!r} is {obj.type}.",
        )

    loc_mat = Matrix.Translation(obj.location) if apply_loc else Matrix.Identity(4)
    rot_mat = obj.rotation_euler.to_matrix().to_4x4() if apply_rot else Matrix.Identity(4)
    scl_mat = Matrix.Diagonal((obj.scale.x, obj.scale.y, obj.scale.z, 1.0)) if apply_scl else Matrix.Identity(4)
    xf = loc_mat @ rot_mat @ scl_mat

    if obj.data.users > 1:
        obj.data = obj.data.copy()
    obj.data.transform(xf)
    obj.data.update()

    if apply_loc:
        obj.location = Vector((0.0, 0.0, 0.0))
    if apply_rot:
        obj.rotation_euler = Euler((0.0, 0.0, 0.0), "XYZ")
    if apply_scl:
        obj.scale = Vector((1.0, 1.0, 1.0))

    bpy.context.view_layer.update()
    return {
        "name": obj.name,
        "applied": {"location": apply_loc, "rotation": apply_rot, "scale": apply_scl},
        "bbox_world": get_object_bbox_world(obj),
    }


def set_origin(params: dict[str, Any], _ctx: ExecutionContext) -> dict[str, Any]:
    obj = resolve_object(str(params.get("object", "")))
    assert obj is not None
    if obj.type != "MESH" or obj.data is None:
        raise AddonError(
            BridgeErrorCode.INVALID_PARAMS,
            f"set_origin requires a MESH object; {obj.name!r} is {obj.type}.",
        )

    origin_type = str(params.get("origin_type", "bounds")).lower()
    bpy.context.view_layer.update()

    if origin_type == "geometry":
        verts = obj.data.vertices
        if not verts:
            local_target = Vector((0.0, 0.0, 0.0))
        else:
            local_target = sum((v.co for v in verts), Vector((0.0, 0.0, 0.0))) / len(verts)
    elif origin_type == "bounds":
        corners = [Vector(c) for c in obj.bound_box]
        local_target = sum(corners, Vector((0.0, 0.0, 0.0))) / len(corners)
    elif origin_type == "bottom_center":
        corners = [Vector(c) for c in obj.bound_box]
        xs = [c.x for c in corners]
        ys = [c.y for c in corners]
        zs = [c.z for c in corners]
        local_target = Vector(((min(xs) + max(xs)) * 0.5, (min(ys) + max(ys)) * 0.5, min(zs)))
    elif origin_type == "world":
        local_target = obj.matrix_world.inverted() @ Vector((0.0, 0.0, 0.0))
    elif origin_type == "cursor":
        local_target = obj.matrix_world.inverted() @ bpy.context.scene.cursor.location
    elif origin_type == "custom":
        pt = params.get("point")
        if not pt or len(pt) != 3:
            raise AddonError(BridgeErrorCode.INVALID_PARAMS, "'point' [x, y, z] is required for custom origin.")
        local_target = obj.matrix_world.inverted() @ Vector((float(pt[0]), float(pt[1]), float(pt[2])))
    else:
        raise AddonError(
            BridgeErrorCode.INVALID_PARAMS,
            f"Unknown origin_type {origin_type!r}.",
            suggestions=["bounds", "geometry", "bottom_center", "world", "cursor", "custom"],
        )

    if obj.data.users > 1:
        obj.data = obj.data.copy()
    world_target = obj.matrix_world @ local_target
    obj.data.transform(Matrix.Translation(-local_target))
    obj.data.update()
    obj.matrix_world.translation = world_target
    bpy.context.view_layer.update()

    return {
        "name": obj.name,
        "origin_type": origin_type,
        "location": [round(float(v), 4) for v in obj.location],
    }


def rename_object(params: dict[str, Any], _ctx: ExecutionContext) -> dict[str, Any]:
    obj = resolve_object(str(params.get("object", "")))
    assert obj is not None
    new_name = str(params.get("new_name", "")).strip()
    if not new_name:
        raise AddonError(BridgeErrorCode.INVALID_PARAMS, "'new_name' cannot be empty.")
    old_name = obj.name
    obj.name = new_name
    if params.get("rename_data", False) and obj.data is not None:
        obj.data.name = new_name
    return {
        "uid": ensure_object_uid(obj),
        "old_name": old_name,
        "new_name": obj.name,
    }


def align_to_ground(params: dict[str, Any], _ctx: ExecutionContext) -> dict[str, Any]:
    refs = params.get("objects") or []
    if params.get("object"):
        refs = [params["object"], *refs]
    if not refs:
        raise AddonError(BridgeErrorCode.INVALID_PARAMS, "Provide 'object' or 'objects'.")
    target_z = float(params.get("target_z", 0.0))

    aligned: list[dict[str, Any]] = []
    for ref in refs:
        obj = resolve_object(str(ref))
        assert obj is not None
        bbox = get_object_bbox_world(obj)
        delta_z = target_z - bbox["min"][2]
        obj.location.z += delta_z
        bpy.context.view_layer.update()
        aligned.append(
            {
                "name": obj.name,
                "delta_z": round(delta_z, 4),
                "location": [round(float(v), 4) for v in obj.location],
            }
        )
    return {"target_z": target_z, "aligned": aligned}


def register(dispatcher: Dispatcher) -> None:
    dispatcher.register("objects.create_primitive", create_primitive)
    dispatcher.register("objects.create_mesh_object", create_mesh_object)
    dispatcher.register("objects.transform", transform_object)
    dispatcher.register("objects.duplicate", duplicate_object)
    dispatcher.register("objects.delete", delete_objects)
    dispatcher.register("objects.parent", parent_objects)
    dispatcher.register("objects.join", join_objects)
    dispatcher.register("objects.apply_transforms", apply_transforms)
    dispatcher.register("objects.set_origin", set_origin)
    dispatcher.register("objects.rename", rename_object)
    dispatcher.register("objects.align_to_ground", align_to_ground)
