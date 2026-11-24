# SPDX-License-Identifier: MIT
"""Unit tests for multiview contact-sheet stitching and dual add-on packaging."""

from __future__ import annotations

import base64
import io
import zipfile
from pathlib import Path

from PIL import Image

from blender_mcp.bridge.launcher import build_addon_zips
from blender_mcp.vision_utils import stitch_multiview_grid


def _make_tile_b64(color: tuple[int, int, int], size: int = 128) -> str:
    img = Image.new("RGB", (size, size), color=color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def test_stitch_multiview_grid_4_views() -> None:
    views = [
        {"view": "iso", "image_base64": _make_tile_b64((200, 60, 60))},
        {"view": "front", "image_base64": _make_tile_b64((60, 200, 60))},
        {"view": "right", "image_base64": _make_tile_b64((60, 60, 200))},
        {"view": "top", "image_base64": _make_tile_b64((200, 200, 60))},
    ]
    png_bytes = stitch_multiview_grid(views, tile_size=128)
    result = Image.open(io.BytesIO(png_bytes))
    # 2x2 grid with 4px padding on outer and inner edges => 2*128 + 3*4 = 268
    assert result.size == (268, 268)


def test_build_addon_zips_dual_formats(tmp_path: Path) -> None:
    ext_zip, legacy_zip = build_addon_zips(tmp_path)
    assert ext_zip.is_file()
    assert legacy_zip.is_file()

    with zipfile.ZipFile(ext_zip) as zf:
        names = set(zf.namelist())
        assert "blender_manifest.toml" in names
        assert "LICENSE" in names
        assert "__init__.py" in names
        assert "handlers/objects.py" in names
        init_src = zf.read("__init__.py").decode("utf-8")
        assert "bl_info" not in init_src
        assert "from .dispatcher import Dispatcher" in init_src

    with zipfile.ZipFile(legacy_zip) as zf:
        names = set(zf.namelist())
        assert "blender_mcp_addon/LICENSE" in names
        assert "blender_mcp_addon/__init__.py" in names
        init_src = zf.read("blender_mcp_addon/__init__.py").decode("utf-8")
        assert "bl_info = {" in init_src
