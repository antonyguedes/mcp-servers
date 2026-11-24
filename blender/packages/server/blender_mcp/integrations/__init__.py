# SPDX-License-Identifier: MIT
"""External 3D asset and AI generation integrations hub."""

from __future__ import annotations

from blender_mcp.config import ServerSettings
from blender_mcp.integrations.ai3d import AI3DProvider, AI3DRegistry
from blender_mcp.integrations.ambientcg import AmbientCGClient
from blender_mcp.integrations.cache import AssetCache
from blender_mcp.integrations.polyhaven import PolyHavenClient
from blender_mcp.integrations.sketchfab import SketchfabClient


class IntegrationsHub:
    """Central facade holding local AssetCache and all external asset/AI 3D providers."""

    def __init__(self, settings: ServerSettings) -> None:
        self.cache = AssetCache(settings.cache_dir)
        self.polyhaven = PolyHavenClient(self.cache)
        self.ambientcg = AmbientCGClient(self.cache)
        self.sketchfab = SketchfabClient(self.cache, api_key=settings.sketchfab_api_key)
        self.ai3d = AI3DRegistry(self.cache, settings)


__all__ = [
    "AI3DProvider",
    "AI3DRegistry",
    "AmbientCGClient",
    "AssetCache",
    "IntegrationsHub",
    "PolyHavenClient",
    "SketchfabClient",
]
