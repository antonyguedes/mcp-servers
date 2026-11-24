# SPDX-License-Identifier: MIT
"""Secure Streamable HTTP configuration (DNS rebinding protection + optional Bearer auth)."""

from __future__ import annotations

import hmac
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from blender_mcp.config import ServerSettings


def build_transport_security(settings: ServerSettings) -> TransportSecuritySettings:
    """Build DNS rebinding / Origin validation settings for Streamable HTTP transport."""
    port = settings.http_port
    allowed_hosts = list(settings.http_allowed_hosts)
    if not allowed_hosts:
        allowed_hosts = [
            f"127.0.0.1:{port}",
            f"localhost:{port}",
            f"[::1]:{port}",
            "127.0.0.1",
            "localhost",
        ]
        if settings.http_host not in ("127.0.0.1", "localhost", "::1"):
            allowed_hosts.append(f"{settings.http_host}:{port}")

    allowed_origins = list(settings.http_allowed_origins)
    if not allowed_origins:
        allowed_origins = [
            f"http://127.0.0.1:{port}",
            f"http://localhost:{port}",
            "http://127.0.0.1",
            "http://localhost",
        ]

    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=allowed_hosts,
        allowed_origins=allowed_origins,
    )


class BearerAuthMiddleware(BaseHTTPMiddleware):
    """Constant-time Bearer token check when BLENDER_MCP_HTTP_BEARER_TOKEN is configured."""

    def __init__(self, app: Any, token: str) -> None:
        super().__init__(app)
        self._token = token

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        auth = request.headers.get("authorization", "")
        prefix = "Bearer "
        provided = auth[len(prefix) :].strip() if auth.startswith(prefix) else ""
        if not provided or not hmac.compare_digest(provided, self._token):
            return JSONResponse(
                {"error": "Unauthorized: missing or invalid Bearer token"},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
        return await call_next(request)


def build_http_app(mcp: MCPServer, settings: ServerSettings) -> Any:
    """Create the hardened Starlette ASGI app for Streamable HTTP."""
    security = build_transport_security(settings)
    app = mcp.streamable_http_app(transport_security=security)
    if settings.http_bearer_token:
        app.add_middleware(BearerAuthMiddleware, token=settings.http_bearer_token)
    return app
