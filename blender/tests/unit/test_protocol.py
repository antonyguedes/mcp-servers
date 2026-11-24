# SPDX-License-Identifier: MIT
"""Unit tests for blender_mcp_protocol and wire parity with packages/addon."""

from __future__ import annotations

import asyncio
import importlib.util
import socket
from pathlib import Path

import pytest

from blender_mcp_protocol import (
    MAX_FRAME_BYTES,
    PROTOCOL_VERSION,
    BridgeError,
    BridgeErrorCode,
    HandshakeResponse,
    PythonPolicy,
    RpcRequest,
    RpcResponse,
    encode_frame,
    parse_python_policy,
    read_frame_async,
    read_frame_sync,
    write_frame_async,
    write_frame_sync,
)


def _load_addon_wire_module():
    wire_path = (
        Path(__file__).resolve().parents[2]
        / "packages"
        / "addon"
        / "blender_mcp_addon"
        / "wire.py"
    )
    spec = importlib.util.spec_from_file_location("addon_wire_under_test", wire_path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_wire_parity_between_protocol_and_addon() -> None:
    addon_wire = _load_addon_wire_module()
    assert addon_wire.PROTOCOL_VERSION == PROTOCOL_VERSION
    assert addon_wire.MAX_FRAME_BYTES == MAX_FRAME_BYTES

    proto_codes = {m.name: m.value for m in BridgeErrorCode}
    addon_codes = {m.name: m.value for m in addon_wire.BridgeErrorCode}
    assert proto_codes == addon_codes

    sample = RpcRequest(method="core.list_objects", params={"limit": 10}, id=42, token="abc").to_dict()
    assert encode_frame(sample) == addon_wire.encode_frame(sample)


def test_sync_socket_framing_roundtrip() -> None:
    s1, s2 = socket.socketpair()
    try:
        msg = {"jsonrpc": "2.0", "id": 1, "method": "system.ping", "params": {"unicode": "olá 3D"}}
        write_frame_sync(s1, msg)
        received = read_frame_sync(s2)
        assert received == msg
        s1.close()
        assert read_frame_sync(s2) is None
    finally:
        s1.close()
        s2.close()


async def test_async_stream_framing_roundtrip() -> None:
    received: list[dict] = []

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        msg = await read_frame_async(reader)
        assert msg is not None
        received.append(msg)
        await write_frame_async(writer, RpcResponse.ok(msg["id"], {"ok": True}).to_dict())
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    async with server:
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        req = RpcRequest(method="test.echo", params={"x": [1, 2, 3]}, id=7, token="tok")
        await write_frame_async(writer, req.to_dict())
        resp_raw = await read_frame_async(reader)
        writer.close()
        await writer.wait_closed()

    assert received[0]["method"] == "test.echo"
    assert resp_raw is not None
    resp = RpcResponse.from_dict(resp_raw)
    assert resp.id == 7
    assert resp.result == {"ok": True}


def test_parse_python_policy_variants() -> None:
    assert parse_python_policy(None) == PythonPolicy.FALSE
    assert parse_python_policy("") == PythonPolicy.FALSE
    assert parse_python_policy("false") == PythonPolicy.FALSE
    assert parse_python_policy("0") == PythonPolicy.FALSE
    assert parse_python_policy("NO") == PythonPolicy.FALSE
    assert parse_python_policy("confirm") == PythonPolicy.CONFIRM
    assert parse_python_policy("ASK") == PythonPolicy.CONFIRM
    assert parse_python_policy("true") == PythonPolicy.TRUE
    assert parse_python_policy("1") == PythonPolicy.TRUE
    assert parse_python_policy("yes") == PythonPolicy.TRUE
    assert parse_python_policy(True) == PythonPolicy.TRUE
    assert parse_python_policy(False) == PythonPolicy.FALSE

    with pytest.raises(ValueError, match="Invalid BLENDER_MCP_ALLOW_PYTHON"):
        parse_python_policy("maybe")


def test_bridge_error_roundtrip_and_formatting() -> None:
    err = BridgeError(
        BridgeErrorCode.NOT_FOUND,
        "Object 'Cub' not found.",
        details={"total_objects": 3},
        suggestions=["Cube", "Cube.001"],
    )
    rehydrated = BridgeError.from_rpc_error(err.to_rpc_error())
    assert rehydrated.code == BridgeErrorCode.NOT_FOUND
    assert rehydrated.suggestions == ["Cube", "Cube.001"]
    formatted = rehydrated.format_for_agent()
    assert "Did you mean: 'Cube', 'Cube.001'?" in formatted


def test_handshake_response_deserialization() -> None:
    hs = HandshakeResponse.from_dict(
        {
            "protocol_version": "1.0",
            "addon_version": "0.1.0",
            "blender_version": [5, 3, 0],
            "blender_version_string": "5.3.0",
            "python_version": "3.13.13",
            "capabilities": {
                "render_engines": ["BLENDER_EEVEE", "CYCLES"],
                "has_slotted_actions": True,
                "is_background": True,
            },
        }
    )
    assert hs.blender_version == [5, 3, 0]
    assert hs.capabilities.has_slotted_actions is True
    assert hs.capabilities.is_background is True
