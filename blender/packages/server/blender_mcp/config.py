# SPDX-License-Identifier: MIT
"""Environment-driven configuration for blender-mcp."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from blender_mcp_protocol import DEFAULT_HOST, DEFAULT_PORT, PythonPolicy, parse_python_policy


def default_session_file() -> Path:
    cfg = Path(os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config"))
    return cfg / "blender-mcp" / "session.json"


def default_audit_log() -> Path:
    state = Path(os.environ.get("XDG_STATE_HOME") or (Path.home() / ".local" / "state"))
    return state / "blender-mcp" / "audit.jsonl"


def default_cache_dir() -> Path:
    cache = Path(os.environ.get("XDG_CACHE_HOME") or (Path.home() / ".cache"))
    return cache / "blender-mcp" / "assets"


def default_sessions_dir() -> Path:
    cfg = Path(os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config"))
    return cfg / "blender-mcp" / "sessions"


def _parse_csv(raw: str | None) -> list[str]:
    if not raw or not raw.strip():
        return []
    return [part.strip() for part in raw.split(",") if part.strip()]


def _parse_allowed_dirs(raw: str | None) -> list[Path]:
    if not raw or not raw.strip():
        return []
    sep = ";" if os.name == "nt" else ":"
    dirs: list[Path] = []
    for part in raw.split(sep):
        p = part.strip()
        if p:
            dirs.append(Path(p).expanduser().resolve())
    return dirs


@dataclass
class ServerSettings:
    """Runtime settings populated from BLENDER_MCP_* environment variables."""

    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    token: str = ""
    session_file: Path = field(default_factory=default_session_file)
    sessions_dir: Path = field(default_factory=default_sessions_dir)
    host_explicit: bool = False
    port_explicit: bool = False

    transport: str = "stdio"
    http_host: str = "127.0.0.1"
    http_port: int = 8765
    http_allowed_hosts: list[str] = field(default_factory=list)
    http_allowed_origins: list[str] = field(default_factory=list)
    http_bearer_token: str = ""

    profile: str = "modeling"
    python_policy: PythonPolicy = PythonPolicy.FALSE
    python_timeout: float = 30.0
    rpc_timeout: float = 120.0

    allowed_dirs: list[Path] = field(default_factory=list)
    cache_dir: Path = field(default_factory=default_cache_dir)
    audit_log: Path | None = field(default_factory=default_audit_log)
    log_level: str = "INFO"
    blender_path: str | None = None

    # External integration credentials / self-hosted endpoints
    sketchfab_api_key: str = ""
    hyper3d_api_key: str = ""
    hyper3d_base_url: str = "https://hyperhuman.deemos.com/api/v2"
    hunyuan3d_api_key: str = ""
    hunyuan3d_base_url: str = ""
    tripo_api_key: str = ""
    meshy_api_key: str = ""
    trellis_base_url: str = ""

    @classmethod
    def from_env(cls, environ: dict[str, str] | None = None) -> ServerSettings:
        env = environ if environ is not None else dict(os.environ)

        host_raw = env.get("BLENDER_MCP_HOST")
        port_raw = env.get("BLENDER_MCP_PORT")
        session_raw = env.get("BLENDER_MCP_SESSION_FILE")
        audit_raw = env.get("BLENDER_MCP_AUDIT_LOG")

        if audit_raw is not None and audit_raw.strip().lower() in ("", "none", "off", "false"):
            audit_path: Path | None = None
        elif audit_raw:
            audit_path = Path(audit_raw).expanduser()
        else:
            audit_path = default_audit_log()

        session_path = Path(session_raw).expanduser() if session_raw else default_session_file()
        sessions_dir_raw = env.get("BLENDER_MCP_SESSIONS_DIR")
        sessions_dir = (
            Path(sessions_dir_raw).expanduser()
            if sessions_dir_raw
            else (session_path.parent / "sessions" if session_raw else default_sessions_dir())
        )

        return cls(
            host=host_raw.strip() if host_raw else DEFAULT_HOST,
            port=int(port_raw) if port_raw else DEFAULT_PORT,
            token=env.get("BLENDER_MCP_TOKEN", "").strip(),
            session_file=session_path,
            sessions_dir=sessions_dir,
            host_explicit=bool(host_raw),
            port_explicit=bool(port_raw),
            transport=env.get("BLENDER_MCP_TRANSPORT", "stdio").strip().lower(),
            http_host=env.get("BLENDER_MCP_HTTP_HOST", "127.0.0.1").strip(),
            http_port=int(env.get("BLENDER_MCP_HTTP_PORT", "8765")),
            http_allowed_hosts=_parse_csv(env.get("BLENDER_MCP_HTTP_ALLOWED_HOSTS")),
            http_allowed_origins=_parse_csv(env.get("BLENDER_MCP_HTTP_ALLOWED_ORIGINS")),
            http_bearer_token=env.get("BLENDER_MCP_HTTP_BEARER_TOKEN", "").strip(),
            profile=env.get("BLENDER_MCP_PROFILE", "modeling").strip().lower(),
            python_policy=parse_python_policy(env.get("BLENDER_MCP_ALLOW_PYTHON")),
            python_timeout=float(env.get("BLENDER_MCP_PYTHON_TIMEOUT", "30")),
            rpc_timeout=float(env.get("BLENDER_MCP_RPC_TIMEOUT", "120")),
            allowed_dirs=_parse_allowed_dirs(env.get("BLENDER_MCP_ALLOWED_DIRS")),
            cache_dir=Path(env["BLENDER_MCP_CACHE_DIR"]).expanduser()
            if env.get("BLENDER_MCP_CACHE_DIR")
            else default_cache_dir(),
            audit_log=audit_path,
            log_level=env.get("BLENDER_MCP_LOG_LEVEL", "INFO").strip().upper(),
            blender_path=env.get("BLENDER_MCP_BLENDER_PATH") or None,
            sketchfab_api_key=env.get("SKETCHFAB_API_KEY", "").strip(),
            hyper3d_api_key=env.get("HYPER3D_API_KEY", "").strip(),
            hyper3d_base_url=env.get("HYPER3D_BASE_URL", "https://hyperhuman.deemos.com/api/v2").strip().rstrip("/"),
            hunyuan3d_api_key=env.get("HUNYUAN3D_API_KEY", "").strip(),
            hunyuan3d_base_url=env.get("HUNYUAN3D_BASE_URL", "").strip().rstrip("/"),
            tripo_api_key=env.get("TRIPO_API_KEY", "").strip(),
            meshy_api_key=env.get("MESHY_API_KEY", "").strip(),
            trellis_base_url=env.get("TRELLIS_BASE_URL", "").strip().rstrip("/"),
        )

    def resolve_bridge_endpoint(self) -> tuple[str, int, str]:
        """Resolve (host, port, token) from explicit env vars or session discovery file."""
        host = self.host
        port = self.port
        token = self.token

        session_data = self.read_session_file()
        if session_data:
            if not self.host_explicit and isinstance(session_data.get("host"), str):
                host = session_data["host"]
            if not self.port_explicit and isinstance(session_data.get("port"), int):
                port = session_data["port"]
            if not token and isinstance(session_data.get("token"), str):
                token = session_data["token"]

        return host, port, token

    def read_session_file(self) -> dict[str, Any] | None:
        try:
            if self.session_file.is_file():
                data = json.loads(self.session_file.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return data
        except Exception:
            return None
        return None
