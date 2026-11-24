# SPDX-License-Identifier: MIT
"""Pytest runner for the blender-mcp baseline agent evaluation suite."""

from __future__ import annotations

from pathlib import Path

import pytest

from blender_mcp.app import create_server
from blender_mcp.bridge.launcher import find_blender_executable, launch_blender_headless
from blender_mcp.config import ServerSettings
from blender_mcp_protocol import PythonPolicy
from tests.evals.harness import run_eval_case
from tests.evals.tasks import EVAL_SUITE

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        find_blender_executable() is None,
        reason="No Blender executable installed on this machine",
    ),
]


async def test_eval_suite_baseline_100_percent(tmp_path: Path) -> None:
    """Verify all baseline agent eval tasks pass 100% with geometric & visual assertions."""
    proc = launch_blender_headless(allow_python=False, startup_timeout=45.0)
    settings = ServerSettings(
        host=proc.host,
        port=proc.port,
        token=proc.token,
        host_explicit=True,
        port_explicit=True,
        profile="full",
        python_policy=PythonPolicy.FALSE,
        allowed_dirs=[tmp_path],
        audit_log=None,
    )
    mcp = create_server(settings, discover_plugins=False)
    runtime = mcp._blender_runtime  # type: ignore[attr-defined]

    try:
        results = []
        for case in EVAL_SUITE:
            res = await run_eval_case(case, mcp, tmp_path)
            results.append(res)

        failures = [r for r in results if not r.passed]
        assert not failures, "Eval failures: " + ", ".join(f"{r.id}: {r.error}" for r in failures)
        assert len(results) == len(EVAL_SUITE)
    finally:
        await runtime.bridge.close()
        proc.stop()
