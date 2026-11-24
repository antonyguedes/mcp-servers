# SPDX-License-Identifier: MIT
"""End-to-end Phase 2 integration tests against a real headless Blender process."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from mcp.server.mcpserver.exceptions import ToolError

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
def blender_p2():
    proc = launch_blender_headless(allow_python=False, startup_timeout=45.0)
    try:
        yield proc
    finally:
        proc.stop()


async def test_phase2_mesh_uv_and_modifiers(blender_p2, tmp_path: Path) -> None:
    settings = ServerSettings(
        host=blender_p2.host,
        port=blender_p2.port,
        token=blender_p2.token,
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
        _extract_json(await mcp.call_tool("create_checkpoint", {"name": "p2_start"}))

        # 1. bmesh modeling chain
        _extract_json(
            await mcp.call_tool("create_primitive", {"primitive": "cube", "name": "HeroBlock", "size": 2.0})
        )
        stats = _extract_json(await mcp.call_tool("mesh_stats", {"object": "HeroBlock"}))
        assert stats["vertices"] == 8
        assert stats["quads"] == 6
        assert stats["is_manifold"] is True
        assert stats["volume"] == pytest.approx(8.0, abs=0.05)

        inset = _extract_json(
            await mcp.call_tool("mesh_inset", {"object": "HeroBlock", "direction": "top", "thickness": 0.2})
        )
        assert inset["faces"] > 6

        extruded = _extract_json(
            await mcp.call_tool("mesh_extrude", {"object": "HeroBlock", "direction": "top", "distance": 0.5, "scale": 0.8})
        )
        assert extruded["vertices"] > inset["vertices"]

        cut = _extract_json(await mcp.call_tool("mesh_loop_cut", {"object": "HeroBlock", "axis": "Z", "cuts": 2}))
        assert cut["faces"] > extruded["faces"]

        beveled = _extract_json(
            await mcp.call_tool("mesh_bevel", {"object": "HeroBlock", "offset": 0.02, "segments": 2})
        )
        assert beveled["faces"] > cut["faces"]

        sub = _extract_json(await mcp.call_tool("mesh_subdivide", {"object": "HeroBlock", "cuts": 1}))
        assert sub["faces"] > beveled["faces"]

        merged = _extract_json(await mcp.call_tool("mesh_merge_by_distance", {"object": "HeroBlock", "distance": 0.0001}))
        assert merged["vertices"] > 0

        _extract_json(await mcp.call_tool("mesh_recalc_normals", {"object": "HeroBlock"}))
        shading = _extract_json(
            await mcp.call_tool("mesh_set_shading", {"object": "HeroBlock", "mode": "auto", "angle_degrees": 35.0})
        )
        assert shading["shading"] == "auto"

        uv = _extract_json(await mcp.call_tool("uv_unwrap", {"object": "HeroBlock", "method": "box"}))
        assert uv["uv_loops"] > 0

        # 2. Boolean difference
        _extract_json(
            await mcp.call_tool(
                "create_primitive",
                {"primitive": "cube", "name": "BoolBase", "size": 2.0, "location": [4.0, 0.0, 0.0]},
            )
        )
        _extract_json(
            await mcp.call_tool(
                "create_primitive",
                {"primitive": "cylinder", "name": "BoolCutter", "radius": 0.5, "depth": 3.0, "location": [4.0, 0.0, 0.0]},
            )
        )
        b_res = _extract_json(
            await mcp.call_tool(
                "mesh_boolean",
                {"target": "BoolBase", "cutter": "BoolCutter", "operation": "DIFFERENCE", "delete_cutter": True},
            )
        )
        assert b_res["cutter_deleted"] is True
        assert b_res["faces"] > 6

        # 3. Typed modifiers stack: add, reorder, configure, apply, remove
        _extract_json(
            await mcp.call_tool(
                "create_primitive", {"primitive": "cube", "name": "ModBox", "size": 1.0, "location": [-3.0, 0.0, 0.0]}
            )
        )
        _extract_json(
            await mcp.call_tool(
                "add_modifier",
                {"object": "ModBox", "modifier_type": "SUBSURF", "name": "SubD", "settings": {"levels": 1, "render_levels": 2}},
            )
        )
        _extract_json(
            await mcp.call_tool(
                "add_modifier",
                {"object": "ModBox", "modifier_type": "BEVEL", "name": "Bev", "settings": {"width": 0.05, "segments": 2}},
            )
        )
        reordered = _extract_json(
            await mcp.call_tool("reorder_modifier", {"object": "ModBox", "modifier": "Bev", "index": 0})
        )
        assert reordered["order"] == ["Bev", "SubD"]

        _extract_json(
            await mcp.call_tool("configure_modifier", {"object": "ModBox", "modifier": "SubD", "settings": {"levels": 2}})
        )
        applied = _extract_json(await mcp.call_tool("apply_modifier", {"object": "ModBox", "modifier": "SubD"}))
        assert applied["applied"] == ["SubD"]
        assert applied["faces"] > 6

        removed = _extract_json(await mcp.call_tool("remove_modifier", {"object": "ModBox", "modifier": "Bev"}))
        assert removed["removed"] == "Bev"

        _extract_json(await mcp.call_tool("restore_checkpoint", {"name": "p2_start"}))
    finally:
        await bridge.close()


async def test_phase2_declarative_nodes_dsl(blender_p2, tmp_path: Path) -> None:
    """Test Shader DSL, Geometry Nodes scatter DSL, Compositor DSL, patch, and live introspection."""
    settings = ServerSettings(
        host=blender_p2.host,
        port=blender_p2.port,
        token=blender_p2.token,
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
        # 1. Live node introspection
        ntypes = _extract_json(
            await mcp.call_tool(
                "list_node_types",
                {"tree_type": "shader", "search": "TexNoise", "include_sockets": True},
            )
        )
        assert any(item["type"] == "ShaderNodeTexNoise" for item in ntypes["node_types"])
        noise_info = next(item for item in ntypes["node_types"] if item["type"] == "ShaderNodeTexNoise")
        assert any(s["name"] == "Scale" for s in noise_info["inputs"])

        # 2. Procedural Shader via DSL (with ColorRamp elements + implicit output + auto layout)
        built_shader = _extract_json(
            await mcp.call_tool(
                "build_node_tree",
                {
                    "tree": "material:BrushedGold",
                    "nodes": {
                        "noise": {"type": "ShaderNodeTexNoise", "inputs": {"Scale": 40.0, "Detail": 8.0}},
                        "ramp": {
                            "type": "ShaderNodeValToRGB",
                            "props": {
                                "color_ramp.elements": [
                                    [0.35, [0.18, 0.18, 0.18, 1.0]],
                                    [0.65, [0.45, 0.45, 0.45, 1.0]],
                                ]
                            },
                        },
                        "bsdf": {
                            "type": "ShaderNodeBsdfPrincipled",
                            "inputs": {"Base Color": [1.0, 0.77, 0.34, 1.0], "Metallic": 1.0},
                        },
                    },
                    "links": [
                        ["noise.Fac", "ramp.Fac"],
                        ["ramp.Color", "bsdf.Roughness"],
                        ["bsdf.BSDF", "output.Surface"],
                    ],
                    "layout": "auto",
                },
            )
        )
        assert built_shader["node_count"] == 4
        assert built_shader["link_count"] == 3
        assert "color_ramp.elements" in built_shader["nodes"]["ramp"]["props"]

        # Bidirectional read-back
        readback = _extract_json(await mcp.call_tool("get_node_tree", {"tree": "material:BrushedGold"}))
        assert readback["node_count"] == 4
        assert readback["nodes"]["noise"]["inputs"]["Scale"] == pytest.approx(40.0)

        # Incremental patch: add Bump node and update noise Scale
        patched = _extract_json(
            await mcp.call_tool(
                "patch_node_tree",
                {
                    "tree": "material:BrushedGold",
                    "add_nodes": {"bump": {"type": "ShaderNodeBump", "inputs": {"Strength": 0.15}}},
                    "update_nodes": {"noise": {"inputs": {"Scale": 65.0}}},
                    "add_links": [
                        ["noise.Fac", "bump.Height"],
                        ["bump.Normal", "bsdf.Normal"],
                    ],
                    "relayout": True,
                },
            )
        )
        assert patched["node_count"] == 5
        assert patched["link_count"] == 5
        assert patched["nodes"]["noise"]["inputs"]["Scale"] == pytest.approx(65.0)

        # 3. Geometry Nodes scatter via DSL + custom interface input + modifier attachment
        _extract_json(
            await mcp.call_tool("create_primitive", {"primitive": "plane", "name": "ScatterGround", "size": 4.0})
        )
        gn = _extract_json(
            await mcp.call_tool(
                "build_node_tree",
                {
                    "tree": "geonodes:ScatterBoxes",
                    "interface": [
                        {
                            "name": "Density",
                            "in_out": "INPUT",
                            "socket_type": "NodeSocketFloat",
                            "default_value": 10.0,
                        }
                    ],
                    "nodes": {
                        "dist": {"type": "GeometryNodeDistributePointsOnFaces"},
                        "box": {"type": "GeometryNodeMeshCube", "inputs": {"Size": [0.15, 0.15, 0.15]}},
                        "inst": {"type": "GeometryNodeInstanceOnPoints"},
                        "realize": {"type": "GeometryNodeRealizeInstances"},
                    },
                    "links": [
                        ["input.Geometry", "dist.Mesh"],
                        ["input.Density", "dist.Density"],
                        ["dist.Points", "inst.Points"],
                        ["box.Mesh", "inst.Instance"],
                        ["inst.Instances", "realize.Geometry"],
                        ["realize.Geometry", "output.Geometry"],
                    ],
                    "attach_to_object": "ScatterGround",
                },
            )
        )
        assert gn["attached_to_object"] == "ScatterGround"
        assert gn["link_count"] == 6

        updated_gn = _extract_json(
            await mcp.call_tool("set_group_inputs", {"object": "ScatterGround", "inputs": {"Density": 25.0}})
        )
        assert "Density" in updated_gn["applied"]

        # 4. Compositor DSL (transparently handles Blender 5.x compositing_node_group & 3.6-4.x scene.node_tree)
        comp = _extract_json(
            await mcp.call_tool(
                "build_node_tree",
                {
                    "tree": "compositor",
                    "nodes": {
                        "bc": {"type": "CompositorNodeBrightContrast", "inputs": {"Bright": 0.1, "Contrast": 0.2}},
                    },
                    "links": [
                        ["input.Image", "bc.Image"],
                        ["bc.Image", "output.Image"],
                    ],
                },
            )
        )
        assert comp["tree"] == "compositor"
        assert comp["link_count"] == 2
    finally:
        await bridge.close()


async def test_phase2_lighting_camera_io_and_introspection(blender_p2, tmp_path: Path) -> None:
    """Test lighting presets, sky, camera framing/DOF, glTF/OBJ/STL/.blend I/O, and RNA introspection."""
    settings = ServerSettings(
        host=blender_p2.host,
        port=blender_p2.port,
        token=blender_p2.token,
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
        _extract_json(
            await mcp.call_tool("create_primitive", {"primitive": "monkey", "name": "SuzanneHero", "smooth": True})
        )

        # 1. Lighting presets, sky, extra light, camera + framing + DOF
        rig = _extract_json(
            await mcp.call_tool("setup_lighting_preset", {"preset": "three_point", "target_objects": ["SuzanneHero"]})
        )
        assert len(rig["lights_created"]) == 3

        sky = _extract_json(await mcp.call_tool("set_world_sky", {"sky_type": "nishita", "sun_elevation": 30.0}))
        assert sky["sky_type"] in ("MULTIPLE_SCATTERING", "NISHITA", "SINGLE_SCATTERING")

        spot = _extract_json(
            await mcp.call_tool(
                "add_light",
                {"light_type": "SPOT", "name": "HeroSpot", "location": [2.0, -2.0, 3.0], "look_at": "SuzanneHero"},
            )
        )
        assert spot["light_type"] == "SPOT"

        cam = _extract_json(
            await mcp.call_tool(
                "add_camera",
                {"name": "HeroCam", "location": [3.0, -3.0, 2.0], "look_at": "SuzanneHero", "lens": 85.0},
            )
        )
        assert cam["is_active"] is True

        framed = _extract_json(
            await mcp.call_tool("camera_frame_objects", {"camera": "HeroCam", "objects": ["SuzanneHero"]})
        )
        assert framed["distance"] > 0.5

        dof = _extract_json(
            await mcp.call_tool(
                "set_camera_lens_dof",
                {"camera": "HeroCam", "lens": 75.0, "focus_object": "SuzanneHero", "fstop": 2.8},
            )
        )
        assert dof["use_dof"] is True
        assert dof["focus_object"] == "SuzanneHero"

        # 2. Export GLB, OBJ, STL, and .blend, then re-import GLB
        glb_path = tmp_path / "hero.glb"
        obj_path = tmp_path / "hero.obj"
        stl_path = tmp_path / "hero.stl"
        blend_path = tmp_path / "hero.blend"

        for fmt_path in (glb_path, obj_path, stl_path):
            exp = _extract_json(await mcp.call_tool("export_file", {"filepath": str(fmt_path)}))
            assert exp["exists"] is True
            assert exp["size_bytes"] > 0

        saved = _extract_json(await mcp.call_tool("save_blend", {"filepath": str(blend_path)}))
        assert saved["size_bytes"] > 0

        imp = _extract_json(await mcp.call_tool("import_file", {"filepath": str(glb_path)}))
        assert len(imp["imported_objects"]) >= 1

        # 3. Safe RNA inspection/mutation & operator safety
        _extract_json(
            await mcp.call_tool("set_rna", {"target": "render", "data_path": "resolution_x", "value": 1280})
        )
        rx = _extract_json(await mcp.call_tool("get_rna", {"target": "render", "data_path": "resolution_x"}))
        assert rx["value"] == 1280

        ops = _extract_json(await mcp.call_tool("list_operators", {"category": "mesh", "search": "subdivide"}))
        assert any(o["id"] == "mesh.subdivide" for o in ops["operators"])

        api = _extract_json(await mcp.call_tool("search_bpy_api", {"query": "Principled"}))
        assert len(api["matches"]) >= 1

        with pytest.raises(ToolError) as blocked:
            await mcp.call_tool("call_operator", {"operator": "wm.quit_blender"})
        assert "restricted" in str(blocked.value).lower()
    finally:
        await bridge.close()
