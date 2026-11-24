# SPDX-License-Identifier: MIT
"""End-to-end integration tests running against a real headless Blender process."""

from __future__ import annotations

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
from blender_mcp_protocol import BridgeError, BridgeErrorCode, PythonPolicy

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        find_blender_executable() is None,
        reason="No Blender executable installed on this machine",
    ),
]


def _extract_json(call_result: object) -> dict:
    """Normalize MCPServer (mcp 2.x) CallToolResult into a Python dict."""
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
    raise AssertionError(f"Unexpected call_tool result format: {call_result!r}")


@pytest.fixture(scope="module")
def headless_blender():
    proc = launch_blender_headless(allow_python=False, startup_timeout=45.0)
    try:
        yield proc
    finally:
        proc.stop()


async def test_rejects_invalid_token(headless_blender) -> None:
    bad_settings = ServerSettings(
        host=headless_blender.host,
        port=headless_blender.port,
        token="wrong-token",
        host_explicit=True,
        port_explicit=True,
        audit_log=None,
    )
    client = BridgeClient(bad_settings)
    try:
        with pytest.raises(BridgeError) as exc:
            await client.connect()
        assert exc.value.code == BridgeErrorCode.UNAUTHORIZED
    finally:
        await client.close()


async def test_full_f1_scene_workflow_without_python(headless_blender, tmp_path: Path) -> None:
    """End-to-end MVP benchmark: build a table + chair with materials, inspect visually, rollback."""
    settings = ServerSettings(
        host=headless_blender.host,
        port=headless_blender.port,
        token=headless_blender.token,
        host_explicit=True,
        port_explicit=True,
        python_policy=PythonPolicy.FALSE,
        allowed_dirs=[tmp_path],
        audit_log=tmp_path / "audit.jsonl",
    )
    bridge = BridgeClient(settings)
    mcp = create_server(settings, bridge=bridge)

    try:
        # 1. Info & Scene Summary
        info = _extract_json(await mcp.call_tool("get_blender_info", {}))
        assert info["blender_version"][0] >= 3
        assert info["capabilities"]["is_background"] is True
        assert info["capabilities"]["addon_allows_python"] is False

        # Save initial factory checkpoint
        ckpt0 = _extract_json(await mcp.call_tool("create_checkpoint", {"name": "factory"}))
        assert ckpt0["name"] == "factory"

        # 2. Remove default Cube and organize into Furniture collection
        _extract_json(await mcp.call_tool("delete_objects", {"objects": ["Cube"]}))
        col = _extract_json(await mcp.call_tool("create_collection", {"name": "Furniture"}))
        assert col["name"] == "Furniture"

        # 3. Build a dining table (tabletop + 4 legs) using pure semantic tools
        top = _extract_json(
            await mcp.call_tool(
                "create_primitive",
                {
                    "primitive": "cube",
                    "name": "TableTop",
                    "size": 1.0,
                    "scale": [1.6, 0.9, 0.08],
                    "location": [0.0, 0.0, 0.76],
                    "collection": "Furniture",
                },
            )
        )
        assert top["name"] == "TableTop"
        assert top["uid"]
        assert "TableTop" in top["diff"]["created"]

        leg1 = _extract_json(
            await mcp.call_tool(
                "create_primitive",
                {
                    "primitive": "cylinder",
                    "name": "TableLeg_1",
                    "radius": 0.035,
                    "depth": 0.72,
                    "location": [-0.7, -0.35, 0.5],
                    "collection": "Furniture",
                },
            )
        )
        # Align leg cleanly to ground Z=0
        aligned = _extract_json(
            await mcp.call_tool("align_to_ground", {"objects": [leg1["uid"]], "target_z": 0.0})
        )
        assert aligned["aligned"][0]["location"][2] == pytest.approx(0.36, abs=0.01)

        # Duplicate remaining legs and parent them to TableTop
        dup = _extract_json(
            await mcp.call_tool(
                "duplicate_object",
                {"object": "TableLeg_1", "new_name": "TableLeg_Dup", "offset": [1.4, 0.0, 0.0], "count": 1},
            )
        )
        leg2_name = dup["created"][0]["name"]

        # Create custom mesh object (a small tabletop centerpiece pyramid)
        pyr = _extract_json(
            await mcp.call_tool(
                "create_mesh_object",
                {
                    "name": "Centerpiece",
                    "vertices": [
                        [-0.1, -0.1, 0.0],
                        [0.1, -0.1, 0.0],
                        [0.1, 0.1, 0.0],
                        [-0.1, 0.1, 0.0],
                        [0.0, 0.0, 0.25],
                    ],
                    "faces": [
                        [0, 1, 2, 3],
                        [0, 1, 4],
                        [1, 2, 4],
                        [2, 3, 4],
                        [3, 0, 4],
                    ],
                    "collection": "Furniture",
                },
            )
        )
        assert pyr["vertices"] == 5
        assert pyr["polygons"] == 5
        _extract_json(await mcp.call_tool("align_to_ground", {"objects": ["Centerpiece"], "target_z": 0.80}))

        # Parent legs under TableTop, test set_origin & apply_transforms & rename
        _extract_json(
            await mcp.call_tool(
                "parent_objects",
                {"children": ["TableLeg_1", leg2_name], "parent": "TableTop"},
            )
        )
        _extract_json(await mcp.call_tool("apply_transforms", {"object": "TableTop", "scale": True}))
        _extract_json(await mcp.call_tool("set_origin", {"object": "Centerpiece", "origin_type": "bottom_center"}))
        renamed = _extract_json(
            await mcp.call_tool("rename_object", {"object": "Centerpiece", "new_name": "CrystalPyramid"})
        )
        assert renamed["new_name"] == "CrystalPyramid"

        # Test join_objects on two small test cubes
        _extract_json(await mcp.call_tool("create_primitive", {"primitive": "cube", "name": "JoinA", "size": 0.2}))
        _extract_json(
            await mcp.call_tool(
                "create_primitive", {"primitive": "cube", "name": "JoinB", "size": 0.2, "location": [0.3, 0, 0]}
            )
        )
        joined = _extract_json(await mcp.call_tool("join_objects", {"target": "JoinA", "sources": ["JoinB"]}))
        assert joined["vertices"] == 16
        assert joined["polygons"] == 12

        # 4. Materials & Image Texture
        wood = _extract_json(
            await mcp.call_tool(
                "create_pbr_material",
                {
                    "name": "OakWood",
                    "base_color": [0.45, 0.28, 0.14, 1.0],
                    "roughness": 0.55,
                    "metallic": 0.0,
                    "assign_to": ["TableTop"],
                },
            )
        )
        assert wood["name"] == "OakWood"
        assert wood["assigned_to"] == ["TableTop"]

        metal = _extract_json(
            await mcp.call_tool(
                "create_pbr_material",
                {
                    "name": "BrushedSteel",
                    "base_color": [0.75, 0.77, 0.8, 1.0],
                    "metallic": 1.0,
                    "roughness": 0.25,
                },
            )
        )
        _extract_json(
            await mcp.call_tool("assign_material", {"material": metal["name"], "objects": ["TableLeg_1", leg2_name]})
        )
        _extract_json(
            await mcp.call_tool("set_material_params", {"material": "OakWood", "params": {"roughness": 0.42}})
        )

        # Create a real PNG image texture and wire it into OakWood
        tex_path = tmp_path / "wood_grain.png"
        Image.new("RGB", (32, 32), color=(140, 95, 50)).save(tex_path)
        tex_res = _extract_json(
            await mcp.call_tool(
                "create_texture_from_image",
                {"material": "OakWood", "filepath": str(tex_path), "channel": "base_color"},
            )
        )
        assert tex_res["channel"] == "base_color"

        # 5. Filtered listing + details + actionable close-match error suggestion
        listed = _extract_json(
            await mcp.call_tool("list_objects", {"collection": "Furniture", "object_type": "MESH"})
        )
        names = {o["name"] for o in listed["objects"]}
        assert {"TableTop", "TableLeg_1", leg2_name, "CrystalPyramid"}.issubset(names)

        details = _extract_json(await mcp.call_tool("get_object_details", {"object": top["uid"]}))
        assert details["name"] == "TableTop"
        assert details["materials"][0]["name"] == "OakWood"

        with pytest.raises(Exception) as typo_err:
            await mcp.call_tool("get_object_details", {"object": "TablTop"})
        assert "TableTop" in str(typo_err.value)

        # 6. Visual feedback loop: single viewport capture + 2x2 multiview contact sheet
        vp_res = await mcp.call_tool(
            "capture_viewport",
            {"view": "iso", "width": 256, "height": 192, "shading": "workbench"},
        )
        vp_content = vp_res.content
        assert len(vp_content) == 2
        assert vp_content[1].type == "image"
        vp_img = Image.open(io.BytesIO(base64.b64decode(vp_content[1].data)))
        assert vp_img.size == (256, 192)

        mv_res = await mcp.call_tool(
            "capture_multiview",
            {"tile_size": 128, "shading": "workbench"},
        )
        mv_content = mv_res.content
        assert len(mv_content) == 2
        mv_img = Image.open(io.BytesIO(base64.b64decode(mv_content[1].data)))
        assert mv_img.size == (268, 268)

        # 7. Checkpoint restore rolls scene cleanly back to factory state
        restored = _extract_json(await mcp.call_tool("restore_checkpoint", {"name": "factory"}))
        assert restored["restored"] == "factory"
        after_restore = _extract_json(await mcp.call_tool("list_objects", {}))
        restored_names = {o["name"] for o in after_restore["objects"]}
        assert "Cube" in restored_names
        assert "TableTop" not in restored_names

        # Verify audit log recorded mutations
        assert (tmp_path / "audit.jsonl").is_file()
        assert len((tmp_path / "audit.jsonl").read_text(encoding="utf-8").splitlines()) >= 10
    finally:
        await bridge.close()


async def test_execute_python_env_gate_e2e(tmp_path: Path) -> None:
    """Verify defense-in-depth for BLENDER_MCP_ALLOW_PYTHON=true end-to-end."""
    proc = launch_blender_headless(allow_python=True, startup_timeout=45.0)
    settings = ServerSettings(
        host=proc.host,
        port=proc.port,
        token=proc.token,
        host_explicit=True,
        port_explicit=True,
        python_policy=PythonPolicy.TRUE,
        audit_log=tmp_path / "py_audit.jsonl",
    )
    bridge = BridgeClient(settings)
    mcp = create_server(settings, bridge=bridge)
    try:
        res = _extract_json(
            await mcp.call_tool(
                "execute_python",
                {
                    "code": (
                        "print('hello from blender')\n"
                        "bpy.data.objects.new('PyMarker', None)\n"
                        "bpy.context.scene.collection.objects.link(bpy.data.objects['PyMarker'])\n"
                        "result = {'count': len(bpy.data.objects)}\n"
                    )
                },
            )
        )
        assert "hello from blender" in res["stdout"]
        assert res["result"]["count"] >= 1
        assert "PyMarker" in res["diff"]["created"]
    finally:
        await bridge.close()
        proc.stop()
