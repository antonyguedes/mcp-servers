# SPDX-License-Identifier: MIT
"""Security policies: BLENDER_MCP_ALLOW_PYTHON guard, path allowlist, and JSONL audit log."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

from blender_mcp_protocol import BridgeError, BridgeErrorCode, PythonPolicy


class PathGuard:
    """Prevents path traversal outside configured allowlisted directories."""

    def __init__(self, allowed_dirs: list[Path] | None = None) -> None:
        self.allowed_dirs = [p.expanduser().resolve() for p in (allowed_dirs or [])]

    def validate(self, raw_path: str, *, must_exist: bool = False) -> Path:
        if not raw_path or not raw_path.strip():
            raise BridgeError(BridgeErrorCode.INVALID_PARAMS, "File path cannot be empty.")
        resolved = Path(raw_path).expanduser().resolve()
        if self.allowed_dirs:
            allowed = False
            for root in self.allowed_dirs:
                try:
                    resolved.relative_to(root)
                    allowed = True
                    break
                except ValueError:
                    continue
            if not allowed:
                raise BridgeError(
                    BridgeErrorCode.PATH_DENIED,
                    f"Access denied for path {str(resolved)!r}. "
                    "Path is outside BLENDER_MCP_ALLOWED_DIRS.",
                    details={"allowed_dirs": [str(d) for d in self.allowed_dirs]},
                )
        if must_exist and not resolved.exists():
            raise BridgeError(BridgeErrorCode.NOT_FOUND, f"File not found: {str(resolved)!r}")
        return resolved


class AuditLogger:
    """Append-only JSONL audit trail for mutating operations and Python executions."""

    def __init__(self, log_path: Path | None) -> None:
        self.log_path = log_path

    def record(
        self,
        *,
        tool: str,
        params: dict[str, Any],
        ok: bool,
        duration_ms: float,
        error: str | None = None,
    ) -> None:
        if self.log_path is None:
            return
        try:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            sanitized = self._sanitize(params)
            entry = {
                "ts": round(time.time(), 3),
                "tool": tool,
                "params": sanitized,
                "ok": ok,
                "duration_ms": round(duration_ms, 2),
                "error": error,
            }
            with self.log_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError:
            pass

    @staticmethod
    def _sanitize(params: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for k, v in params.items():
            if k == "code" and isinstance(v, str):
                digest = hashlib.sha256(v.encode("utf-8")).hexdigest()[:16]
                out["code_sha256"] = digest
                out["code_preview"] = v[:300]
            elif isinstance(v, str) and len(v) > 500:
                out[k] = v[:500] + "...<truncated>"
            else:
                out[k] = v
        return out


def check_python_policy(policy: PythonPolicy, *, confirmed: bool = False) -> None:
    """Enforce BLENDER_MCP_ALLOW_PYTHON before dispatching script execution."""
    if policy == PythonPolicy.FALSE:
        raise BridgeError(
            BridgeErrorCode.POLICY_DENIED,
            "Python execution is disabled (BLENDER_MCP_ALLOW_PYTHON=false). "
            "Set BLENDER_MCP_ALLOW_PYTHON=true or BLENDER_MCP_ALLOW_PYTHON=confirm to enable it.",
        )
    if policy == PythonPolicy.CONFIRM and not confirmed:
        raise BridgeError(
            BridgeErrorCode.CONFIRMATION_REQUIRED,
            "Python execution requires explicit confirmation (BLENDER_MCP_ALLOW_PYTHON=confirm). "
            "Approve via MCP elicitation or pass confirmed=true after user approval.",
        )
