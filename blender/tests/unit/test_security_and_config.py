# SPDX-License-Identifier: MIT
"""Unit tests for config, security policies, audit logging, and MCP tool registration."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from blender_mcp.app import create_server
from blender_mcp.config import ServerSettings
from blender_mcp.security import AuditLogger, PathGuard, check_python_policy
from blender_mcp_protocol import BridgeError, BridgeErrorCode, PythonPolicy


def test_settings_from_env_and_session_discovery(tmp_path: Path) -> None:
    session_file = tmp_path / "session.json"
    session_file.write_text(
        json.dumps({"host": "127.0.0.1", "port": 19999, "token": "secret-from-file"}),
        encoding="utf-8",
    )

    cfg = ServerSettings.from_env(
        {
            "BLENDER_MCP_SESSION_FILE": str(session_file),
            "BLENDER_MCP_ALLOW_PYTHON": "confirm",
            "BLENDER_MCP_PROFILE": "minimal",
        }
    )
    assert cfg.python_policy == PythonPolicy.CONFIRM
    assert cfg.profile == "minimal"
    assert cfg.resolve_bridge_endpoint() == ("127.0.0.1", 19999, "secret-from-file")

    # Explicit port & token override session file
    cfg_override = ServerSettings.from_env(
        {
            "BLENDER_MCP_SESSION_FILE": str(session_file),
            "BLENDER_MCP_PORT": "12345",
            "BLENDER_MCP_TOKEN": "explicit-tok",
        }
    )
    assert cfg_override.resolve_bridge_endpoint() == ("127.0.0.1", 12345, "explicit-tok")


def test_path_guard_allowlist_and_traversal_protection(tmp_path: Path) -> None:
    safe_dir = tmp_path / "workspace"
    safe_dir.mkdir()
    ok_file = safe_dir / "tex.png"
    ok_file.write_bytes(b"png")

    outside = tmp_path / "secret.txt"
    outside.write_text("top secret", encoding="utf-8")

    guard = PathGuard([safe_dir])
    assert guard.validate(str(ok_file), must_exist=True) == ok_file.resolve()

    with pytest.raises(BridgeError) as exc_info:
        guard.validate(str(safe_dir / ".." / "secret.txt"))
    assert exc_info.value.code == BridgeErrorCode.PATH_DENIED

    with pytest.raises(BridgeError) as missing_info:
        guard.validate(str(safe_dir / "does_not_exist.png"), must_exist=True)
    assert missing_info.value.code == BridgeErrorCode.NOT_FOUND


def test_python_policy_enforcement() -> None:
    with pytest.raises(BridgeError) as denied:
        check_python_policy(PythonPolicy.FALSE, confirmed=True)
    assert denied.value.code == BridgeErrorCode.POLICY_DENIED

    with pytest.raises(BridgeError) as need_confirm:
        check_python_policy(PythonPolicy.CONFIRM, confirmed=False)
    assert need_confirm.value.code == BridgeErrorCode.CONFIRMATION_REQUIRED

    # Allowed when confirmed or TRUE
    check_python_policy(PythonPolicy.CONFIRM, confirmed=True)
    check_python_policy(PythonPolicy.TRUE, confirmed=False)


def test_audit_logger_hashes_python_code(tmp_path: Path) -> None:
    log_file = tmp_path / "audit.jsonl"
    logger = AuditLogger(log_file)
    logger.record(
        tool="scripting.execute_python",
        params={"code": "import bpy\nprint('hi')"},
        ok=True,
        duration_ms=12.34,
    )
    lines = log_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["tool"] == "scripting.execute_python"
    assert "code_sha256" in entry["params"]
    assert "code" not in entry["params"]


async def test_scripting_tools_hidden_when_allow_python_false() -> None:
    cfg_off = ServerSettings(python_policy=PythonPolicy.FALSE, audit_log=None)
    mcp_off = create_server(cfg_off)
    tools_off = {t.name for t in await mcp_off.list_tools()}
    assert "create_primitive" in tools_off
    assert "capture_multiview" in tools_off
    assert "execute_python" not in tools_off
    assert "run_script_file" not in tools_off

    cfg_on = ServerSettings(python_policy=PythonPolicy.TRUE, audit_log=None)
    mcp_on = create_server(cfg_on)
    tools_on = {t.name for t in await mcp_on.list_tools()}
    assert "execute_python" in tools_on
    assert "run_script_file" in tools_on

    cfg_min = ServerSettings(profile="minimal", python_policy=PythonPolicy.FALSE, audit_log=None)
    mcp_min = create_server(cfg_min)
    tools_min = {t.name for t in await mcp_min.list_tools()}
    assert "get_scene_summary" in tools_min
    assert "capture_viewport" in tools_min
    assert "create_primitive" not in tools_min
