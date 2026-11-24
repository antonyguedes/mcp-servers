# SPDX-License-Identifier: GPL-3.0-or-later
"""Localhost-only authenticated TCP JSON-RPC 2.0 server inside Blender.

Supports multi-instance discovery (`sessions/<instance_id>.json`) and
debounced push notifications (`event.scene_changed`) to connected MCP servers.
"""

from __future__ import annotations

import hmac
import json
import os
import secrets
import socket
import sys
import threading
import uuid
from pathlib import Path
from typing import Any

import bpy  # type: ignore[import-not-found]

from .compat import detect_capabilities
from .dispatcher import Dispatcher
from .events import SceneEventWatcher
from .wire import (
    ADDON_VERSION,
    DEFAULT_HOST,
    DEFAULT_PORT,
    JSONRPC_VERSION,
    PROTOCOL_VERSION,
    AddonError,
    BridgeErrorCode,
    make_error_response,
    make_ok_response,
    read_frame,
    write_frame,
)


def default_session_file() -> Path:
    cfg = Path(os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config"))
    return cfg / "blender-mcp" / "session.json"


def default_sessions_dir() -> Path:
    cfg = Path(os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config"))
    return cfg / "blender-mcp" / "sessions"


class _ClientChannel:
    """Thread-safe socket wrapper preventing interleaved RPC responses and push events."""

    def __init__(self, conn: socket.socket) -> None:
        self.conn = conn
        self.write_lock = threading.Lock()
        self.authenticated = False

    def send(self, payload: dict[str, Any]) -> None:
        with self.write_lock:
            write_frame(self.conn, payload)


class BridgeTCPServer:
    """Threaded TCP server accepting authenticated JSON-RPC calls on localhost."""

    def __init__(
        self,
        dispatcher: Dispatcher,
        *,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        token: str | None = None,
        session_file: Path | None = None,
        sessions_dir: Path | None = None,
        allow_python: bool = False,
    ) -> None:
        if host not in ("127.0.0.1", "localhost", "::1"):
            raise ValueError(f"Bridge must bind to localhost only, got {host!r}")
        self.dispatcher = dispatcher
        self.host = host
        self.port = port
        self.token = token or secrets.token_urlsafe(32)
        self.session_file = session_file or default_session_file()
        self.sessions_dir = sessions_dir or (self.session_file.parent / "sessions")
        self.allow_python = allow_python
        self.instance_id = uuid.uuid4().hex[:10]

        self._sock: socket.socket | None = None
        self._accept_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._clients_lock = threading.Lock()
        self._channels: set[_ClientChannel] = set()
        self._cached_capabilities: dict[str, Any] | None = None
        self._events = SceneEventWatcher(self.broadcast_notification, debounce_sec=0.15)

    @property
    def is_running(self) -> bool:
        return self._sock is not None and not self._stop_event.is_set()

    @property
    def active_clients(self) -> int:
        with self._clients_lock:
            return len(self._channels)

    def start(self) -> None:
        if self.is_running:
            return
        self._stop_event.clear()

        self._cached_capabilities = detect_capabilities(allow_python=self.allow_python)

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((self.host, self.port))
        self.port = int(sock.getsockname()[1])
        sock.listen(8)
        sock.settimeout(0.5)
        self._sock = sock

        self._write_session_files()
        self._events.start()
        self.dispatcher.on_scene_mutated = self._events.notify_changed

        self._accept_thread = threading.Thread(
            target=self._accept_loop,
            name="blender-mcp-accept",
            daemon=True,
        )
        self._accept_thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self.dispatcher.on_scene_mutated = None
        self._events.stop()
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None
        if self._accept_thread is not None and self._accept_thread.is_alive():
            self._accept_thread.join(timeout=2.0)
        self._remove_session_files()

    def broadcast_notification(self, method: str, params: dict[str, Any]) -> None:
        """Push a JSON-RPC 2.0 notification to every authenticated MCP client."""
        frame = {
            "jsonrpc": JSONRPC_VERSION,
            "method": method,
            "params": {"instance_id": self.instance_id, **params},
        }
        with self._clients_lock:
            targets = [ch for ch in self._channels if ch.authenticated]
        for ch in targets:
            try:
                ch.send(frame)
            except OSError:
                pass

    def _session_payload(self) -> dict[str, Any]:
        return {
            "host": self.host,
            "port": self.port,
            "token": self.token,
            "pid": os.getpid(),
            "instance_id": self.instance_id,
            "blender_version": list(bpy.app.version),
            "blender_version_string": bpy.app.version_string,
            "filepath": bpy.data.filepath,
            "background": bool(bpy.app.background),
        }

    def _atomic_write_json(self, path: Path, data: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        tmp.replace(path)

    def _write_session_files(self) -> None:
        try:
            data = self._session_payload()
            self._atomic_write_json(self.session_file, data)
            self._atomic_write_json(self.sessions_dir / f"{self.instance_id}.json", data)
        except Exception:
            pass

    def _remove_session_files(self) -> None:
        try:
            inst_file = self.sessions_dir / f"{self.instance_id}.json"
            inst_file.unlink(missing_ok=True)
        except Exception:
            pass
        try:
            if self.session_file.exists():
                current = json.loads(self.session_file.read_text(encoding="utf-8"))
                if current.get("instance_id") == self.instance_id:
                    self.session_file.unlink(missing_ok=True)
        except Exception:
            pass

    def _accept_loop(self) -> None:
        assert self._sock is not None
        while not self._stop_event.is_set():
            try:
                conn, _addr = self._sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            t = threading.Thread(
                target=self._serve_client,
                args=(conn,),
                name="blender-mcp-client",
                daemon=True,
            )
            t.start()

    def _verify_token(self, provided: Any) -> bool:
        if not isinstance(provided, str) or not provided:
            return False
        return hmac.compare_digest(provided, self.token)

    def _serve_client(self, conn: socket.socket) -> None:
        channel = _ClientChannel(conn)
        with self._clients_lock:
            self._channels.add(channel)
        try:
            conn.settimeout(None)
            while not self._stop_event.is_set():
                try:
                    msg = read_frame(conn)
                except AddonError as err:
                    channel.send(make_error_response(None, err))
                    continue
                except (ConnectionError, OSError):
                    break

                if msg is None:
                    break

                req_id = msg.get("id")
                response = self._handle_message(msg, channel)
                if req_id is not None:
                    try:
                        channel.send(response)
                    except OSError:
                        break
        finally:
            try:
                conn.close()
            except OSError:
                pass
            with self._clients_lock:
                self._channels.discard(channel)

    def _handle_message(self, msg: dict[str, Any], channel: _ClientChannel) -> dict[str, Any]:
        req_id = msg.get("id")
        if not self._verify_token(msg.get("token")):
            return make_error_response(
                req_id,
                AddonError(
                    BridgeErrorCode.UNAUTHORIZED,
                    "Invalid or missing bridge authentication token.",
                ),
            )
        channel.authenticated = True

        method = msg.get("method")
        if not isinstance(method, str) or not method:
            return make_error_response(
                req_id,
                AddonError(BridgeErrorCode.INVALID_REQUEST, "Missing RPC method."),
            )

        params = msg.get("params")
        if params is None:
            params = {}
        if not isinstance(params, dict):
            return make_error_response(
                req_id,
                AddonError(BridgeErrorCode.INVALID_PARAMS, "'params' must be an object."),
            )

        if method == "system.ping":
            return make_ok_response(req_id, {"pong": True, "instance_id": self.instance_id})

        if method == "system.handshake":
            caps = dict(self._cached_capabilities or {})
            caps["addon_allows_python"] = bool(self.allow_python)
            return make_ok_response(
                req_id,
                {
                    "protocol_version": PROTOCOL_VERSION,
                    "addon_version": ADDON_VERSION,
                    "blender_version": list(bpy.app.version),
                    "blender_version_string": bpy.app.version_string,
                    "python_version": sys.version.split()[0],
                    "filepath": bpy.data.filepath,
                    "instance_id": self.instance_id,
                    "methods": self.dispatcher.list_methods(),
                    "capabilities": caps,
                },
            )

        if method == "system.shutdown":
            self.dispatcher.request_stop()
            return make_ok_response(req_id, {"stopping": True})

        if method == "jobs.get_status":
            try:
                return make_ok_response(req_id, self.dispatcher.jobs.get_status(str(params.get("job_id", ""))))
            except AddonError as err:
                return make_error_response(req_id, err)

        if method == "jobs.list_jobs":
            return make_ok_response(
                req_id,
                {"jobs": self.dispatcher.jobs.list_jobs(limit=int(params.get("limit", 30)))},
            )

        if method == "jobs.cancel":
            try:
                return make_ok_response(req_id, self.dispatcher.jobs.cancel(str(params.get("job_id", ""))))
            except AddonError as err:
                return make_error_response(req_id, err)

        try:
            result = self.dispatcher.submit(
                method,
                params,
                allow_python=self.allow_python,
            )
            return make_ok_response(req_id, result)
        except AddonError as err:
            return make_error_response(req_id, err)
        except Exception as exc:
            return make_error_response(
                req_id,
                AddonError(BridgeErrorCode.INTERNAL_ERROR, f"{type(exc).__name__}: {exc}"),
            )
