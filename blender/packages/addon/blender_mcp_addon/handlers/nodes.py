# SPDX-License-Identifier: GPL-3.0-or-later
"""RPC handlers exposing the declarative bidirectional Nodes DSL."""

from __future__ import annotations

from typing import Any

from ..compat import set_geometry_nodes_input
from ..dispatcher import Dispatcher, ExecutionContext
from ..nodes_dsl import (
    build_node_tree,
    introspect_node_types,
    patch_node_tree,
    resolve_node_tree,
    serialize_node_tree,
)
from ..state import resolve_object
from ..wire import AddonError, BridgeErrorCode


def get_node_tree(params: dict[str, Any], _ctx: ExecutionContext) -> dict[str, Any]:
    spec = str(params.get("tree", ""))
    tree, _kind, canonical = resolve_node_tree(spec, create_if_missing=False)
    return serialize_node_tree(tree, canonical)


def build_node_tree_handler(params: dict[str, Any], _ctx: ExecutionContext) -> dict[str, Any]:
    spec = str(params.get("tree", ""))
    tree, kind, canonical = resolve_node_tree(spec, create_if_missing=True)
    result = build_node_tree(
        tree,
        kind,
        canonical,
        nodes_spec=params.get("nodes") or {},
        links_spec=params.get("links") or [],
        interface_spec=params.get("interface"),
        clear=bool(params.get("clear", True)),
        layout=str(params.get("layout", "auto")),
    )

    attach_obj = params.get("attach_to_object")
    if attach_obj and kind == "geonodes":
        obj = resolve_object(str(attach_obj))
        assert obj is not None
        mod_name = str(params.get("modifier_name") or tree.name)
        mod = obj.modifiers.get(mod_name)
        if mod is None or mod.type != "NODES":
            mod = obj.modifiers.new(name=mod_name, type="NODES")
        mod.node_group = tree
        result["attached_to_object"] = obj.name
        result["modifier_name"] = mod.name

    return result


def patch_node_tree_handler(params: dict[str, Any], _ctx: ExecutionContext) -> dict[str, Any]:
    spec = str(params.get("tree", ""))
    tree, _kind, canonical = resolve_node_tree(spec, create_if_missing=False)
    return patch_node_tree(
        tree,
        canonical,
        add_nodes=params.get("add_nodes"),
        update_nodes=params.get("update_nodes"),
        remove_nodes=params.get("remove_nodes"),
        add_links=params.get("add_links"),
        remove_links=params.get("remove_links"),
        interface=params.get("interface"),
        relayout=bool(params.get("relayout", False)),
    )


def list_node_types_handler(params: dict[str, Any], _ctx: ExecutionContext) -> dict[str, Any]:
    return introspect_node_types(
        tree_type=str(params.get("tree_type", "ShaderNodeTree")),
        search=params.get("search"),
        include_sockets=bool(params.get("include_sockets", False)),
        limit=int(params.get("limit", 40)),
    )


def set_group_inputs(params: dict[str, Any], _ctx: ExecutionContext) -> dict[str, Any]:
    """Set input socket values on a Geometry Nodes modifier attached to an object."""
    obj = resolve_object(str(params.get("object", "")))
    assert obj is not None
    mod_name = params.get("modifier")
    if mod_name:
        mod = obj.modifiers.get(str(mod_name))
    else:
        mod = next((m for m in obj.modifiers if m.type == "NODES"), None)
    if mod is None or mod.type != "NODES" or mod.node_group is None:
        raise AddonError(
            BridgeErrorCode.NOT_FOUND,
            f"No Geometry Nodes modifier found on {obj.name!r}.",
        )

    values = params.get("inputs") or {}
    applied: list[str] = []
    ignored: list[str] = []

    for k, v in values.items():
        if set_geometry_nodes_input(mod, k, v):
            applied.append(k)
        else:
            ignored.append(k)

    obj.update_tag()
    return {
        "object": obj.name,
        "modifier": mod.name,
        "applied": applied,
        "ignored": ignored,
    }


def register(dispatcher: Dispatcher) -> None:
    dispatcher.register("nodes.get_node_tree", get_node_tree, mutating=False)
    dispatcher.register("nodes.build_node_tree", build_node_tree_handler)
    dispatcher.register("nodes.patch_node_tree", patch_node_tree_handler)
    dispatcher.register("nodes.list_node_types", list_node_types_handler, mutating=False)
    dispatcher.register("nodes.set_group_inputs", set_group_inputs)
