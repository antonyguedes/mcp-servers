# SPDX-License-Identifier: MIT
"""Guided MCP workflow Prompts for end-to-end 3D creation tasks in Blender."""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer


def register_prompts(mcp: MCPServer) -> None:
    @mcp.prompt(
        name="product_shot",
        title="Studio Product Shot",
        description="Stage, light, shade, and render a studio product shot for an object or subject.",
    )
    def product_shot(subject: str = "HeroProduct", lighting_preset: str = "studio") -> str:
        return (
            f"Create a studio product shot showcasing '{subject}' in Blender:\n"
            "1. Inspect the scene via `get_scene_summary` and save a checkpoint (`create_checkpoint`).\n"
            "2. Ensure the hero asset rests cleanly on a backdrop cyclorama/plane at Z=0 (`align_to_ground`).\n"
            "3. Build rich PBR or procedural shaders via `create_pbr_material` or `build_node_tree`.\n"
            f"4. Apply `{lighting_preset}` lighting with `setup_lighting_preset` and frame the subject with `add_camera` + `camera_frame_objects` + shallow DOF (`set_camera_lens_dof`, 85mm, f/2.8).\n"
            "5. Verify proportions using `capture_multiview`, refine, then produce a Cycles/EEVEE render preview (`render_preview`)."
        )

    @mcp.prompt(
        name="low_poly_scene",
        title="Low-Poly Stylized Scene",
        description="Block out and style a cohesive low-poly 3D diorama with flat/auto shading and clean lighting.",
    )
    def low_poly_scene(theme: str = "cozy forest campsite") -> str:
        return (
            f"Design a cohesive low-poly stylized diorama for theme: '{theme}'.\n"
            "1. Organize props into clear collections (`create_collection`: Terrain, Props, Foliage, Lighting).\n"
            "2. Keep segment counts crisp and stylized (`segments=6..12`), using `mesh_extrude`, `mesh_inset`, `mesh_bevel`, and `mesh_set_shading(mode='flat')`.\n"
            "3. Rest every prop accurately on ground/surfaces with `align_to_ground`.\n"
            "4. Assign harmonious matte PBR palettes (`roughness=0.7..0.9`) and warm/cool contrast lighting (`setup_lighting_preset` or `set_world_sky`).\n"
            "5. Visually inspect via `capture_multiview` after blockout and `capture_viewport(shading='eevee')` after shading."
        )

    @mcp.prompt(
        name="architectural_interior",
        title="Architectural Interior",
        description="Build an accurate meter-scale interior room with furniture, materials, and natural/studio lighting.",
    )
    def architectural_interior(room_type: str = "modern living room", width_m: str = "5.0", depth_m: str = "4.0") -> str:
        return (
            f"Model a real-world meter-scale {room_type} ({width_m}m x {depth_m}m, ceiling height 2.8m):\n"
            "1. Create structural shell (floor, walls with boolean window cutouts via `mesh_boolean`, ceiling) in a `Structure` collection.\n"
            "2. Build hero furniture pieces at accurate real-world dimensions and seat them cleanly with `align_to_ground`.\n"
            "3. Apply layered PBR materials (wood, fabric, matte plaster, brushed metal) and procedural roughness via `build_node_tree`.\n"
            "4. Light with `set_world_sky` plus window portal `AREA` lights (`add_light`).\n"
            "5. Place an interior wide-angle camera (28-35mm) and validate composition via `capture_viewport`."
        )

    @mcp.prompt(
        name="character_blockout",
        title="Character Blockout & Rig",
        description="Block out a proportional stylized character, build an armature, bind weights, and set up IK.",
    )
    def character_blockout(style: str = "stylized robot") -> str:
        return (
            f"Create and rig a '{style}' character in Blender:\n"
            "1. Enable `objects`, `mesh`, `modifiers`, and `rigging` toolsets if not already active.\n"
            "2. Block out torso, head, limbs, and joints symmetrically at real human-scale height (~1.75m, feet at Z=0).\n"
            "3. Inspect silhouette from all 4 views with `capture_multiview`.\n"
            "4. Build a clean bone hierarchy (`create_armature`), bind geometry (`bind_auto_weights`), add limb IK (`setup_ik`), and test a dynamic pose (`pose_bone`)."
        )

    @mcp.prompt(
        name="turntable_animation",
        title="360° Turntable Animation",
        description="Set up a smooth 360-degree turntable animation and render it asynchronously.",
    )
    def turntable_animation(target: str = "Cube", frames: str = "60", engine: str = "eevee") -> str:
        return (
            f"Create a seamless {frames}-frame 360° turntable for '{target}':\n"
            f"1. Configure timeline (`set_frame_range(frame_start=1, frame_end={frames}, fps=24)`).\n"
            "2. Insert linear Z-rotation keyframes from 0° at frame 1 to 360° at frame end (`insert_keyframes(..., data_path='rotation_euler', interpolation='LINEAR')`).\n"
            "3. Frame the object with `camera_frame_objects` and apply `setup_lighting_preset('three_point')`.\n"
            f"4. Configure render (`configure_render(engine='{engine}')`) and launch `render_animation`."
        )

    @mcp.prompt(
        name="procedural_material_workshop",
        title="Procedural Material Workshop (Nodes DSL)",
        description="Author a multi-layered procedural shader using the declarative Nodes DSL.",
    )
    def procedural_material_workshop(material_name: str = "BrushedGold", look: str = "anisotropic brushed gold with micro-scratches") -> str:
        return (
            f"Design a procedural Blender material '{material_name}' matching: {look}.\n"
            "1. If unsure about node socket names on this Blender build, call `list_node_types(tree_type='shader', search=..., include_sockets=True)`.\n"
            "2. Build the full shader graph declaratively in one call with `build_node_tree(tree=f'material:{material_name}', ...)` using `layout='auto'`.\n"
            "3. Assign to a preview sphere/object, light it, inspect with `capture_viewport(shading='eevee')`, and iterate with `patch_node_tree`."
        )

    @mcp.prompt(
        name="game_asset_optimization",
        title="Game Engine Asset Audit & Export",
        description="Audit topology, normals, UVs, transforms, and export a clean game-ready GLB/FBX.",
    )
    def game_asset_optimization(object_name: str = "HeroAsset", target_format: str = "glb") -> str:
        return (
            f"Prepare '{object_name}' for a real-time game engine and export as `.{target_format}`:\n"
            "1. Audit polygon counts, ngons, manifold state, and UV layers via `mesh_stats`.\n"
            "2. Clean up geometry (`mesh_merge_by_distance`, `mesh_recalc_normals`, `mesh_set_shading('auto')`).\n"
            "3. Bake transforms (`apply_transforms`), set pivot cleanly (`set_origin('bottom_center')`), rest at origin (`align_to_ground`).\n"
            "4. Generate clean UVs if missing (`uv_unwrap`), verify with `capture_multiview`, and export via `export_file`."
        )
