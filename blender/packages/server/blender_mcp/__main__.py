# SPDX-License-Identifier: MIT
"""CLI entry point for blender-mcp (serve, launch, build-addon, install-addon, doctor)."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

from blender_mcp.app import create_server
from blender_mcp.bridge.client import BridgeClient
from blender_mcp.bridge.launcher import (
    build_addon_zips,
    find_blender_executable,
    get_addon_source_dir,
    get_blender_version,
    install_addon,
    launch_blender_headless,
)
from blender_mcp.config import ServerSettings
from blender_mcp.http_security import build_http_app, build_transport_security
from blender_mcp_protocol import DEFAULT_HOST, DEFAULT_PORT, PythonPolicy


def _cmd_serve(args: argparse.Namespace) -> int:
    settings = ServerSettings.from_env()
    if args.transport:
        settings.transport = args.transport
    if args.host:
        settings.http_host = args.host
    if args.port:
        settings.http_port = args.port
    if args.profile:
        settings.profile = args.profile

    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )

    mcp = create_server(settings)
    if settings.transport in ("http", "streamable-http"):
        if settings.http_bearer_token:
            import uvicorn

            app = build_http_app(mcp, settings)
            uvicorn.run(app, host=settings.http_host, port=settings.http_port)
        else:
            mcp.run(
                transport="streamable-http",
                host=settings.http_host,
                port=settings.http_port,
                transport_security=build_transport_security(settings),
            )
    else:
        mcp.run(transport="stdio")
    return 0


def _cmd_launch(args: argparse.Namespace) -> int:
    settings = ServerSettings.from_env()
    allow_py = args.allow_python or (settings.python_policy != PythonPolicy.FALSE)
    handle = launch_blender_headless(
        blender_bin=Path(args.blender) if args.blender else None,
        blend_file=Path(args.file) if args.file else None,
        host=args.host,
        port=args.port,
        token=args.token or settings.token or None,
        session_file=settings.session_file,
        allow_python=allow_py,
        factory_startup=not args.no_factory_startup,
    )
    print(
        json.dumps(
            {
                "status": "running",
                "pid": handle.process.pid,
                "host": handle.host,
                "port": handle.port,
                "session_file": str(handle.session_file),
                "allow_python": allow_py,
            },
            indent=2,
        ),
        flush=True,
    )
    try:
        handle.process.wait()
    except KeyboardInterrupt:
        handle.stop()
    return 0


def _cmd_build_addon(args: argparse.Namespace) -> int:
    out_dir = Path(args.out_dir).resolve()
    ext_zip, legacy_zip = build_addon_zips(out_dir)
    print(f"Built Blender 4.2+ Extension: {ext_zip}")
    print(f"Built Blender 3.6-4.1 Legacy Add-on: {legacy_zip}")
    return 0


def _cmd_install_addon(args: argparse.Namespace) -> int:
    info = install_addon(Path(args.blender) if args.blender else None)
    print(json.dumps(info, indent=2))
    return 0


async def _run_doctor(settings: ServerSettings) -> int:
    checks: dict[str, object] = {
        "python": sys.version.split()[0],
        "python_policy": settings.python_policy.value,
        "profile": settings.profile,
        "session_file": str(settings.session_file),
        "session_file_exists": settings.session_file.is_file(),
    }

    blender_bin = find_blender_executable(settings.blender_path)
    if blender_bin:
        ver = get_blender_version(blender_bin)
        checks["blender_executable"] = str(blender_bin)
        checks["blender_version"] = ".".join(map(str, ver)) if ver else "unknown"
    else:
        checks["blender_executable"] = None

    try:
        checks["addon_source_dir"] = str(get_addon_source_dir())
    except FileNotFoundError:
        checks["addon_source_dir"] = None

    host, port, token = settings.resolve_bridge_endpoint()
    checks["bridge_target"] = f"{host}:{port}"
    checks["bridge_token_present"] = bool(token)

    client = BridgeClient(settings)
    try:
        hs = await client.connect()
        checks["bridge_connected"] = True
        checks["bridge_handshake"] = hs.to_dict()
        exit_code = 0
    except Exception as exc:
        checks["bridge_connected"] = False
        checks["bridge_error"] = str(exc)
        exit_code = 1 if blender_bin is None else 0
    finally:
        await client.close()

    print(json.dumps(checks, indent=2))
    return exit_code


def _cmd_doctor(_args: argparse.Namespace) -> int:
    settings = ServerSettings.from_env()
    return asyncio.run(_run_doctor(settings))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="blender-mcp",
        description="Production-grade MCP server for Blender 3D (3.6 LTS - 5.3+)",
    )
    sub = parser.add_subparsers(dest="command")

    p_serve = sub.add_parser("serve", help="Run the MCP server (default)")
    p_serve.add_argument("--transport", choices=["stdio", "http", "streamable-http"], default=None)
    p_serve.add_argument("--host", default=None, help="Bind host for HTTP transport")
    p_serve.add_argument("--port", type=int, default=None, help="Bind port for HTTP transport")
    p_serve.add_argument(
        "--profile",
        choices=["minimal", "modeling", "animation", "integrations", "full"],
        default=None,
    )

    p_launch = sub.add_parser("launch", help="Launch headless Blender with the MCP bridge active")
    p_launch.add_argument("--blender", default=None, help="Path to Blender executable")
    p_launch.add_argument("--file", default=None, help="Optional .blend file to open")
    p_launch.add_argument("--host", default=DEFAULT_HOST)
    p_launch.add_argument("--port", type=int, default=DEFAULT_PORT)
    p_launch.add_argument("--token", default=None)
    p_launch.add_argument("--allow-python", action="store_true")
    p_launch.add_argument("--no-factory-startup", action="store_true")

    p_build = sub.add_parser("build-addon", help="Build Blender 4.2+ Extension and 3.6-4.1 Legacy Add-on zips")
    p_build.add_argument("--out-dir", default="dist/addon")

    p_install = sub.add_parser("install-addon", help="Install the MCP bridge add-on into Blender")
    p_install.add_argument("--blender", default=None)

    sub.add_parser("doctor", help="Diagnose Blender installation, add-on, and bridge connectivity")
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    # Allow running `blender-mcp` or `blender-mcp --transport http` directly as `serve`
    raw = list(sys.argv[1:] if argv is None else argv)
    known_cmds = {"serve", "launch", "build-addon", "install-addon", "doctor", "-h", "--help"}
    if not raw or raw[0] not in known_cmds:
        raw = ["serve", *raw]

    args = parser.parse_args(raw)
    if args.command == "launch":
        code = _cmd_launch(args)
    elif args.command == "build-addon":
        code = _cmd_build_addon(args)
    elif args.command == "install-addon":
        code = _cmd_install_addon(args)
    elif args.command == "doctor":
        code = _cmd_doctor(args)
    else:
        code = _cmd_serve(args)
    raise SystemExit(code)


if __name__ == "__main__":
    main()
