# `blender-mcp` — Complete Schema Reference

> Auto-generated from live `MCPServer` schemas via `uv run python scripts/generate_docs.py`.

- **Total tools (`full` profile + scripting):** `128`
- **Toolsets:** `19` (+ dynamic toolset & multi-instance management tools)
- **Resources:** `3` static + `4` templates
- **Guided Prompts:** `7`

---

## Tools by Toolset

### `core` — Scene inspection, object listing, selection, and modes (7 tools)

| Tool | Flags | Description | Parameters |
|---|---|---|---|
| `get_blender_info` | `read-only` | Return Blender version, active scene name, Python version, and runtime capabilities. | _None_ |
| `get_object_details` | `read-only` | Inspect detailed geometry, world bounding box, transforms, materials, and modifiers of an object. | `object` (`string`) *(required)* |
| `get_scene_summary` | `read-only` | Return a compact overview of the active Blender scene (objects, collections, render, frames). | _None_ |
| `list_objects` | `read-only` | List objects in the scene with optional filtering and pagination. | `object_type` (`string \| null`), `collection` (`string \| null`), `name_contains` (`string \| null`), `offset` (`integer`), `limit` (`integer`) |
| `select_objects` | `idempotent` | Select or deselect objects in the active view layer. | `objects` (`array \| null`), `extend` (`boolean`), `select_all` (`boolean`), `deselect_all` (`boolean`) |
| `set_active_object` | `idempotent` | Set the active object in the scene. | `object` (`string`) *(required)* |
| `set_mode` | `idempotent` | Switch Blender interaction mode (optionally activating a target object first). | `mode` (`string`), `object` (`string \| null`) |

### `objects` — Primitives, custom meshes, transforms, hierarchy, alignment (11 tools)

| Tool | Flags | Description | Parameters |
|---|---|---|---|
| `align_to_ground` | `idempotent` | Rest each object cleanly on `target_z` (default Z=0) using its world-space bounding box. | `objects` (`array`) *(required)*, `target_z` (`number`) |
| `apply_transforms` | `idempotent` | Bake object location/rotation/scale transforms directly into mesh geometry. | `object` (`string`) *(required)*, `location` (`boolean`), `rotation` (`boolean`), `scale` (`boolean`) |
| `create_mesh_object` |  | Create a custom mesh object directly from vertex coordinates and face/edge index lists. | `name` (`string`) *(required)*, `vertices` (`array`) *(required)*, `faces` (`array \| null`), `edges` (`array \| null`), `location` (`array \| null`), `rotation_degrees` (`array \| null`), `scale` (`array \| number \| null`), `smooth` (`boolean`), `collection` (`string \| null`) |
| `create_primitive` |  | Create a 3D primitive (mesh, empty, or text) at the given transform. | `primitive` (`string`), `name` (`string \| null`), `location` (`array \| null`), `rotation_degrees` (`array \| null`), `scale` (`array \| number \| null`), `size` (`number`), `radius` (`number \| null`), `depth` (`number \| null`), `segments` (`integer`), `rings` (`integer`), `subdivisions` (`integer`), `smooth` (`boolean`), `text` (`string \| null`), `collection` (`string \| null`) |
| `delete_objects` | `destructive` | Delete one or more objects (and optionally their child hierarchy) from the scene. | `objects` (`array`) *(required)*, `include_children` (`boolean`) |
| `duplicate_object` |  | Duplicate an object one or more times, optionally linked (shared mesh data) and spaced by `offset`. | `object` (`string`) *(required)*, `new_name` (`string \| null`), `offset` (`array \| null`), `count` (`integer`), `linked` (`boolean`) |
| `join_objects` | `destructive` | Merge source mesh objects into `target` mesh, preserving materials and removing merged sources. | `target` (`string`) *(required)*, `sources` (`array`) *(required)* |
| `parent_objects` | `idempotent` | Parent objects to `parent`, or unparent them when `parent` is null. | `children` (`array`) *(required)*, `parent` (`string \| null`), `keep_transform` (`boolean`) |
| `rename_object` | `idempotent` | Rename an object (and optionally its underlying data-block). Its persistent `uid` remains unchanged. | `object` (`string`) *(required)*, `new_name` (`string`) *(required)*, `rename_data` (`boolean`) |
| `set_origin` | `idempotent` | Reposition a mesh object's pivot/origin without moving its geometry in world space. | `object` (`string`) *(required)*, `origin_type` (`string`), `point` (`array \| null`) |
| `transform_object` | `idempotent` | Move, rotate (degrees), or scale an object (absolute or relative, world or local space). | `object` (`string`) *(required)*, `location` (`array \| null`), `rotation_degrees` (`array \| null`), `scale` (`array \| number \| null`), `relative` (`boolean`), `space` (`string`) |

### `collections` — Collection organization, visibility, and view layers (5 tools)

| Tool | Flags | Description | Parameters |
|---|---|---|---|
| `create_collection` | `idempotent` | Create a new collection under `parent` (or the root Scene Collection). | `name` (`string`) *(required)*, `parent` (`string \| null`) |
| `list_collections` | `read-only` | List all collections, their objects, nested children, and visibility flags. | _None_ |
| `list_view_layers` | `read-only` | List all view layers in the active scene. | _None_ |
| `move_to_collection` | `idempotent` | Move (or link when `link_only=True`) objects into a target collection. | `objects` (`array`) *(required)*, `collection` (`string`) *(required)*, `link_only` (`boolean`) |
| `set_collection_visibility` | `idempotent` | Toggle viewport visibility, render visibility, or view-layer exclusion for a collection. | `collection` (`string`) *(required)*, `hide_viewport` (`boolean \| null`), `hide_render` (`boolean \| null`), `exclude` (`boolean \| null`) |

### `materials` — PBR materials, parameter edits, and image texture wiring (6 tools)

| Tool | Flags | Description | Parameters |
|---|---|---|---|
| `assign_material` | `idempotent` | Assign an existing material to one or more objects. | `material` (`string`) *(required)*, `objects` (`array`) *(required)*, `slot_index` (`integer \| null`) |
| `create_pbr_material` | `idempotent` | Create a Principled BSDF PBR material (compatible with Blender 3.6-5.3+) and optionally assign it. | `name` (`string`) *(required)*, `base_color` (`array \| null`), `metallic` (`number \| null`), `roughness` (`number \| null`), `ior` (`number \| null`), `alpha` (`number \| null`), `specular` (`number \| null`), `subsurface` (`number \| null`), `transmission` (`number \| null`), `coat_weight` (`number \| null`), `coat_roughness` (`number \| null`), `emission_color` (`array \| null`), `emission_strength` (`number \| null`), `assign_to` (`array \| null`), `overwrite` (`boolean`) |
| `create_texture_from_image` | `idempotent` | Load an image texture from disk and connect it to a material's Principled BSDF channel. | `material` (`string`) *(required)*, `filepath` (`string`) *(required)*, `channel` (`string`), `colorspace` (`string \| null`), `normal_strength` (`number`) |
| `get_material_details` | `read-only` | Inspect a material's nodes and Principled BSDF parameters. | `material` (`string`) *(required)* |
| `list_materials` | `read-only` | List all materials in the Blender file with their current Principled BSDF parameters. | _None_ |
| `set_material_params` | `idempotent` | Update Principled BSDF parameters on an existing material (e.g. roughness, base_color, metallic). | `material` (`string`) *(required)*, `params` (`object`) *(required)* |

### `mesh` — bmesh modeling (extrude, bevel, inset, boolean, loop cut, UV) (11 tools)

| Tool | Flags | Description | Parameters |
|---|---|---|---|
| `mesh_bevel` |  | Bevel edges or vertices of a mesh object via bmesh (optionally restricted to edges sharper than `angle_limit_degrees`). | `object` (`string`) *(required)*, `offset` (`number`), `segments` (`integer`), `affect` (`string`), `profile` (`number`), `clamp_overlap` (`boolean`), `angle_limit_degrees` (`number \| null`) |
| `mesh_boolean` | `destructive` | Apply a destructive boolean operation (DIFFERENCE, UNION, INTERSECT) between `target` and `cutter` meshes. | `target` (`string`) *(required)*, `cutter` (`string`) *(required)*, `operation` (`string`), `solver` (`string`), `delete_cutter` (`boolean`), `hide_cutter` (`boolean`) |
| `mesh_extrude` |  | Extrude selected faces (by `face_indices` or normal `direction`) along normal or explicit `offset`. | `object` (`string`) *(required)*, `distance` (`number`), `direction` (`string`), `face_indices` (`array \| null`), `offset` (`array \| null`), `scale` (`number \| null`) |
| `mesh_inset` |  | Inset faces on a mesh object (all faces, by normal direction, or explicit face indices). | `object` (`string`) *(required)*, `thickness` (`number`), `depth` (`number`), `individual` (`boolean`), `direction` (`string`), `face_indices` (`array \| null`) |
| `mesh_loop_cut` |  | Insert N evenly spaced parallel cuts across a mesh along local axis X, Y, or Z. | `object` (`string`) *(required)*, `axis` (`string`), `cuts` (`integer`) |
| `mesh_merge_by_distance` | `idempotent` | Weld/merge duplicate vertices within `distance` meters. | `object` (`string`) *(required)*, `distance` (`number`) |
| `mesh_recalc_normals` | `idempotent` | Recalculate consistent outward (or inward when `inside=True`) face normals. | `object` (`string`) *(required)*, `inside` (`boolean`) |
| `mesh_set_shading` | `idempotent` | Set flat, smooth, or angle-based auto-smooth shading (works across Blender 3.6-5.3+). | `object` (`string`) *(required)*, `mode` (`string`), `angle_degrees` (`number`) |
| `mesh_stats` | `read-only` | Inspect mesh topology: verts/edges/faces, tris/quads/ngons, manifold check, surface area, volume, and UVs. | `object` (`string`) *(required)* |
| `mesh_subdivide` |  | Subdivide all edges of a mesh object with optional smoothing or fractal displacement. | `object` (`string`) *(required)*, `cuts` (`integer`), `smoothness` (`number`), `fractal` (`number`) |
| `uv_unwrap` | `idempotent` | Generate clean UV coordinates for a mesh object (headless-safe projection). | `object` (`string`) *(required)*, `method` (`string`), `scale` (`number`), `uv_layer` (`string`) |

### `modifiers` — Typed modifier stack (Subsurf, Bevel, Array, GeoNodes, apply) (6 tools)

| Tool | Flags | Description | Parameters |
|---|---|---|---|
| `add_modifier` |  | Add a modifier (e.g. SUBSURF, BEVEL, ARRAY, MIRROR, SOLIDIFY, BOOLEAN, DECIMATE, NODES) with optional settings. | `object` (`string`) *(required)*, `modifier_type` (`string`) *(required)*, `name` (`string \| null`), `settings` (`object \| null`) |
| `apply_modifier` | `destructive` | Bake a specific modifier (or all modifiers when `modifier` is omitted) into mesh geometry. | `object` (`string`) *(required)*, `modifier` (`string \| null`) |
| `configure_modifier` | `idempotent` | Update properties (or Geometry Nodes input sockets) on an existing modifier. | `object` (`string`) *(required)*, `modifier` (`string`) *(required)*, `settings` (`object`) *(required)* |
| `list_modifiers` | `read-only` | List all modifiers on an object with their current settings. | `object` (`string`) *(required)* |
| `remove_modifier` | `destructive` | Remove a modifier from an object without applying it. | `object` (`string`) *(required)*, `modifier` (`string`) *(required)* |
| `reorder_modifier` | `idempotent` | Move a modifier to a specific 0-based position in an object's modifier stack. | `object` (`string`) *(required)*, `modifier` (`string`) *(required)*, `index` (`integer`) *(required)* |

### `nodes` — Declarative bidirectional Nodes DSL (Shader, GeoNodes, Compositor) (5 tools)

| Tool | Flags | Description | Parameters |
|---|---|---|---|
| `build_node_tree` | `idempotent` | Build a Shader, World, Geometry Nodes, or Compositor graph from declarative DSL JSON. | `tree` (`string`) *(required)*, `nodes` (`object`) *(required)*, `links` (`array`) *(required)*, `interface` (`array \| null`), `clear` (`boolean`), `layout` (`string`), `attach_to_object` (`string \| null`), `modifier_name` (`string \| null`) |
| `get_node_tree` | `read-only` | Serialize any Blender node tree into declarative DSL JSON. | `tree` (`string`) *(required)* |
| `list_node_types` | `read-only` | Discover valid node `bl_idname` types (and live socket names when `include_sockets=True`) on the connected Blender version. | `tree_type` (`string`), `search` (`string \| null`), `include_sockets` (`boolean`), `limit` (`integer`) |
| `patch_node_tree` | `idempotent` | Incrementally add, update, remove, or rewire nodes in an existing node tree without rebuilding it. | `tree` (`string`) *(required)*, `add_nodes` (`object \| null`), `update_nodes` (`object \| null`), `remove_nodes` (`array \| null`), `add_links` (`array \| null`), `remove_links` (`array \| null`), `interface` (`array \| null`), `relayout` (`boolean`) |
| `set_group_inputs` | `idempotent` | Set Geometry Nodes modifier input values by socket name or identifier on an object. | `object` (`string`) *(required)*, `inputs` (`object`) *(required)*, `modifier` (`string \| null`) |

### `lighting_camera` — Lights, presets, physical sky/HDRI, cameras, framing, DOF (8 tools)

| Tool | Flags | Description | Parameters |
|---|---|---|---|
| `add_camera` |  | Create a camera aimed at `look_at` (object name or [x,y,z]) and optionally set it as active. | `name` (`string`), `location` (`array \| null`), `look_at` (`string \| array \| null`), `rotation_degrees` (`array \| null`), `lens` (`number`), `sensor_width` (`number`), `set_active` (`boolean`), `collection` (`string \| null`) |
| `add_light` |  | Create a POINT, SUN, SPOT, or AREA light aimed via `look_at` (object name or [x,y,z]) or `rotation_degrees`. | `light_type` (`string`), `name` (`string \| null`), `location` (`array \| null`), `rotation_degrees` (`array \| null`), `look_at` (`string \| array \| null`), `energy` (`number`), `color` (`array \| null`), `size` (`number`), `spot_angle_degrees` (`number`), `spot_blend` (`number`), `collection` (`string \| null`) |
| `camera_frame_objects` | `idempotent` | Auto-position a camera so target objects (or the whole scene) fill the frame cleanly. | `objects` (`array \| null`), `camera` (`string \| null`), `direction` (`array \| null`), `margin` (`number`) |
| `camera_look_at` | `idempotent` | Aim a camera (or the active scene camera) at an object's center or world point `[x, y, z]`. | `target` (`string \| array`) *(required)*, `camera` (`string \| null`) |
| `set_camera_lens_dof` | `idempotent` | Configure camera focal length, projection type, clipping range, and depth of field (DOF). | `camera` (`string \| null`), `lens` (`number \| null`), `camera_type` (`string \| null`), `use_dof` (`boolean \| null`), `focus_object` (`string \| null`), `focus_distance` (`number \| null`), `fstop` (`number \| null`), `clip_start` (`number \| null`), `clip_end` (`number \| null`) |
| `set_world_hdri` | `idempotent` | Load an HDRI (.hdr/.exr/image) into the World shader with Z-rotation mapping and strength control. | `filepath` (`string`) *(required)*, `strength` (`number`), `rotation_degrees` (`number`) |
| `set_world_sky` | `idempotent` | Configure a physical Sky Texture in the World shader (adapts Nishita/Multiple-Scattering across Blender 3.6-5.3+). | `sky_type` (`string`), `sun_elevation` (`number`), `sun_rotation` (`number`), `strength` (`number`), `air_density` (`number \| null`), `dust_density` (`number \| null`) |
| `setup_lighting_preset` | `idempotent` | Auto-position a complete lighting rig (`three_point`, `studio`, `dramatic`, or `outdoor`) around the scene or target objects. | `preset` (`string`), `target_objects` (`array \| null`), `intensity` (`number`), `clear_existing_lights` (`boolean`) |

### `animation` — Keyframes (Slotted/Classic Actions), constraints, drivers, NLA, shape keys (11 tools)

| Tool | Flags | Description | Parameters |
|---|---|---|---|
| `add_constraint` | `idempotent` | Add an object constraint (e.g. TRACK_TO, COPY_LOCATION, COPY_ROTATION, FOLLOW_PATH, LIMIT_LOCATION). | `object` (`string`) *(required)*, `constraint_type` (`string`), `target` (`string \| null`), `name` (`string \| null`), `settings` (`object \| null`) |
| `add_driver` | `idempotent` | Attach a scripted driver expression (e.g. `frame * 0.05`) to an object property. | `object` (`string`) *(required)*, `data_path` (`string`) *(required)*, `expression` (`string`) *(required)*, `index` (`integer`), `variables` (`array \| null`) |
| `delete_keyframes` | `destructive` | Delete keyframes at specific `frames` (or all keyframes on `data_path` when `frames` is omitted). | `object` (`string`) *(required)*, `data_path` (`string`), `frames` (`array \| null`) |
| `insert_keyframes` | `idempotent` | Insert one or more keyframes on an object property. | `object` (`string`) *(required)*, `keyframes` (`array`) *(required)*, `data_path` (`string`), `degrees` (`boolean`), `interpolation` (`string \| null`), `easing` (`string \| null`) |
| `list_keyframes` | `read-only` | List all FCurves and keyframe points on an object's active animation action. | `object` (`string`) *(required)* |
| `nla_push_down` | `idempotent` | Push an object's active Action down onto a named NLA track strip. | `object` (`string`) *(required)*, `track_name` (`string \| null`), `start_frame` (`integer \| null`), `clear_active_action` (`boolean`) |
| `set_current_frame` | `idempotent` | Scrub the Blender timeline to a specific frame number. | `frame` (`integer`) *(required)* |
| `set_frame_range` | `idempotent` | Configure scene timeline frame range, FPS, and optional current frame. | `frame_start` (`integer \| null`), `frame_end` (`integer \| null`), `fps` (`integer \| null`), `frame_current` (`integer \| null`) |
| `set_interpolation` | `idempotent` | Set FCurve keyframe interpolation across an object's action (Slotted Actions & classic Actions). | `object` (`string`) *(required)*, `interpolation` (`string`), `data_path` (`string \| null`), `easing` (`string \| null`) |
| `shape_key_add` | `idempotent` | Add a named shape key (auto-creating `Basis`) with optional vertex deltas `[idx, dx, dy, dz]` or `scale_offset`. | `object` (`string`) *(required)*, `name` (`string`), `vertex_deltas` (`array \| null`), `scale_offset` (`array \| null`), `value` (`number`), `from_mix` (`boolean`) |
| `shape_key_set` | `idempotent` | Set a shape key's blend weight (and optionally insert a keyframe at `keyframe_frame`). | `object` (`string`) *(required)*, `shape_key` (`string`) *(required)*, `value` (`number`) *(required)*, `keyframe_frame` (`integer \| null`) |

### `rigging` — Declarative armatures, auto-weights, bone posing, IK (4 tools)

| Tool | Flags | Description | Parameters |
|---|---|---|---|
| `bind_auto_weights` | `idempotent` | Bind a mesh object to an armature with automatic bone weights (with deterministic distance fallback). | `mesh` (`string`) *(required)*, `armature` (`string`) *(required)* |
| `create_armature` |  | Create an Armature from a declarative bone hierarchy spec. | `bones` (`array`) *(required)*, `name` (`string`), `location` (`array \| null`), `collection` (`string \| null`) |
| `pose_bone` | `idempotent` | Pose a bone in local space (degrees) and optionally keyframe it at `keyframe_frame`. | `armature` (`string`) *(required)*, `bone` (`string`) *(required)*, `location` (`array \| null`), `rotation_degrees` (`array \| null`), `scale` (`array \| number \| null`), `keyframe_frame` (`integer \| null`) |
| `setup_ik` | `idempotent` | Add an Inverse Kinematics (IK) constraint to a bone (auto-creating an Empty target if `target` is omitted). | `armature` (`string`) *(required)*, `bone` (`string`) *(required)*, `chain_count` (`integer`), `target` (`string \| null`), `pole_target` (`string \| null`), `pole_angle_degrees` (`number`), `name` (`string \| null`) |

### `physics` — Rigid body, cloth, collision, fluid, and cancellable bake jobs (5 tools)

| Tool | Flags | Description | Parameters |
|---|---|---|---|
| `add_cloth` | `idempotent` | Add or update a Cloth simulation modifier on a mesh object. | `object` (`string`) *(required)*, `quality` (`integer \| null`), `mass` (`number \| null`), `tension_stiffness` (`number \| null`), `bending_stiffness` (`number \| null`), `pin_group` (`string \| null`) |
| `add_collision` | `idempotent` | Add or update a Collision physics modifier on a mesh object. | `object` (`string`) *(required)*, `damping` (`number \| null`), `thickness_outer` (`number \| null`), `friction_factor` (`number \| null`) |
| `add_fluid` | `idempotent` | Add or configure a Mantaflow Fluid modifier (DOMAIN, FLOW, or EFFECTOR) on a mesh object. | `object` (`string`) *(required)*, `fluid_type` (`string`), `domain_type` (`string \| null`), `resolution_max` (`integer \| null`), `flow_type` (`string \| null`), `flow_behavior` (`string \| null`) |
| `add_rigid_body` | `idempotent` | Enable Rigid Body physics on an object (auto-creating the scene RigidBodyWorld). | `object` (`string`) *(required)*, `body_type` (`string`), `mass` (`number \| null`), `friction` (`number \| null`), `restitution` (`number \| null`), `collision_shape` (`string \| null`), `kinematic` (`boolean \| null`) |
| `bake_physics` | `idempotent` | Step and bake scene physics frame-by-frame as a cancellable job with live MCP progress. | `frame_start` (`integer \| null`), `frame_end` (`integer \| null`), `wait` (`boolean`) |

### `render` — Render settings, async still/animation render jobs, progress & cancel (6 tools)

| Tool | Flags | Description | Parameters |
|---|---|---|---|
| `cancel_job` | `idempotent` | Cancel a queued or running render/bake job immediately between frames. | `job_id` (`string`) *(required)* |
| `configure_render` | `idempotent` | Configure scene render engine (Cycles/EEVEE/Workbench), resolution, samples, device, and output settings. | `engine` (`string \| null`), `resolution_x` (`integer \| null`), `resolution_y` (`integer \| null`), `resolution_percentage` (`integer \| null`), `samples` (`integer \| null`), `device` (`string \| null`), `use_denoising` (`boolean \| null`), `film_transparent` (`boolean \| null`), `file_format` (`string \| null`), `output_path` (`string \| null`) |
| `get_job_status` | `read-only` | Query the live status, progress (0..1), and result of an async render or physics bake job. | `job_id` (`string`) *(required)* |
| `list_jobs` | `read-only` | List recent and currently active background Blender jobs. | `limit` (`integer`) |
| `render_animation` | `idempotent` | Render an animation frame-by-frame to `output_dir` with real-time progress and cancellation support. | `output_dir` (`string`) *(required)*, `frame_start` (`integer \| null`), `frame_end` (`integer \| null`), `frame_step` (`integer`), `filename_prefix` (`string`), `engine` (`string \| null`), `samples` (`integer \| null`), `width` (`integer \| null`), `height` (`integer \| null`), `wait` (`boolean`) |
| `render_still` | `idempotent` | Render a single frame to `output_path` via the cooperative JobManager. | `output_path` (`string`) *(required)*, `frame` (`integer \| null`), `engine` (`string \| null`), `samples` (`integer \| null`), `width` (`integer \| null`), `height` (`integer \| null`), `wait` (`boolean`), `return_image` (`boolean`) |

### `sculpt_gp` — Voxel remesh, procedural sculpt strokes, Grease Pencil v2/v3 (4 tools)

| Tool | Flags | Description | Parameters |
|---|---|---|---|
| `gp_create_object` |  | Create a Grease Pencil object with an initial layer and stroke material (supports GPv3 4.3+/5.x and GPv2 3.6-4.2). | `name` (`string`), `layer_name` (`string`), `color` (`array \| null`), `location` (`array \| null`), `frame` (`integer`), `collection` (`string \| null`) |
| `gp_draw_stroke` |  | Draw a 3D stroke onto a Grease Pencil object (works identically on GPv3 and GPv2). | `object` (`string`) *(required)*, `points` (`array`) *(required)*, `layer` (`string`), `frame` (`integer \| null`), `radius` (`number`), `opacity` (`number`), `cyclic` (`boolean`) |
| `sculpt_remesh` |  | Perform voxel remeshing on a mesh to create uniform sculptable topology (headless-safe). | `object` (`string`) *(required)*, `voxel_size` (`number`), `smooth_shading` (`boolean`) |
| `sculpt_stroke` |  | Apply a procedural sculpt brush stroke along 3D world-space `points` (supports X-symmetry, works headless). | `object` (`string`) *(required)*, `points` (`array`) *(required)*, `brush` (`string`), `radius` (`number`), `strength` (`number`), `symmetry_x` (`boolean`) |

### `io` — Import/export glTF/FBX/OBJ/USD/STL/PLY/Alembic and .blend I/O (6 tools)

| Tool | Flags | Description | Parameters |
|---|---|---|---|
| `export_file` |  | Export the scene (or selected objects) to glTF/GLB, FBX, OBJ, STL, PLY, USD, or Alembic. | `filepath` (`string`) *(required)*, `file_format` (`string \| null`), `selected_only` (`boolean`) |
| `import_file` |  | Import a 3D file (glTF/GLB, FBX, OBJ, STL, PLY, USD, Alembic) into the active Blender scene. | `filepath` (`string`) *(required)*, `file_format` (`string \| null`) |
| `link_append` |  | Append (or link when `link=True`) data-blocks from another `.blend` file. | `filepath` (`string`) *(required)*, `data_type` (`string`), `names` (`array \| null`), `link` (`boolean`) |
| `list_asset_libraries` | `read-only` | List Asset Libraries configured in Blender Preferences. | _None_ |
| `open_blend` | `destructive` | Open a `.blend` file in Blender (replaces current scene while keeping the MCP bridge connected). | `filepath` (`string`) *(required)* |
| `save_blend` |  | Save the active Blender scene to a `.blend` file. | `filepath` (`string`) *(required)*, `copy` (`boolean`), `compress` (`boolean`), `pack_resources` (`boolean`) |

### `introspection` — Safe RNA get/set, bpy.ops discovery/calling, live bpy API search (5 tools)

| Tool | Flags | Description | Parameters |
|---|---|---|---|
| `call_operator` |  | Invoke a Blender operator (`'category.name'`) with optional context override (`active_object`, `selected_objects`). | `operator` (`string`) *(required)*, `props` (`object \| null`), `active_object` (`string \| null`), `selected_objects` (`array \| null`) |
| `get_rna` | `read-only` | Read a Blender RNA property path without Python scripting. | `target` (`string`), `data_path` (`string`) |
| `list_operators` | `read-only` | Search available `bpy.ops` operators (optionally filtered by category and substring). | `category` (`string \| null`), `search` (`string \| null`), `limit` (`integer`) |
| `search_bpy_api` | `read-only` | Search live `bpy.types` RNA classes and properties on the connected Blender version. | `query` (`string`) *(required)*, `limit` (`integer`) |
| `set_rna` |  | Set a Blender RNA property by target (`scene`, `render`, `object:Cube`, `material:Gold`) and dotted `data_path`. | `target` (`string`) *(required)*, `data_path` (`string`) *(required)*, `value` (`any`) *(required)* |

### `history` — Undo/redo and named session checkpoints (6 tools)

| Tool | Flags | Description | Parameters |
|---|---|---|---|
| `create_checkpoint` |  | Save a named .blend snapshot of the current scene (works in both GUI and headless modes). | `name` (`string \| null`), `description` (`string`) |
| `delete_checkpoint` | `destructive` | Delete a saved checkpoint from disk. | `name` (`string`) *(required)* |
| `list_checkpoints` | `read-only` | List all checkpoints saved in the current Blender session. | _None_ |
| `redo` |  | Redo the last N undone actions in interactive GUI Blender sessions. | `steps` (`integer`) |
| `restore_checkpoint` | `destructive` | Restore the Blender scene to a previously created named checkpoint. | `name` (`string`) *(required)* |
| `undo` |  | Undo the last N mutating actions in interactive GUI Blender sessions. | `steps` (`integer`) |

### `vision` — Auto-framed viewport capture, 2x2 multiview grid, render preview (3 tools)

| Tool | Flags | Description | Parameters |
|---|---|---|---|
| `capture_multiview` | `read-only` | Capture a labeled 2x2 contact sheet (default: ISO, FRONT, RIGHT, TOP) for 3D spatial verification. | `views` (`array \| null`), `target_objects` (`array \| null`), `tile_size` (`integer`), `shading` (`string`), `samples` (`integer`) |
| `capture_viewport` | `read-only` | Capture an auto-framed image of the scene or target objects so you can visually inspect your work. | `view` (`string`), `target_objects` (`array \| null`), `width` (`integer`), `height` (`integer`), `shading` (`string`), `samples` (`integer`), `camera_location` (`array \| null`), `look_at` (`array \| null`), `lens` (`number`), `margin` (`number`) |
| `render_preview` | `read-only` | Render a quick preview from the active scene camera (or an auto-framed ISO angle if none exists). | `width` (`integer`), `height` (`integer`), `engine` (`string`), `samples` (`integer`) |

### `integrations` — Poly Haven, ambientCG, Sketchfab, AI 3D generators, and local asset cache (12 tools)

| Tool | Flags | Description | Parameters |
|---|---|---|---|
| `ai3d_generate` |  | Generate a 3D GLB model from text or an image using a configured AI 3D provider and import it into Blender. | `prompt` (`string \| null`), `image_path` (`string \| null`), `provider` (`string \| null`), `collection` (`string \| null`), `align_ground` (`boolean`) |
| `ai3d_list_providers` | `read-only` | List all registered AI 3D generation providers and show which ones are currently configured. | _None_ |
| `ambientcg_apply_material` |  | Download an ambientCG CC0 material pack, wire its PBR maps into Principled BSDF, and optionally assign it. | `asset_id` (`string`) *(required)*, `resolution` (`string`), `material_name` (`string \| null`), `assign_to` (`array \| null`) |
| `ambientcg_search` | `read-only` | Search ambientCG's free CC0 PBR material library (no API key required). | `query` (`string`), `limit` (`integer`) |
| `asset_cache_clear` | `destructive` | Clear cached downloaded assets (all providers or a specific provider like 'polyhaven'). | `provider` (`string \| null`) |
| `asset_cache_status` | `read-only` | Inspect local asset cache location, total size, and cached file counts by provider. | _None_ |
| `polyhaven_apply_hdri` |  | Download (and cache) a Poly Haven HDRI and configure the Blender World shader automatically. | `asset_id` (`string`) *(required)*, `resolution` (`string`), `file_format` (`string`), `strength` (`number`), `rotation_degrees` (`number`) |
| `polyhaven_apply_texture` |  | Download a Poly Haven CC0 PBR texture set, wire albedo/roughness/normal/metallic maps, and optionally assign it. | `asset_id` (`string`) *(required)*, `resolution` (`string`), `material_name` (`string \| null`), `assign_to` (`array \| null`) |
| `polyhaven_import_model` |  | Download a Poly Haven CC0 glTF 3D model into the local cache and import it into Blender. | `asset_id` (`string`) *(required)*, `resolution` (`string`), `collection` (`string \| null`), `align_ground` (`boolean`) |
| `polyhaven_search` | `read-only` | Search Poly Haven's free CC0 catalog of HDRIs, PBR textures, and 3D models (no API key required). | `asset_type` (`string`), `query` (`string`), `categories` (`array \| null`), `limit` (`integer`) |
| `sketchfab_import` |  | Download a Sketchfab glTF model (requires `SKETCHFAB_API_KEY`), cache it, and import it into Blender. | `uid` (`string`) *(required)*, `collection` (`string \| null`), `align_ground` (`boolean`) |
| `sketchfab_search` | `read-only` | Search downloadable 3D models on Sketchfab (downloads require `SKETCHFAB_API_KEY`). | `query` (`string`) *(required)*, `max_face_count` (`integer \| null`), `animated` (`boolean \| null`), `categories` (`array \| null`), `limit` (`integer`) |

### `scripting` — Python execution (governed by BLENDER_MCP_ALLOW_PYTHON) (2 tools)

| Tool | Flags | Description | Parameters |
|---|---|---|---|
| `execute_python` | `destructive` | Execute arbitrary Python code inside Blender's main thread. | `code` (`string`) *(required)*, `confirmed` (`boolean`) |
| `run_script_file` | `destructive` | Run a local Python script file inside Blender (subject to path allowlist & BLENDER_MCP_ALLOW_PYTHON). | `filepath` (`string`) *(required)*, `confirmed` (`boolean`) |

### `platform` — Dynamic Toolsets & Multi-Instance Management (5 tools)

| Tool | Flags | Description | Parameters |
|---|---|---|---|
| `disable_toolset` | `idempotent` | Dynamically unload a Blender toolset to reduce context usage and emit tools/list_changed. | `name` (`string`) *(required)* |
| `enable_toolset` | `idempotent` | Dynamically activate a Blender toolset (e.g. 'nodes', 'animation', 'render') and emit tools/list_changed. | `name` (`string`) *(required)* |
| `list_blender_instances` | `read-only` | Discover all running Blender instances with active MCP bridges and show which one is selected. | _None_ |
| `list_toolsets` | `read-only` | List all available Blender toolsets, which ones are enabled, and their tool counts. | _None_ |
| `select_blender_instance` | `idempotent` | Switch the active target Blender instance when controlling multiple Blender sessions. | `instance_id` (`string`) *(required)* |

---

## Resources & Resource Templates

| URI | MIME Type | Description |
|---|---|---|
| `blender://guide` | `text/markdown` | Conventions, Nodes DSL quick reference, and best practices for AI agents using Blender. |
| `blender://scene` | `application/json` | Live JSON summary of the active Blender scene (objects, collections, render, timeline). Supports real-time subscriptions. |
| `blender://instances` | `application/json` | List of all discovered running Blender MCP bridge instances and the active selection. |
| `blender://object/{ref}` | `application/json` | Detailed geometry, world bounding box, transforms, materials, and modifiers for an object (by name or uid). |
| `blender://material/{name}` | `application/json` | Nodes and Principled BSDF parameters of a Blender material. |
| `blender://node-tree/{kind}/{name}` | `application/json` | Declarative DSL JSON serialization of a node tree (kind: material, geonodes, world, compositor). |
| `docs://bpy/{query}` | `application/json` | Live RNA classes and properties matching `query` on the connected Blender version. |

---

## Guided Prompts

| Prompt | Description | Arguments |
|---|---|---|
| `product_shot` | Stage, light, shade, and render a studio product shot for an object or subject. | `subject`, `lighting_preset` |
| `low_poly_scene` | Block out and style a cohesive low-poly 3D diorama with flat/auto shading and clean lighting. | `theme` |
| `architectural_interior` | Build an accurate meter-scale interior room with furniture, materials, and natural/studio lighting. | `room_type`, `width_m`, `depth_m` |
| `character_blockout` | Block out a proportional stylized character, build an armature, bind weights, and set up IK. | `style` |
| `turntable_animation` | Set up a smooth 360-degree turntable animation and render it asynchronously. | `target`, `frames`, `engine` |
| `procedural_material_workshop` | Author a multi-layered procedural shader using the declarative Nodes DSL. | `material_name`, `look` |
| `game_asset_optimization` | Audit topology, normals, UVs, transforms, and export a clean game-ready GLB/FBX. | `object_name`, `target_format` |
