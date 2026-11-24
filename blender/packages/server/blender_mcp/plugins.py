# SPDX-License-Identifier: MIT
"""Third-party plugin discovery and loading via Python entry points (`blender_mcp.plugins`)."""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from importlib.metadata import entry_points
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mcp.server.mcpserver import MCPServer

    from blender_mcp.integrations import IntegrationsHub
    from blender_mcp.tools import ToolRuntime
    from blender_mcp.toolsets import ToolsetManager

logger = logging.getLogger("blender_mcp.plugins")

PLUGIN_ENTRY_POINT_GROUP = "blender_mcp.plugins"


@dataclass
class PluginContext:
    """Extension surface provided to every loaded blender-mcp plugin."""

    mcp: MCPServer
    runtime: ToolRuntime
    integrations: IntegrationsHub
    toolsets: ToolsetManager


PluginCallback = Callable[[PluginContext], Any]


def load_plugins(
    ctx: PluginContext,
    *,
    extra_plugins: Sequence[PluginCallback] | None = None,
    discover_entry_points: bool = True,
) -> list[str]:
    """Load installed `blender_mcp.plugins` entry points plus any programmatic plugins."""
    loaded: list[str] = []

    if discover_entry_points:
        try:
            eps = entry_points(group=PLUGIN_ENTRY_POINT_GROUP)
        except Exception:
            eps = ()
        for ep in eps:
            try:
                fn = ep.load()
                if callable(fn):
                    fn(ctx)
                    loaded.append(ep.name)
                    logger.info("Loaded blender-mcp plugin entry point: %s", ep.name)
            except Exception:
                logger.warning("Failed to load plugin entry point %s", ep.name, exc_info=True)

    for idx, fn in enumerate(extra_plugins or ()):
        name = getattr(fn, "__name__", f"plugin_{idx}")
        fn(ctx)
        loaded.append(name)

    return loaded
