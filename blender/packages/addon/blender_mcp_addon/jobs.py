# SPDX-License-Identifier: GPL-3.0-or-later
"""Cooperative main-thread JobManager supporting live progress and cancellation."""

from __future__ import annotations

import threading
import time
import traceback
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any, Callable

from .wire import AddonError, BridgeErrorCode

JobStepperFactory = Callable[["JobRecord"], Iterator[None]]


@dataclass
class JobRecord:
    """Thread-safe snapshotable state of an asynchronous Blender job."""

    job_id: str
    kind: str
    status: str = "pending"  # pending | running | completed | cancelled | failed
    progress: float = 0.0
    current_step: int = 0
    total_steps: int = 1
    message: str = ""
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    result: Any = None
    error: str | None = None
    cancel_event: threading.Event = field(default_factory=threading.Event, repr=False)
    _iterator: Iterator[None] | None = field(default=None, repr=False)
    _factory: JobStepperFactory | None = field(default=None, repr=False)

    @property
    def is_cancelled(self) -> bool:
        return self.cancel_event.is_set()

    def update_progress(self, current: int, total: int, message: str = "") -> None:
        self.current_step = current
        self.total_steps = max(1, total)
        self.progress = round(min(1.0, max(0.0, current / self.total_steps)), 4)
        if message:
            self.message = message

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "kind": self.kind,
            "status": self.status,
            "progress": self.progress,
            "current_step": self.current_step,
            "total_steps": self.total_steps,
            "message": self.message,
            "created_at": round(self.created_at, 3),
            "started_at": round(self.started_at, 3) if self.started_at else None,
            "finished_at": round(self.finished_at, 3) if self.finished_at else None,
            "result": self.result,
            "error": self.error,
        }


class JobManager:
    """Schedules cooperative sliced jobs on Blender's main thread.

    Status queries and cancellation flags are thread-safe so socket threads
    can inspect progress or cancel a job immediately without blocking on the
    currently rendering frame.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: dict[str, JobRecord] = {}
        self._queue: list[str] = []
        self._active_id: str | None = None

    def submit(
        self,
        kind: str,
        factory: JobStepperFactory,
        *,
        total_steps: int = 1,
        message: str = "Queued",
    ) -> JobRecord:
        job_id = f"job_{uuid.uuid4().hex[:10]}"
        rec = JobRecord(
            job_id=job_id,
            kind=kind,
            status="pending",
            total_steps=max(1, total_steps),
            message=message,
            _factory=factory,
        )
        with self._lock:
            self._jobs[job_id] = rec
            self._queue.append(job_id)
        return rec

    def has_work(self) -> bool:
        with self._lock:
            return self._active_id is not None or bool(self._queue)

    def get_status(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            rec = self._jobs.get(job_id)
            if rec is None:
                raise AddonError(BridgeErrorCode.NOT_FOUND, f"Job {job_id!r} not found.")
            return rec.to_dict()

    def list_jobs(self, *, limit: int = 30) -> list[dict[str, Any]]:
        with self._lock:
            ordered = sorted(self._jobs.values(), key=lambda j: j.created_at, reverse=True)
            return [j.to_dict() for j in ordered[: max(1, min(limit, 100))]]

    def cancel(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            rec = self._jobs.get(job_id)
            if rec is None:
                raise AddonError(BridgeErrorCode.NOT_FOUND, f"Job {job_id!r} not found.")
            if rec.status in ("completed", "failed", "cancelled"):
                return rec.to_dict()
            rec.cancel_event.set()
            if rec.status == "pending":
                rec.status = "cancelled"
                rec.message = "Cancelled before starting"
                rec.finished_at = time.time()
                if job_id in self._queue:
                    self._queue.remove(job_id)
            else:
                rec.message = "Cancellation requested"
            return rec.to_dict()

    def tick_main_thread(self) -> bool:
        """Advance the active job by exactly one cooperative slice on Blender's main thread.

        Returns True if work was performed.
        """
        rec: JobRecord | None = None
        with self._lock:
            if self._active_id is None:
                while self._queue:
                    next_id = self._queue.pop(0)
                    cand = self._jobs.get(next_id)
                    if cand is None or cand.status != "pending":
                        continue
                    if cand.is_cancelled:
                        cand.status = "cancelled"
                        cand.finished_at = time.time()
                        continue
                    self._active_id = next_id
                    cand.status = "running"
                    cand.started_at = time.time()
                    cand.message = "Starting"
                    rec = cand
                    break
            else:
                rec = self._jobs.get(self._active_id)

        if rec is None:
            return False

        # Instantiate generator on first tick
        if rec._iterator is None:
            assert rec._factory is not None
            try:
                rec._iterator = rec._factory(rec)
            except Exception as exc:
                self._finish_job(rec, status="failed", error=f"{type(exc).__name__}: {exc}")
                return True

        # Check cancellation before running next slice
        if rec.is_cancelled:
            try:
                rec._iterator.close()
            except Exception:
                pass
            self._finish_job(rec, status="cancelled", message="Cancelled by client")
            return True

        try:
            next(rec._iterator)
            if rec.is_cancelled:
                try:
                    rec._iterator.close()
                except Exception:
                    pass
                self._finish_job(rec, status="cancelled", message="Cancelled by client")
        except StopIteration:
            if rec.is_cancelled:
                self._finish_job(rec, status="cancelled", message="Cancelled by client")
            else:
                rec.progress = 1.0
                rec.current_step = rec.total_steps
                self._finish_job(rec, status="completed", message=rec.message or "Completed")
        except Exception as exc:
            tb = traceback.format_exc()[-1500:]
            self._finish_job(rec, status="failed", error=f"{type(exc).__name__}: {exc}\n{tb}")

        return True

    def _finish_job(
        self,
        rec: JobRecord,
        *,
        status: str,
        message: str | None = None,
        error: str | None = None,
    ) -> None:
        with self._lock:
            rec.status = status
            if message is not None:
                rec.message = message
            if error is not None:
                rec.error = error
            rec.finished_at = time.time()
            rec._iterator = None
            if self._active_id == rec.job_id:
                self._active_id = None
