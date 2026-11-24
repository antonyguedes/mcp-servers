# SPDX-License-Identifier: MIT
"""Controlled Python scripting MCP tools governed by BLENDER_MCP_ALLOW_PYTHON."""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import BaseModel

from blender_mcp.security import check_python_policy
from blender_mcp.tools import ToolRuntime
from blender_mcp_protocol import BridgeError, PythonPolicy

_SCRIPT_ANNOTATIONS = ToolAnnotations(
    read_only_hint=False,
    destructive_hint=True,
    idempotent_hint=False,
)


class _ConfirmPythonExec(BaseModel):
    approve: bool = False


async def _confirm_if_needed(
    rt: ToolRuntime,
    ctx: Context | None,
    summary: str,
    confirmed: bool,
) -> bool:
    if rt.settings.python_policy != PythonPolicy.CONFIRM:
        return True
    if confirmed:
        return True
    if ctx is not None and hasattr(ctx, "elicit"):
        try:
            elicit_res = await ctx.elicit(
                message=f"Allow executing Python in Blender?\n{summary}",
                schema=_ConfirmPythonExec,
            )
            action = getattr(elicit_res, "action", None)
            data = getattr(elicit_res, "data", None)
            if action == "accept" and data is not None and bool(getattr(data, "approve", False)):
                return True
        except Exception:
            pass
    return False


def register(mcp: MCPServer, rt: ToolRuntime) -> bool:
    """Register scripting tools ONLY if BLENDER_MCP_ALLOW_PYTHON is not `false`."""
    if rt.settings.python_policy == PythonPolicy.FALSE:
        return False

    @mcp.tool(annotations=_SCRIPT_ANNOTATIONS)
    async def execute_python(
        code: str,
        confirmed: bool = False,
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        """Execute arbitrary Python code inside Blender's main thread.

        Available globals: `bpy`, `bmesh`, `mathutils`, `math`.
        Assign to `result` to return a JSON-serializable value alongside `stdout`/`stderr` and scene `diff`.
        Only exposed when `BLENDER_MCP_ALLOW_PYTHON` is `true` or `confirm`.
        """
        is_confirmed = await _confirm_if_needed(rt, ctx, code[:300], confirmed)
        try:
            check_python_policy(rt.settings.python_policy, confirmed=is_confirmed)
        except BridgeError as err:
            raise ToolError(err.format_for_agent()) from err

        return await rt.invoke(
            "scripting.execute_python",
            {"code": code},
            timeout=rt.settings.python_timeout,
            audit=True,
        )

    @mcp.tool(annotations=_SCRIPT_ANNOTATIONS)
    async def run_script_file(
        filepath: str,
        confirmed: bool = False,
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        """Run a local Python script file inside Blender (subject to path allowlist & BLENDER_MCP_ALLOW_PYTHON)."""
        try:
            resolved = rt.path_guard.validate(filepath, must_exist=True)
            is_confirmed = await _confirm_if_needed(rt, ctx, f"Run script: {resolved}", confirmed)
            check_python_policy(rt.settings.python_policy, confirmed=is_confirmed)
        except BridgeError as err:
            raise ToolError(err.format_for_agent()) from err

        return await rt.invoke(
            "scripting.run_script_file",
            {"filepath": str(resolved)},
            timeout=rt.settings.python_timeout,
            audit=True,
        )

    return True
