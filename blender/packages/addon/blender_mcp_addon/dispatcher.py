# SPDX-License-Identifier: GPL-3.0-or-later
"""Main-thread RPC dispatcher supporting GUI timers and headless background loops."""

from __future__ import annotations

import queue
import threading
import traceback
from concurrent.futures import Future
from dataclasses import dataclass
from typing import Any, Callable

import bpy  # type: ignore[import-not-found]

from .compat import safe_undo_push
from .jobs import JobManager
from .state import CheckpointManager, compute_scene_diff, take_scene_snapshot
from .wire import AddonError, BridgeErrorCode

HandlerFn = Callable[[dict[str, Any], "ExecutionContext"], Any]


@dataclass
class ExecutionContext:
    """Context passed to every add-on RPC handler."""

    checkpoints: CheckpointManager
    jobs: JobManager
    allow_python: bool = False
    request_stop: Callable[[], None] | None = None


@dataclass
class _MethodSpec:
    fn: HandlerFn
    mutating: bool = True
    push_undo: bool = True
    track_diff: bool = True


@dataclass
class _QueuedTask:
    method: str
    params: dict[str, Any]
    allow_python: bool
    future: Future[Any]


class Dispatcher:
    """Executes all bpy-touching RPC methods safely on Blender's main thread."""

    def __init__(self) -> None:
        self._methods: dict[str, _MethodSpec] = {}
        self._queue: queue.Queue[_QueuedTask] = queue.Queue()
        self._stop_event = threading.Event()
        self._timer_registered = False
        self.checkpoints = CheckpointManager()
        self.jobs = JobManager()
        self.on_scene_mutated: Callable[[str], None] | None = None

    def register(
        self,
        method: str,
        fn: HandlerFn,
        *,
        mutating: bool = True,
        push_undo: bool = True,
        track_diff: bool = True,
    ) -> None:
        self._methods[method] = _MethodSpec(
            fn=fn,
            mutating=mutating,
            push_undo=push_undo,
            track_diff=track_diff,
        )

    def list_methods(self) -> list[str]:
        return sorted(self._methods.keys())

    def submit(
        self,
        method: str,
        params: dict[str, Any],
        *,
        allow_python: bool = False,
        timeout: float = 300.0,
    ) -> Any:
        """Enqueue a call from the socket thread and block until main thread completes it."""
        if method not in self._methods:
            raise AddonError(
                BridgeErrorCode.METHOD_NOT_FOUND,
                f"Unknown bridge method: {method!r}",
            )
        fut: Future[Any] = Future()
        self._queue.put(
            _QueuedTask(
                method=method,
                params=params,
                allow_python=allow_python,
                future=fut,
            )
        )
        try:
            return fut.result(timeout=timeout)
        except TimeoutError as exc:
            raise AddonError(
                BridgeErrorCode.TIMEOUT,
                f"Bridge method {method!r} timed out after {timeout}s",
            ) from exc

    def _execute_task(self, task: _QueuedTask) -> None:
        spec = self._methods[task.method]
        ctx = ExecutionContext(
            checkpoints=self.checkpoints,
            jobs=self.jobs,
            allow_python=task.allow_python,
            request_stop=self.request_stop,
        )
        try:
            before = take_scene_snapshot() if (spec.mutating and spec.track_diff) else None
            result = spec.fn(task.params, ctx)
            if spec.mutating:
                if spec.push_undo:
                    safe_undo_push(f"MCP: {task.method}")
                if before is not None:
                    after = take_scene_snapshot()
                    diff = compute_scene_diff(before, after)
                    if isinstance(result, dict):
                        result.setdefault("diff", diff)
                if self.on_scene_mutated is not None:
                    try:
                        self.on_scene_mutated(task.method)
                    except Exception:
                        pass
            task.future.set_result(result)
        except AddonError as err:
            task.future.set_exception(err)
        except Exception as exc:
            tb = traceback.format_exc()
            task.future.set_exception(
                AddonError(
                    BridgeErrorCode.BLENDER_ERROR,
                    f"{type(exc).__name__}: {exc}",
                    details={"traceback": tb[-2000:]},
                )
            )

    def poll_once(self) -> float | None:
        """GUI timer callback — drains pending RPCs first, then advances 1 job slice."""
        if self._stop_event.is_set():
            self._timer_registered = False
            return None
        processed = 0
        while processed < 16:
            try:
                task = self._queue.get_nowait()
            except queue.Empty:
                break
            self._execute_task(task)
            processed += 1
        if self.jobs.has_work():
            self.jobs.tick_main_thread()
        return 0.01

    def start_gui_timer(self) -> None:
        self._stop_event.clear()
        if not self._timer_registered:
            bpy.app.timers.register(self.poll_once, first_interval=0.01, persistent=True)
            self._timer_registered = True

    def run_headless_loop(self) -> None:
        """Main-thread loop for `blender --background`, interleaving RPCs and job slices."""
        self._stop_event.clear()
        while not self._stop_event.is_set():
            if self.jobs.has_work():
                # Drain any waiting RPCs immediately between job slices
                while not self._stop_event.is_set():
                    try:
                        task = self._queue.get_nowait()
                    except queue.Empty:
                        break
                    self._execute_task(task)
                if not self._stop_event.is_set():
                    self.jobs.tick_main_thread()
            else:
                try:
                    task = self._queue.get(timeout=0.05)
                except queue.Empty:
                    continue
                self._execute_task(task)

    def request_stop(self) -> None:
        self._stop_event.set()
