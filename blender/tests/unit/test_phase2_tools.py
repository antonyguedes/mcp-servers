# SPDX-License-Identifier: MIT
"""Unit tests for Phase 2 tool registration, profiles, and I/O PathGuard enforcement."""

from __future__ import annotations

from pathlib import Path

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from blender_mcp.app import create_server
from blender_mcp.config import ServerSettings
from blender_mcp_protocol import PythonPolicy


async def test_phase2_tools_registered_by_profile() -> None:
    mcp_modeling = create_server(
        ServerSettings(profile="modeling", python_policy=PythonPolicy.FALSE, audit_log=None)
    )
    modeling_tools = {t.name for t in await mcp_modeling.list_tools()}
    for expected in (
        "mesh_bevel",
        "mesh_boolean",
        "uv_unwrap",
        "add_modifier",
        "build_node_tree",
        "patch_node_tree",
        "list_node_types",
        "setup_lighting_preset",
        "camera_frame_objects",
        "export_file",
        "import_file",
    ):
        assert expected in modeling_tools
    assert "get_rna" not in modeling_tools

    mcp_full = create_server(
        ServerSettings(profile="full", python_policy=PythonPolicy.FALSE, audit_log=None)
    )
    full_tools = {t.name for t in await mcp_full.list_tools()}
    for expected in ("get_rna", "set_rna", "list_operators", "call_operator", "search_bpy_api"):
        assert expected in full_tools
    assert "execute_python" not in full_tools


async def test_io_tools_enforce_path_guard(tmp_path: Path) -> None:
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    outside = tmp_path / "outside.glb"
    outside.write_bytes(b"glTF")

    mcp = create_server(
        ServerSettings(
            profile="full",
            python_policy=PythonPolicy.FALSE,
            allowed_dirs=[allowed],
            audit_log=None,
        )
    )

    for tool_name, args in (
        ("export_file", {"filepath": str(outside)}),
        ("import_file", {"filepath": str(outside)}),
        ("save_blend", {"filepath": str(tmp_path / "escape.blend")}),
        ("open_blend", {"filepath": str(outside)}),
        ("set_world_hdri", {"filepath": str(outside)}),
    ):
        with pytest.raises(ToolError) as exc:
            await mcp.call_tool(tool_name, args)
        assert "Access denied" in str(exc.value)
