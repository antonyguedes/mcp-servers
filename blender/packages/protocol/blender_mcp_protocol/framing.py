# SPDX-License-Identifier: MIT
"""Length-prefixed JSON-RPC 2.0 framing (sync socket + asyncio streams)."""

from __future__ import annotations

import asyncio
import json
import socket
import struct
from typing import Any

from blender_mcp_protocol.constants import HEADER_FORMAT, HEADER_SIZE, MAX_FRAME_BYTES
from blender_mcp_protocol.errors import BridgeError, BridgeErrorCode


def encode_frame(payload: dict[str, Any]) -> bytes:
    """Encode a JSON-serializable dict as a length-prefixed UTF-8 frame."""
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    if len(body) > MAX_FRAME_BYTES:
        raise BridgeError(
            BridgeErrorCode.INVALID_REQUEST,
            f"Frame size {len(body)} exceeds max limit of {MAX_FRAME_BYTES} bytes",
        )
    return struct.pack(HEADER_FORMAT, len(body)) + body


def decode_frame_length(header: bytes) -> int:
    """Decode and validate a 4-byte length header."""
    if len(header) != HEADER_SIZE:
        raise BridgeError(BridgeErrorCode.PARSE_ERROR, "Incomplete frame header")
    (length,) = struct.unpack(HEADER_FORMAT, header)
    if length == 0 or length > MAX_FRAME_BYTES:
        raise BridgeError(
            BridgeErrorCode.PARSE_ERROR,
            f"Invalid frame length: {length}",
        )
    return int(length)


def decode_payload(body: bytes) -> dict[str, Any]:
    """Decode UTF-8 JSON bytes into a dictionary."""
    try:
        obj = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BridgeError(BridgeErrorCode.PARSE_ERROR, f"Invalid JSON payload: {exc}") from exc
    if not isinstance(obj, dict):
        raise BridgeError(BridgeErrorCode.INVALID_REQUEST, "JSON-RPC message must be an object")
    return obj


def _recv_exact_sync(sock: socket.socket, size: int) -> bytes | None:
    chunks: list[bytes] = []
    remaining = size
    while remaining > 0:
        chunk = sock.recv(remaining)
        if not chunk:
            if not chunks:
                return None
            raise ConnectionError("Unexpected EOF while reading RPC frame")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def read_frame_sync(sock: socket.socket) -> dict[str, Any] | None:
    """Read a single length-prefixed JSON frame from a blocking socket.

    Returns None on clean EOF.
    """
    header = _recv_exact_sync(sock, HEADER_SIZE)
    if header is None:
        return None
    length = decode_frame_length(header)
    body = _recv_exact_sync(sock, length)
    if body is None:
        raise ConnectionError("Unexpected EOF while reading RPC body")
    return decode_payload(body)


def write_frame_sync(sock: socket.socket, payload: dict[str, Any]) -> None:
    """Write a single length-prefixed JSON frame to a blocking socket."""
    sock.sendall(encode_frame(payload))


async def read_frame_async(reader: asyncio.StreamReader) -> dict[str, Any] | None:
    """Read a single length-prefixed JSON frame from an asyncio StreamReader.

    Returns None on clean EOF.
    """
    try:
        header = await reader.readexactly(HEADER_SIZE)
    except asyncio.IncompleteReadError as exc:
        if not exc.partial:
            return None
        raise ConnectionError("Unexpected EOF while reading RPC header") from exc
    length = decode_frame_length(header)
    try:
        body = await reader.readexactly(length)
    except asyncio.IncompleteReadError as exc:
        raise ConnectionError("Unexpected EOF while reading RPC body") from exc
    return decode_payload(body)


async def write_frame_async(writer: asyncio.StreamWriter, payload: dict[str, Any]) -> None:
    """Write a single length-prefixed JSON frame to an asyncio StreamWriter."""
    writer.write(encode_frame(payload))
    await writer.drain()
