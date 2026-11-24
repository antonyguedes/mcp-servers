# SPDX-License-Identifier: MIT
"""Async TCP JSON-RPC 2.0 client with full-duplex response/notification demultiplexing."""

from __future__ import annotations

import asyncio
import contextlib
import itertools
import logging
import time
from collections.abc import Callable
from typing import Any

from blender_mcp.config import ServerSettings
from blender_mcp.security import AuditLogger
from blender_mcp_protocol import (
    BridgeError,
    BridgeErrorCode,
    HandshakeResponse,
    RpcRequest,
    RpcResponse,
    read_frame_async,
    write_frame_async,
)

logger = logging.getLogger("blender_mcp.bridge")

NotificationCallback = Callable[[str, dict[str, Any]], Any]


class BridgeClient:
    """Manages an authenticated, auto-reconnecting TCP link to a single Blender add-on."""

    def __init__(
        self,
        settings: ServerSettings,
        *,
        audit_logger: AuditLogger | None = None,
    ) -> None:
        self.settings = settings
        self.audit = audit_logger or AuditLogger(settings.audit_log)
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._connect_lock = asyncio.Lock()
        self._write_lock = asyncio.Lock()
        self._reader_task: asyncio.Task[None] | None = None
        self._bg_tasks: set[asyncio.Task[Any]] = set()
        self._pending: dict[int, asyncio.Future[RpcResponse]] = {}
        self._listeners: list[NotificationCallback] = []
        self._id_counter = itertools.count(1)
        self._token: str = ""
        self._handshake: HandshakeResponse | None = None

    def add_notification_listener(self, cb: NotificationCallback) -> None:
        if cb not in self._listeners:
            self._listeners.append(cb)

    def remove_notification_listener(self, cb: NotificationCallback) -> None:
        with contextlib.suppress(ValueError):
            self._listeners.remove(cb)

    @property
    def is_connected(self) -> bool:
        return (
            self._writer is not None
            and not self._writer.is_closing()
            and self._reader_task is not None
            and not self._reader_task.done()
        )

    @property
    def handshake(self) -> HandshakeResponse | None:
        return self._handshake

    async def connect(self) -> HandshakeResponse:
        async with self._connect_lock:
            return await self._ensure_connected_locked()

    async def close(self) -> None:
        async with self._connect_lock:
            await self._close_locked()

    async def _close_locked(self) -> None:
        task = self._reader_task
        self._reader_task = None
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task

        if self._writer is not None:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception:
                pass
        self._reader = None
        self._writer = None
        self._handshake = None
        self._fail_pending(ConnectionError("Blender bridge connection closed"))

    def _fail_pending(self, exc: Exception) -> None:
        pending = list(self._pending.values())
        self._pending.clear()
        for fut in pending:
            if not fut.done():
                fut.set_exception(exc)

    async def _reader_loop(self, reader: asyncio.StreamReader) -> None:
        try:
            while True:
                raw = await read_frame_async(reader)
                if raw is None:
                    break
                req_id = raw.get("id")
                if req_id is None and "method" in raw:
                    method = str(raw["method"])
                    raw_params = raw.get("params")
                    params: dict[str, Any] = raw_params if isinstance(raw_params, dict) else {}
                    for cb in list(self._listeners):
                        try:
                            res = cb(method, params)
                            if asyncio.iscoroutine(res):
                                bg = asyncio.create_task(res)
                                self._bg_tasks.add(bg)
                                bg.add_done_callback(self._bg_tasks.discard)
                        except Exception:
                            logger.debug("Notification listener raised", exc_info=True)
                    continue

                if isinstance(req_id, int):
                    fut = self._pending.pop(req_id, None)
                    if fut is not None and not fut.done():
                        fut.set_result(RpcResponse.from_dict(raw))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._fail_pending(ConnectionError(f"Bridge reader terminated: {exc}"))
        finally:
            self._fail_pending(ConnectionError("Blender bridge closed the connection unexpectedly"))

    async def _ensure_connected_locked(self) -> HandshakeResponse:
        if self.is_connected and self._handshake is not None:
            return self._handshake

        await self._close_locked()
        host, port, token = self.settings.resolve_bridge_endpoint()
        self._token = token

        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port),
                timeout=5.0,
            )
        except OSError as exc:
            raise BridgeError(
                BridgeErrorCode.INTERNAL_ERROR,
                f"Cannot connect to Blender MCP bridge at {host}:{port} ({exc}). "
                "Ensure Blender is running with the Blender MCP Bridge add-on started, "
                "or launch a headless session with `blender-mcp launch --background`.",
            ) from exc

        self._reader = reader
        self._writer = writer
        self._reader_task = asyncio.create_task(self._reader_loop(reader), name="blender-mcp-reader")

        try:
            hs_data = await self._send_rpc("system.handshake", {}, timeout=10.0)
            self._handshake = HandshakeResponse.from_dict(hs_data)
            logger.info(
                "Connected to Blender %s (protocol %s, instance=%s, background=%s)",
                self._handshake.blender_version_string,
                self._handshake.protocol_version,
                self._handshake.instance_id,
                self._handshake.capabilities.is_background,
            )
            return self._handshake
        except Exception:
            await self._close_locked()
            raise

    async def _send_rpc(
        self,
        method: str,
        params: dict[str, Any],
        *,
        timeout: float,
    ) -> Any:
        if self._writer is None:
            raise ConnectionError("Bridge writer is not connected")
        req_id = next(self._id_counter)
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[RpcResponse] = loop.create_future()
        self._pending[req_id] = fut

        req = RpcRequest(method=method, params=params, id=req_id, token=self._token)
        try:
            async with self._write_lock:
                await write_frame_async(self._writer, req.to_dict())
            resp = await asyncio.wait_for(fut, timeout=timeout)
        except Exception:
            self._pending.pop(req_id, None)
            raise

        if resp.error is not None:
            raise BridgeError.from_rpc_error(resp.error)
        return resp.result

    async def call(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        timeout: float | None = None,
        audit: bool = False,
    ) -> Any:
        """Send an RPC call to Blender, auto-reconnecting once on stale socket."""
        call_params = params or {}
        effective_timeout = timeout if timeout is not None else self.settings.rpc_timeout
        started = time.perf_counter()

        last_exc: Exception | None = None
        for attempt in range(2):
            try:
                async with self._connect_lock:
                    await self._ensure_connected_locked()
                result = await self._send_rpc(method, call_params, timeout=effective_timeout)
                if audit:
                    self.audit.record(
                        tool=method,
                        params=call_params,
                        ok=True,
                        duration_ms=(time.perf_counter() - started) * 1000.0,
                    )
                return result
            except TimeoutError as exc:
                async with self._connect_lock:
                    await self._close_locked()
                err = BridgeError(
                    BridgeErrorCode.TIMEOUT,
                    f"Call {method!r} timed out after {effective_timeout}s.",
                )
                if audit:
                    self.audit.record(
                        tool=method,
                        params=call_params,
                        ok=False,
                        duration_ms=(time.perf_counter() - started) * 1000.0,
                        error=err.message,
                    )
                raise err from exc
            except (ConnectionError, OSError, asyncio.IncompleteReadError) as exc:
                last_exc = exc
                async with self._connect_lock:
                    await self._close_locked()
                if attempt == 0:
                    logger.debug("Reconnecting to Blender bridge after %s", exc)
                    continue
            except BridgeError as err:
                if audit:
                    self.audit.record(
                        tool=method,
                        params=call_params,
                        ok=False,
                        duration_ms=(time.perf_counter() - started) * 1000.0,
                        error=err.message,
                    )
                raise

        err = BridgeError(
            BridgeErrorCode.INTERNAL_ERROR,
            f"Lost connection to Blender bridge during {method!r}: {last_exc}",
        )
        if audit:
            self.audit.record(
                tool=method,
                params=call_params,
                ok=False,
                duration_ms=(time.perf_counter() - started) * 1000.0,
                error=err.message,
            )
        raise err
