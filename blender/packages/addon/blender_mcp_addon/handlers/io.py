# SPDX-License-Identifier: GPL-3.0-or-later
"""Cross-version 3D file I/O (glTF, FBX, OBJ, USD, STL, PLY, Alembic, .blend, libraries)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import bpy  # type: ignore[import-not-found]

from ..dispatcher import Dispatcher, ExecutionContext
from ..state import ensure_object_uid
from ..wire import AddonError, BridgeErrorCode


def _infer_format(filepath: Path, explicit: str | None) -> str:
    if explicit:
        return explicit.strip().lower().lstrip(".")
    ext = filepath.suffix.lower().lstrip(".")
    if ext in ("glb", "gltf", "fbx", "obj", "stl", "ply", "usd", "usda", "usdc", "abc"):
        return ext
    raise AddonError(
        BridgeErrorCode.INVALID_PARAMS,
        f"Cannot infer 3D format from extension {filepath.suffix!r}. Pass 'file_format' explicitly.",
        suggestions=["glb", "gltf", "fbx", "obj", "stl", "ply", "usd", "abc"],
    )


def export_file(params: dict[str, Any], _ctx: ExecutionContext) -> dict[str, Any]:
    raw_path = str(params.get("filepath", "")).strip()
    if not raw_path:
        raise AddonError(BridgeErrorCode.INVALID_PARAMS, "'filepath' is required.")
    path = Path(raw_path).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    fmt = _infer_format(path, params.get("file_format"))
    selected_only = bool(params.get("selected_only", False))

    if fmt in ("glb", "gltf"):
        export_fmt = "GLB" if fmt == "glb" else "GLTF_SEPARATE"
        bpy.ops.export_scene.gltf(
            filepath=str(path),
            export_format=export_fmt,
            use_selection=selected_only,
        )
    elif fmt == "fbx":
        bpy.ops.export_scene.fbx(filepath=str(path), use_selection=selected_only)
    elif fmt == "obj":
        if hasattr(bpy.ops.wm, "obj_export"):
            bpy.ops.wm.obj_export(filepath=str(path), export_selected_objects=selected_only)
        else:
            bpy.ops.export_scene.obj(filepath=str(path), use_selection=selected_only)
    elif fmt == "stl":
        if hasattr(bpy.ops.wm, "stl_export"):
            bpy.ops.wm.stl_export(filepath=str(path), export_selected_objects=selected_only)
        else:
            bpy.ops.export_mesh.stl(filepath=str(path), use_selection=selected_only)
    elif fmt == "ply":
        if hasattr(bpy.ops.wm, "ply_export"):
            bpy.ops.wm.ply_export(filepath=str(path), export_selected_objects=selected_only)
        else:
            bpy.ops.export_mesh.ply(filepath=str(path), use_selection=selected_only)
    elif fmt in ("usd", "usda", "usdc"):
        bpy.ops.wm.usd_export(filepath=str(path), selected_objects_only=selected_only)
    elif fmt == "abc":
        bpy.ops.wm.alembic_export(filepath=str(path), selected=selected_only)
    else:
        raise AddonError(
            BridgeErrorCode.INVALID_PARAMS,
            f"Unsupported export format {fmt!r}.",
            suggestions=["glb", "gltf", "fbx", "obj", "stl", "ply", "usd", "abc"],
        )

    return {
        "filepath": str(path),
        "format": fmt,
        "exists": path.exists(),
        "size_bytes": path.stat().st_size if path.exists() else 0,
    }


def import_file(params: dict[str, Any], _ctx: ExecutionContext) -> dict[str, Any]:
    raw_path = str(params.get("filepath", "")).strip()
    if not raw_path:
        raise AddonError(BridgeErrorCode.INVALID_PARAMS, "'filepath' is required.")
    path = Path(raw_path).expanduser().resolve()
    if not path.is_file():
        raise AddonError(BridgeErrorCode.NOT_FOUND, f"File not found: {str(path)!r}")
    fmt = _infer_format(path, params.get("file_format"))

    before_ptrs = {o.as_pointer() for o in bpy.data.objects}

    if fmt in ("glb", "gltf"):
        bpy.ops.import_scene.gltf(filepath=str(path))
    elif fmt == "fbx":
        if hasattr(bpy.ops.wm, "fbx_import"):
            bpy.ops.wm.fbx_import(filepath=str(path))
        else:
            bpy.ops.import_scene.fbx(filepath=str(path))
    elif fmt == "obj":
        if hasattr(bpy.ops.wm, "obj_import"):
            bpy.ops.wm.obj_import(filepath=str(path))
        else:
            bpy.ops.import_scene.obj(filepath=str(path))
    elif fmt == "stl":
        if hasattr(bpy.ops.wm, "stl_import"):
            bpy.ops.wm.stl_import(filepath=str(path))
        else:
            bpy.ops.import_mesh.stl(filepath=str(path))
    elif fmt == "ply":
        if hasattr(bpy.ops.wm, "ply_import"):
            bpy.ops.wm.ply_import(filepath=str(path))
        else:
            bpy.ops.import_mesh.ply(filepath=str(path))
    elif fmt in ("usd", "usda", "usdc"):
        bpy.ops.wm.usd_import(filepath=str(path))
    elif fmt == "abc":
        bpy.ops.wm.alembic_import(filepath=str(path))
    else:
        raise AddonError(
            BridgeErrorCode.INVALID_PARAMS,
            f"Unsupported import format {fmt!r}.",
            suggestions=["glb", "gltf", "fbx", "obj", "stl", "ply", "usd", "abc"],
        )

    imported = []
    for obj in bpy.data.objects:
        if obj.as_pointer() not in before_ptrs:
            imported.append({"uid": ensure_object_uid(obj), "name": obj.name, "type": obj.type})

    return {"filepath": str(path), "format": fmt, "imported_objects": imported}


def save_blend(params: dict[str, Any], _ctx: ExecutionContext) -> dict[str, Any]:
    raw_path = params.get("filepath") or bpy.data.filepath
    if not raw_path:
        raise AddonError(BridgeErrorCode.INVALID_PARAMS, "Provide 'filepath' when saving an unsaved scene.")
    path = Path(str(raw_path)).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    if params.get("pack_resources", False):
        try:
            bpy.ops.file.pack_all()
        except Exception:
            pass
    bpy.ops.wm.save_as_mainfile(
        filepath=str(path),
        copy=bool(params.get("copy", False)),
        compress=bool(params.get("compress", True)),
    )
    return {
        "filepath": str(path),
        "size_bytes": path.stat().st_size if path.exists() else 0,
    }


def open_blend(params: dict[str, Any], _ctx: ExecutionContext) -> dict[str, Any]:
    raw_path = str(params.get("filepath", "")).strip()
    if not raw_path:
        raise AddonError(BridgeErrorCode.INVALID_PARAMS, "'filepath' is required.")
    path = Path(raw_path).expanduser().resolve()
    if not path.is_file():
        raise AddonError(BridgeErrorCode.NOT_FOUND, f".blend file not found: {str(path)!r}")
    bpy.ops.wm.open_mainfile(filepath=str(path))
    return {
        "filepath": bpy.data.filepath,
        "scene_name": bpy.context.scene.name,
        "object_count": len(bpy.data.objects),
    }


def link_append(params: dict[str, Any], _ctx: ExecutionContext) -> dict[str, Any]:
    raw_path = str(params.get("filepath", "")).strip()
    if not raw_path:
        raise AddonError(BridgeErrorCode.INVALID_PARAMS, "'filepath' is required.")
    path = Path(raw_path).expanduser().resolve()
    if not path.is_file():
        raise AddonError(BridgeErrorCode.NOT_FOUND, f"Source .blend not found: {str(path)!r}")

    data_type = str(params.get("data_type", "objects")).strip().lower()
    valid_types = {"objects", "materials", "collections", "node_groups", "meshes", "worlds"}
    if data_type not in valid_types:
        raise AddonError(
            BridgeErrorCode.INVALID_PARAMS,
            f"Unsupported data_type {data_type!r}.",
            suggestions=sorted(valid_types),
        )
    names_filter = set(params.get("names") or [])
    link = bool(params.get("link", False))

    loaded_names: list[str] = []
    with bpy.data.libraries.load(str(path), link=link) as (data_from, data_to):
        available = list(getattr(data_from, data_type))
        selected = [n for n in available if not names_filter or n in names_filter]
        setattr(data_to, data_type, selected)
        loaded_names = selected

    # Link appended/linked objects into active scene collection so they are visible
    if data_type == "objects":
        for name in loaded_names:
            obj = bpy.data.objects.get(name)
            if obj is not None and obj.name not in bpy.context.scene.collection.objects:
                bpy.context.scene.collection.objects.link(obj)
                ensure_object_uid(obj)
    elif data_type == "collections":
        for name in loaded_names:
            col = bpy.data.collections.get(name)
            if col is not None and col.name not in bpy.context.scene.collection.children:
                bpy.context.scene.collection.children.link(col)

    return {"filepath": str(path), "data_type": data_type, "link": link, "loaded": loaded_names}


def list_asset_libraries(_params: dict[str, Any], _ctx: ExecutionContext) -> dict[str, Any]:
    libs = []
    prefs = getattr(bpy.context.preferences, "filepaths", None)
    if prefs is not None and hasattr(prefs, "asset_libraries"):
        for lib in prefs.asset_libraries:
            libs.append({"name": lib.name, "path": lib.path})
    return {"asset_libraries": libs}


def register(dispatcher: Dispatcher) -> None:
    dispatcher.register("io.export_file", export_file, mutating=False)
    dispatcher.register("io.import_file", import_file)
    dispatcher.register("io.save_blend", save_blend, mutating=False)
    dispatcher.register("io.open_blend", open_blend, mutating=False)
    dispatcher.register("io.link_append", link_append)
    dispatcher.register("io.list_asset_libraries", list_asset_libraries, mutating=False)
