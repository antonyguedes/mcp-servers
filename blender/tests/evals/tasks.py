# SPDX-License-Identifier: MIT
"""Representative end-to-end 3D agent evaluation tasks covering the full Blender pipeline."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer

from tests.evals.harness import EvalCase, assert_image_non_blank, extract_tool_json


async def _eval_furniture_dining_set(mcp: MCPServer, _work_dir: Path) -> dict[str, Any]:
    extract_tool_json(await mcp.call_tool("delete_objects", {"objects": ["Cube"]}))
    extract_tool_json(await mcp.call_tool("create_collection", {"name": "DiningSet"}))
    extract_tool_json(
        await mcp.call_tool(
            "create_primitive",
            {
                "primitive": "cube",
                "name": "DiningTop",
                "size": 1.0,
                "scale": [1.8, 1.0, 0.08],
                "location": [0, 0, 0.76],
                "collection": "DiningSet",
            },
        )
    )
    leg_positions = [(-0.8, -0.4, 0.5), (0.8, -0.4, 0.5), (-0.8, 0.4, 0.5), (0.8, 0.4, 0.5)]
    leg_names: list[str] = []
    for idx, pos in enumerate(leg_positions, 1):
        nm = f"Leg_{idx}"
        extract_tool_json(
            await mcp.call_tool(
                "create_primitive",
                {"primitive": "cylinder", "name": nm, "radius": 0.035, "depth": 0.72, "location": list(pos), "collection": "DiningSet"},
            )
        )
        leg_names.append(nm)
    extract_tool_json(await mcp.call_tool("align_to_ground", {"objects": leg_names, "target_z": 0.0}))
    extract_tool_json(await mcp.call_tool("parent_objects", {"children": leg_names, "parent": "DiningTop"}))
    extract_tool_json(
        await mcp.call_tool(
            "create_pbr_material",
            {"name": "Walnut", "base_color": [0.32, 0.18, 0.09, 1.0], "roughness": 0.48, "assign_to": ["DiningTop"]},
        )
    )
    extract_tool_json(
        await mcp.call_tool(
            "create_pbr_material",
            {"name": "BlackSteel", "base_color": [0.08, 0.08, 0.09, 1.0], "metallic": 1.0, "roughness": 0.3, "assign_to": leg_names},
        )
    )
    # Assert every leg rests at Z=0
    for nm in leg_names:
        det = extract_tool_json(await mcp.call_tool("get_object_details", {"object": nm}))
        assert abs(det["bbox_world"]["min"][2]) < 0.01
    mv = await mcp.call_tool("capture_multiview", {"tile_size": 128, "shading": "workbench"})
    vis = assert_image_non_blank(mv.content[1].data)
    return {"objects": 5, "visual": vis}


async def _eval_procedural_gold_dsl(mcp: MCPServer, _work_dir: Path) -> dict[str, Any]:
    extract_tool_json(await mcp.call_tool("create_primitive", {"primitive": "uv_sphere", "name": "GoldOrb", "smooth": True}))
    built = extract_tool_json(
        await mcp.call_tool(
            "build_node_tree",
            {
                "tree": "material:BrushedGoldEval",
                "nodes": {
                    "noise": {"type": "ShaderNodeTexNoise", "inputs": {"Scale": 35.0, "Detail": 6.0}},
                    "ramp": {
                        "type": "ShaderNodeValToRGB",
                        "props": {"color_ramp.elements": [[0.3, [0.15, 0.15, 0.15, 1.0]], [0.7, [0.4, 0.4, 0.4, 1.0]]]},
                    },
                    "bsdf": {
                        "type": "ShaderNodeBsdfPrincipled",
                        "inputs": {"Base Color": [1.0, 0.78, 0.32, 1.0], "Metallic": 1.0},
                    },
                },
                "links": [["noise.Fac", "ramp.Fac"], ["ramp.Color", "bsdf.Roughness"], ["bsdf.BSDF", "output.Surface"]],
            },
        )
    )
    assert built["node_count"] == 4
    extract_tool_json(await mcp.call_tool("assign_material", {"material": "BrushedGoldEval", "objects": ["GoldOrb"]}))
    extract_tool_json(await mcp.call_tool("setup_lighting_preset", {"preset": "studio", "target_objects": ["GoldOrb"]}))
    cap = await mcp.call_tool("capture_viewport", {"target_objects": ["GoldOrb"], "width": 192, "height": 192, "shading": "eevee"})
    vis = assert_image_non_blank(cap.content[1].data)
    return {"nodes": built["node_count"], "visual": vis}


async def _eval_geonodes_scatter(mcp: MCPServer, _work_dir: Path) -> dict[str, Any]:
    extract_tool_json(await mcp.call_tool("create_primitive", {"primitive": "plane", "name": "Meadow", "size": 5.0}))
    gn = extract_tool_json(
        await mcp.call_tool(
            "build_node_tree",
            {
                "tree": "geonodes:PebbleScatter",
                "interface": [{"name": "Density", "in_out": "INPUT", "socket_type": "NodeSocketFloat", "default_value": 12.0}],
                "nodes": {
                    "dist": {"type": "GeometryNodeDistributePointsOnFaces"},
                    "ico": {"type": "GeometryNodeMeshIcoSphere", "inputs": {"Radius": 0.12}},
                    "inst": {"type": "GeometryNodeInstanceOnPoints"},
                    "real": {"type": "GeometryNodeRealizeInstances"},
                },
                "links": [
                    ["input.Geometry", "dist.Mesh"],
                    ["input.Density", "dist.Density"],
                    ["dist.Points", "inst.Points"],
                    ["ico.Mesh", "inst.Instance"],
                    ["inst.Instances", "real.Geometry"],
                    ["real.Geometry", "output.Geometry"],
                ],
                "attach_to_object": "Meadow",
            },
        )
    )
    extract_tool_json(await mcp.call_tool("set_group_inputs", {"object": "Meadow", "inputs": {"Density": 20.0}}))
    assert gn["attached_to_object"] == "Meadow"
    return {"links": gn["link_count"]}


async def _eval_hard_surface_bracket(mcp: MCPServer, work_dir: Path) -> dict[str, Any]:
    extract_tool_json(await mcp.call_tool("create_primitive", {"primitive": "cube", "name": "Bracket", "size": 1.0}))
    extract_tool_json(await mcp.call_tool("mesh_bevel", {"object": "Bracket", "offset": 0.05, "segments": 2}))
    extract_tool_json(await mcp.call_tool("create_primitive", {"primitive": "cylinder", "name": "BoltHole", "radius": 0.2, "depth": 2.0}))
    b = extract_tool_json(
        await mcp.call_tool("mesh_boolean", {"target": "Bracket", "cutter": "BoltHole", "operation": "DIFFERENCE", "delete_cutter": True})
    )
    extract_tool_json(await mcp.call_tool("uv_unwrap", {"object": "Bracket", "method": "box"}))
    glb = work_dir / "bracket.glb"
    exp = extract_tool_json(await mcp.call_tool("export_file", {"filepath": str(glb)}))
    assert exp["size_bytes"] > 500
    return {"faces": b["faces"], "glb_bytes": exp["size_bytes"]}


async def _eval_turntable_and_rig(mcp: MCPServer, work_dir: Path) -> dict[str, Any]:
    extract_tool_json(await mcp.call_tool("set_frame_range", {"frame_start": 1, "frame_end": 3, "fps": 24}))
    extract_tool_json(
        await mcp.call_tool(
            "insert_keyframes",
            {
                "object": "Cube",
                "data_path": "rotation_euler",
                "interpolation": "LINEAR",
                "keyframes": [{"frame": 1, "value": [0, 0, 0]}, {"frame": 3, "value": [0, 0, 90]}],
            },
        )
    )
    arm = extract_tool_json(
        await mcp.call_tool(
            "create_armature",
            {
                "name": "BotArm",
                "bones": [
                    {"name": "Base", "head": [0, 0, 0], "tail": [0, 0, 0.8]},
                    {"name": "Forearm", "head": [0, 0, 0.8], "tail": [0, 0, 1.6], "parent": "Base", "use_connect": True},
                ],
            },
        )
    )
    extract_tool_json(await mcp.call_tool("setup_ik", {"armature": "BotArm", "bone": "Forearm", "chain_count": 2}))
    out_dir = work_dir / "turntable_eval"
    anim = extract_tool_json(
        await mcp.call_tool(
            "render_animation",
            {"output_dir": str(out_dir), "frame_start": 1, "frame_end": 3, "engine": "workbench", "width": 96, "height": 96, "wait": True},
        )
    )
    assert anim["status"] == "completed"
    assert anim["result"]["rendered_count"] == 3
    return {"bones": len(arm["bones"]), "rendered_frames": 3}


EVAL_SUITE: list[EvalCase] = [
    EvalCase(
        id="furniture_dining_set",
        category="modeling_and_layout",
        title="Dining table with 4 grounded legs and PBR materials",
        prompt="Create a dining table with 4 metal legs resting cleanly on Z=0 and a walnut top, then inspect multiview.",
        execute_and_verify=_eval_furniture_dining_set,
    ),
    EvalCase(
        id="procedural_gold_dsl",
        category="nodes_dsl",
        title="Procedural brushed gold shader via Nodes DSL + studio render",
        prompt="Author a procedural brushed gold material using build_node_tree, light with studio preset, and capture EEVEE preview.",
        execute_and_verify=_eval_procedural_gold_dsl,
    ),
    EvalCase(
        id="geonodes_scatter",
        category="geometry_nodes",
        title="Geometry Nodes surface scatter with custom Density input",
        prompt="Build a Geometry Nodes scatter network on a ground plane with an exposed Density parameter.",
        execute_and_verify=_eval_geonodes_scatter,
    ),
    EvalCase(
        id="hard_surface_bracket",
        category="cad_and_export",
        title="Beveled boolean bracket with UVs exported to GLB",
        prompt="Create a beveled bracket with a boolean bolt hole, unwrap UVs, and export a valid game-ready GLB.",
        execute_and_verify=_eval_hard_surface_bracket,
    ),
    EvalCase(
        id="turntable_and_rig",
        category="animation_and_render",
        title="Animated turntable render + 2-bone IK rig",
        prompt="Animate a 3-frame turntable, rig a 2-bone IK arm, and render frames asynchronously.",
        execute_and_verify=_eval_turntable_and_rig,
    ),
]
