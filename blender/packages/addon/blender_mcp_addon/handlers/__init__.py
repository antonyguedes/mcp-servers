# SPDX-License-Identifier: GPL-3.0-or-later
"""Registration hub for all Blender MCP add-on RPC handlers."""

from __future__ import annotations

from ..dispatcher import Dispatcher
from . import (
    animation,
    collections,
    core,
    history,
    introspection,
    io,
    lighting_camera,
    materials,
    mesh,
    modifiers,
    nodes,
    objects,
    physics,
    render,
    rigging,
    scripting,
    sculpt_gp,
    vision,
)


def register_all_handlers(dispatcher: Dispatcher) -> None:
    # Phase 0 & 1
    core.register(dispatcher)
    objects.register(dispatcher)
    collections.register(dispatcher)
    materials.register(dispatcher)
    history.register(dispatcher)
    vision.register(dispatcher)
    scripting.register(dispatcher)
    # Phase 2
    mesh.register(dispatcher)
    modifiers.register(dispatcher)
    nodes.register(dispatcher)
    lighting_camera.register(dispatcher)
    io.register(dispatcher)
    introspection.register(dispatcher)
    # Phase 3
    animation.register(dispatcher)
    rigging.register(dispatcher)
    physics.register(dispatcher)
    render.register(dispatcher)
    sculpt_gp.register(dispatcher)
