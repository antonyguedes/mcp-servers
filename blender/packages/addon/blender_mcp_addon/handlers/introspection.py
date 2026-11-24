# SPDX-License-Identifier: GPL-3.0-or-later
"""Safe RNA data-path inspection/mutation, operator listing/invocation, and bpy API search."""

from __future__ import annotations

import difflib
from typing import Any

import bpy  # type: ignore[import-not-found]

from ..dispatcher import Dispatcher, ExecutionContext
from ..state import resolve_material, resolve_object
from ..wire import AddonError, BridgeErrorCode


def _serialize_rna_value(val: Any, depth: int = 0) -> Any:
    if val is None or isinstance(val, (bool, int, float, str)):
        return round(val, 6) if isinstance(val, float) else val
    if depth > 2:
        return repr(val)
    if hasattr(val, "name") and hasattr(val, "bl_rna"):
        return {"rna_type": val.bl_rna.identifier, "name": val.name}
    if hasattr(val, "__len__") and not isinstance(val, (bytes, bytearray)):
        try:
            items = list(val)
            if len(items) <= 32:
                return [_serialize_rna_value(x, depth + 1) for x in items]
            return f"<{type(val).__name__} len={len(items)}>"
        except Exception:
            pass
    return repr(val)


def _resolve_root(target: str) -> Any:
    raw = target.strip()
    low = raw.lower()
    if low == "scene":
        return bpy.context.scene
    if low == "render":
        return bpy.context.scene.render
    if low == "world":
        return bpy.context.scene.world
    if low == "view_layer":
        return bpy.context.view_layer
    if ":" in raw:
        kind, name = raw.split(":", 1)
        kind = kind.strip().lower()
        name = name.strip()
        if kind in ("object", "obj"):
            return resolve_object(name)
        if kind in ("material", "mat"):
            return resolve_material(name)
        if kind == "collection":
            col = bpy.data.collections.get(name)
            if col is None:
                raise AddonError(BridgeErrorCode.NOT_FOUND, f"Collection {name!r} not found.")
            return col
        if kind == "scene":
            scn = bpy.data.scenes.get(name)
            if scn is None:
                raise AddonError(BridgeErrorCode.NOT_FOUND, f"Scene {name!r} not found.")
            return scn
    # Fallback: try object name directly
    return resolve_object(raw)


def _traverse_rna(root: Any, data_path: str) -> tuple[Any, str]:
    """Walk `a.b.c` cleanly without eval, returning `(parent_obj, leaf_attr)`."""
    if not data_path or any(ch in data_path for ch in ("(", ")", ";", "__")):
        raise AddonError(BridgeErrorCode.INVALID_PARAMS, f"Unsafe or empty RNA data_path {data_path!r}.")
    parts = data_path.split(".")
    curr = root
    for attr in parts[:-1]:
        if not hasattr(curr, attr):
            raise AddonError(
                BridgeErrorCode.NOT_FOUND,
                f"RNA attribute {attr!r} not found while resolving {data_path!r}.",
            )
        curr = getattr(curr, attr)
    leaf = parts[-1]
    if not hasattr(curr, leaf):
        available = [p.identifier for p in curr.bl_rna.properties] if hasattr(curr, "bl_rna") else []
        raise AddonError(
            BridgeErrorCode.NOT_FOUND,
            f"RNA property {leaf!r} not found on {type(curr).__name__}.",
            suggestions=difflib.get_close_matches(leaf, available, n=5, cutoff=0.35),
        )
    return curr, leaf


def get_rna(params: dict[str, Any], _ctx: ExecutionContext) -> dict[str, Any]:
    target = str(params.get("target", "scene"))
    data_path = str(params.get("data_path", "")).strip()
    root = _resolve_root(target)
    if not data_path:
        props = [p.identifier for p in root.bl_rna.properties[:60]] if hasattr(root, "bl_rna") else []
        return {"target": target, "rna_type": type(root).__name__, "properties": props}
    parent, leaf = _traverse_rna(root, data_path)
    value = getattr(parent, leaf)
    return {
        "target": target,
        "data_path": data_path,
        "value": _serialize_rna_value(value),
    }


def set_rna(params: dict[str, Any], _ctx: ExecutionContext) -> dict[str, Any]:
    target = str(params.get("target", "scene"))
    data_path = str(params.get("data_path", "")).strip()
    value = params.get("value")
    root = _resolve_root(target)
    parent, leaf = _traverse_rna(root, data_path)
    try:
        setattr(parent, leaf, value)
    except Exception as exc:
        raise AddonError(
            BridgeErrorCode.INVALID_PARAMS,
            f"Failed setting {target}.{data_path} = {value!r}: {exc}",
        ) from exc
    return {
        "target": target,
        "data_path": data_path,
        "value": _serialize_rna_value(getattr(parent, leaf)),
    }


def list_operators(params: dict[str, Any], _ctx: ExecutionContext) -> dict[str, Any]:
    category = params.get("category")
    search = (params.get("search") or "").strip().lower()
    limit = max(1, min(100, int(params.get("limit", 40))))

    categories = [str(category).strip().lower()] if category else sorted(
        c for c in dir(bpy.ops) if not c.startswith("_")
    )

    found: list[dict[str, Any]] = []
    for cat in categories:
        sub = getattr(bpy.ops, cat, None)
        if sub is None:
            continue
        for op_name in sorted(dir(sub)):
            if op_name.startswith("_"):
                continue
            full_id = f"{cat}.{op_name}"
            if search and search not in full_id.lower():
                continue
            desc = ""
            try:
                rna = getattr(sub, op_name).get_rna_type()
                desc = getattr(rna, "description", "") or getattr(rna, "name", "")
            except Exception:
                pass
            found.append({"id": full_id, "description": desc})
            if len(found) >= limit:
                return {"operators": found, "truncated": True}

    return {"operators": found, "truncated": False}


def call_operator(params: dict[str, Any], _ctx: ExecutionContext) -> dict[str, Any]:
    op_id = str(params.get("operator", "")).strip()
    if "." not in op_id:
        raise AddonError(
            BridgeErrorCode.INVALID_PARAMS,
            f"Operator must be in 'category.name' format (got {op_id!r}).",
        )
    cat, name = op_id.split(".", 1)
    # Block arbitrary script/quit operators through call_operator
    if cat in ("script", "wm") and name in ("quit_blender", "python_file_run", "console_exec"):
        raise AddonError(
            BridgeErrorCode.POLICY_DENIED,
            f"Operator {op_id!r} is restricted for safety.",
        )

    if cat not in dir(bpy.ops):
        raise AddonError(BridgeErrorCode.NOT_FOUND, f"Operator bpy.ops.{op_id} not found.")
    sub = getattr(bpy.ops, cat)
    if name not in dir(sub):
        raise AddonError(BridgeErrorCode.NOT_FOUND, f"Operator bpy.ops.{op_id} not found.")
    op_fn = getattr(sub, name)

    kwargs = params.get("props") or {}
    override_kwargs: dict[str, Any] = {}
    if params.get("active_object"):
        active = resolve_object(str(params["active_object"]))
        override_kwargs["active_object"] = active
        override_kwargs["object"] = active
    if params.get("selected_objects"):
        override_kwargs["selected_objects"] = [resolve_object(str(r)) for r in params["selected_objects"]]

    try:
        if override_kwargs:
            with bpy.context.temp_override(**override_kwargs):
                res = op_fn(**kwargs)
        else:
            res = op_fn(**kwargs)
    except Exception as exc:
        raise AddonError(
            BridgeErrorCode.BLENDER_ERROR,
            f"Operator {op_id} failed: {exc}",
        ) from exc

    return {"operator": op_id, "status": sorted(str(s) for s in res)}


def search_bpy_api(params: dict[str, Any], _ctx: ExecutionContext) -> dict[str, Any]:
    query = str(params.get("query", "")).strip().lower()
    if not query:
        raise AddonError(BridgeErrorCode.INVALID_PARAMS, "'query' cannot be empty.")
    limit = max(1, min(50, int(params.get("limit", 20))))

    matches: list[dict[str, Any]] = []
    for type_name in sorted(dir(bpy.types)):
        if query not in type_name.lower():
            continue
        cls = getattr(bpy.types, type_name, None)
        rna = getattr(cls, "bl_rna", None)
        if rna is None:
            continue
        props = [
            {"name": p.identifier, "type": p.type}
            for p in list(rna.properties)[:15]
            if p.identifier != "rna_type"
        ]
        matches.append(
            {
                "type": type_name,
                "description": getattr(rna, "description", ""),
                "properties": props,
            }
        )
        if len(matches) >= limit:
            break

    return {"query": query, "blender_version": bpy.app.version_string, "matches": matches}


def register(dispatcher: Dispatcher) -> None:
    dispatcher.register("introspection.get_rna", get_rna, mutating=False)
    dispatcher.register("introspection.set_rna", set_rna)
    dispatcher.register("introspection.list_operators", list_operators, mutating=False)
    dispatcher.register("introspection.call_operator", call_operator)
    dispatcher.register("introspection.search_bpy_api", search_bpy_api, mutating=False)
