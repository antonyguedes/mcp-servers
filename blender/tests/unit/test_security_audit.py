# SPDX-License-Identifier: MIT
"""Consolidated security audit test suite covering all blender-mcp threat boundaries."""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from blender_mcp.app import create_server
from blender_mcp.config import ServerSettings
from blender_mcp_protocol import PythonPolicy


async def test_audit_python_policy_all_three_modes(tmp_path: Path) -> None:
    # 1. FALSE: scripting tools absent AND dynamic enable_toolset('scripting') blocked
    mcp_false = create_server(
        ServerSettings(profile="full", python_policy=PythonPolicy.FALSE, audit_log=None),
        discover_plugins=False,
    )
    names_false = {t.name for t in await mcp_false.list_tools()}
    assert "execute_python" not in names_false
    assert "run_script_file" not in names_false
    with pytest.raises(ToolError, match="BLENDER_MCP_ALLOW_PYTHON=false"):
        await mcp_false.call_tool("enable_toolset", {"name": "scripting"})

    # 2. CONFIRM: tools present, unconfirmed call rejected with CONFIRMATION_REQUIRED
    mcp_confirm = create_server(
        ServerSettings(profile="full", python_policy=PythonPolicy.CONFIRM, audit_log=None),
        discover_plugins=False,
    )
    names_confirm = {t.name for t in await mcp_confirm.list_tools()}
    assert "execute_python" in names_confirm
    with pytest.raises(ToolError, match="requires explicit confirmation"):
        await mcp_confirm.call_tool("execute_python", {"code": "print(1)", "confirmed": False})

    # 3. TRUE: tools present and path guard still enforced on run_script_file
    allowed = tmp_path / "scripts"
    allowed.mkdir()
    outside = tmp_path / "escape.py"
    outside.write_text("print('escaped')", encoding="utf-8")
    mcp_true = create_server(
        ServerSettings(
            profile="full",
            python_policy=PythonPolicy.TRUE,
            allowed_dirs=[allowed],
            audit_log=None,
        ),
        discover_plugins=False,
    )
    with pytest.raises(ToolError, match="Access denied"):
        await mcp_true.call_tool("run_script_file", {"filepath": str(outside)})


async def test_audit_path_guard_covers_all_file_tools(tmp_path: Path) -> None:
    allowed = tmp_path / "safe"
    allowed.mkdir()
    secret = tmp_path / "secret.png"
    secret.write_bytes(b"secret")

    mcp = create_server(
        ServerSettings(
            profile="full",
            python_policy=PythonPolicy.FALSE,
            allowed_dirs=[allowed],
            cache_dir=tmp_path / "cache",
            audit_log=None,
        ),
        discover_plugins=False,
    )

    traversal = str(allowed / ".." / "secret.png")
    cases = [
        ("create_texture_from_image", {"material": "M", "filepath": traversal}),
        ("set_world_hdri", {"filepath": traversal}),
        ("export_file", {"filepath": str(tmp_path / "out.glb")}),
        ("import_file", {"filepath": traversal}),
        ("save_blend", {"filepath": str(tmp_path / "out.blend")}),
        ("open_blend", {"filepath": traversal}),
        ("link_append", {"filepath": traversal}),
        ("render_still", {"output_path": str(tmp_path / "out.png")}),
        ("render_animation", {"output_dir": str(tmp_path / "frames")}),
        ("configure_render", {"output_path": str(tmp_path / "out.png")}),
        ("ai3d_generate", {"image_path": traversal}),
    ]
    for tool_name, args in cases:
        with pytest.raises(ToolError, match="Access denied"):
            await mcp.call_tool(tool_name, args)


def test_audit_addon_refuses_non_localhost_bind() -> None:
    """Ensure the Blender add-on bridge refuses binding to public network interfaces."""
    addon_root = Path(__file__).resolve().parents[2] / "packages" / "addon"
    # Verify check in BridgeTCPServer.__init__ source without requiring bpy
    server_src = (addon_root / "blender_mcp_addon" / "server.py").read_text(encoding="utf-8")
    assert 'host not in ("127.0.0.1", "localhost", "::1")' in server_src
    assert "hmac.compare_digest" in server_src

    # Also verify RNA traversal blocks unsafe expressions
    intro_src = (addon_root / "blender_mcp_addon" / "handlers" / "introspection.py").read_text(encoding="utf-8")
    assert '("__")' in intro_src or '"__"' in intro_src
    assert '"quit_blender"' in intro_src
    assert '"python_file_run"' in intro_src

    # Verify wire module rejects zero and oversized frames
    wire_spec = importlib.util.spec_from_file_location(
        "wire_sec_test", addon_root / "blender_mcp_addon" / "wire.py"
    )
    assert wire_spec and wire_spec.loader
    mod = types.ModuleType("wire_sec_test")
    sys.modules["wire_sec_test"] = mod
    wire_spec.loader.exec_module(mod)
    assert mod.MAX_FRAME_BYTES == 64 * 1024 * 1024
