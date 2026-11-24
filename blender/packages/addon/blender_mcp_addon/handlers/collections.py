# SPDX-License-Identifier: GPL-3.0-or-later
"""Collection and view-layer management handlers."""

from __future__ import annotations

from typing import Any

import bpy  # type: ignore[import-not-found]

from ..dispatcher import Dispatcher, ExecutionContext
from ..state import resolve_collection, resolve_object
from ..wire import AddonError, BridgeErrorCode


def _find_layer_collection(layer_col: Any, target_name: str) -> Any | None:
    if layer_col.collection.name == target_name:
        return layer_col
    for child in layer_col.children:
        found = _find_layer_collection(child, target_name)
        if found is not None:
            return found
    return None


def list_collections(_params: dict[str, Any], _ctx: ExecutionContext) -> dict[str, Any]:
    items = []
    for col in bpy.data.collections:
        items.append(
            {
                "name": col.name,
                "object_count": len(col.objects),
                "objects": [o.name for o in col.objects],
                "children": [c.name for c in col.children],
                "hide_viewport": col.hide_viewport,
                "hide_render": col.hide_render,
            }
        )
    return {"collections": items}


def create_collection(params: dict[str, Any], _ctx: ExecutionContext) -> dict[str, Any]:
    name = str(params.get("name", "")).strip()
    if not name:
        raise AddonError(BridgeErrorCode.INVALID_PARAMS, "Collection 'name' is required.")
    parent_name = params.get("parent")
    parent = resolve_collection(str(parent_name)) if parent_name else bpy.context.scene.collection
    assert parent is not None

    col = bpy.data.collections.new(name)
    parent.children.link(col)
    return {"name": col.name, "parent": parent.name}


def move_to_collection(params: dict[str, Any], _ctx: ExecutionContext) -> dict[str, Any]:
    refs = params.get("objects") or []
    if params.get("object"):
        refs = [params["object"], *refs]
    if not refs:
        raise AddonError(BridgeErrorCode.INVALID_PARAMS, "Provide 'object' or 'objects'.")
    target = resolve_collection(str(params.get("collection", "")))
    assert target is not None
    link_only = bool(params.get("link_only", False))

    moved: list[str] = []
    for ref in refs:
        obj = resolve_object(str(ref))
        assert obj is not None
        if not link_only:
            for existing in list(obj.users_collection):
                if existing != target:
                    existing.objects.unlink(obj)
        if obj.name not in target.objects:
            target.objects.link(obj)
        moved.append(obj.name)

    return {"collection": target.name, "objects": moved, "link_only": link_only}


def set_collection_visibility(params: dict[str, Any], _ctx: ExecutionContext) -> dict[str, Any]:
    col = resolve_collection(str(params.get("collection", "")))
    assert col is not None

    if "hide_viewport" in params and params["hide_viewport"] is not None:
        col.hide_viewport = bool(params["hide_viewport"])
    if "hide_render" in params and params["hide_render"] is not None:
        col.hide_render = bool(params["hide_render"])
    if "exclude" in params and params["exclude"] is not None:
        lc = _find_layer_collection(bpy.context.view_layer.layer_collection, col.name)
        if lc is not None:
            lc.exclude = bool(params["exclude"])

    lc = _find_layer_collection(bpy.context.view_layer.layer_collection, col.name)
    return {
        "collection": col.name,
        "hide_viewport": col.hide_viewport,
        "hide_render": col.hide_render,
        "exclude": lc.exclude if lc is not None else False,
    }


def list_view_layers(_params: dict[str, Any], _ctx: ExecutionContext) -> dict[str, Any]:
    active = bpy.context.view_layer
    return {
        "active": active.name,
        "view_layers": [
            {"name": vl.name, "use": vl.use}
            for vl in bpy.context.scene.view_layers
        ],
    }


def register(dispatcher: Dispatcher) -> None:
    dispatcher.register("collections.list_collections", list_collections, mutating=False)
    dispatcher.register("collections.create_collection", create_collection)
    dispatcher.register("collections.move_to_collection", move_to_collection)
    dispatcher.register("collections.set_collection_visibility", set_collection_visibility)
    dispatcher.register("collections.list_view_layers", list_view_layers, mutating=False)
