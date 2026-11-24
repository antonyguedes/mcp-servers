# SPDX-License-Identifier: GPL-3.0-or-later
"""Typed modifier management and headless-safe modifier application."""

from __future__ import annotations

import difflib
from typing import Any

import bpy  # type: ignore[import-not-found]

from ..compat import set_geometry_nodes_input
from ..dispatcher import Dispatcher, ExecutionContext
from ..state import resolve_object
from ..wire import AddonError, BridgeErrorCode

_MODIFIER_ALIASES: dict[str, str] = {
    "subsurf": "SUBSURF",
    "subdivision": "SUBSURF",
    "subdivision_surface": "SUBSURF",
    "bevel": "BEVEL",
    "array": "ARRAY",
    "mirror": "MIRROR",
    "solidify": "SOLIDIFY",
    "boolean": "BOOLEAN",
    "decimate": "DECIMATE",
    "remesh": "REMESH",
    "smooth": "SMOOTH",
    "displace": "DISPLACE",
    "shrinkwrap": "SHRINKWRAP",
    "wireframe": "WIREFRAME",
    "screw": "SCREW",
    "skin": "SKIN",
    "curve": "CURVE",
    "triangulate": "TRIANGULATE",
    "weld": "WELD",
    "weighted_normal": "WEIGHTED_NORMAL",
    "nodes": "NODES",
    "geometry_nodes": "NODES",
    "geonodes": "NODES",
}

_COMMON_READ_PROPS = (
    "levels",
    "render_levels",
    "width",
    "segments",
    "count",
    "thickness",
    "offset",
    "operation",
    "ratio",
    "voxel_size",
    "factor",
    "iterations",
    "use_axis",
    "relative_offset_displace",
    "constant_offset_displace",
    "show_viewport",
    "show_render",
)


def _apply_modifier_settings(mod: Any, settings: dict[str, Any]) -> tuple[list[str], list[str]]:
    applied: list[str] = []
    ignored: list[str] = []
    for key, val in settings.items():
        # Geometry Nodes input socket assignment by identifier or display name
        if (
            mod.type == "NODES"
            and mod.node_group is not None
            and not hasattr(mod, key)
            and set_geometry_nodes_input(mod, key, val)
        ):
            applied.append(key)
            continue

        if not hasattr(mod, key):
            ignored.append(key)
            continue

        prop = mod.bl_rna.properties.get(key)
        if prop is not None and prop.type == "POINTER":
            fixed_type = getattr(prop.fixed_type, "identifier", "")
            if fixed_type == "Object" and isinstance(val, str):
                target_obj = resolve_object(val)
                setattr(mod, key, target_obj)
                applied.append(key)
                continue
            if fixed_type == "NodeTree" and isinstance(val, str):
                ng = bpy.data.node_groups.get(val)
                if ng is None:
                    raise AddonError(BridgeErrorCode.NOT_FOUND, f"Node group {val!r} not found.")
                setattr(mod, key, ng)
                applied.append(key)
                continue
            if val is None:
                setattr(mod, key, None)
                applied.append(key)
                continue

        try:
            setattr(mod, key, val)
            applied.append(key)
        except Exception as exc:
            raise AddonError(
                BridgeErrorCode.INVALID_PARAMS,
                f"Failed to set modifier property {key!r}={val!r}: {exc}",
            ) from exc
    return applied, ignored


def _serialize_modifier(mod: Any) -> dict[str, Any]:
    props: dict[str, Any] = {}
    for k in _COMMON_READ_PROPS:
        if hasattr(mod, k):
            v = getattr(mod, k)
            if isinstance(v, (bool, int, float, str)):
                props[k] = v
            elif hasattr(v, "__len__"):
                props[k] = [round(float(x), 4) if isinstance(x, float) else bool(x) for x in v]
    if getattr(mod, "object", None) is not None:
        props["object"] = mod.object.name
    if getattr(mod, "mirror_object", None) is not None:
        props["mirror_object"] = mod.mirror_object.name
    if mod.type == "NODES" and getattr(mod, "node_group", None) is not None:
        props["node_group"] = mod.node_group.name
    return {"name": mod.name, "type": mod.type, "props": props}


def _find_modifier(obj: Any, mod_name: str) -> Any:
    mod = obj.modifiers.get(mod_name)
    if mod is not None:
        return mod
    names = [m.name for m in obj.modifiers]
    raise AddonError(
        BridgeErrorCode.NOT_FOUND,
        f"Modifier {mod_name!r} not found on {obj.name!r}.",
        suggestions=difflib.get_close_matches(mod_name, names, n=5, cutoff=0.4),
    )


def list_modifiers(params: dict[str, Any], _ctx: ExecutionContext) -> dict[str, Any]:
    obj = resolve_object(str(params.get("object", "")))
    assert obj is not None
    return {
        "object": obj.name,
        "modifiers": [_serialize_modifier(m) for m in obj.modifiers],
    }


def add_modifier(params: dict[str, Any], _ctx: ExecutionContext) -> dict[str, Any]:
    obj = resolve_object(str(params.get("object", "")))
    assert obj is not None
    raw_type = str(params.get("modifier_type", "")).strip()
    mod_type = _MODIFIER_ALIASES.get(raw_type.lower(), raw_type.upper())
    name = str(params.get("name") or mod_type.title())
    settings = params.get("settings") or {}

    try:
        mod = obj.modifiers.new(name=name, type=mod_type)
    except Exception as exc:
        raise AddonError(
            BridgeErrorCode.INVALID_PARAMS,
            f"Unsupported modifier type {raw_type!r} for {obj.name!r}: {exc}",
            suggestions=sorted(set(_MODIFIER_ALIASES.values())),
        ) from exc

    applied, ignored = _apply_modifier_settings(mod, settings)
    bpy.context.view_layer.update()
    return {
        "object": obj.name,
        "modifier": _serialize_modifier(mod),
        "applied_settings": applied,
        "ignored_settings": ignored,
    }


def configure_modifier(params: dict[str, Any], _ctx: ExecutionContext) -> dict[str, Any]:
    obj = resolve_object(str(params.get("object", "")))
    assert obj is not None
    mod = _find_modifier(obj, str(params.get("modifier", "")))
    settings = params.get("settings") or {}
    applied, ignored = _apply_modifier_settings(mod, settings)
    bpy.context.view_layer.update()
    return {
        "object": obj.name,
        "modifier": _serialize_modifier(mod),
        "applied_settings": applied,
        "ignored_settings": ignored,
    }


def reorder_modifier(params: dict[str, Any], _ctx: ExecutionContext) -> dict[str, Any]:
    obj = resolve_object(str(params.get("object", "")))
    assert obj is not None
    mod = _find_modifier(obj, str(params.get("modifier", "")))
    index = int(params.get("index", 0))
    clamped = max(0, min(len(obj.modifiers) - 1, index))
    bpy.context.view_layer.objects.active = obj
    obj.modifiers.move(obj.modifiers.find(mod.name), clamped)
    return {
        "object": obj.name,
        "order": [m.name for m in obj.modifiers],
    }


def apply_modifier(params: dict[str, Any], _ctx: ExecutionContext) -> dict[str, Any]:
    """Bake modifiers into mesh data safely in both GUI and headless modes."""
    obj = resolve_object(str(params.get("object", "")))
    assert obj is not None
    if obj.type != "MESH" or obj.data is None:
        raise AddonError(BridgeErrorCode.INVALID_PARAMS, f"Object {obj.name!r} must be a MESH.")

    mod_name = params.get("modifier")
    if mod_name:
        target_mod = _find_modifier(obj, str(mod_name))
        # Temporarily disable modifiers below target so only target (and those above if needed) evaluate,
        # or evaluate solely target_mod cleanly when applying one modifier
        saved_vis = [(m, m.show_viewport) for m in obj.modifiers]
        for m, _ in saved_vis:
            m.show_viewport = m == target_mod
        bpy.context.view_layer.update()
        depsgraph = bpy.context.evaluated_depsgraph_get()
        eval_obj = obj.evaluated_get(depsgraph)
        new_mesh = bpy.data.meshes.new_from_object(eval_obj)
        for m, vis in saved_vis:
            m.show_viewport = vis
        removed_name = target_mod.name
        obj.modifiers.remove(target_mod)
        old_mesh = obj.data
        obj.data = new_mesh
        new_mesh.name = old_mesh.name
        if old_mesh.users == 0:
            bpy.data.meshes.remove(old_mesh)
        return {
            "object": obj.name,
            "applied": [removed_name],
            "vertices": len(obj.data.vertices),
            "faces": len(obj.data.polygons),
        }

    # Apply all viewport-enabled modifiers
    applied_names = [m.name for m in obj.modifiers]
    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    eval_obj = obj.evaluated_get(depsgraph)
    new_mesh = bpy.data.meshes.new_from_object(eval_obj)
    obj.modifiers.clear()
    old_mesh = obj.data
    obj.data = new_mesh
    new_mesh.name = old_mesh.name
    if old_mesh.users == 0:
        bpy.data.meshes.remove(old_mesh)
    return {
        "object": obj.name,
        "applied": applied_names,
        "vertices": len(obj.data.vertices),
        "faces": len(obj.data.polygons),
    }


def remove_modifier(params: dict[str, Any], _ctx: ExecutionContext) -> dict[str, Any]:
    obj = resolve_object(str(params.get("object", "")))
    assert obj is not None
    mod = _find_modifier(obj, str(params.get("modifier", "")))
    removed = mod.name
    obj.modifiers.remove(mod)
    return {"object": obj.name, "removed": removed}


def register(dispatcher: Dispatcher) -> None:
    dispatcher.register("modifiers.list_modifiers", list_modifiers, mutating=False)
    dispatcher.register("modifiers.add_modifier", add_modifier)
    dispatcher.register("modifiers.configure_modifier", configure_modifier)
    dispatcher.register("modifiers.reorder_modifier", reorder_modifier)
    dispatcher.register("modifiers.apply_modifier", apply_modifier)
    dispatcher.register("modifiers.remove_modifier", remove_modifier)
