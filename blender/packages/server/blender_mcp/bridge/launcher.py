# SPDX-License-Identifier: MIT
"""Blender executable discovery, headless launcher, dual packaging, and installer."""

from __future__ import annotations

import os
import re
import secrets
import shutil
import socket
import subprocess
import tempfile
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path

from blender_mcp_protocol import DEFAULT_HOST, RpcRequest, read_frame_sync, write_frame_sync

_LEGACY_BL_INFO = '''bl_info = {
    "name": "Blender MCP Bridge",
    "author": "Antony Guedes",
    "version": (1, 0, 0),
    "blender": (3, 6, 0),
    "location": "View3D > Sidebar > MCP",
    "description": "Local authenticated JSON-RPC bridge for AI agents via MCP",
    "category": "System",
}
'''


def find_blender_executable(preferred: str | None = None) -> Path | None:
    """Locate a Blender executable on PATH or standard install locations."""
    candidates: list[str] = []
    if preferred:
        candidates.append(preferred)
    env_bin = os.environ.get("BLENDER_MCP_BLENDER_PATH")
    if env_bin:
        candidates.append(env_bin)
    on_path = shutil.which("blender")
    if on_path:
        candidates.append(on_path)

    # Common OS paths
    candidates.extend(
        [
            str(Path.home() / ".local" / "bin" / "blender"),
            "/usr/bin/blender",
            "/usr/local/bin/blender",
            "/snap/bin/blender",
            "/Applications/Blender.app/Contents/MacOS/Blender",
        ]
    )

    for raw in candidates:
        p = Path(raw).expanduser()
        if p.is_file() and os.access(p, os.X_OK):
            return p
    return None


def get_blender_version(blender_bin: Path) -> tuple[int, int, int] | None:
    """Query `blender --version` and parse (major, minor, patch)."""
    try:
        out = subprocess.check_output(
            [str(blender_bin), "--version"],
            stderr=subprocess.STDOUT,
            text=True,
            timeout=15,
        )
    except Exception:
        return None
    m = re.search(r"Blender\s+(\d+)\.(\d+)\.(\d+)", out)
    if not m:
        return None
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)))


def get_addon_source_dir() -> Path:
    """Locate the Blender add-on source directory (repo checkout or bundled wheel)."""
    here = Path(__file__).resolve()
    # 1. Editable / source checkout: packages/server/blender_mcp/bridge/launcher.py -> packages/addon
    for parent in here.parents:
        candidate = parent / "packages" / "addon"
        if (candidate / "bootstrap.py").is_file():
            return candidate
    # 2. Installed wheel / `uvx`: blender_mcp/_bundled_addon
    bundled = here.parent.parent / "_bundled_addon"
    if (bundled / "bootstrap.py").is_file():
        return bundled
    raise FileNotFoundError("Could not locate Blender add-on directory containing bootstrap.py")


def _find_free_port(host: str = DEFAULT_HOST) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((host, 0))
        return int(s.getsockname()[1])


@dataclass
class HeadlessBlenderProcess:
    """Handle for a managed headless Blender instance running the MCP bridge."""

    process: subprocess.Popen[str]
    host: str
    port: int
    token: str
    session_file: Path

    def stop(self, timeout: float = 5.0) -> None:
        if self.process.poll() is None:
            # Ask bridge to stop cleanly first
            try:
                with socket.create_connection((self.host, self.port), timeout=1.5) as sock:
                    req = RpcRequest(method="system.shutdown", id=1, token=self.token)
                    write_frame_sync(sock, req.to_dict())
                    read_frame_sync(sock)
            except Exception:
                pass
            try:
                self.process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                self.process.terminate()
                try:
                    self.process.wait(timeout=3.0)
                except subprocess.TimeoutExpired:
                    self.process.kill()
        self.session_file.unlink(missing_ok=True)


def launch_blender_headless(
    *,
    blender_bin: Path | None = None,
    blend_file: Path | None = None,
    host: str = DEFAULT_HOST,
    port: int = 0,
    token: str | None = None,
    session_file: Path | None = None,
    allow_python: bool = False,
    factory_startup: bool = True,
    startup_timeout: float = 30.0,
) -> HeadlessBlenderProcess:
    """Spawn `blender --background` running the MCP bridge and wait until ready."""
    exe = blender_bin or find_blender_executable()
    if exe is None:
        raise FileNotFoundError("Blender executable not found. Set BLENDER_MCP_BLENDER_PATH or install Blender.")

    addon_dir = get_addon_source_dir()
    bootstrap = addon_dir / "bootstrap.py"
    actual_port = port if port > 0 else _find_free_port(host)
    actual_token = token or secrets.token_urlsafe(32)
    actual_session = session_file or Path(tempfile.gettempdir()) / f"blender_mcp_session_{actual_port}.json"

    cmd: list[str] = [str(exe), "--background"]
    if factory_startup and blend_file is None:
        cmd.append("--factory-startup")
    if blend_file is not None:
        cmd.append(str(blend_file))
    cmd.extend(
        [
            "--python",
            str(bootstrap),
            "--",
            "--host",
            host,
            "--port",
            str(actual_port),
            "--session-file",
            str(actual_session),
        ]
    )
    if allow_python:
        cmd.append("--allow-python")

    proc_env = os.environ.copy()
    proc_env["BLENDER_MCP_TOKEN"] = actual_token

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=proc_env,
    )

    deadline = time.monotonic() + startup_timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            out, err = proc.communicate(timeout=2)
            raise RuntimeError(
                f"Blender exited early (code {proc.returncode}).\nSTDOUT:\n{out[-1500:]}\nSTDERR:\n{err[-1500:]}"
            )
        try:
            with socket.create_connection((host, actual_port), timeout=0.5) as sock:
                req = RpcRequest(method="system.ping", id=1, token=actual_token)
                write_frame_sync(sock, req.to_dict())
                resp = read_frame_sync(sock)
                if resp and resp.get("result", {}).get("pong"):
                    return HeadlessBlenderProcess(
                        process=proc,
                        host=host,
                        port=actual_port,
                        token=actual_token,
                        session_file=actual_session,
                    )
        except OSError:
            time.sleep(0.15)

    proc.terminate()
    raise TimeoutError(f"Blender MCP bridge did not become ready within {startup_timeout}s.")


def build_addon_zips(output_dir: Path) -> tuple[Path, Path]:
    """Build both Blender 4.2+ Extension zip and Blender 3.6-4.1 legacy Add-on zip."""
    addon_dir = get_addon_source_dir()
    pkg_dir = addon_dir / "blender_mcp_addon"
    output_dir.mkdir(parents=True, exist_ok=True)

    ext_zip = output_dir / "blender_mcp_bridge-ext-4.2+.zip"
    legacy_zip = output_dir / "blender_mcp_bridge-legacy-3.6-4.1.zip"

    # 1. Blender 4.2+ Extension (manifest + __init__.py at zip root, relative imports)
    with zipfile.ZipFile(ext_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(addon_dir / "blender_manifest.toml", "blender_manifest.toml")
        zf.write(addon_dir / "LICENSE", "LICENSE")
        for path in sorted(pkg_dir.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            rel = path.relative_to(pkg_dir)
            zf.write(path, rel.as_posix())

    # 2. Blender 3.6 - 4.1 Legacy Add-on (injects bl_info into __init__.py)
    with zipfile.ZipFile(legacy_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(addon_dir / "LICENSE", "blender_mcp_addon/LICENSE")
        for path in sorted(pkg_dir.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            rel = path.relative_to(pkg_dir)
            text = path.read_text(encoding="utf-8")
            if rel.as_posix() == "__init__.py":
                text = _LEGACY_BL_INFO + "\n" + text
            zf.writestr(f"blender_mcp_addon/{rel.as_posix()}", text)

    return ext_zip, legacy_zip


def install_addon(blender_bin: Path | None = None) -> dict[str, str]:
    """Build and install the appropriate add-on format for the detected Blender version."""
    exe = blender_bin or find_blender_executable()
    if exe is None:
        raise FileNotFoundError("Blender executable not found.")
    version = get_blender_version(exe)
    with tempfile.TemporaryDirectory(prefix="blender_mcp_build_") as tmp:
        ext_zip, legacy_zip = build_addon_zips(Path(tmp))
        if version is not None and version >= (4, 2, 0):
            cmd = [
                str(exe),
                "--background",
                "--command",
                "extension",
                "install-file",
                "-r",
                "user_default",
                "-e",
                str(ext_zip),
            ]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            if res.returncode != 0:
                raise RuntimeError(f"Extension install failed:\n{res.stdout}\n{res.stderr}")
            return {
                "mode": "extension (4.2+)",
                "blender": str(exe),
                "version": ".".join(map(str, version)),
                "output": res.stdout.strip(),
            }

        # Legacy 3.6 - 4.1 install via bpy.ops.preferences.addon_install
        script = (
            "import bpy, sys; "
            f"bpy.ops.preferences.addon_install(filepath={str(legacy_zip)!r}, overwrite=True); "
            "bpy.ops.preferences.addon_enable(module='blender_mcp_addon'); "
            "bpy.ops.wm.save_userpref()"
        )
        res = subprocess.run(
            [str(exe), "--background", "--python-expr", script],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if res.returncode != 0:
            raise RuntimeError(f"Legacy add-on install failed:\n{res.stdout}\n{res.stderr}")
        return {
            "mode": "legacy_addon (3.6-4.1)",
            "blender": str(exe),
            "version": ".".join(map(str, version)) if version else "unknown",
            "output": res.stdout.strip(),
        }
