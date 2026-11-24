# SPDX-License-Identifier: MIT
"""Deterministic + visual evaluation harness for benchmarking AI agents on blender-mcp."""

from __future__ import annotations

import base64
import io
import json
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer
from PIL import Image, ImageStat


def extract_tool_json(call_result: object) -> dict[str, Any]:
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


def assert_image_non_blank(image_b64: str, *, min_stddev: float = 1.5) -> dict[str, Any]:
    """Verify a rendered image contains actual visual structure (not solid black/flat)."""
    img = Image.open(io.BytesIO(base64.b64decode(image_b64))).convert("RGB")
    stat = ImageStat.Stat(img)
    avg_std = sum(stat.stddev) / 3.0
    if avg_std < min_stddev:
        raise AssertionError(f"Rendered image appears blank/flat (avg RGB stddev={avg_std:.2f} < {min_stddev})")
    return {"size": list(img.size), "avg_stddev": round(avg_std, 2)}


EvalRunnerFn = Callable[[MCPServer, Path], Awaitable[dict[str, Any]]]


@dataclass
class EvalCase:
    id: str
    category: str
    title: str
    prompt: str
    execute_and_verify: EvalRunnerFn


@dataclass
class EvalResult:
    id: str
    category: str
    title: str
    passed: bool
    duration_sec: float
    metrics: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


async def run_eval_case(case: EvalCase, mcp: MCPServer, work_dir: Path) -> EvalResult:
    """Execute a single eval case cleanly with checkpoint isolation."""
    ckpt_name = f"eval_base_{case.id}"
    extract_tool_json(await mcp.call_tool("create_checkpoint", {"name": ckpt_name}))
    t0 = time.perf_counter()
    try:
        metrics = await case.execute_and_verify(mcp, work_dir)
        return EvalResult(
            id=case.id,
            category=case.category,
            title=case.title,
            passed=True,
            duration_sec=round(time.perf_counter() - t0, 3),
            metrics=metrics,
        )
    except Exception as exc:
        return EvalResult(
            id=case.id,
            category=case.category,
            title=case.title,
            passed=False,
            duration_sec=round(time.perf_counter() - t0, 3),
            error=f"{type(exc).__name__}: {exc}",
        )
    finally:
        await mcp.call_tool("restore_checkpoint", {"name": ckpt_name})
        await mcp.call_tool("delete_checkpoint", {"name": ckpt_name})
