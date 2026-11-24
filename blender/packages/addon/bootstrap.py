# SPDX-License-Identifier: GPL-3.0-or-later
"""Headless / CLI bootstrap script for running the Blender MCP bridge.

Usage:
    blender --background --factory-startup --python bootstrap.py -- \
        --host 127.0.0.1 --port 9876 --token <secret>
"""

from __future__ import annotations

import argparse
import os
import signal
import sys
from pathlib import Path


def _parse_args(argv: list[str]) -> argparse.Namespace:
    script_args = argv[argv.index("--") + 1 :] if "--" in argv else []

    parser = argparse.ArgumentParser(description="Blender MCP Bridge Bootstrap")
    parser.add_argument("--host", default=os.environ.get("BLENDER_MCP_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("BLENDER_MCP_PORT", "9876")))
    parser.add_argument("--token", default=os.environ.get("BLENDER_MCP_TOKEN", ""))
    parser.add_argument("--session-file", default=os.environ.get("BLENDER_MCP_SESSION_FILE", ""))
    parser.add_argument(
        "--allow-python",
        action="store_true",
        default=os.environ.get("BLENDER_MCP_ALLOW_PYTHON", "false").strip().lower()
        in ("true", "1", "yes", "on", "confirm"),
    )
    return parser.parse_args(script_args)


def main() -> None:
    addon_root = str(Path(__file__).resolve().parent)
    if addon_root not in sys.path:
        sys.path.insert(0, addon_root)

    import bpy  # type: ignore[import-not-found]

    from blender_mcp_addon.dispatcher import Dispatcher
    from blender_mcp_addon.handlers import register_all_handlers
    from blender_mcp_addon.server import BridgeTCPServer

    args = _parse_args(sys.argv)

    dispatcher = Dispatcher()
    register_all_handlers(dispatcher)

    server = BridgeTCPServer(
        dispatcher=dispatcher,
        host=args.host,
        port=args.port,
        token=args.token or None,
        session_file=Path(args.session_file) if args.session_file else None,
        allow_python=args.allow_python,
    )

    def _handle_signal(_signum: int, _frame: object) -> None:
        dispatcher.request_stop()

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    server.start()
    print(
        f"[blender-mcp] Bridge listening on {server.host}:{server.port} "
        f"(background={bpy.app.background}, blender={bpy.app.version_string})",
        flush=True,
    )

    if bpy.app.background:
        try:
            dispatcher.run_headless_loop()
        finally:
            server.stop()
            print("[blender-mcp] Bridge stopped.", flush=True)
    else:
        dispatcher.start_gui_timer()


if __name__ == "__main__":
    main()
