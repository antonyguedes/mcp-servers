# SPDX-License-Identifier: MIT
"""Unit tests for Phase 4 MCP platform features: dynamic toolsets, prompts, resources, HTTP security."""

from __future__ import annotations

import json

import httpx
import pytest
from mcp.server.mcpserver.exceptions import ToolError

from blender_mcp.app import create_server
from blender_mcp.config import ServerSettings
from blender_mcp.http_security import build_http_app
from blender_mcp_protocol import PythonPolicy


def _extract_json(call_result: object) -> dict:
    structured = getattr(call_result, "structured_content", None)
    if isinstance(structured, dict):
        return structured
    content = getattr(call_result, "content", None)
    if content:
        return json.loads(content[0].text)
    raise AssertionError(f"Unexpected result: {call_result!r}")


async def test_dynamic_toolsets_enable_disable_and_cursor_budget() -> None:
    mcp = create_server(
        ServerSettings(profile="minimal", python_policy=PythonPolicy.FALSE, audit_log=None)
    )
    initial_tools = {t.name for t in await mcp.list_tools()}
    # Minimal profile stays super lean (well below Cursor's ~40 tool cap)
    assert len(initial_tools) <= 20
    assert "build_node_tree" not in initial_tools
    assert "list_toolsets" in initial_tools
    assert "enable_toolset" in initial_tools

    # Enable 'nodes' dynamically
    enabled = _extract_json(await mcp.call_tool("enable_toolset", {"name": "nodes"}))
    assert enabled["enabled"] is True
    assert "build_node_tree" in enabled["tools_added"]
    after_enable = {t.name for t in await mcp.list_tools()}
    assert "build_node_tree" in after_enable

    # Disable 'nodes' dynamically
    disabled = _extract_json(await mcp.call_tool("disable_toolset", {"name": "nodes"}))
    assert disabled["enabled"] is False
    assert "build_node_tree" in disabled["tools_removed"]
    after_disable = {t.name for t in await mcp.list_tools()}
    assert "build_node_tree" not in after_disable

    # Core toolset cannot be disabled; scripting cannot be enabled when ALLOW_PYTHON=false
    with pytest.raises(ToolError):
        await mcp.call_tool("disable_toolset", {"name": "core"})
    with pytest.raises(ToolError):
        await mcp.call_tool("enable_toolset", {"name": "scripting"})


async def test_prompts_and_static_resources() -> None:
    mcp = create_server(
        ServerSettings(profile="minimal", python_policy=PythonPolicy.FALSE, audit_log=None)
    )
    prompts = await mcp.list_prompts()
    prompt_names = {p.name for p in prompts}
    assert {
        "product_shot",
        "low_poly_scene",
        "architectural_interior",
        "character_blockout",
        "turntable_animation",
        "procedural_material_workshop",
        "game_asset_optimization",
    }.issubset(prompt_names)

    rendered = await mcp.get_prompt("turntable_animation", {"target": "Robot", "frames": "120", "engine": "cycles"})
    assert rendered.messages
    assert "Robot" in str(rendered.messages[0].content)

    resources = await mcp.list_resources()
    uris = {str(r.uri) for r in resources}
    assert {"blender://guide", "blender://scene", "blender://instances"}.issubset(uris)

    templates = await mcp.list_resource_templates()
    template_uris = {str(t.uri_template) for t in templates}
    assert "blender://object/{ref}" in template_uris
    assert "blender://material/{name}" in template_uris
    assert "blender://node-tree/{kind}/{name}" in template_uris
    assert "docs://bpy/{query}" in template_uris

    guide_result = await mcp.read_resource("blender://guide")
    assert "Z-up" in str(guide_result)


async def test_streamable_http_dns_rebinding_and_bearer_auth() -> None:
    settings = ServerSettings(
        profile="minimal",
        python_policy=PythonPolicy.FALSE,
        http_host="127.0.0.1",
        http_port=8765,
        http_bearer_token="super-secret-token",
        audit_log=None,
    )
    mcp = create_server(settings)
    app = build_http_app(mcp, settings)

    transport = httpx.ASGITransport(app=app)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8765") as client,
    ):
        # 1. Missing bearer token -> 401
        r_no_auth = await client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"})
        assert r_no_auth.status_code == 401

        # 2. Wrong bearer token -> 401
        r_bad_auth = await client.post(
            "/mcp",
            headers={"Authorization": "Bearer wrong-token"},
            json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
        )
        assert r_bad_auth.status_code == 401

        # 3. Valid bearer token but evil Origin -> rejected by DNS rebinding protection (403)
        r_evil_origin = await client.post(
            "/mcp",
            headers={
                "Authorization": "Bearer super-secret-token",
                "Origin": "https://evil-site.example",
                "Host": "127.0.0.1:8765",
            },
            json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
        )
        assert r_evil_origin.status_code in (400, 403, 421)
