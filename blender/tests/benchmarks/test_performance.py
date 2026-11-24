# SPDX-License-Identifier: MIT
"""Performance benchmarks verifying p95 < 150ms latency SLA and paginated dense scene scaling."""

from __future__ import annotations

import json
import time

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
    structured = getattr(call_result, "structured_content", None)
    if isinstance(structured, dict):
        return structured
    return json.loads(getattr(call_result, "content", [])[0].text)


async def test_tool_latency_p95_under_150ms_and_pagination_scaling() -> None:
    proc = launch_blender_headless(allow_python=False, startup_timeout=45.0)
    settings = ServerSettings(
        host=proc.host,
        port=proc.port,
        token=proc.token,
        host_explicit=True,
        port_explicit=True,
        profile="modeling",
        python_policy=PythonPolicy.FALSE,
        audit_log=None,
    )
    mcp = create_server(settings, discover_plugins=False)
    runtime = mcp._blender_runtime  # type: ignore[attr-defined]

    try:
        # Warm up handshake
        _extract_json(await mcp.call_tool("get_blender_info", {}))

        # 1. Measure 30 simple tool calls -> enforce p95 < 150 ms SLA
        latencies_ms: list[float] = []
        for i in range(30):
            t0 = time.perf_counter()
            if i % 3 == 0:
                _extract_json(await mcp.call_tool("get_scene_summary", {}))
            elif i % 3 == 1:
                _extract_json(await mcp.call_tool("list_objects", {"limit": 50}))
            else:
                _extract_json(
                    await mcp.call_tool(
                        "transform_object",
                        {"object": "Cube", "location": [float(i) * 0.05, 0.0, 0.0]},
                    )
                )
            latencies_ms.append((time.perf_counter() - t0) * 1000.0)

        latencies_ms.sort()
        p95_ms = latencies_ms[int(len(latencies_ms) * 0.95)]
        assert p95_ms < 150.0, f"p95 latency {p95_ms:.1f}ms exceeded 150ms budget (samples={latencies_ms[-5:]})"

        # 2. Dense scene stress: duplicate 100 objects and verify fast paginated listing
        _extract_json(
            await mcp.call_tool(
                "duplicate_object",
                {"object": "Cube", "new_name": "BenchObj", "offset": [0.1, 0.0, 0.0], "count": 100, "linked": True},
            )
        )
        t_list = time.perf_counter()
        page = _extract_json(await mcp.call_tool("list_objects", {"offset": 0, "limit": 25}))
        list_ms = (time.perf_counter() - t_list) * 1000.0
        assert page["total"] >= 103
        assert len(page["objects"]) == 25
        assert page["has_more"] is True
        assert list_ms < 150.0, f"Paginated list_objects took {list_ms:.1f}ms"
    finally:
        await runtime.bridge.close()
        proc.stop()
