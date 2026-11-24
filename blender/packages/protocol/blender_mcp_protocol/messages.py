# SPDX-License-Identifier: MIT
"""Core protocol message dataclasses and enums."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any

from blender_mcp_protocol.constants import JSONRPC_VERSION, PROTOCOL_VERSION
from blender_mcp_protocol.errors import BridgeError


class PythonPolicy(str, Enum):
    """Policy governing arbitrary Python script execution in Blender."""

    FALSE = "false"
    CONFIRM = "confirm"
    TRUE = "true"


def parse_python_policy(raw: str | bool | None) -> PythonPolicy:
    """Parse BLENDER_MCP_ALLOW_PYTHON values ergonomically."""
    if raw is None:
        return PythonPolicy.FALSE
    if isinstance(raw, bool):
        return PythonPolicy.TRUE if raw else PythonPolicy.FALSE
    normalized = str(raw).strip().lower()
    if normalized in ("", "false", "0", "no", "off", "disabled"):
        return PythonPolicy.FALSE
    if normalized in ("confirm", "ask", "prompt"):
        return PythonPolicy.CONFIRM
    if normalized in ("true", "1", "yes", "on", "allow", "enabled"):
        return PythonPolicy.TRUE
    raise ValueError(
        f"Invalid BLENDER_MCP_ALLOW_PYTHON value {raw!r}. "
        "Expected one of: false, confirm, true."
    )


@dataclass(slots=True)
class RpcRequest:
    method: str
    params: dict[str, Any] = field(default_factory=dict)
    id: str | int | None = None
    token: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "jsonrpc": JSONRPC_VERSION,
            "method": self.method,
            "params": self.params,
        }
        if self.id is not None:
            payload["id"] = self.id
        if self.token is not None:
            payload["token"] = self.token
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RpcRequest:
        method = data.get("method")
        if not isinstance(method, str) or not method:
            raise ValueError("Missing or invalid 'method'")
        params = data.get("params")
        if params is None:
            params = {}
        if not isinstance(params, dict):
            raise ValueError("'params' must be a dict")
        return cls(
            method=method,
            params=params,
            id=data.get("id"),
            token=data.get("token"),
        )


@dataclass(slots=True)
class RpcResponse:
    id: str | int | None
    result: Any = None
    error: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"jsonrpc": JSONRPC_VERSION, "id": self.id}
        if self.error is not None:
            payload["error"] = self.error
        else:
            payload["result"] = self.result
        return payload

    @classmethod
    def ok(cls, req_id: str | int | None, result: Any) -> RpcResponse:
        return cls(id=req_id, result=result)

    @classmethod
    def fail(cls, req_id: str | int | None, err: BridgeError) -> RpcResponse:
        return cls(id=req_id, error=err.to_rpc_error())

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RpcResponse:
        return cls(
            id=data.get("id"),
            result=data.get("result"),
            error=data.get("error"),
        )


@dataclass(slots=True)
class RpcNotification:
    method: str
    params: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "jsonrpc": JSONRPC_VERSION,
            "method": self.method,
            "params": self.params,
        }


@dataclass(slots=True)
class BlenderCapabilities:
    """Feature-detection flags advertised by the connected Blender instance."""

    render_engines: list[str] = field(default_factory=list)
    eevee_engine_id: str = "BLENDER_EEVEE"
    has_node_tree_interface: bool = True
    has_slotted_actions: bool = False
    has_grease_pencil_v3: bool = False
    has_use_auto_smooth: bool = False
    has_material_use_nodes: bool = True
    is_background: bool = False
    addon_allows_python: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BlenderCapabilities:
        return cls(
            render_engines=list(data.get("render_engines", [])),
            eevee_engine_id=str(data.get("eevee_engine_id", "BLENDER_EEVEE")),
            has_node_tree_interface=bool(data.get("has_node_tree_interface", True)),
            has_slotted_actions=bool(data.get("has_slotted_actions", False)),
            has_grease_pencil_v3=bool(data.get("has_grease_pencil_v3", False)),
            has_use_auto_smooth=bool(data.get("has_use_auto_smooth", False)),
            has_material_use_nodes=bool(data.get("has_material_use_nodes", True)),
            is_background=bool(data.get("is_background", False)),
            addon_allows_python=bool(data.get("addon_allows_python", True)),
        )


@dataclass(slots=True)
class HandshakeResponse:
    protocol_version: str = PROTOCOL_VERSION
    addon_version: str = "1.0.0"
    blender_version: list[int] = field(default_factory=list)
    blender_version_string: str = ""
    python_version: str = ""
    filepath: str = ""
    instance_id: str = ""
    capabilities: BlenderCapabilities = field(default_factory=BlenderCapabilities)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["capabilities"] = self.capabilities.to_dict()
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HandshakeResponse:
        caps_raw = data.get("capabilities")
        caps = (
            BlenderCapabilities.from_dict(caps_raw)
            if isinstance(caps_raw, dict)
            else BlenderCapabilities()
        )
        return cls(
            protocol_version=str(data.get("protocol_version", PROTOCOL_VERSION)),
            addon_version=str(data.get("addon_version", "0.1.0")),
            blender_version=[int(x) for x in data.get("blender_version", [])],
            blender_version_string=str(data.get("blender_version_string", "")),
            python_version=str(data.get("python_version", "")),
            filepath=str(data.get("filepath", "")),
            instance_id=str(data.get("instance_id", "")),
            capabilities=caps,
        )


@dataclass(slots=True)
class SceneDiff:
    """Compact summary of scene changes produced by a mutating tool call."""

    created: list[str] = field(default_factory=list)
    modified: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    materials_created: list[str] = field(default_factory=list)
    collections_created: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def is_empty(self) -> bool:
        return not (
            self.created
            or self.modified
            or self.deleted
            or self.materials_created
            or self.collections_created
        )
