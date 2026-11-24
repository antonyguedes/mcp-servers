# SPDX-License-Identifier: MIT
"""Structured JSON-RPC error codes and exception types."""

from __future__ import annotations

from enum import IntEnum
from typing import Any


class BridgeErrorCode(IntEnum):
    """Standard JSON-RPC 2.0 errors plus blender-mcp domain error codes."""

    # JSON-RPC 2.0 standard errors
    PARSE_ERROR = -32700
    INVALID_REQUEST = -32600
    METHOD_NOT_FOUND = -32601
    INVALID_PARAMS = -32602
    INTERNAL_ERROR = -32603

    # blender-mcp bridge errors (-32000 .. -32099)
    UNAUTHORIZED = -32001
    POLICY_DENIED = -32002
    NOT_FOUND = -32003
    ALREADY_EXISTS = -32004
    INVALID_STATE = -32005
    UNSUPPORTED_VERSION = -32006
    PATH_DENIED = -32007
    TIMEOUT = -32008
    CANCELLED = -32009
    BLENDER_ERROR = -32010
    PYTHON_EXEC_ERROR = -32011
    CONFIRMATION_REQUIRED = -32012


class BridgeError(Exception):
    """Structured error returned over the bridge or raised locally."""

    def __init__(
        self,
        code: BridgeErrorCode | int,
        message: str,
        *,
        details: dict[str, Any] | None = None,
        suggestions: list[str] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = int(code)
        self.message = message
        self.details = details or {}
        self.suggestions = suggestions or []

    def to_rpc_error(self) -> dict[str, Any]:
        data: dict[str, Any] = {}
        if self.details:
            data["details"] = self.details
        if self.suggestions:
            data["suggestions"] = self.suggestions
        err: dict[str, Any] = {"code": self.code, "message": self.message}
        if data:
            err["data"] = data
        return err

    @classmethod
    def from_rpc_error(cls, payload: dict[str, Any]) -> BridgeError:
        code = int(payload.get("code", BridgeErrorCode.INTERNAL_ERROR))
        message = str(payload.get("message", "Unknown bridge error"))
        data = payload.get("data") or {}
        details = data.get("details") if isinstance(data, dict) else None
        suggestions = data.get("suggestions") if isinstance(data, dict) else None
        return cls(
            code=code,
            message=message,
            details=details if isinstance(details, dict) else {},
            suggestions=suggestions if isinstance(suggestions, list) else [],
        )

    def format_for_agent(self) -> str:
        """Concise, actionable error message for AI agents."""
        parts = [f"[{self.code}] {self.message}"]
        if self.suggestions:
            parts.append("Did you mean: " + ", ".join(repr(s) for s in self.suggestions[:5]) + "?")
        return " ".join(parts)
