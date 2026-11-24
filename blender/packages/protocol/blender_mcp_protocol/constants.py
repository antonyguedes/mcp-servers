# SPDX-License-Identifier: MIT
"""Protocol constants shared between MCP server and Blender bridge."""

from __future__ import annotations

PROTOCOL_VERSION = "1.0"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 9876
HEADER_FORMAT = "!I"
HEADER_SIZE = 4
# 64 MiB max single RPC frame (covers high-res base64 renders safely)
MAX_FRAME_BYTES = 64 * 1024 * 1024
JSONRPC_VERSION = "2.0"
