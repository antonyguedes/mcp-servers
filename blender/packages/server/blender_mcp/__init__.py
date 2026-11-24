# SPDX-License-Identifier: MIT
"""blender-mcp: Production-grade MCP server for Blender 3D."""

from blender_mcp.app import create_server
from blender_mcp.config import ServerSettings

__version__ = "1.0.0"
__all__ = ["ServerSettings", "__version__", "create_server"]
