# SPDX-License-Identifier: MIT
"""Shared wire protocol, error codes, and message types for blender-mcp.

Strictly stdlib-only and Python 3.10+ compatible.
"""

from blender_mcp_protocol.constants import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    MAX_FRAME_BYTES,
    PROTOCOL_VERSION,
)
from blender_mcp_protocol.errors import BridgeError, BridgeErrorCode
from blender_mcp_protocol.framing import (
    decode_frame_length,
    encode_frame,
    read_frame_async,
    read_frame_sync,
    write_frame_async,
    write_frame_sync,
)
from blender_mcp_protocol.messages import (
    BlenderCapabilities,
    HandshakeResponse,
    PythonPolicy,
    RpcNotification,
    RpcRequest,
    RpcResponse,
    SceneDiff,
    parse_python_policy,
)

__all__ = [
    "DEFAULT_HOST",
    "DEFAULT_PORT",
    "MAX_FRAME_BYTES",
    "PROTOCOL_VERSION",
    "BlenderCapabilities",
    "BridgeError",
    "BridgeErrorCode",
    "HandshakeResponse",
    "PythonPolicy",
    "RpcNotification",
    "RpcRequest",
    "RpcResponse",
    "SceneDiff",
    "decode_frame_length",
    "encode_frame",
    "parse_python_policy",
    "read_frame_async",
    "read_frame_sync",
    "write_frame_async",
    "write_frame_sync",
]
