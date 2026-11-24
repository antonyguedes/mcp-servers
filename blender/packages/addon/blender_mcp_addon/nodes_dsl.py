# SPDX-License-Identifier: GPL-3.0-or-later
"""Declarative bidirectional Node Tree DSL compiler, validator, auto-layout, and serializer.

Supports Shader (material & world), Geometry Nodes, and Compositor trees across
Blender 3.6 LTS through 5.3+.
"""

from __future__ import annotations

import difflib
import re
from collections import defaultdict, deque
from typing import Any

import bpy  # type: ignore[import-not-found]

from .compat import (
    ensure_material_nodes,
    ensure_node_group_socket,
    get_or_create_compositor_tree,
    get_or_create_world_tree,
    list_node_group_sockets,
    resolve_bsdf_socket,
)
from .state import resolve_material
from .wire import AddonError, BridgeErrorCode

_INDEX_RE = re.compile(r"^(.+?)\[(\d+)\]$")


def resolve_node_tree(spec: str, *, create_if_missing: bool = False) -> tuple[Any, str, str]:
    """Resolve a target specifier like `material:Gold`, `world`, `compositor`, `geonodes:Scatter`.

    Returns `(node_tree, kind, canonical_spec)`.
    """
    raw = spec.strip()
    if not raw:
        raise AddonError(BridgeErrorCode.INVALID_PARAMS, "'tree' specifier cannot be empty.")

    lower = raw.lower()
    if lower == "compositor":
        tree = get_or_create_compositor_tree(bpy.context.scene)
        if tree is None:
            raise AddonError(BridgeErrorCode.BLENDER_ERROR, "Failed to initialize scene compositor tree.")
        return tree, "compositor", "compositor"

    if lower == "world":
        world, tree = get_or_create_world_tree(bpy.context.scene)
        return tree, "world", f"world:{world.name}"

    if ":" not in raw:
        # Convenience: check material first, then node_groups
        mat = bpy.data.materials.get(raw)
        if mat is not None:
            return ensure_material_nodes(mat), "material", f"material:{mat.name}"
        ng = bpy.data.node_groups.get(raw)
        if ng is not None:
            kind = "geonodes" if ng.bl_idname == "GeometryNodeTree" else "node_group"
            return ng, kind, f"{kind}:{ng.name}"
        raise AddonError(
            BridgeErrorCode.NOT_FOUND,
            f"Node tree {raw!r} not found. Prefix with 'material:', 'geonodes:', 'world:', 'compositor', or 'shader_group:'.",
        )

    prefix, target = raw.split(":", 1)
    prefix = prefix.strip().lower()
    target = target.strip()

    if prefix in ("material", "mat", "shader"):
        mat = bpy.data.materials.get(target)
        if mat is None:
            if not create_if_missing:
                resolve_material(target, required=True)
            mat = bpy.data.materials.new(name=target)
        tree = ensure_material_nodes(mat)
        return tree, "material", f"material:{mat.name}"

    if prefix == "world":
        world = bpy.data.worlds.get(target)
        if world is None:
            if not create_if_missing:
                raise AddonError(BridgeErrorCode.NOT_FOUND, f"World {target!r} not found.")
            world = bpy.data.worlds.new(name=target)
            bpy.context.scene.world = world
        if hasattr(world, "use_nodes") and (getattr(world, "node_tree", None) is None or not world.use_nodes):
            try:
                world.use_nodes = True
            except Exception:
                pass
        return world.node_tree, "world", f"world:{world.name}"

    if prefix in ("geonodes", "geometry", "gn", "geometry_nodes"):
        ng = bpy.data.node_groups.get(target)
        if ng is None:
            if not create_if_missing:
                names = [g.name for g in bpy.data.node_groups if g.bl_idname == "GeometryNodeTree"]
                raise AddonError(
                    BridgeErrorCode.NOT_FOUND,
                    f"Geometry Nodes group {target!r} not found.",
                    suggestions=difflib.get_close_matches(target, names, n=5, cutoff=0.4),
                )
            ng = bpy.data.node_groups.new(name=target, type="GeometryNodeTree")
            ensure_node_group_socket(ng, "Geometry", "INPUT", "NodeSocketGeometry")
            ensure_node_group_socket(ng, "Geometry", "OUTPUT", "NodeSocketGeometry")
        return ng, "geonodes", f"geonodes:{ng.name}"

    if prefix in ("shader_group", "node_group"):
        ng = bpy.data.node_groups.get(target)
        if ng is None:
            if not create_if_missing:
                raise AddonError(BridgeErrorCode.NOT_FOUND, f"Node group {target!r} not found.")
            ng = bpy.data.node_groups.new(name=target, type="ShaderNodeTree")
        return ng, "shader_group", f"shader_group:{ng.name}"

    if prefix == "compositor":
        tree = get_or_create_compositor_tree(bpy.context.scene, name=target or "Compositor")
        return tree, "compositor", "compositor"

    raise AddonError(
        BridgeErrorCode.INVALID_PARAMS,
        f"Unknown tree prefix {prefix!r}.",
        suggestions=["material", "world", "compositor", "geonodes", "shader_group"],
    )


def _find_socket(sockets: Any, spec: str, node: Any, *, is_input: bool) -> Any:
    """Resolve socket by exact name, `[index]` notation, integer string, BSDF alias, or case-insensitive match."""
    # 1. Pure integer index (e.g. "0", "1")
    if spec.isdigit():
        idx = int(spec)
        if 0 <= idx < len(sockets):
            return sockets[idx]

    # 2. Name[index] notation (e.g. "Value[1]" for 2nd socket named Value)
    m = _INDEX_RE.match(spec)
    if m:
        base_name, occ_str = m.group(1), m.group(2)
        occ = int(occ_str)
        matches = [s for s in sockets if s.name == base_name or s.identifier == base_name]
        if 0 <= occ < len(matches):
            return matches[occ]
        if base_name == "" and 0 <= occ < len(sockets):
            return sockets[occ]

    # 3. Exact name or identifier
    sock = sockets.get(spec)
    if sock is not None:
        return sock
    for s in sockets:
        if s.identifier == spec:
            return s

    # 4. Principled BSDF cross-version alias fallback
    if is_input and getattr(node, "type", "") == "BSDF_PRINCIPLED":
        alias_sock = resolve_bsdf_socket(node, spec)
        if alias_sock is not None:
            return alias_sock

    # 5. Case-insensitive name match
    low = spec.lower()
    for s in sockets:
        if s.name.lower() == low or s.identifier.lower() == low:
            return s

    available = [f"{s.name} ({s.identifier})" if s.name != s.identifier else s.name for s in sockets]
    names_only = [s.name for s in sockets]
    direction = "input" if is_input else "output"
    raise AddonError(
        BridgeErrorCode.NOT_FOUND,
        f"Socket {spec!r} not found in {direction}s of node {node.name!r} ({node.bl_idname}).",
        details={"available_sockets": available},
        suggestions=difflib.get_close_matches(spec, names_only, n=5, cutoff=0.35),
    )


def _assign_socket_default(sock: Any, value: Any) -> None:
    """Assign a JSON value to a Blender NodeSocket default_value with shape normalization."""
    if not hasattr(sock, "default_value"):
        return
    stype = getattr(sock, "type", "")
    if stype == "RGBA" and isinstance(value, (list, tuple)):
        vals = [float(v) for v in value]
        if len(vals) == 3:
            vals.append(1.0)
        sock.default_value = tuple(vals[:4])
    elif stype == "VECTOR" and isinstance(value, (list, tuple)):
        vals = [float(v) for v in value]
        while len(vals) < 3:
            vals.append(0.0)
        sock.default_value = tuple(vals[:3])
    elif stype == "BOOLEAN":
        sock.default_value = bool(value)
    elif stype == "INT":
        sock.default_value = int(value)
    elif stype == "STRING":
        sock.default_value = str(value)
    elif stype == "OBJECT" and isinstance(value, str):
        obj = bpy.data.objects.get(value)
        if obj is None:
            raise AddonError(BridgeErrorCode.NOT_FOUND, f"Object {value!r} not found for socket {sock.name!r}.")
        sock.default_value = obj
    elif stype == "COLLECTION" and isinstance(value, str):
        col = bpy.data.collections.get(value)
        if col is None:
            raise AddonError(BridgeErrorCode.NOT_FOUND, f"Collection {value!r} not found for socket {sock.name!r}.")
        sock.default_value = col
    elif stype == "MATERIAL" and isinstance(value, str):
        mat = bpy.data.materials.get(value)
        if mat is None:
            raise AddonError(BridgeErrorCode.NOT_FOUND, f"Material {value!r} not found for socket {sock.name!r}.")
        sock.default_value = mat
    elif stype == "IMAGE" and isinstance(value, str):
        img = bpy.data.images.get(value)
        if img is None:
            img = bpy.data.images.load(value, check_existing=True)
        sock.default_value = img
    else:
        try:
            sock.default_value = float(value) if isinstance(value, (int, float)) else value
        except Exception as exc:
            raise AddonError(
                BridgeErrorCode.INVALID_PARAMS,
                f"Cannot set socket {sock.name!r} to {value!r}: {exc}",
            ) from exc


def _apply_color_ramp_elements(ramp: Any, elements: list[Any]) -> None:
    """Replace ColorRamp stops from `[[pos, [r, g, b, a]], ...]`."""
    if not elements:
        return
    # Remove extras down to 1 stop, then rebuild cleanly
    while len(ramp.elements) > 1:
        ramp.elements.remove(ramp.elements[-1])
    for idx, stop in enumerate(elements):
        pos = float(stop[0])
        col = [float(c) for c in stop[1]]
        if len(col) == 3:
            col.append(1.0)
        elem = ramp.elements[0] if idx == 0 else ramp.elements.new(pos)
        elem.position = pos
        elem.color = tuple(col[:4])


def _apply_node_props(node: Any, props: dict[str, Any]) -> None:
    """Apply node attributes including dotted paths, ColorRamp stops, and bpy.data pointers."""
    for prop_path, val in props.items():
        if prop_path == "color_ramp.elements" and hasattr(node, "color_ramp"):
            _apply_color_ramp_elements(node.color_ramp, val)
            continue

        parts = prop_path.split(".")
        target = node
        for attr in parts[:-1]:
            if not hasattr(target, attr):
                raise AddonError(
                    BridgeErrorCode.INVALID_PARAMS,
                    f"Node {node.name!r} ({node.bl_idname}) has no attribute {prop_path!r}.",
                )
            target = getattr(target, attr)

        leaf = parts[-1]
        if not hasattr(target, leaf):
            raise AddonError(
                BridgeErrorCode.INVALID_PARAMS,
                f"Node {node.name!r} ({node.bl_idname}) has no property {prop_path!r}.",
            )

        # Resolve bpy.data pointer names when appropriate
        rna_prop = target.bl_rna.properties.get(leaf) if hasattr(target, "bl_rna") else None
        if rna_prop is not None and rna_prop.type == "POINTER" and isinstance(val, str):
            fixed = getattr(rna_prop.fixed_type, "identifier", "")
            if fixed == "Image":
                val = bpy.data.images.get(val) or bpy.data.images.load(val, check_existing=True)
            elif fixed == "Object":
                val = bpy.data.objects.get(val)
            elif fixed == "Collection":
                val = bpy.data.collections.get(val)
            elif fixed == "Material":
                val = bpy.data.materials.get(val)
            elif fixed == "NodeTree":
                val = bpy.data.node_groups.get(val)

        try:
            setattr(target, leaf, val)
        except Exception as exc:
            raise AddonError(
                BridgeErrorCode.INVALID_PARAMS,
                f"Failed setting {node.name!r}.{prop_path}={val!r}: {exc}",
            ) from exc


def _parse_endpoint(endpoint: str) -> tuple[str, str]:
    """Parse `'node_id.Socket Name'` or `'node_id[0]'` into `(node_id, socket_spec)`."""
    if "." in endpoint:
        nid, sock = endpoint.split(".", 1)
        return nid.strip(), sock.strip()
    m = _INDEX_RE.match(endpoint.strip())
    if m:
        return m.group(1).strip(), m.group(2).strip()
    raise AddonError(
        BridgeErrorCode.INVALID_PARAMS,
        f"Invalid link endpoint {endpoint!r}. Expected 'node_id.SocketName' or 'node_id[index]'.",
    )


def _auto_layout_tree(tree: Any) -> None:
    """Arrange nodes cleanly in left-to-right topological columns."""
    nodes = list(tree.nodes)
    if not nodes:
        return

    deps: dict[str, set[str]] = {n.name: set() for n in nodes}
    children: dict[str, set[str]] = defaultdict(set)
    in_deg: dict[str, int] = {n.name: 0 for n in nodes}

    for link in tree.links:
        src = link.from_node.name
        dst = link.to_node.name
        if src == dst or dst not in deps or src not in deps:
            continue
        if src not in deps[dst]:
            deps[dst].add(src)
            children[src].add(dst)
            in_deg[dst] += 1

    layer: dict[str, int] = {n.name: 0 for n in nodes}
    q: deque[str] = deque(name for name, deg in in_deg.items() if deg == 0)
    visited = 0
    while q:
        curr = q.popleft()
        visited += 1
        for nxt in children[curr]:
            layer[nxt] = max(layer[nxt], layer[curr] + 1)
            in_deg[nxt] -= 1
            if in_deg[nxt] == 0:
                q.append(nxt)

    columns: dict[int, list[Any]] = defaultdict(list)
    for n in nodes:
        columns[layer[n.name]].append(n)

    x_step = 300.0
    y_step = 240.0
    for col_idx in sorted(columns.keys()):
        col_nodes = sorted(columns[col_idx], key=lambda nd: nd.name)
        y_offset = (len(col_nodes) - 1) * y_step * 0.5
        for row_idx, nd in enumerate(col_nodes):
            nd.location = (col_idx * x_step, y_offset - row_idx * y_step)


def _default_output_type(kind: str) -> str:
    if kind == "material":
        return "ShaderNodeOutputMaterial"
    if kind == "world":
        return "ShaderNodeOutputWorld"
    if kind == "compositor":
        return "NodeGroupOutput" if hasattr(bpy.context.scene, "compositing_node_group") else "CompositorNodeComposite"
    return "NodeGroupOutput"


def _default_input_type(kind: str) -> str:
    if kind == "compositor":
        return "CompositorNodeRLayers"
    return "NodeGroupInput"


def _serialize_socket_value(sock: Any) -> Any:
    if not hasattr(sock, "default_value"):
        return None
    val = sock.default_value
    if isinstance(val, (bool, int, float, str)):
        return round(val, 5) if isinstance(val, float) else val
    if hasattr(val, "name"):
        return val.name
    if hasattr(val, "__len__"):
        try:
            return [round(float(x), 5) for x in val]
        except Exception:
            return None
    return None


def serialize_node_tree(tree: Any, canonical_spec: str) -> dict[str, Any]:
    """Serialize any Blender node tree into our declarative DSL dictionary."""
    nodes_dict: dict[str, dict[str, Any]] = {}
    for nd in tree.nodes:
        inputs_map: dict[str, Any] = {}
        name_counts: dict[str, int] = defaultdict(int)
        for sock in nd.inputs:
            key = sock.name
            if name_counts[key] > 0:
                key = f"{sock.name}[{name_counts[sock.name]}]"
            name_counts[sock.name] += 1
            if not sock.is_linked:
                val = _serialize_socket_value(sock)
                if val is not None:
                    inputs_map[key] = val

        entry: dict[str, Any] = {
            "type": nd.bl_idname,
            "location": [round(float(nd.location.x), 1), round(float(nd.location.y), 1)],
        }
        if nd.label:
            entry["label"] = nd.label
        if inputs_map:
            entry["inputs"] = inputs_map

        props: dict[str, Any] = {}
        for attr in ("operation", "blend_type", "data_type", "domain", "distribute_method", "mode", "sky_type"):
            if hasattr(nd, attr):
                v = getattr(nd, attr)
                if isinstance(v, (str, bool, int, float)):
                    props[attr] = v
        if hasattr(nd, "color_ramp") and nd.color_ramp is not None:
            props["color_ramp.elements"] = [
                [round(float(e.position), 4), [round(float(c), 4) for c in e.color]]
                for e in nd.color_ramp.elements
            ]
        if props:
            entry["props"] = props

        nodes_dict[nd.name] = entry

    links_list: list[list[str]] = []
    for lk in tree.links:
        src_name = lk.from_node.name
        dst_name = lk.to_node.name
        # Disambiguate duplicate socket names via [occ]
        out_dups = [s for s in lk.from_node.outputs if s.name == lk.from_socket.name]
        src_sock = (
            f"{lk.from_socket.name}[{out_dups.index(lk.from_socket)}]"
            if len(out_dups) > 1
            else lk.from_socket.name
        )
        in_dups = [s for s in lk.to_node.inputs if s.name == lk.to_socket.name]
        dst_sock = (
            f"{lk.to_socket.name}[{in_dups.index(lk.to_socket)}]"
            if len(in_dups) > 1
            else lk.to_socket.name
        )
        links_list.append([f"{src_name}.{src_sock}", f"{dst_name}.{dst_sock}"])

    result: dict[str, Any] = {
        "tree": canonical_spec,
        "tree_type": tree.bl_idname,
        "node_count": len(nodes_dict),
        "link_count": len(links_list),
        "nodes": nodes_dict,
        "links": links_list,
    }
    if hasattr(tree, "interface") or hasattr(tree, "inputs"):
        sockets = list_node_group_sockets(tree)
        if sockets:
            result["interface"] = sockets
    return result


def validate_dsl_spec(nodes_spec: dict[str, Any], links_spec: list[Any]) -> None:
    """Validate DSL structure before touching the Blender node tree."""
    if not isinstance(nodes_spec, dict):
        raise AddonError(BridgeErrorCode.INVALID_PARAMS, "'nodes' must be an object mapping node_id -> spec.")
    for nid, nspec in nodes_spec.items():
        if not isinstance(nspec, dict) or not isinstance(nspec.get("type"), str) or not nspec["type"]:
            raise AddonError(
                BridgeErrorCode.INVALID_PARAMS,
                f"Node {nid!r} must specify a non-empty string 'type' (e.g. 'ShaderNodeBsdfPrincipled').",
            )
    if not isinstance(links_spec, list):
        raise AddonError(BridgeErrorCode.INVALID_PARAMS, "'links' must be a list of [source, target] pairs.")
    for item in links_spec:
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            raise AddonError(
                BridgeErrorCode.INVALID_PARAMS,
                f"Invalid link entry {item!r}. Expected ['src_node.Socket', 'dst_node.Socket'].",
            )
        _parse_endpoint(str(item[0]))
        _parse_endpoint(str(item[1]))


def build_node_tree(
    tree: Any,
    kind: str,
    canonical_spec: str,
    *,
    nodes_spec: dict[str, Any],
    links_spec: list[Any],
    interface_spec: list[dict[str, Any]] | None = None,
    clear: bool = True,
    layout: str = "auto",
) -> dict[str, Any]:
    """Compile a declarative DSL specification into a live Blender node tree."""
    validate_dsl_spec(nodes_spec, links_spec)

    if interface_spec:
        for sock_def in interface_spec:
            s_name = str(sock_def["name"])
            s_dir = str(sock_def.get("in_out", "INPUT")).upper()
            s_type = str(sock_def.get("socket_type", "NodeSocketFloat"))
            item = ensure_node_group_socket(tree, s_name, s_dir, s_type)
            if "default_value" in sock_def and hasattr(item, "default_value"):
                try:
                    item.default_value = sock_def["default_value"]
                except Exception:
                    pass

    if clear:
        tree.nodes.clear()

    alias_map: dict[str, Any] = {}

    # 1. Create nodes (apply props BEFORE inputs because props like data_type change available sockets!)
    for nid, nspec in nodes_spec.items():
        ntype = str(nspec["type"])
        try:
            nd = tree.nodes.new(type=ntype)
        except Exception as exc:
            raise AddonError(
                BridgeErrorCode.INVALID_PARAMS,
                f"Cannot create node type {ntype!r} in {tree.bl_idname}: {exc}",
            ) from exc
        nd.name = nid
        if nspec.get("label"):
            nd.label = str(nspec["label"])
        if nspec.get("location") and len(nspec["location"]) == 2:
            nd.location = (float(nspec["location"][0]), float(nspec["location"][1]))
        if nspec.get("props"):
            _apply_node_props(nd, nspec["props"])
        if nspec.get("inputs"):
            for sock_key, sock_val in nspec["inputs"].items():
                sock = _find_socket(nd.inputs, str(sock_key), nd, is_input=True)
                _assign_socket_default(sock, sock_val)
        alias_map[nid] = nd

    # Auto-provision implicit 'output' and 'input' terminal nodes when referenced in links
    referenced_ids = set()
    for src_ep, dst_ep in links_spec:
        referenced_ids.add(_parse_endpoint(str(src_ep))[0])
        referenced_ids.add(_parse_endpoint(str(dst_ep))[0])

    if "output" in referenced_ids and "output" not in alias_map:
        out_type = _default_output_type(kind)
        out_node = next((n for n in tree.nodes if n.bl_idname == out_type), None)
        if out_node is None:
            out_node = tree.nodes.new(type=out_type)
        out_node.name = "output"
        alias_map["output"] = out_node

    if "input" in referenced_ids and "input" not in alias_map:
        in_type = _default_input_type(kind)
        in_node = next((n for n in tree.nodes if n.bl_idname == in_type), None)
        if in_node is None:
            in_node = tree.nodes.new(type=in_type)
        in_node.name = "input"
        alias_map["input"] = in_node

    # 2. Wire links
    for src_ep, dst_ep in links_spec:
        src_id, src_sock_spec = _parse_endpoint(str(src_ep))
        dst_id, dst_sock_spec = _parse_endpoint(str(dst_ep))
        src_node = alias_map.get(src_id) or tree.nodes.get(src_id)
        dst_node = alias_map.get(dst_id) or tree.nodes.get(dst_id)
        if src_node is None:
            raise AddonError(
                BridgeErrorCode.NOT_FOUND,
                f"Link source node {src_id!r} not found.",
                suggestions=difflib.get_close_matches(src_id, list(alias_map.keys()), n=5, cutoff=0.35),
            )
        if dst_node is None:
            raise AddonError(
                BridgeErrorCode.NOT_FOUND,
                f"Link target node {dst_id!r} not found.",
                suggestions=difflib.get_close_matches(dst_id, list(alias_map.keys()), n=5, cutoff=0.35),
            )
        from_sock = _find_socket(src_node.outputs, src_sock_spec, src_node, is_input=False)
        to_sock = _find_socket(dst_node.inputs, dst_sock_spec, dst_node, is_input=True)
        tree.links.new(from_sock, to_sock)

    if layout == "auto":
        _auto_layout_tree(tree)

    return serialize_node_tree(tree, canonical_spec)


def patch_node_tree(
    tree: Any,
    canonical_spec: str,
    *,
    add_nodes: dict[str, Any] | None = None,
    update_nodes: dict[str, Any] | None = None,
    remove_nodes: list[str] | None = None,
    add_links: list[Any] | None = None,
    remove_links: list[Any] | None = None,
    interface: list[dict[str, Any]] | None = None,
    relayout: bool = False,
) -> dict[str, Any]:
    """Incrementally patch an existing Blender node tree without rebuilding it from scratch."""
    if interface:
        for sock_def in interface:
            ensure_node_group_socket(
                tree,
                str(sock_def["name"]),
                str(sock_def.get("in_out", "INPUT")).upper(),
                str(sock_def.get("socket_type", "NodeSocketFloat")),
            )

    for nid in remove_nodes or []:
        nd = tree.nodes.get(nid)
        if nd is None:
            raise AddonError(
                BridgeErrorCode.NOT_FOUND,
                f"Node {nid!r} not found to remove.",
                suggestions=difflib.get_close_matches(nid, [n.name for n in tree.nodes], n=5, cutoff=0.35),
            )
        tree.nodes.remove(nd)

    for src_ep, dst_ep in remove_links or []:
        src_id, src_sock_spec = _parse_endpoint(str(src_ep))
        dst_id, dst_sock_spec = _parse_endpoint(str(dst_ep))
        for lk in list(tree.links):
            if (
                lk.from_node.name == src_id
                and lk.to_node.name == dst_id
                and (lk.from_socket.name == src_sock_spec or lk.from_socket.identifier == src_sock_spec)
                and (lk.to_socket.name == dst_sock_spec or lk.to_socket.identifier == dst_sock_spec)
            ):
                tree.links.remove(lk)

    for nid, nspec in (add_nodes or {}).items():
        ntype = str(nspec["type"])
        nd = tree.nodes.new(type=ntype)
        nd.name = nid
        if nspec.get("label"):
            nd.label = str(nspec["label"])
        if nspec.get("location") and len(nspec["location"]) == 2:
            nd.location = (float(nspec["location"][0]), float(nspec["location"][1]))
        if nspec.get("props"):
            _apply_node_props(nd, nspec["props"])
        if nspec.get("inputs"):
            for sock_key, sock_val in nspec["inputs"].items():
                sock = _find_socket(nd.inputs, str(sock_key), nd, is_input=True)
                _assign_socket_default(sock, sock_val)

    for nid, uspec in (update_nodes or {}).items():
        nd = tree.nodes.get(nid)
        if nd is None:
            raise AddonError(
                BridgeErrorCode.NOT_FOUND,
                f"Node {nid!r} not found to update.",
                suggestions=difflib.get_close_matches(nid, [n.name for n in tree.nodes], n=5, cutoff=0.35),
            )
        if uspec.get("props"):
            _apply_node_props(nd, uspec["props"])
        if uspec.get("inputs"):
            for sock_key, sock_val in uspec["inputs"].items():
                sock = _find_socket(nd.inputs, str(sock_key), nd, is_input=True)
                _assign_socket_default(sock, sock_val)

    for src_ep, dst_ep in add_links or []:
        src_id, src_sock_spec = _parse_endpoint(str(src_ep))
        dst_id, dst_sock_spec = _parse_endpoint(str(dst_ep))
        src_node = tree.nodes.get(src_id)
        dst_node = tree.nodes.get(dst_id)
        if src_node is None or dst_node is None:
            raise AddonError(
                BridgeErrorCode.NOT_FOUND,
                f"Cannot link {src_ep!r} -> {dst_ep!r}: node missing.",
            )
        from_sock = _find_socket(src_node.outputs, src_sock_spec, src_node, is_input=False)
        to_sock = _find_socket(dst_node.inputs, dst_sock_spec, dst_node, is_input=True)
        tree.links.new(from_sock, to_sock)

    if relayout:
        _auto_layout_tree(tree)

    return serialize_node_tree(tree, canonical_spec)


def introspect_node_types(
    *,
    tree_type: str = "ShaderNodeTree",
    search: str | None = None,
    include_sockets: bool = False,
    limit: int = 40,
) -> dict[str, Any]:
    """Discover registered Blender node bl_idnames and live sockets for the running version."""
    prefix_map = {
        "shader": ("ShaderNodeTree", ("ShaderNode", "NodeGroup")),
        "shadernodetree": ("ShaderNodeTree", ("ShaderNode", "NodeGroup")),
        "geometry": ("GeometryNodeTree", ("GeometryNode", "FunctionNode", "ShaderNodeValToRGB", "ShaderNodeMath", "ShaderNodeVectorMath", "ShaderNodeMix", "ShaderNodeTex", "NodeGroup")),
        "geonodes": ("GeometryNodeTree", ("GeometryNode", "FunctionNode", "ShaderNodeValToRGB", "ShaderNodeMath", "ShaderNodeVectorMath", "ShaderNodeMix", "ShaderNodeTex", "NodeGroup")),
        "geometrynodetree": ("GeometryNodeTree", ("GeometryNode", "FunctionNode", "ShaderNodeValToRGB", "ShaderNodeMath", "ShaderNodeVectorMath", "ShaderNodeMix", "ShaderNodeTex", "NodeGroup")),
        "compositor": ("CompositorNodeTree", ("CompositorNode", "NodeGroup")),
        "compositornodetree": ("CompositorNodeTree", ("CompositorNode", "NodeGroup")),
    }
    tree_idname, prefixes = prefix_map.get(tree_type.strip().lower(), ("ShaderNodeTree", ("ShaderNode",)))
    q = (search or "").strip().lower()

    matched: list[str] = []
    for name in sorted(dir(bpy.types)):
        if not name.startswith(prefixes):
            continue
        cls = getattr(bpy.types, name, None)
        if cls is None or not isinstance(cls, type):
            continue
        if not issubclass(cls, bpy.types.Node):
            continue
        if q and q not in name.lower():
            continue
        matched.append(name)

    total = len(matched)
    selected = matched[: max(1, min(limit, 100))]

    items: list[dict[str, Any]] = []
    if include_sockets:
        scratch = bpy.data.node_groups.new("_mcp_introspect_tmp", tree_idname)
        try:
            for bl_id in selected[:20]:
                try:
                    nd = scratch.nodes.new(type=bl_id)
                    items.append(
                        {
                            "type": bl_id,
                            "label": getattr(nd, "bl_label", bl_id),
                            "inputs": [{"name": s.name, "type": s.type} for s in nd.inputs],
                            "outputs": [{"name": s.name, "type": s.type} for s in nd.outputs],
                        }
                    )
                    scratch.nodes.remove(nd)
                except Exception:
                    continue
        finally:
            bpy.data.node_groups.remove(scratch)
    else:
        for bl_id in selected:
            cls = getattr(bpy.types, bl_id)
            items.append({"type": bl_id, "label": getattr(cls, "bl_rna", None).name if hasattr(cls, "bl_rna") else bl_id})

    return {
        "tree_type": tree_idname,
        "total_matches": total,
        "returned": len(items),
        "node_types": items,
    }
