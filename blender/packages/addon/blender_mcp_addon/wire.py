# SPDX-License-Identifier: GPL-3.0-or-later
"""Self-contained JSON-RPC 2.0 length-prefixed wire helpers for the Blender add-on.

Must remain stdlib-only, Python 3.10+ compatible, and wire-identical to
`blender_mcp_protocol` (verified by unit tests).
"""

from __future__ import annotations

import json
import socket
import struct
from enum import IntEnum
from typing import Any

PROTOCOL_VERSION = "1.0"
ADDON_VERSION = "1.0.0"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 9876
HEADER_FORMAT = "!I"
HEADER_SIZE = 4
MAX_FRAME_BYTES = 64 * 1024 * 1024
JSONRPC_VERSION = "2.0"


class BridgeErrorCode(IntEnum):
    PARSE_ERROR = -32700
    INVALID_REQUEST = -32600
    METHOD_NOT_FOUND = -32601
    INVALID_PARAMS = -32602
    INTERNAL_ERROR = -32603

    UNAUTHORIZED = -32001
    POLICY_DENIED = -32002
    NOT_FOUND = -32003
    ALREADY_EXISTS = -32004
    INVALID_STATE = -32005
    UNSUPPORTED_VERSION = -32006
    PATH_DENIED = -32007
    TIMEOUT = -32008
    CANCELLED = -32009
    BLENDER_ERROR = -32010
    PYTHON_EXEC_ERROR = -32011
    CONFIRMATION_REQUIRED = -32012


class AddonError(Exception):
    """Structured error raised by add-on handlers."""

    def __init__(
        self,
        code: BridgeErrorCode | int,
        message: str,
        *,
        details: dict[str, Any] | None = None,
        suggestions: list[str] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = int(code)
        self.message = message
        self.details = details or {}
        self.suggestions = suggestions or []

    def to_rpc_error(self) -> dict[str, Any]:
        err: dict[str, Any] = {"code": self.code, "message": self.message}
        data: dict[str, Any] = {}
        if self.details:
            data["details"] = self.details
        if self.suggestions:
            data["suggestions"] = self.suggestions
        if data:
            err["data"] = data
        return err


def encode_frame(payload: dict[str, Any]) -> bytes:
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    if len(body) > MAX_FRAME_BYTES:
        raise AddonError(
            BridgeErrorCode.INVALID_REQUEST,
            f"Frame size {len(body)} exceeds max limit of {MAX_FRAME_BYTES} bytes",
        )
    return struct.pack(HEADER_FORMAT, len(body)) + body


def _recv_exact(sock: socket.socket, size: int) -> bytes | None:
    chunks: list[bytes] = []
    remaining = size
    while remaining > 0:
        chunk = sock.recv(remaining)
        if not chunk:
            if not chunks:
                return None
            raise ConnectionError("Unexpected EOF while reading frame")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def read_frame(sock: socket.socket) -> dict[str, Any] | None:
    header = _recv_exact(sock, HEADER_SIZE)
    if header is None:
        return None
    (length,) = struct.unpack(HEADER_FORMAT, header)
    if length == 0 or length > MAX_FRAME_BYTES:
        raise AddonError(BridgeErrorCode.PARSE_ERROR, f"Invalid frame length: {length}")
    body = _recv_exact(sock, length)
    if body is None:
        raise ConnectionError("Unexpected EOF while reading frame body")
    try:
        obj = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AddonError(BridgeErrorCode.PARSE_ERROR, f"Invalid JSON payload: {exc}") from exc
    if not isinstance(obj, dict):
        raise AddonError(BridgeErrorCode.INVALID_REQUEST, "Message must be a JSON object")
    return obj


def write_frame(sock: socket.socket, payload: dict[str, Any]) -> None:
    sock.sendall(encode_frame(payload))


def make_ok_response(req_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": JSONRPC_VERSION, "id": req_id, "result": result}


def make_error_response(req_id: Any, err: AddonError) -> dict[str, Any]:
    return {"jsonrpc": JSONRPC_VERSION, "id": req_id, "error": err.to_rpc_error()}
