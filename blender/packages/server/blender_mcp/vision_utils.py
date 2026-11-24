# SPDX-License-Identifier: MIT
"""Image compositing utilities for visual feedback tools (multiview 2x2 grid)."""

from __future__ import annotations

import base64
import io
from typing import Any

from PIL import Image, ImageDraw


def stitch_multiview_grid(views: list[dict[str, Any]], tile_size: int = 384) -> bytes:
    """Composite 1-4 rendered views into a labeled 2x2 PNG contact sheet."""
    if not views:
        raise ValueError("No views supplied to stitch_multiview_grid")

    cols = 2 if len(views) > 1 else 1
    rows = 2 if len(views) > 2 else 1
    pad = 4
    canvas_w = cols * tile_size + (cols + 1) * pad
    canvas_h = rows * tile_size + (rows + 1) * pad
    canvas = Image.new("RGB", (canvas_w, canvas_h), color=(24, 24, 28))
    draw = ImageDraw.Draw(canvas)

    for idx, item in enumerate(views[:4]):
        raw = base64.b64decode(item["image_base64"])
        tile = Image.open(io.BytesIO(raw)).convert("RGB")
        if tile.size != (tile_size, tile_size):
            tile = tile.resize((tile_size, tile_size), Image.Resampling.LANCZOS)

        r = idx // cols
        c = idx % cols
        x0 = pad + c * (tile_size + pad)
        y0 = pad + r * (tile_size + pad)
        canvas.paste(tile, (x0, y0))

        label = str(item.get("view", f"view_{idx + 1}")).upper()
        badge_w = max(56, len(label) * 8 + 16)
        draw.rectangle([x0 + 6, y0 + 6, x0 + 6 + badge_w, y0 + 26], fill=(15, 15, 20))
        draw.text((x0 + 13, y0 + 10), label, fill=(240, 240, 245))

    out = io.BytesIO()
    canvas.save(out, format="PNG", optimize=True)
    return out.getvalue()
