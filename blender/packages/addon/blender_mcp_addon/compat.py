# SPDX-License-Identifier: GPL-3.0-or-later
"""Feature-detection compatibility layer spanning Blender 3.6 LTS through 5.3+."""

from __future__ import annotations

from typing import Any

import bpy  # type: ignore[import-not-found]
from mathutils import Vector  # type: ignore[import-not-found]

# Canonical Principled BSDF socket names mapped to fallback aliases across 3.6 -> 5.x
BSDF_SOCKET_ALIASES: dict[str, tuple[str, ...]] = {
    "base_color": ("Base Color",),
    "metallic": ("Metallic",),
    "roughness": ("Roughness",),
    "ior": ("IOR",),
    "alpha": ("Alpha",),
    "specular": ("Specular IOR Level", "Specular"),
    "subsurface": ("Subsurface Weight", "Subsurface"),
    "subsurface_scale": ("Subsurface Scale",),
    "transmission": ("Transmission Weight", "Transmission"),
    "coat_weight": ("Coat Weight", "Clearcoat"),
    "coat_roughness": ("Coat Roughness", "Clearcoat Roughness"),
    "sheen_weight": ("Sheen Weight", "Sheen"),
    "emission_color": ("Emission Color", "Emission"),
    "emission_strength": ("Emission Strength",),
}


def get_available_render_engines() -> list[str]:
    """Discover all valid render engine IDs on this Blender build."""
    engines: list[str] = []
    scene = bpy.context.scene
    try:
        for item in scene.render.bl_rna.properties["engine"].enum_items:
            if item.identifier and item.identifier not in engines:
                engines.append(item.identifier)
    except Exception:
        pass

    for sub in bpy.types.RenderEngine.__subclasses__():
        bl_id = getattr(sub, "bl_idname", None)
        if isinstance(bl_id, str) and bl_id and bl_id not in engines:
            engines.append(bl_id)

    # Probe standard built-in engines safely (some are dynamic enum items in 4.x/5.x)
    original = scene.render.engine
    for candidate in ("BLENDER_WORKBENCH", "BLENDER_EEVEE_NEXT", "BLENDER_EEVEE", "CYCLES"):
        if candidate in engines:
            continue
        try:
            scene.render.engine = candidate
            engines.append(candidate)
        except Exception:
            pass
    try:
        scene.render.engine = original
    except Exception:
        pass
    return engines


def get_eevee_engine_id(engines: list[str] | None = None) -> str:
    available = engines if engines is not None else get_available_render_engines()
    if "BLENDER_EEVEE_NEXT" in available:
        return "BLENDER_EEVEE_NEXT"
    if "BLENDER_EEVEE" in available:
        return "BLENDER_EEVEE"
    return available[0] if available else "BLENDER_EEVEE"


def resolve_render_engine(name: str) -> str:
    """Resolve logical names ('eevee', 'cycles', 'workbench') or raw IDs."""
    key = name.strip().lower()
    available = get_available_render_engines()
    if key in ("eevee", "blender_eevee", "blender_eevee_next"):
        return get_eevee_engine_id(available)
    if key == "cycles":
        return "CYCLES" if "CYCLES" in available else get_eevee_engine_id(available)
    if key in ("workbench", "solid", "blender_workbench"):
        return "BLENDER_WORKBENCH" if "BLENDER_WORKBENCH" in available else get_eevee_engine_id(available)
    upper = name.strip().upper()
    if upper in available:
        return upper
    return get_eevee_engine_id(available)


def detect_capabilities(*, allow_python: bool = False) -> dict[str, Any]:
    """Return runtime feature flags advertised during bridge handshake."""
    engines = get_available_render_engines()
    has_node_tree_interface = hasattr(bpy.types.NodeTree, "interface")
    has_slotted_actions = hasattr(bpy.types.Action, "slots")
    has_grease_pencil_v3 = hasattr(bpy.types, "GreasePencilv3") or (
        bpy.app.version >= (4, 3, 0)
    )
    has_use_auto_smooth = hasattr(bpy.types.Mesh, "use_auto_smooth")
    has_material_use_nodes = hasattr(bpy.types.Material, "use_nodes")
    return {
        "render_engines": engines,
        "eevee_engine_id": get_eevee_engine_id(engines),
        "has_node_tree_interface": has_node_tree_interface,
        "has_slotted_actions": has_slotted_actions,
        "has_grease_pencil_v3": has_grease_pencil_v3,
        "has_use_auto_smooth": has_use_auto_smooth,
        "has_material_use_nodes": has_material_use_nodes,
        "is_background": bool(bpy.app.background),
        "addon_allows_python": bool(allow_python),
    }


def ensure_material_nodes(mat: Any) -> Any:
    """Safely ensure a material has a node_tree across Blender 3.6 -> 5.3+."""
    if hasattr(mat, "use_nodes") and (getattr(mat, "node_tree", None) is None or not mat.use_nodes):
        try:
            mat.use_nodes = True
        except Exception:
            pass
    return mat.node_tree


def find_or_create_principled_bsdf(mat: Any) -> Any:
    """Locate or create a Principled BSDF connected to Material Output."""
    tree = ensure_material_nodes(mat)
    if tree is None:
        return None
    bsdf = next((n for n in tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
    output = next((n for n in tree.nodes if n.type == "OUTPUT_MATERIAL"), None)
    if output is None:
        output = tree.nodes.new("ShaderNodeOutputMaterial")
        output.location = (300, 0)
    if bsdf is None:
        bsdf = tree.nodes.new("ShaderNodeBsdfPrincipled")
        bsdf.location = (0, 0)
        tree.links.new(bsdf.outputs["BSDF"], output.inputs["Surface"])
    return bsdf


def resolve_bsdf_socket(bsdf: Any, canonical_key: str) -> Any | None:
    """Resolve a canonical PBR parameter name or exact socket name on Principled BSDF."""
    if canonical_key in bsdf.inputs:
        return bsdf.inputs[canonical_key]
    aliases = BSDF_SOCKET_ALIASES.get(canonical_key.lower(), ())
    for name in aliases:
        if name in bsdf.inputs:
            return bsdf.inputs[name]
    return None


def set_bsdf_input(bsdf: Any, canonical_key: str, value: Any) -> bool:
    """Set a Principled BSDF socket value with automatic RGB->RGBA padding."""
    sock = resolve_bsdf_socket(bsdf, canonical_key)
    if sock is None:
        return False
    if sock.type == "RGBA" and isinstance(value, (list, tuple)):
        vals = [float(v) for v in value]
        if len(vals) == 3:
            vals.append(1.0)
        sock.default_value = tuple(vals[:4])
    elif sock.type == "VECTOR" and isinstance(value, (list, tuple)):
        sock.default_value = tuple(float(v) for v in value[:3])
    else:
        sock.default_value = float(value)
    return True


def read_bsdf_params(bsdf: Any) -> dict[str, Any]:
    """Read canonical PBR properties from a Principled BSDF."""
    result: dict[str, Any] = {}
    for key in (
        "base_color",
        "metallic",
        "roughness",
        "ior",
        "alpha",
        "specular",
        "subsurface",
        "transmission",
        "coat_weight",
        "coat_roughness",
        "emission_color",
        "emission_strength",
    ):
        sock = resolve_bsdf_socket(bsdf, key)
        if sock is None:
            continue
        val = sock.default_value
        if hasattr(val, "__len__"):
            result[key] = [round(float(x), 4) for x in val]
        else:
            result[key] = round(float(val), 4)
    return result


def safe_undo_push(message: str) -> bool:
    """Push an undo step when supported (no-op safely in headless background mode)."""
    if bpy.app.background:
        return False
    try:
        res = bpy.ops.ed.undo_push(message=message)
        return "FINISHED" in res
    except Exception:
        return False


def get_object_bbox_world(obj: Any) -> dict[str, list[float]]:
    """Compute axis-aligned world-space bounding box of an object."""
    bpy.context.view_layer.update()
    if not getattr(obj, "bound_box", None):
        loc = [round(float(c), 4) for c in obj.matrix_world.translation]
        return {"min": loc, "max": loc, "center": loc, "dimensions": [0.0, 0.0, 0.0]}
    corners = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
    xs = [c.x for c in corners]
    ys = [c.y for c in corners]
    zs = [c.z for c in corners]
    bmin = [round(min(xs), 4), round(min(ys), 4), round(min(zs), 4)]
    bmax = [round(max(xs), 4), round(max(ys), 4), round(max(zs), 4)]
    center = [round((bmin[i] + bmax[i]) * 0.5, 4) for i in range(3)]
    dims = [round(bmax[i] - bmin[i], 4) for i in range(3)]
    return {"min": bmin, "max": bmax, "center": center, "dimensions": dims}


def get_or_create_world_tree(scene: Any | None = None) -> tuple[Any, Any]:
    """Ensure the scene has a World with an active node tree across 3.6 -> 5.3+."""
    scn = scene or bpy.context.scene
    if scn.world is None:
        scn.world = bpy.data.worlds.new("World")
    world = scn.world
    if hasattr(world, "use_nodes") and (getattr(world, "node_tree", None) is None or not world.use_nodes):
        try:
            world.use_nodes = True
        except Exception:
            pass
    return world, world.node_tree


def get_or_create_compositor_tree(scene: Any | None = None, name: str = "Compositor") -> Any:
    """Return active scene compositor node tree across Blender 3.6-4.x and 5.x."""
    scn = scene or bpy.context.scene
    # Blender 5.0+ uses scene.compositing_node_group
    if hasattr(scn, "compositing_node_group"):
        if hasattr(scn, "use_nodes"):
            try:
                scn.use_nodes = True
            except Exception:
                pass
        tree = scn.compositing_node_group
        if tree is None:
            tree = bpy.data.node_groups.new(name, "CompositorNodeTree")
            ensure_node_group_socket(tree, "Image", "OUTPUT", "NodeSocketColor")
            rl = tree.nodes.new("CompositorNodeRLayers")
            rl.location = (-300, 0)
            out = tree.nodes.new("NodeGroupOutput")
            out.location = (300, 0)
            if "Image" in rl.outputs and "Image" in out.inputs:
                tree.links.new(rl.outputs["Image"], out.inputs["Image"])
            scn.compositing_node_group = tree
        return tree

    # Blender 3.6 - 4.x uses scene.use_nodes + scene.node_tree
    if hasattr(scn, "use_nodes"):
        scn.use_nodes = True
    return getattr(scn, "node_tree", None)


def ensure_node_group_socket(
    tree: Any,
    name: str,
    in_out: str,
    socket_type: str,
) -> Any:
    """Create or retrieve a node-group socket across Blender 3.6 (inputs/outputs) and 4.0+ (interface)."""
    direction = in_out.upper()
    if hasattr(tree, "interface"):
        for item in tree.interface.items_tree:
            if (
                getattr(item, "item_type", None) == "SOCKET"
                and item.name == name
                and getattr(item, "in_out", "").upper() == direction
            ):
                return item
        return tree.interface.new_socket(name=name, in_out=direction, socket_type=socket_type)

    # Blender 3.6 fallback
    collection = tree.inputs if direction == "INPUT" else tree.outputs
    existing = collection.get(name)
    if existing is not None:
        return existing
    return collection.new(socket_type, name)


def list_node_group_sockets(tree: Any) -> list[dict[str, Any]]:
    """List node-group interface sockets across Blender 3.6 and 4.0-5.3+."""
    sockets: list[dict[str, Any]] = []
    if hasattr(tree, "interface"):
        for item in tree.interface.items_tree:
            if getattr(item, "item_type", None) == "SOCKET":
                sockets.append(
                    {
                        "name": item.name,
                        "identifier": getattr(item, "identifier", item.name),
                        "in_out": getattr(item, "in_out", "INPUT"),
                        "socket_type": getattr(item, "socket_type", ""),
                    }
                )
        return sockets

    for direction, coll in (("INPUT", getattr(tree, "inputs", ())), ("OUTPUT", getattr(tree, "outputs", ()))):
        for item in coll:
            sockets.append(
                {
                    "name": item.name,
                    "identifier": getattr(item, "identifier", item.name),
                    "in_out": direction,
                    "socket_type": getattr(item, "bl_socket_idname", ""),
                }
            )
    return sockets


def resolve_sky_type(sky_node: Any, requested: str = "nishita") -> str:
    """Map logical sky names to valid enum items on Blender 3.6-5.3+."""
    available = [item.identifier for item in sky_node.bl_rna.properties["sky_type"].enum_items]
    key = requested.strip().upper()
    if key in available:
        return key
    if key in ("NISHITA", "PHYSICAL", "REALISTIC", "MULTIPLE_SCATTERING"):
        for candidate in ("MULTIPLE_SCATTERING", "NISHITA", "SINGLE_SCATTERING"):
            if candidate in available:
                return candidate
    if key == "SINGLE_SCATTERING":
        for candidate in ("SINGLE_SCATTERING", "NISHITA", "PREETHAM"):
            if candidate in available:
                return candidate
    return available[0] if available else "PREETHAM"


def set_mesh_shading(obj: Any, mode: str, angle_degrees: float = 30.0) -> dict[str, Any]:
    """Set flat, smooth, or angle-based auto-smooth shading across Blender 3.6 -> 5.3+."""
    import math

    import bmesh  # type: ignore[import-not-found]

    mesh = obj.data
    m = mode.strip().lower()
    if m == "flat":
        if len(mesh.polygons) > 0:
            mesh.polygons.foreach_set("use_smooth", [False] * len(mesh.polygons))
        if hasattr(mesh, "use_auto_smooth"):
            mesh.use_auto_smooth = False
        mesh.update()
        return {"shading": "flat"}

    if m == "smooth":
        if len(mesh.polygons) > 0:
            mesh.polygons.foreach_set("use_smooth", [True] * len(mesh.polygons))
        if hasattr(mesh, "use_auto_smooth"):
            mesh.use_auto_smooth = False
        else:
            bm = bmesh.new()
            try:
                bm.from_mesh(mesh)
                for e in bm.edges:
                    e.smooth = True
                bm.to_mesh(mesh)
            finally:
                bm.free()
        mesh.update()
        return {"shading": "smooth"}

    # Auto-smooth by angle: works identically headless across 3.6, 4.x, and 5.x
    angle_rad = math.radians(max(0.0, min(180.0, angle_degrees)))
    if len(mesh.polygons) > 0:
        mesh.polygons.foreach_set("use_smooth", [True] * len(mesh.polygons))
    if hasattr(mesh, "use_auto_smooth"):
        mesh.use_auto_smooth = True
        mesh.auto_smooth_angle = angle_rad
        mesh.update()
        return {"shading": "auto", "angle_degrees": angle_degrees, "backend": "use_auto_smooth"}

    bm = bmesh.new()
    sharp_count = 0
    try:
        bm.from_mesh(mesh)
        bm.normal_update()
        for e in bm.edges:
            if len(e.link_faces) == 2:
                ang = e.calc_face_angle(0.0)
                if ang > angle_rad:
                    e.smooth = False
                    sharp_count += 1
                else:
                    e.smooth = True
            else:
                e.smooth = True
        bm.to_mesh(mesh)
    finally:
        bm.free()
    mesh.update()
    return {
        "shading": "auto",
        "angle_degrees": angle_degrees,
        "sharp_edges": sharp_count,
        "backend": "sharp_edges",
    }


def set_geometry_nodes_input(mod: Any, key: str, value: Any) -> bool:
    """Set a Geometry Nodes modifier input by display name or identifier across Blender 3.6 -> 5.3+."""
    tree = getattr(mod, "node_group", None)
    if tree is None:
        return False

    ident: str | None = None
    if hasattr(tree, "interface"):
        for item in tree.interface.items_tree:
            if (
                getattr(item, "item_type", None) == "SOCKET"
                and getattr(item, "in_out", "") == "INPUT"
                and (item.name == key or item.identifier == key)
            ):
                ident = item.identifier
                break
    elif hasattr(tree, "inputs"):
        for item in tree.inputs:
            if item.name == key or item.identifier == key:
                ident = item.identifier
                break

    if ident is None:
        return False

    # Blender 5.3+: GeometryNodesModifierInterface (`mod.properties.inputs.<ident>.value`)
    props = getattr(mod, "properties", None)
    inputs_group = getattr(props, "inputs", None) if props is not None else None
    if inputs_group is not None and hasattr(inputs_group, ident):
        sock_prop = getattr(inputs_group, ident)
        if hasattr(sock_prop, "value"):
            sock_prop.value = value
            return True

    # Blender 3.6 - 5.2: IDProperties on modifier (`mod[ident] = value`)
    mod[ident] = value
    return True


def get_action_fcurves(obj: Any, action: Any | None = None, *, ensure: bool = False) -> Any | None:
    """Return the fcurves collection for `obj` across Blender 3.6-4.3 and 4.4-5.3+ Slotted Actions."""
    anim = obj.animation_data
    if anim is None:
        if not ensure:
            return None
        anim = obj.animation_data_create()

    act = action if action is not None else anim.action
    if act is None:
        if not ensure:
            return None
        act = bpy.data.actions.new(name=f"{obj.name}Action")
        anim.action = act

    # Blender 3.6 - 4.3 classic Action.fcurves
    if hasattr(act, "fcurves"):
        return act.fcurves

    # Blender 4.4 - 5.3+ Layered / Slotted Actions (channelbag.fcurves)
    slot = getattr(anim, "action_slot", None)
    if slot is None:
        if len(act.slots) > 0:
            slot = act.slots[0]
            try:
                anim.action_slot = slot
            except Exception:
                pass
        elif ensure:
            slot = act.slots.new(id_type="OBJECT", name=obj.name)
            anim.action_slot = slot
        else:
            return None

    if len(act.layers) == 0:
        if not ensure:
            return None
        layer = act.layers.new(name="Layer")
    else:
        layer = act.layers[0]

    if len(layer.strips) == 0:
        if not ensure:
            return None
        strip = layer.strips.new(type="KEYFRAME")
    else:
        strip = layer.strips[0]

    cb = strip.channelbag(slot, ensure=ensure)
    return cb.fcurves if cb is not None else None


def iter_fcurves(obj: Any) -> list[Any]:
    """Return a plain list of all FCurves bound to `obj` across Blender 3.6 -> 5.3+."""
    fcurves = get_action_fcurves(obj, ensure=False)
    return list(fcurves) if fcurves is not None else []


def add_grease_pencil_stroke(
    gp_data: Any,
    layer_name: str,
    frame_number: int,
    points: list[list[float]],
    *,
    radius: float = 0.02,
    opacity: float = 1.0,
    cyclic: bool = False,
) -> dict[str, Any]:
    """Create a Grease Pencil stroke compatible with both GPv3 (4.3+/5.x) and GPv2 (3.6-4.2)."""
    layer = gp_data.layers.get(layer_name)
    if layer is None:
        layer = gp_data.layers.new(layer_name)

    frame = next((f for f in layer.frames if f.frame_number == frame_number), None)
    if frame is None:
        frame = layer.frames.new(frame_number)

    if hasattr(frame, "drawing"):
        # Grease Pencil v3 (Blender 4.3+ / 5.x)
        drawing = frame.drawing
        before = len(drawing.strokes)
        drawing.add_strokes([len(points)])
        stroke = drawing.strokes[before]
        stroke.cyclic = cyclic
        for idx, pt in enumerate(points):
            p = stroke.points[idx]
            p.position = (float(pt[0]), float(pt[1]), float(pt[2]))
            p.radius = radius
            p.opacity = opacity
        if hasattr(drawing, "tag_positions_changed"):
            drawing.tag_positions_changed()
        return {"backend": "gpv3", "stroke_index": before, "points": len(points)}

    # Grease Pencil v2 (Blender 3.6 - 4.2)
    stroke = frame.strokes.new()
    stroke.use_cyclic = cyclic
    stroke.line_width = max(1, int(radius * 1000))
    stroke.points.add(len(points))
    for idx, pt in enumerate(points):
        p = stroke.points[idx]
        p.co = (float(pt[0]), float(pt[1]), float(pt[2]))
        p.pressure = 1.0
        p.strength = opacity
    return {"backend": "gpv2", "stroke_index": len(frame.strokes) - 1, "points": len(points)}
