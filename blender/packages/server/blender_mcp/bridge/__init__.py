# SPDX-License-Identifier: MIT
"""Bridge client and headless Blender process management."""

from blender_mcp.bridge.client import BridgeClient
from blender_mcp.bridge.launcher import (
    HeadlessBlenderProcess,
    build_addon_zips,
    find_blender_executable,
    get_addon_source_dir,
    install_addon,
    launch_blender_headless,
)
from blender_mcp.bridge.pool import BridgePool

__all__ = [
    "BridgeClient",
    "BridgePool",
    "HeadlessBlenderProcess",
    "build_addon_zips",
    "find_blender_executable",
    "get_addon_source_dir",
    "install_addon",
    "launch_blender_headless",
]
