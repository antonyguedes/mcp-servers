# SPDX-License-Identifier: GPL-3.0-or-later
"""PBR material creation, assignment, parameter update, and image texture wiring."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import bpy  # type: ignore[import-not-found]

from ..compat import (
    ensure_material_nodes,
    find_or_create_principled_bsdf,
    read_bsdf_params,
    resolve_bsdf_socket,
    set_bsdf_input,
)
from ..dispatcher import Dispatcher, ExecutionContext
from ..state import resolve_material, resolve_object
from ..wire import AddonError, BridgeErrorCode

_PBR_KEYS = (
    "base_color",
    "metallic",
    "roughness",
    "ior",
    "alpha",
    "specular",
    "subsurface",
    "subsurface_scale",
    "transmission",
    "coat_weight",
    "coat_roughness",
    "sheen_weight",
    "emission_color",
    "emission_strength",
)


def _assign_mat_to_obj(obj: Any, mat: Any, slot_index: int | None = None) -> None:
    if not hasattr(obj, "data") or obj.data is None or not hasattr(obj.data, "materials"):
        raise AddonError(
            BridgeErrorCode.INVALID_PARAMS,
            f"Object {obj.name!r} (type {obj.type}) does not support materials.",
        )
    mats = obj.data.materials
    if slot_index is None:
        if len(mats) == 0:
            mats.append(mat)
        else:
            mats[0] = mat
    else:
        while len(mats) <= slot_index:
            mats.append(None)
        mats[slot_index] = mat


def list_materials(_params: dict[str, Any], _ctx: ExecutionContext) -> dict[str, Any]:
    items = []
    for mat in bpy.data.materials:
        bsdf = None
        if getattr(mat, "node_tree", None) is not None:
            bsdf = next((n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
        items.append(
            {
                "name": mat.name,
                "users": mat.users,
                "params": read_bsdf_params(bsdf) if bsdf is not None else {},
            }
        )
    return {"materials": items}


def get_material_details(params: dict[str, Any], _ctx: ExecutionContext) -> dict[str, Any]:
    mat = resolve_material(str(params.get("material", "")))
    assert mat is not None
    tree = getattr(mat, "node_tree", None)
    bsdf = next((n for n in tree.nodes if n.type == "BSDF_PRINCIPLED"), None) if tree else None
    return {
        "name": mat.name,
        "users": mat.users,
        "node_count": len(tree.nodes) if tree else 0,
        "params": read_bsdf_params(bsdf) if bsdf else {},
        "nodes": [
            {"name": n.name, "type": n.type, "bl_idname": n.bl_idname}
            for n in (tree.nodes if tree else [])
        ],
    }


def create_pbr_material(params: dict[str, Any], _ctx: ExecutionContext) -> dict[str, Any]:
    name = str(params.get("name", "Material")).strip() or "Material"
    overwrite = bool(params.get("overwrite", False))

    existing = bpy.data.materials.get(name)
    mat = existing if existing is not None and overwrite else bpy.data.materials.new(name=name)

    bsdf = find_or_create_principled_bsdf(mat)
    if bsdf is None:
        raise AddonError(BridgeErrorCode.BLENDER_ERROR, f"Failed to initialize node tree for {mat.name!r}")

    applied: list[str] = []
    for key in _PBR_KEYS:
        if key in params and params[key] is not None and set_bsdf_input(bsdf, key, params[key]):
            applied.append(key)

    assigned_to: list[str] = []
    for ref in params.get("assign_to") or []:
        obj = resolve_object(str(ref))
        assert obj is not None
        _assign_mat_to_obj(obj, mat)
        assigned_to.append(obj.name)

    return {
        "name": mat.name,
        "applied_params": applied,
        "params": read_bsdf_params(bsdf),
        "assigned_to": assigned_to,
    }


def assign_material(params: dict[str, Any], _ctx: ExecutionContext) -> dict[str, Any]:
    mat = resolve_material(str(params.get("material", "")))
    assert mat is not None
    refs = params.get("objects") or []
    if params.get("object"):
        refs = [params["object"], *refs]
    if not refs:
        raise AddonError(BridgeErrorCode.INVALID_PARAMS, "Provide 'object' or 'objects'.")
    slot_index = params.get("slot_index")
    slot_int = int(slot_index) if slot_index is not None else None

    assigned: list[str] = []
    for ref in refs:
        obj = resolve_object(str(ref))
        assert obj is not None
        _assign_mat_to_obj(obj, mat, slot_int)
        assigned.append(obj.name)

    return {"material": mat.name, "assigned_to": assigned, "slot_index": slot_int}


def set_material_params(params: dict[str, Any], _ctx: ExecutionContext) -> dict[str, Any]:
    mat = resolve_material(str(params.get("material", "")))
    assert mat is not None
    bsdf = find_or_create_principled_bsdf(mat)
    if bsdf is None:
        raise AddonError(BridgeErrorCode.BLENDER_ERROR, f"Material {mat.name!r} has no node tree.")

    updates = params.get("params") or {}
    # Also accept top-level canonical keys for convenience
    merged: dict[str, Any] = dict(updates)
    for key in _PBR_KEYS:
        if key in params and params[key] is not None:
            merged[key] = params[key]

    applied: list[str] = []
    ignored: list[str] = []
    for k, v in merged.items():
        if set_bsdf_input(bsdf, k, v):
            applied.append(k)
        else:
            ignored.append(k)

    return {
        "material": mat.name,
        "applied": applied,
        "ignored": ignored,
        "params": read_bsdf_params(bsdf),
    }


def create_texture_from_image(params: dict[str, Any], _ctx: ExecutionContext) -> dict[str, Any]:
    mat = resolve_material(str(params.get("material", "")))
    assert mat is not None
    filepath = str(params.get("filepath", "")).strip()
    if not filepath or not Path(filepath).is_file():
        raise AddonError(BridgeErrorCode.NOT_FOUND, f"Image file not found: {filepath!r}")

    channel = str(params.get("channel", "base_color")).strip().lower()
    colorspace = params.get("colorspace")
    normal_strength = float(params.get("normal_strength", 1.0))

    tree = ensure_material_nodes(mat)
    bsdf = find_or_create_principled_bsdf(mat)
    assert tree is not None and bsdf is not None

    img = bpy.data.images.load(filepath, check_existing=True)
    if colorspace:
        img.colorspace_settings.name = str(colorspace)
    elif channel in ("roughness", "metallic", "normal", "alpha", "specular"):
        try:
            img.colorspace_settings.name = "Non-Color"
        except Exception:
            pass

    tex_node = tree.nodes.new("ShaderNodeTexImage")
    tex_node.image = img
    tex_node.location = (-450, 0)

    if channel == "normal":
        normal_node = tree.nodes.new("ShaderNodeNormalMap")
        normal_node.location = (-200, -150)
        normal_node.inputs["Strength"].default_value = normal_strength
        tree.links.new(tex_node.outputs["Color"], normal_node.inputs["Color"])
        norm_sock = bsdf.inputs.get("Normal")
        if norm_sock is None:
            raise AddonError(BridgeErrorCode.BLENDER_ERROR, "Principled BSDF has no Normal input.")
        tree.links.new(normal_node.outputs["Normal"], norm_sock)
    else:
        target_sock = resolve_bsdf_socket(bsdf, channel)
        if target_sock is None:
            raise AddonError(
                BridgeErrorCode.INVALID_PARAMS,
                f"Unknown material channel {channel!r}.",
                suggestions=["base_color", "roughness", "metallic", "normal", "emission_color", "alpha"],
            )
        tree.links.new(tex_node.outputs["Color"], target_sock)

    return {
        "material": mat.name,
        "image": img.name,
        "channel": channel,
        "node": tex_node.name,
    }


def register(dispatcher: Dispatcher) -> None:
    dispatcher.register("materials.list_materials", list_materials, mutating=False)
    dispatcher.register("materials.get_material_details", get_material_details, mutating=False)
    dispatcher.register("materials.create_pbr_material", create_pbr_material)
    dispatcher.register("materials.assign_material", assign_material)
    dispatcher.register("materials.set_material_params", set_material_params)
    dispatcher.register("materials.create_texture_from_image", create_texture_from_image)
