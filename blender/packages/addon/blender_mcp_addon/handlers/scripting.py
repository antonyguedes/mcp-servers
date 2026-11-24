# SPDX-License-Identifier: GPL-3.0-or-later
"""Controlled Python execution handlers (defense-in-depth with BLENDER_MCP_ALLOW_PYTHON)."""

from __future__ import annotations

import contextlib
import io
import json
import math
import traceback
from pathlib import Path
from typing import Any

import bmesh  # type: ignore[import-not-found]
import bpy  # type: ignore[import-not-found]
import mathutils  # type: ignore[import-not-found]

from ..dispatcher import Dispatcher, ExecutionContext
from ..wire import AddonError, BridgeErrorCode


def _safe_serialize(val: Any) -> Any:
    if val is None or isinstance(val, (bool, int, float, str)):
        return val
    try:
        json.dumps(val)
        return val
    except TypeError:
        return repr(val)


def _run_code(code: str, filename: str, ctx: ExecutionContext) -> dict[str, Any]:
    if not ctx.allow_python:
        raise AddonError(
            BridgeErrorCode.POLICY_DENIED,
            "Python execution is disabled in the Blender add-on bridge. "
            "Enable BLENDER_MCP_ALLOW_PYTHON=true (or confirm) and allow Python in the bridge.",
        )

    stdout_buf = io.StringIO()
    stderr_buf = io.StringIO()
    namespace: dict[str, Any] = {
        "__name__": "__blender_mcp__",
        "bpy": bpy,
        "bmesh": bmesh,
        "mathutils": mathutils,
        "math": math,
    }

    try:
        compiled = compile(code, filename, "exec")
        with contextlib.redirect_stdout(stdout_buf), contextlib.redirect_stderr(stderr_buf):
            exec(compiled, namespace, namespace)
    except Exception as exc:
        tb = traceback.format_exc()
        raise AddonError(
            BridgeErrorCode.PYTHON_EXEC_ERROR,
            f"Python execution error ({type(exc).__name__}): {exc}",
            details={
                "stdout": stdout_buf.getvalue()[-4000:],
                "stderr": stderr_buf.getvalue()[-4000:],
                "traceback": tb[-3000:],
            },
        ) from exc

    return {
        "stdout": stdout_buf.getvalue()[-8000:],
        "stderr": stderr_buf.getvalue()[-8000:],
        "result": _safe_serialize(namespace.get("result")),
    }


def execute_python(params: dict[str, Any], ctx: ExecutionContext) -> dict[str, Any]:
    code = params.get("code")
    if not isinstance(code, str) or not code.strip():
        raise AddonError(BridgeErrorCode.INVALID_PARAMS, "'code' must be a non-empty Python string.")
    return _run_code(code, "<mcp_execute_python>", ctx)


def run_script_file(params: dict[str, Any], ctx: ExecutionContext) -> dict[str, Any]:
    filepath = str(params.get("filepath", "")).strip()
    if not filepath:
        raise AddonError(BridgeErrorCode.INVALID_PARAMS, "'filepath' is required.")
    path = Path(filepath)
    if not path.is_file():
        raise AddonError(BridgeErrorCode.NOT_FOUND, f"Script file not found: {filepath!r}")
    code = path.read_text(encoding="utf-8")
    return _run_code(code, str(path), ctx)


def register(dispatcher: Dispatcher) -> None:
    dispatcher.register("scripting.execute_python", execute_python)
    dispatcher.register("scripting.run_script_file", run_script_file)
