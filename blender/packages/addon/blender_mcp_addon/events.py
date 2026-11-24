# SPDX-License-Identifier: GPL-3.0-or-later
"""Debounced Blender scene event watcher (depsgraph_update_post & load_post)."""

from __future__ import annotations

import threading
import time
from typing import Any, Callable

import bpy  # type: ignore[import-not-found]


class SceneEventWatcher:
    """Coalesces Blender depsgraph/file events and emits debounced notifications."""

    def __init__(
        self,
        emit_fn: Callable[[str, dict[str, Any]], None],
        *,
        debounce_sec: float = 0.2,
    ) -> None:
        self._emit_fn = emit_fn
        self._debounce_sec = debounce_sec
        self._lock = threading.Lock()
        self._timer: threading.Timer | None = None
        self._installed = False
        self._pending_reason = "depsgraph"
        self._pending_payload: dict[str, Any] = {}

    def start(self) -> None:
        if self._installed:
            return
        if self._on_depsgraph not in bpy.app.handlers.depsgraph_update_post:
            bpy.app.handlers.depsgraph_update_post.append(self._on_depsgraph)
        if self._on_load not in bpy.app.handlers.load_post:
            bpy.app.handlers.load_post.append(self._on_load)
        self._installed = True

    def stop(self) -> None:
        if not self._installed:
            return
        if self._on_depsgraph in bpy.app.handlers.depsgraph_update_post:
            bpy.app.handlers.depsgraph_update_post.remove(self._on_depsgraph)
        if self._on_load in bpy.app.handlers.load_post:
            bpy.app.handlers.load_post.remove(self._on_load)
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
        self._installed = False

    def notify_changed(self, reason: str = "mutation") -> None:
        """Schedule a debounced `event.scene_changed` notification safely from main thread."""
        scene = getattr(bpy.context, "scene", None)
        payload = {
            "reason": reason,
            "scene": scene.name if scene is not None else "",
            "object_count": len(bpy.data.objects),
            "material_count": len(bpy.data.materials),
            "ts": round(time.time(), 3),
        }
        with self._lock:
            self._pending_reason = reason
            self._pending_payload = payload
            if self._timer is not None:
                self._timer.cancel()
            self._timer = threading.Timer(self._debounce_sec, self._flush)
            self._timer.daemon = True
            self._timer.start()

    def _flush(self) -> None:
        with self._lock:
            payload = dict(self._pending_payload)
            self._timer = None
        if payload:
            try:
                self._emit_fn("event.scene_changed", payload)
            except Exception:
                pass

    def _on_depsgraph(self, _scene: Any, _depsgraph: Any = None) -> None:
        self.notify_changed("depsgraph_update")

    def _on_load(self, _filepath: Any = None) -> None:
        self.notify_changed("file_loaded")
