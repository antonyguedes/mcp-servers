# SPDX-License-Identifier: GPL-3.0-or-later
"""Persistent object UIDs, name resolution with suggestions, scene diff, and checkpoints."""

from __future__ import annotations

import difflib
import os
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import bpy  # type: ignore[import-not-found]

from .wire import AddonError, BridgeErrorCode

UID_PROP = "blender_mcp_uid"


def ensure_object_uid(obj: Any) -> str:
    """Return an object's persistent UID, assigning one if absent."""
    uid = obj.get(UID_PROP)
    if not isinstance(uid, str) or not uid:
        uid = uuid.uuid4().hex[:12]
        obj[UID_PROP] = uid
    return uid


def resolve_object(ref: str, *, required: bool = True) -> Any | None:
    """Resolve an object by exact name or persistent UID; raise with suggestions if missing."""
    if not ref:
        if required:
            raise AddonError(BridgeErrorCode.INVALID_PARAMS, "Object reference cannot be empty")
        return None

    # 1. Exact name lookup (fast path)
    obj = bpy.data.objects.get(ref)
    if obj is not None:
        ensure_object_uid(obj)
        return obj

    # 2. Persistent UID lookup
    for candidate in bpy.data.objects:
        if candidate.get(UID_PROP) == ref:
            return candidate

    if not required:
        return None

    names = [o.name for o in bpy.data.objects]
    suggestions = difflib.get_close_matches(ref, names, n=5, cutoff=0.4)
    raise AddonError(
        BridgeErrorCode.NOT_FOUND,
        f"Object {ref!r} not found in scene.",
        details={"reference": ref, "total_objects": len(names)},
        suggestions=suggestions,
    )


def resolve_collection(name: str, *, required: bool = True) -> Any | None:
    if name in ("Scene Collection", "Master Collection", "root"):
        return bpy.context.scene.collection
    col = bpy.data.collections.get(name)
    if col is not None:
        return col
    if not required:
        return None
    names = [c.name for c in bpy.data.collections]
    suggestions = difflib.get_close_matches(name, names, n=5, cutoff=0.4)
    raise AddonError(
        BridgeErrorCode.NOT_FOUND,
        f"Collection {name!r} not found.",
        suggestions=suggestions,
    )


def resolve_material(name: str, *, required: bool = True) -> Any | None:
    mat = bpy.data.materials.get(name)
    if mat is not None:
        return mat
    if not required:
        return None
    names = [m.name for m in bpy.data.materials]
    suggestions = difflib.get_close_matches(name, names, n=5, cutoff=0.4)
    raise AddonError(
        BridgeErrorCode.NOT_FOUND,
        f"Material {name!r} not found.",
        suggestions=suggestions,
    )


def _object_fingerprint(obj: Any) -> tuple[Any, ...]:
    loc = tuple(round(float(v), 5) for v in obj.location)
    rot = tuple(round(float(v), 5) for v in obj.rotation_euler)
    scl = tuple(round(float(v), 5) for v in obj.scale)
    parent = obj.parent.name if obj.parent else None
    mats = tuple(slot.material.name if slot.material else None for slot in obj.material_slots)
    mods = tuple(m.name for m in obj.modifiers)
    verts = len(obj.data.vertices) if obj.type == "MESH" and obj.data else 0
    return (obj.name, obj.type, loc, rot, scl, parent, mats, mods, verts, obj.hide_viewport)


@dataclass
class SceneSnapshot:
    objects: dict[str, tuple[str, tuple[Any, ...]]]  # uid -> (name, fingerprint)
    materials: set[str]
    collections: set[str]


def take_scene_snapshot() -> SceneSnapshot:
    objs: dict[str, tuple[str, tuple[Any, ...]]] = {}
    for obj in bpy.data.objects:
        uid = ensure_object_uid(obj)
        objs[uid] = (obj.name, _object_fingerprint(obj))
    mats = {m.name for m in bpy.data.materials}
    cols = {c.name for c in bpy.data.collections}
    return SceneSnapshot(objects=objs, materials=mats, collections=cols)


def compute_scene_diff(before: SceneSnapshot, after: SceneSnapshot) -> dict[str, list[str]]:
    created: list[str] = []
    modified: list[str] = []
    deleted: list[str] = []

    for uid, (name, fp) in after.objects.items():
        if uid not in before.objects:
            created.append(name)
        elif before.objects[uid][1] != fp:
            modified.append(name)

    for uid, (name, _fp) in before.objects.items():
        if uid not in after.objects:
            deleted.append(name)

    materials_created = sorted(after.materials - before.materials)
    collections_created = sorted(after.collections - before.collections)

    return {
        "created": sorted(created),
        "modified": sorted(modified),
        "deleted": sorted(deleted),
        "materials_created": materials_created,
        "collections_created": collections_created,
    }


class CheckpointManager:
    """In-session named .blend snapshots for reliable rollback."""

    def __init__(self) -> None:
        self._dir = Path(tempfile.mkdtemp(prefix="blender_mcp_ckpt_"))
        self._entries: dict[str, dict[str, Any]] = {}

    def create(self, name: str | None = None, description: str = "") -> dict[str, Any]:
        ckpt_id = name.strip() if name and name.strip() else f"ckpt_{len(self._entries) + 1:03d}"
        safe_fname = "".join(c if c.isalnum() or c in "-_" else "_" for c in ckpt_id) + ".blend"
        path = self._dir / safe_fname
        bpy.ops.wm.save_as_mainfile(filepath=str(path), copy=True)
        entry = {
            "name": ckpt_id,
            "description": description,
            "created_at": time.time(),
            "object_count": len(bpy.data.objects),
            "size_bytes": path.stat().st_size if path.exists() else 0,
            "path": str(path),
        }
        self._entries[ckpt_id] = entry
        return {k: v for k, v in entry.items() if k != "path"}

    def restore(self, name: str) -> dict[str, Any]:
        entry = self._entries.get(name)
        if entry is None:
            suggestions = difflib.get_close_matches(name, list(self._entries.keys()), n=5, cutoff=0.4)
            raise AddonError(
                BridgeErrorCode.NOT_FOUND,
                f"Checkpoint {name!r} not found.",
                suggestions=suggestions,
            )
        path = Path(entry["path"])
        if not path.exists():
            raise AddonError(
                BridgeErrorCode.NOT_FOUND,
                f"Checkpoint file for {name!r} is missing on disk.",
            )
        bpy.ops.wm.open_mainfile(filepath=str(path))
        return {
            "restored": name,
            "object_count": len(bpy.data.objects),
        }

    def list_all(self) -> list[dict[str, Any]]:
        return [
            {k: v for k, v in entry.items() if k != "path"}
            for entry in sorted(self._entries.values(), key=lambda e: e["created_at"])
        ]

    def delete(self, name: str) -> bool:
        entry = self._entries.pop(name, None)
        if entry is None:
            return False
        path = Path(entry["path"])
        try:
            if path.exists():
                os.unlink(path)
        except OSError:
            pass
        return True
