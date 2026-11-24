# SPDX-License-Identifier: MIT
"""End-to-end Phase 3 integration tests against a real headless Blender 5.3+ process."""

from __future__ import annotations

import asyncio
import base64
import io
import json
from pathlib import Path

import pytest
from PIL import Image

from blender_mcp.app import create_server
from blender_mcp.bridge.client import BridgeClient
from blender_mcp.bridge.launcher import find_blender_executable, launch_blender_headless
from blender_mcp.config import ServerSettings
from blender_mcp_protocol import PythonPolicy

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        find_blender_executable() is None,
        reason="No Blender executable installed on this machine",
    ),
]


def _extract_json(call_result: object) -> dict:
    if getattr(call_result, "is_error", False):
        content = getattr(call_result, "content", []) or []
        msg = content[0].text if content else "Unknown MCP tool error"
        raise RuntimeError(msg)
    structured = getattr(call_result, "structured_content", None)
    if isinstance(structured, dict):
        return structured
    content = getattr(call_result, "content", None)
    if content:
        return json.loads(content[0].text)
    raise AssertionError(f"Unexpected call_tool result: {call_result!r}")


@pytest.fixture(scope="module")
def blender_p3():
    proc = launch_blender_headless(allow_python=False, startup_timeout=45.0)
    try:
        yield proc
    finally:
        proc.stop()


async def test_phase3_animation_rigging_physics_sculpt_gp(blender_p3, tmp_path: Path) -> None:
    settings = ServerSettings(
        host=blender_p3.host,
        port=blender_p3.port,
        token=blender_p3.token,
        host_explicit=True,
        port_explicit=True,
        profile="full",
        python_policy=PythonPolicy.FALSE,
        allowed_dirs=[tmp_path],
        audit_log=None,
    )
    bridge = BridgeClient(settings)
    mcp = create_server(settings, bridge=bridge)

    try:
        _extract_json(await mcp.call_tool("create_checkpoint", {"name": "p3_start"}))

        # 1. Animation: Slotted Actions (5.x) / Classic Actions (3.6-4.x)
        fr = _extract_json(
            await mcp.call_tool("set_frame_range", {"frame_start": 1, "frame_end": 20, "fps": 24, "frame_current": 1})
        )
        assert fr["frame_end"] == 20
        assert fr["fps"] == 24

        kf = _extract_json(
            await mcp.call_tool(
                "insert_keyframes",
                {
                    "object": "Cube",
                    "data_path": "rotation_euler",
                    "interpolation": "LINEAR",
                    "keyframes": [
                        {"frame": 1, "value": [0.0, 0.0, 0.0]},
                        {"frame": 20, "value": [0.0, 0.0, 360.0]},
                    ],
                },
            )
        )
        assert kf["frames"] == [1, 20]

        listed = _extract_json(await mcp.call_tool("list_keyframes", {"object": "Cube"}))
        assert len(listed["fcurves"]) >= 3
        assert listed["fcurves"][2]["keyframes"][0]["interpolation"] == "LINEAR"

        interp = _extract_json(await mcp.call_tool("set_interpolation", {"object": "Cube", "interpolation": "BEZIER"}))
        assert interp["updated_keyframes"] >= 6

        # Constraint + Driver + NLA + Shape Keys
        _extract_json(await mcp.call_tool("create_primitive", {"primitive": "empty", "name": "LookTarget", "location": [0, 3, 1]}))
        con = _extract_json(
            await mcp.call_tool(
                "add_constraint",
                {"object": "Camera", "constraint_type": "TRACK_TO", "target": "LookTarget"},
            )
        )
        assert con["type"] == "TRACK_TO"

        drv = _extract_json(
            await mcp.call_tool(
                "add_driver",
                {"object": "LookTarget", "data_path": "location", "index": 2, "expression": "frame * 0.05"},
            )
        )
        assert drv["drivers_created"] == 1

        nla = _extract_json(await mcp.call_tool("nla_push_down", {"object": "Cube", "track_name": "TurntableTrack"}))
        assert nla["track"] == "TurntableTrack"

        sk = _extract_json(
            await mcp.call_tool(
                "shape_key_add",
                {"object": "Cube", "name": "Stretched", "scale_offset": [1.0, 1.0, 1.5], "value": 0.5},
            )
        )
        assert "Stretched" in sk["all_keys"]
        sk_set = _extract_json(
            await mcp.call_tool("shape_key_set", {"object": "Cube", "shape_key": "Stretched", "value": 1.0, "keyframe_frame": 10})
        )
        assert sk_set["keyframed"] is True

        # 2. Rigging: Armature + Auto Weights + Bone Pose + IK
        _extract_json(
            await mcp.call_tool(
                "create_primitive",
                {"primitive": "cylinder", "name": "ArmMesh", "radius": 0.15, "depth": 2.0, "location": [3.0, 0.0, 1.0]},
            )
        )
        arm = _extract_json(
            await mcp.call_tool(
                "create_armature",
                {
                    "name": "ArmRig",
                    "location": [3.0, 0.0, 0.0],
                    "bones": [
                        {"name": "Upper", "head": [0, 0, 0], "tail": [0, 0, 1.0]},
                        {"name": "Lower", "head": [0, 0, 1.0], "tail": [0, 0, 2.0], "parent": "Upper", "use_connect": True},
                    ],
                },
            )
        )
        assert arm["bones"] == ["Upper", "Lower"]

        bound = _extract_json(await mcp.call_tool("bind_auto_weights", {"mesh": "ArmMesh", "armature": "ArmRig"}))
        assert len(bound["vertex_groups"]) >= 2

        posed = _extract_json(
            await mcp.call_tool(
                "pose_bone",
                {"armature": "ArmRig", "bone": "Lower", "rotation_degrees": [30.0, 0.0, 0.0], "keyframe_frame": 1},
            )
        )
        assert posed["keyframed"] is True

        ik = _extract_json(await mcp.call_tool("setup_ik", {"armature": "ArmRig", "bone": "Lower", "chain_count": 2}))
        assert ik["target"].startswith("IK_Lower")

        # 3. Physics: Rigid Body + Cloth + Collision + Fluid + Cooperative Bake Job
        _extract_json(
            await mcp.call_tool("create_primitive", {"primitive": "plane", "name": "PhysFloor", "size": 6.0, "location": [0, 0, -2.0]})
        )
        _extract_json(
            await mcp.call_tool("create_primitive", {"primitive": "uv_sphere", "name": "PhysBall", "radius": 0.4, "location": [0, 0, 2.0]})
        )
        rb_floor = _extract_json(await mcp.call_tool("add_rigid_body", {"object": "PhysFloor", "body_type": "PASSIVE"}))
        rb_ball = _extract_json(
            await mcp.call_tool("add_rigid_body", {"object": "PhysBall", "body_type": "ACTIVE", "mass": 2.0, "restitution": 0.6})
        )
        assert rb_floor["body_type"] == "PASSIVE"
        assert rb_ball["mass"] == pytest.approx(2.0)

        _extract_json(await mcp.call_tool("add_collision", {"object": "PhysFloor"}))
        _extract_json(await mcp.call_tool("create_primitive", {"primitive": "grid", "name": "ClothSheet", "size": 2.0, "location": [0, 0, 3.5]}))
        cloth = _extract_json(await mcp.call_tool("add_cloth", {"object": "ClothSheet", "quality": 3}))
        assert cloth["quality"] == 3

        _extract_json(await mcp.call_tool("create_primitive", {"primitive": "cube", "name": "FluidBox", "size": 1.0, "location": [-4, 0, 0]}))
        fl = _extract_json(
            await mcp.call_tool("add_fluid", {"object": "FluidBox", "fluid_type": "DOMAIN", "domain_type": "GAS", "resolution_max": 16})
        )
        assert fl["fluid_type"] == "DOMAIN"

        baked = _extract_json(await mcp.call_tool("bake_physics", {"frame_start": 1, "frame_end": 5, "wait": True}))
        assert baked["status"] == "completed"
        assert baked["result"]["frames_simulated"] == 5

        # 4. Sculpt (remesh + stroke) & Grease Pencil (GPv3 on Blender 5.3)
        _extract_json(
            await mcp.call_tool("create_primitive", {"primitive": "uv_sphere", "name": "SculptClay", "radius": 1.0, "location": [-3, 3, 0]})
        )
        rem = _extract_json(await mcp.call_tool("sculpt_remesh", {"object": "SculptClay", "voxel_size": 0.15}))
        assert rem["vertices"] > 100

        st = _extract_json(
            await mcp.call_tool(
                "sculpt_stroke",
                {
                    "object": "SculptClay",
                    "brush": "DRAW",
                    "points": [[-3.0, 2.0, 0.0], [-3.0, 2.0, 0.5]],
                    "radius": 0.6,
                    "strength": 0.25,
                    "symmetry_x": True,
                },
            )
        )
        assert st["affected_vertices"] > 0

        gp = _extract_json(await mcp.call_tool("gp_create_object", {"name": "SketchGP", "layer_name": "Ink"}))
        assert gp["type"] in ("GREASEPENCIL", "GPENCIL")
        gp_st = _extract_json(
            await mcp.call_tool(
                "gp_draw_stroke",
                {
                    "object": "SketchGP",
                    "layer": "Ink",
                    "frame": 1,
                    "points": [[0.0, 0.0, 0.0], [0.5, 0.0, 0.5], [1.0, 0.0, 0.0]],
                },
            )
        )
        assert gp_st["points"] == 3

        _extract_json(await mcp.call_tool("restore_checkpoint", {"name": "p3_start"}))
    finally:
        await bridge.close()


async def test_phase3_cycles_turntable_and_cancellation(blender_p3, tmp_path: Path) -> None:
    """Verify Cycles still render, animated turntable render, and mid-flight job cancellation."""
    settings = ServerSettings(
        host=blender_p3.host,
        port=blender_p3.port,
        token=blender_p3.token,
        host_explicit=True,
        port_explicit=True,
        profile="full",
        python_policy=PythonPolicy.FALSE,
        allowed_dirs=[tmp_path],
        audit_log=None,
    )
    bridge = BridgeClient(settings)
    mcp = create_server(settings, bridge=bridge)

    try:
        # Configure lightweight Cycles CPU render
        cfg = _extract_json(
            await mcp.call_tool(
                "configure_render",
                {
                    "engine": "cycles",
                    "device": "CPU",
                    "samples": 2,
                    "resolution_x": 96,
                    "resolution_y": 96,
                },
            )
        )
        assert cfg["engine"] == "CYCLES"

        # Animate Cube turntable over 4 frames
        _extract_json(
            await mcp.call_tool(
                "insert_keyframes",
                {
                    "object": "Cube",
                    "data_path": "rotation_euler",
                    "interpolation": "LINEAR",
                    "keyframes": [
                        {"frame": 1, "value": [0.0, 0.0, 0.0]},
                        {"frame": 4, "value": [0.0, 0.0, 90.0]},
                    ],
                },
            )
        )

        # 1. Still render with inline image return
        still_path = tmp_path / "still.png"
        still_res = await mcp.call_tool(
            "render_still",
            {"output_path": str(still_path), "engine": "cycles", "samples": 2, "width": 96, "height": 96, "return_image": True},
        )
        assert len(still_res.content) == 2
        assert still_res.content[1].type == "image"
        assert still_path.is_file()
        img = Image.open(io.BytesIO(base64.b64decode(still_res.content[1].data)))
        assert img.size == (96, 96)

        # 2. Complete 4-frame Cycles turntable render
        anim_dir = tmp_path / "turntable"
        anim_done = _extract_json(
            await mcp.call_tool(
                "render_animation",
                {
                    "output_dir": str(anim_dir),
                    "frame_start": 1,
                    "frame_end": 4,
                    "engine": "cycles",
                    "samples": 2,
                    "width": 64,
                    "height": 64,
                    "wait": True,
                },
            )
        )
        assert anim_done["status"] == "completed"
        assert anim_done["result"]["rendered_count"] == 4
        assert len(list(anim_dir.glob("frame_*.png"))) == 4

        # 3. Mid-flight cancellation of a 40-frame Cycles render
        cancel_dir = tmp_path / "cancelled_anim"
        started = _extract_json(
            await mcp.call_tool(
                "render_animation",
                {
                    "output_dir": str(cancel_dir),
                    "frame_start": 1,
                    "frame_end": 40,
                    "engine": "cycles",
                    "samples": 4,
                    "width": 128,
                    "height": 128,
                    "wait": False,
                },
            )
        )
        job_id = started["job_id"]
        assert started["status"] in ("pending", "running")

        # Wait briefly so at least 1 frame starts, then cancel immediately
        await asyncio.sleep(0.25)
        _extract_json(await mcp.call_tool("cancel_job", {"job_id": job_id}))

        final_state: dict = {}
        for _ in range(50):
            final_state = _extract_json(await mcp.call_tool("get_job_status", {"job_id": job_id}))
            if final_state["status"] in ("cancelled", "completed", "failed"):
                break
            await asyncio.sleep(0.1)

        assert final_state["status"] == "cancelled"
        rendered_before_cancel = (final_state.get("result") or {}).get("rendered_count", 0)
        assert rendered_before_cancel < 40

        jobs_list = _extract_json(await mcp.call_tool("list_jobs", {"limit": 10}))
        assert any(j["job_id"] == job_id for j in jobs_list["jobs"])
    finally:
        await bridge.close()
