# SPDX-License-Identifier: MIT
"""Unit tests for Phase 5: AssetCache (incl. Zip-Slip), Poly Haven, ambientCG, Sketchfab, AI3D, and Plugins."""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import httpx
import pytest
from PIL import Image

from blender_mcp.app import create_server
from blender_mcp.config import ServerSettings
from blender_mcp.integrations.ai3d import (
    AI3DProvider,
    AI3DRegistry,
    Hunyuan3DProvider,
    MeshyProvider,
)
from blender_mcp.integrations.ambientcg import AmbientCGClient
from blender_mcp.integrations.cache import AssetCache
from blender_mcp.integrations.polyhaven import PolyHavenClient
from blender_mcp.integrations.sketchfab import SketchfabClient
from blender_mcp.plugins import PluginContext
from blender_mcp_protocol import PythonPolicy


def _png_bytes(color: tuple[int, int, int] = (120, 140, 160)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), color=color).save(buf, format="PNG")
    return buf.getvalue()


def _zip_bytes(entries: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return buf.getvalue()


async def test_asset_cache_dedup_status_and_zip_slip_protection(tmp_path: Path) -> None:
    cache = AssetCache(tmp_path / "cache")
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, content=b"asset-bytes")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        dest = cache.asset_dir("polyhaven", "wood_01", "2k") / "wood.png"
        await cache.download_file("https://example.test/wood.png", dest, client=client)
        # Second download hits cache without HTTP request
        await cache.download_file("https://example.test/wood.png", dest, client=client)

    assert calls == 1
    st = cache.status()
    assert st["total_files"] == 1
    assert st["providers"]["polyhaven"]["bytes"] == len(b"asset-bytes")

    # Zip-Slip archive traversal MUST be blocked
    evil_zip = tmp_path / "evil.zip"
    evil_zip.write_bytes(_zip_bytes({"../../escape.txt": b"pwned"}))
    with pytest.raises(ValueError, match="Refusing unsafe archive member"):
        cache.safe_extract_zip(evil_zip, cache.asset_dir("sketchfab", "bad", "gltf"))

    cleared = cache.clear("polyhaven")
    assert cleared["removed"] is True
    assert cache.status()["total_files"] == 0


async def test_polyhaven_and_ambientcg_clients(tmp_path: Path) -> None:
    cache = AssetCache(tmp_path / "cache")
    png = _png_bytes()
    acg_zip = _zip_bytes(
        {
            "Wood049_2K-PNG_Color.png": png,
            "Wood049_2K-PNG_Roughness.png": png,
            "Wood049_2K-PNG_NormalGL.png": png,
        }
    )

    def ph_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/assets":
            return httpx.Response(
                200,
                json={
                    "studio_small": {
                        "name": "Studio Small 01",
                        "type": 0,
                        "categories": ["studio"],
                        "tags": ["softbox"],
                        "download_count": 5000,
                    },
                    "brick_wall": {
                        "name": "Brick Wall",
                        "type": 1,
                        "categories": ["bricks"],
                        "tags": ["red"],
                        "download_count": 3000,
                    },
                },
            )
        if request.url.path == "/files/studio_small":
            return httpx.Response(
                200,
                json={"hdri": {"2k": {"hdr": {"url": "https://cdn.test/studio_small_2k.hdr"}}}},
            )
        if request.url.path == "/files/brick_wall":
            return httpx.Response(
                200,
                json={
                    "Diffuse": {"2k": {"png": {"url": "https://cdn.test/brick_diff.png"}}},
                    "Rough": {"2k": {"png": {"url": "https://cdn.test/brick_rough.png"}}},
                    "nor_gl": {"2k": {"png": {"url": "https://cdn.test/brick_nor.png"}}},
                },
            )
        return httpx.Response(200, content=png)

    async with httpx.AsyncClient(transport=httpx.MockTransport(ph_handler)) as ph_http:
        ph = PolyHavenClient(cache, http_client=ph_http, base_url="https://api.test")
        res = await ph.search(asset_type="hdris", query="studio")
        assert res["total_matches"] == 1
        assert res["results"][0]["id"] == "studio_small"

        hdri = await ph.download_hdri("studio_small", resolution="2k")
        assert hdri.is_file()

        maps = await ph.download_texture_maps("brick_wall", resolution="2k")
        assert set(maps.keys()) == {"base_color", "roughness", "normal"}

    def acg_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v2/full_json":
            return httpx.Response(
                200,
                json={
                    "numberOfResults": 1,
                    "foundAssets": [
                        {
                            "assetId": "Wood049",
                            "displayName": "Wood 049",
                            "displayCategory": "Wood",
                            "tags": ["oak", "planks"],
                            "downloadFolders": {
                                "default": {
                                    "downloadFiletypeCategories": {
                                        "zip": {
                                            "downloads": [
                                                {
                                                    "attribute": "2K-PNG",
                                                    "downloadLink": "https://cdn.test/Wood049_2K-PNG.zip",
                                                }
                                            ]
                                        }
                                    }
                                }
                            },
                        }
                    ],
                },
            )
        return httpx.Response(200, content=acg_zip)

    async with httpx.AsyncClient(transport=httpx.MockTransport(acg_handler)) as acg_http:
        acg = AmbientCGClient(cache, http_client=acg_http, api_url="https://acg.test/api/v2/full_json")
        s = await acg.search(query="wood")
        assert s["results"][0]["id"] == "Wood049"
        acg_maps = await acg.download_material_maps("Wood049", resolution="2K-PNG")
        assert set(acg_maps.keys()) == {"base_color", "roughness", "normal"}


async def test_sketchfab_and_ai3d_providers(tmp_path: Path) -> None:
    cache = AssetCache(tmp_path / "cache")

    # Sketchfab refuses download without API key
    sf_nokey = SketchfabClient(cache, api_key="")
    with pytest.raises(PermissionError, match="SKETCHFAB_API_KEY"):
        await sf_nokey.download_model("abc123")

    # Hunyuan3D self-hosted direct binary GLB response + progress reporting
    progress_events: list[tuple[float, str]] = []

    async def on_prog(frac: float, msg: str) -> None:
        progress_events.append((frac, msg))

    def hy_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b"glTF\x02\x00\x00\x00fakeglb",
            headers={"content-type": "model/gltf-binary"},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(hy_handler)) as hy_http:
        hy = Hunyuan3DProvider(base_url="http://127.0.0.1:8080", http_client=hy_http)
        assert hy.is_configured() is True
        glb = await hy.generate(
            prompt="stylized wooden chair",
            image_path=None,
            output_dir=cache.asset_dir("ai3d_hunyuan3d", "chair", "glb"),
            cache=cache,
            on_progress=on_prog,
        )
        assert glb.is_file()
        assert glb.read_bytes().startswith(b"glTF")
        assert len(progress_events) >= 2

    # Meshy async task poll -> SUCCEEDED -> download GLB
    poll_count = 0

    def meshy_handler(request: httpx.Request) -> httpx.Response:
        nonlocal poll_count
        if request.method == "POST" and request.url.path.endswith("/text-to-3d"):
            return httpx.Response(200, json={"result": "task_99"})
        if request.method == "GET" and request.url.path.endswith("/text-to-3d/task_99"):
            poll_count += 1
            if poll_count == 1:
                return httpx.Response(200, json={"status": "IN_PROGRESS", "progress": 50})
            return httpx.Response(
                200,
                json={"status": "SUCCEEDED", "progress": 100, "model_urls": {"glb": "https://cdn.test/m.glb"}},
            )
        return httpx.Response(200, content=b"glTF-meshy")

    async with httpx.AsyncClient(transport=httpx.MockTransport(meshy_handler)) as m_http:
        meshy = MeshyProvider("fake-key", http_client=m_http)
        m_glb = await meshy.generate(
            prompt="crystal sword",
            image_path=None,
            output_dir=cache.asset_dir("ai3d_meshy", "sword", "glb"),
            cache=cache,
            poll_interval=0.01,
        )
        assert m_glb.read_bytes() == b"glTF-meshy"

    # Registry reports all 5 built-in providers cleanly
    reg = AI3DRegistry(cache, ServerSettings(audit_log=None))
    names = {p["name"] for p in reg.list_providers()}
    assert {"hyper3d", "hunyuan3d", "tripo", "meshy", "trellis"} == names
    with pytest.raises(PermissionError, match="No AI 3D provider is configured"):
        reg.resolve()


async def test_third_party_plugin_registers_tool_and_ai3d_provider(tmp_path: Path) -> None:
    class _DummyProvider(AI3DProvider):
        name = "custom_studio"
        env_hint = "none"

        def is_configured(self) -> bool:
            return True

        async def generate(self, **kwargs) -> Path:
            p = kwargs["output_dir"] / "custom.glb"
            p.write_bytes(b"glTF")
            return p

    def sample_plugin(ctx: PluginContext) -> None:
        ctx.integrations.ai3d.register(_DummyProvider())

        @ctx.mcp.tool()
        async def plugin_ping(echo: str = "ok") -> dict[str, str]:
            """Custom tool added by a third-party plugin."""
            return {"plugin": "sample_plugin", "echo": echo}

    mcp = create_server(
        ServerSettings(
            profile="integrations",
            python_policy=PythonPolicy.FALSE,
            cache_dir=tmp_path / "cache",
            audit_log=None,
        ),
        extra_plugins=[sample_plugin],
        discover_plugins=False,
    )
    tool_names = {t.name for t in await mcp.list_tools()}
    assert "plugin_ping" in tool_names
    assert "polyhaven_apply_hdri" in tool_names
    assert "ai3d_generate" in tool_names

    ping_res = await mcp.call_tool("plugin_ping", {"echo": "hello"})
    structured = ping_res.structured_content or json.loads(ping_res.content[0].text)
    assert structured == {"plugin": "sample_plugin", "echo": "hello"}

    provs_res = await mcp.call_tool("ai3d_list_providers", {})
    provs = (provs_res.structured_content or json.loads(provs_res.content[0].text))["providers"]
    assert any(p["name"] == "custom_studio" and p["configured"] is True for p in provs)
