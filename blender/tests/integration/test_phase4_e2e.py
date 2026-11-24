# SPDX-License-Identifier: MIT
"""End-to-end Phase 4 integration tests: Resources, push subscriptions, and multi-instance Blender."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from blender_mcp.app import create_server
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


def _read_resource_json(res: object) -> dict:
    contents = getattr(res, "contents", res)
    if isinstance(contents, list) and contents:
        first = contents[0]
        text = getattr(first, "content", None) or getattr(first, "text", None)
        if isinstance(text, str):
            return json.loads(text)
    raise AssertionError(f"Unexpected read_resource output: {res!r}")


async def test_phase4_resources_and_live_scene_push_events(tmp_path: Path) -> None:
    session_file = tmp_path / "session.json"
    proc = launch_blender_headless(
        allow_python=False,
        session_file=session_file,
        startup_timeout=45.0,
    )
    settings = ServerSettings(
        host=proc.host,
        port=proc.port,
        token=proc.token,
        session_file=session_file,
        sessions_dir=tmp_path / "sessions",
        host_explicit=True,
        port_explicit=True,
        profile="full",
        python_policy=PythonPolicy.FALSE,
        audit_log=None,
    )
    mcp = create_server(settings)
    runtime = mcp._blender_runtime  # type: ignore[attr-defined]

    try:
        # 1. Read live MCP Resources
        scene_data = _read_resource_json(await mcp.read_resource("blender://scene"))
        assert scene_data["object_count"] >= 1

        cube_data = _read_resource_json(await mcp.read_resource("blender://object/Cube"))
        assert cube_data["name"] == "Cube"

        _extract_json(
            await mcp.call_tool(
                "create_pbr_material",
                {"name": "GoldSample", "base_color": [1.0, 0.8, 0.2, 1.0], "metallic": 1.0},
            )
        )
        mat_data = _read_resource_json(await mcp.read_resource("blender://material/GoldSample"))
        assert mat_data["name"] == "GoldSample"

        nt_data = _read_resource_json(await mcp.read_resource("blender://node-tree/material/GoldSample"))
        assert nt_data["tree"] == "material:GoldSample"
        assert nt_data["node_count"] >= 2

        docs_data = _read_resource_json(await mcp.read_resource("docs://bpy/Principled"))
        assert len(docs_data["matches"]) >= 1

        # 2. Verify debounced real-time push notification from Blender over TCP
        runtime.last_scene_event = None
        _extract_json(
            await mcp.call_tool("create_primitive", {"primitive": "ico_sphere", "name": "LiveEventSphere"})
        )
        for _ in range(30):
            if runtime.last_scene_event is not None:
                break
            await asyncio.sleep(0.05)

        assert runtime.last_scene_event is not None
        assert runtime.last_scene_event["object_count"] >= 4
    finally:
        await runtime.bridge.close()
        proc.stop()


async def test_phase4_multi_instance_simultaneous_control(tmp_path: Path) -> None:
    """Launch TWO headless Blender 5.3 instances and control both independently via instance_id."""
    shared_session = tmp_path / "session.json"
    proc_a = launch_blender_headless(allow_python=False, session_file=shared_session, startup_timeout=45.0)
    proc_b = launch_blender_headless(allow_python=False, session_file=shared_session, startup_timeout=45.0)

    settings = ServerSettings(
        session_file=shared_session,
        sessions_dir=tmp_path / "sessions",
        profile="modeling",
        python_policy=PythonPolicy.FALSE,
        audit_log=None,
    )
    mcp = create_server(settings)
    runtime = mcp._blender_runtime  # type: ignore[attr-defined]

    try:
        listed = _extract_json(await mcp.call_tool("list_blender_instances", {}))
        instances = listed["instances"]
        assert len(instances) == 2

        id_a = instances[0]["instance_id"]
        id_b = instances[1]["instance_id"]
        assert id_a != id_b

        # Work in instance A
        _extract_json(await mcp.call_tool("select_blender_instance", {"instance_id": id_a}))
        _extract_json(
            await mcp.call_tool("create_primitive", {"primitive": "cube", "name": "OnlyInInstanceA"})
        )

        # Switch to instance B and verify total scene isolation
        _extract_json(await mcp.call_tool("select_blender_instance", {"instance_id": id_b}))
        _extract_json(
            await mcp.call_tool("create_primitive", {"primitive": "uv_sphere", "name": "OnlyInInstanceB"})
        )
        objs_b = {o["name"] for o in _extract_json(await mcp.call_tool("list_objects", {}))["objects"]}
        assert "OnlyInInstanceB" in objs_b
        assert "OnlyInInstanceA" not in objs_b

        # Switch back to instance A and verify its object is intact
        _extract_json(await mcp.call_tool("select_blender_instance", {"instance_id": id_a}))
        objs_a = {o["name"] for o in _extract_json(await mcp.call_tool("list_objects", {}))["objects"]}
        assert "OnlyInInstanceA" in objs_a
        assert "OnlyInInstanceB" not in objs_a
    finally:
        await runtime.bridge.close()
        proc_a.stop()
        proc_b.stop()
