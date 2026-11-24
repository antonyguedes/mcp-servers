# SPDX-License-Identifier: MIT
"""Unit tests for Phase 3 tool profiles, render PathGuard, and JobManager lifecycle."""

from __future__ import annotations

import importlib.util
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from blender_mcp.app import create_server
from blender_mcp.config import ServerSettings
from blender_mcp_protocol import PythonPolicy


def _load_job_manager():
    addon_pkg = Path(__file__).resolve().parents[2] / "packages" / "addon"
    if str(addon_pkg) not in sys.path:
        sys.path.insert(0, str(addon_pkg))
    wire_spec = importlib.util.spec_from_file_location(
        "blender_mcp_addon.wire", addon_pkg / "blender_mcp_addon" / "wire.py"
    )
    jobs_spec = importlib.util.spec_from_file_location(
        "blender_mcp_addon.jobs", addon_pkg / "blender_mcp_addon" / "jobs.py"
    )
    assert wire_spec and wire_spec.loader and jobs_spec and jobs_spec.loader
    # Ensure lightweight namespace package without importing bpy
    import types

    pkg = types.ModuleType("blender_mcp_addon")
    pkg.__path__ = [str(addon_pkg / "blender_mcp_addon")]
    sys.modules.setdefault("blender_mcp_addon", pkg)
    wire_mod = importlib.util.module_from_spec(wire_spec)
    sys.modules["blender_mcp_addon.wire"] = wire_mod
    wire_spec.loader.exec_module(wire_mod)

    jobs_mod = importlib.util.module_from_spec(jobs_spec)
    sys.modules["blender_mcp_addon.jobs"] = jobs_mod
    jobs_spec.loader.exec_module(jobs_mod)
    return jobs_mod.JobManager


async def test_phase3_tools_registered_by_profile() -> None:
    mcp_anim = create_server(
        ServerSettings(profile="animation", python_policy=PythonPolicy.FALSE, audit_log=None)
    )
    anim_tools = {t.name for t in await mcp_anim.list_tools()}
    for expected in (
        "insert_keyframes",
        "create_armature",
        "add_rigid_body",
        "bake_physics",
        "configure_render",
        "render_still",
        "render_animation",
        "get_job_status",
        "cancel_job",
    ):
        assert expected in anim_tools
    assert "sculpt_remesh" not in anim_tools

    mcp_full = create_server(
        ServerSettings(profile="full", python_policy=PythonPolicy.FALSE, audit_log=None)
    )
    full_tools = {t.name for t in await mcp_full.list_tools()}
    for expected in ("sculpt_remesh", "sculpt_stroke", "gp_create_object", "gp_draw_stroke", "render_animation"):
        assert expected in full_tools


async def test_render_tools_enforce_path_guard(tmp_path: Path) -> None:
    allowed = tmp_path / "renders"
    allowed.mkdir()
    outside = tmp_path / "escape.png"

    mcp = create_server(
        ServerSettings(
            profile="full",
            python_policy=PythonPolicy.FALSE,
            allowed_dirs=[allowed],
            audit_log=None,
        )
    )
    for tool_name, args in (
        ("render_still", {"output_path": str(outside)}),
        ("render_animation", {"output_dir": str(tmp_path / "outside_dir")}),
        ("configure_render", {"output_path": str(outside)}),
    ):
        with pytest.raises(ToolError) as exc:
            await mcp.call_tool(tool_name, args)
        assert "Access denied" in str(exc.value)


def test_job_manager_progress_and_cancellation() -> None:
    job_manager_cls = _load_job_manager()
    jm = job_manager_cls()

    # 1. Cooperative job runs to completion
    def ok_job(rec) -> Iterator[None]:
        for i in range(1, 4):
            rec.update_progress(i, 3, f"step {i}")
            rec.result = {"steps": i}
            yield

    rec1 = jm.submit("test.ok", ok_job, total_steps=3)
    assert rec1.status == "pending"
    while jm.has_work():
        jm.tick_main_thread()
    st1 = jm.get_status(rec1.job_id)
    assert st1["status"] == "completed"
    assert st1["progress"] == 1.0
    assert st1["result"] == {"steps": 3}

    # 2. Job cancelled mid-flight stops immediately
    cleaned_up = False

    def long_job(rec) -> Iterator[None]:
        nonlocal cleaned_up
        try:
            for i in range(1, 20):
                rec.update_progress(i, 20, f"frame {i}")
                rec.result = {"frames": i}
                yield
        finally:
            cleaned_up = True

    rec2 = jm.submit("test.cancel", long_job, total_steps=20)
    jm.tick_main_thread()  # Runs slice 1
    assert jm.get_status(rec2.job_id)["current_step"] == 1
    jm.cancel(rec2.job_id)
    jm.tick_main_thread()  # Triggers cancellation cleanup
    st2 = jm.get_status(rec2.job_id)
    assert st2["status"] == "cancelled"
    assert st2["result"]["frames"] == 1
    assert cleaned_up is True
