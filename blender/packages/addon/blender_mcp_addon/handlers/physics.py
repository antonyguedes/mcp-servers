# SPDX-License-Identifier: GPL-3.0-or-later
"""Physics setup (Rigid Body, Cloth, Collision, Fluid) and cooperative baking jobs."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import bpy  # type: ignore[import-not-found]

from ..dispatcher import Dispatcher, ExecutionContext
from ..jobs import JobRecord
from ..state import resolve_object
from ..wire import AddonError, BridgeErrorCode


def _ensure_rigidbody_world() -> Any:
    scene = bpy.context.scene
    if scene.rigidbody_world is None:
        bpy.ops.rigidbody.world_add()
    return scene.rigidbody_world


def add_rigid_body(params: dict[str, Any], _ctx: ExecutionContext) -> dict[str, Any]:
    obj = resolve_object(str(params.get("object", "")))
    assert obj is not None
    rb_type = str(params.get("body_type", "ACTIVE")).strip().upper()
    if rb_type not in ("ACTIVE", "PASSIVE"):
        raise AddonError(BridgeErrorCode.INVALID_PARAMS, f"body_type must be ACTIVE or PASSIVE, got {rb_type!r}.")

    _ensure_rigidbody_world()
    if obj.rigid_body is None:
        with bpy.context.temp_override(active_object=obj, object=obj, selected_objects=[obj]):
            bpy.ops.rigidbody.object_add(type=rb_type)
    else:
        obj.rigid_body.type = rb_type

    rb = obj.rigid_body
    if params.get("mass") is not None:
        rb.mass = max(0.001, float(params["mass"]))
    if params.get("friction") is not None:
        rb.friction = max(0.0, float(params["friction"]))
    if params.get("restitution") is not None:
        rb.restitution = max(0.0, min(1.0, float(params["restitution"])))
    if params.get("collision_shape") is not None:
        rb.collision_shape = str(params["collision_shape"]).upper()
    if params.get("kinematic") is not None:
        rb.kinematic = bool(params["kinematic"])

    return {
        "object": obj.name,
        "body_type": rb.type,
        "mass": round(float(rb.mass), 4),
        "friction": round(float(rb.friction), 4),
        "restitution": round(float(rb.restitution), 4),
        "collision_shape": rb.collision_shape,
    }


def add_cloth(params: dict[str, Any], _ctx: ExecutionContext) -> dict[str, Any]:
    obj = resolve_object(str(params.get("object", "")))
    assert obj is not None
    if obj.type != "MESH":
        raise AddonError(BridgeErrorCode.INVALID_PARAMS, f"Cloth requires a MESH object (got {obj.type}).")

    mod = next((m for m in obj.modifiers if m.type == "CLOTH"), None)
    if mod is None:
        mod = obj.modifiers.new(name=str(params.get("name", "Cloth")), type="CLOTH")

    s = mod.settings
    if params.get("quality") is not None:
        s.quality = max(1, int(params["quality"]))
    if params.get("mass") is not None:
        s.mass = max(0.001, float(params["mass"]))
    if params.get("tension_stiffness") is not None:
        s.tension_stiffness = float(params["tension_stiffness"])
    if params.get("bending_stiffness") is not None:
        s.bending_stiffness = float(params["bending_stiffness"])
    if params.get("pin_group") is not None:
        s.vertex_group_mass = str(params["pin_group"])

    return {
        "object": obj.name,
        "modifier": mod.name,
        "quality": s.quality,
        "mass": round(float(s.mass), 4),
    }


def add_collision(params: dict[str, Any], _ctx: ExecutionContext) -> dict[str, Any]:
    obj = resolve_object(str(params.get("object", "")))
    assert obj is not None
    if obj.type != "MESH":
        raise AddonError(BridgeErrorCode.INVALID_PARAMS, f"Collision requires a MESH object (got {obj.type}).")

    mod = next((m for m in obj.modifiers if m.type == "COLLISION"), None)
    if mod is None:
        mod = obj.modifiers.new(name=str(params.get("name", "Collision")), type="COLLISION")

    c = obj.collision
    if params.get("damping") is not None:
        c.damping = float(params["damping"])
    if params.get("thickness_outer") is not None:
        c.thickness_outer = float(params["thickness_outer"])
    if params.get("friction_factor") is not None:
        c.cloth_friction = float(params["friction_factor"])

    return {
        "object": obj.name,
        "modifier": mod.name,
        "thickness_outer": round(float(c.thickness_outer), 4),
    }


def add_fluid(params: dict[str, Any], _ctx: ExecutionContext) -> dict[str, Any]:
    obj = resolve_object(str(params.get("object", "")))
    assert obj is not None
    if obj.type != "MESH":
        raise AddonError(BridgeErrorCode.INVALID_PARAMS, f"Fluid requires a MESH object (got {obj.type}).")

    fluid_type = str(params.get("fluid_type", "DOMAIN")).strip().upper()
    if fluid_type not in ("DOMAIN", "FLOW", "EFFECTOR"):
        raise AddonError(
            BridgeErrorCode.INVALID_PARAMS,
            f"Unsupported fluid_type {fluid_type!r}.",
            suggestions=["DOMAIN", "FLOW", "EFFECTOR"],
        )

    mod = next((m for m in obj.modifiers if m.type == "FLUID"), None)
    if mod is None:
        mod = obj.modifiers.new(name=str(params.get("name", "Fluid")), type="FLUID")
    mod.fluid_type = fluid_type

    if fluid_type == "DOMAIN" and mod.domain_settings is not None:
        ds = mod.domain_settings
        if params.get("domain_type"):
            ds.domain_type = str(params["domain_type"]).upper()
        if params.get("resolution_max") is not None:
            ds.resolution_max = max(8, int(params["resolution_max"]))
    elif fluid_type == "FLOW" and mod.flow_settings is not None:
        fs = mod.flow_settings
        if params.get("flow_type"):
            fs.flow_type = str(params["flow_type"]).upper()
        if params.get("flow_behavior"):
            fs.flow_behavior = str(params["flow_behavior"]).upper()

    return {"object": obj.name, "modifier": mod.name, "fluid_type": mod.fluid_type}


def bake_physics(params: dict[str, Any], ctx: ExecutionContext) -> dict[str, Any]:
    """Run a cancellable frame-by-frame physics evaluation/bake job."""
    scene = bpy.context.scene
    start = int(params.get("frame_start", scene.frame_start))
    end = int(params.get("frame_end", scene.frame_end))
    if end < start:
        raise AddonError(BridgeErrorCode.INVALID_PARAMS, "frame_end must be >= frame_start.")

    frames = list(range(start, end + 1))

    def _stepper(job: JobRecord) -> Iterator[None]:
        saved_frame = scene.frame_current
        if scene.rigidbody_world is not None and scene.rigidbody_world.point_cache is not None:
            scene.rigidbody_world.point_cache.frame_start = start
            scene.rigidbody_world.point_cache.frame_end = end
        baked_frames = 0
        try:
            for idx, fr in enumerate(frames):
                if job.is_cancelled:
                    break
                scene.frame_set(fr)
                bpy.context.view_layer.update()
                baked_frames = idx + 1
                job.update_progress(baked_frames, len(frames), f"Simulated frame {fr}/{end}")
                yield
            job.result = {
                "frame_start": start,
                "frame_end": end,
                "frames_simulated": baked_frames,
            }
        finally:
            scene.frame_set(saved_frame)

    rec = ctx.jobs.submit(
        "physics.bake",
        _stepper,
        total_steps=len(frames),
        message=f"Queued physics bake ({start}..{end})",
    )
    return rec.to_dict()


def register(dispatcher: Dispatcher) -> None:
    dispatcher.register("physics.add_rigid_body", add_rigid_body)
    dispatcher.register("physics.add_cloth", add_cloth)
    dispatcher.register("physics.add_collision", add_collision)
    dispatcher.register("physics.add_fluid", add_fluid)
    dispatcher.register("physics.bake_physics", bake_physics, mutating=False)
