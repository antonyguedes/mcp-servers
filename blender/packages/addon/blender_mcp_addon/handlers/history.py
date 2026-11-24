# SPDX-License-Identifier: GPL-3.0-or-later
"""Undo, redo, and session checkpoint handlers."""

from __future__ import annotations

from typing import Any

import bpy  # type: ignore[import-not-found]

from ..dispatcher import Dispatcher, ExecutionContext
from ..wire import AddonError, BridgeErrorCode


def undo(params: dict[str, Any], _ctx: ExecutionContext) -> dict[str, Any]:
    if bpy.app.background:
        raise AddonError(
            BridgeErrorCode.INVALID_STATE,
            "Interactive undo stack is unavailable in headless background mode; use checkpoints instead.",
        )
    steps = max(1, min(20, int(params.get("steps", 1))))
    done = 0
    for _ in range(steps):
        try:
            res = bpy.ops.ed.undo()
            if "FINISHED" in res:
                done += 1
            else:
                break
        except Exception:
            break
    return {"undone_steps": done, "object_count": len(bpy.data.objects)}


def redo(params: dict[str, Any], _ctx: ExecutionContext) -> dict[str, Any]:
    if bpy.app.background:
        raise AddonError(
            BridgeErrorCode.INVALID_STATE,
            "Interactive redo stack is unavailable in headless background mode; use checkpoints instead.",
        )
    steps = max(1, min(20, int(params.get("steps", 1))))
    done = 0
    for _ in range(steps):
        try:
            res = bpy.ops.ed.redo()
            if "FINISHED" in res:
                done += 1
            else:
                break
        except Exception:
            break
    return {"redone_steps": done, "object_count": len(bpy.data.objects)}


def create_checkpoint(params: dict[str, Any], ctx: ExecutionContext) -> dict[str, Any]:
    name = params.get("name")
    description = str(params.get("description", ""))
    return ctx.checkpoints.create(name=str(name) if name else None, description=description)


def restore_checkpoint(params: dict[str, Any], ctx: ExecutionContext) -> dict[str, Any]:
    name = str(params.get("name", "")).strip()
    if not name:
        raise AddonError(BridgeErrorCode.INVALID_PARAMS, "Checkpoint 'name' is required.")
    return ctx.checkpoints.restore(name)


def list_checkpoints(_params: dict[str, Any], ctx: ExecutionContext) -> dict[str, Any]:
    return {"checkpoints": ctx.checkpoints.list_all()}


def delete_checkpoint(params: dict[str, Any], ctx: ExecutionContext) -> dict[str, Any]:
    name = str(params.get("name", "")).strip()
    deleted = ctx.checkpoints.delete(name)
    return {"name": name, "deleted": deleted}


def register(dispatcher: Dispatcher) -> None:
    dispatcher.register("history.undo", undo, mutating=False)
    dispatcher.register("history.redo", redo, mutating=False)
    dispatcher.register("history.create_checkpoint", create_checkpoint, mutating=False)
    dispatcher.register("history.restore_checkpoint", restore_checkpoint, mutating=False)
    dispatcher.register("history.list_checkpoints", list_checkpoints, mutating=False)
    dispatcher.register("history.delete_checkpoint", delete_checkpoint, mutating=False)
