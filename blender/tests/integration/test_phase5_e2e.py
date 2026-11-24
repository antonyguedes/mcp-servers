# SPDX-License-Identifier: MIT
"""End-to-end Phase 5 integration tests wiring mocked external providers into real Blender 5.3+."""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import httpx
import pytest
from PIL import Image

from blender_mcp.app import create_server
from blender_mcp.bridge.launcher import find_blender_executable, launch_blender_headless
from blender_mcp.config import ServerSettings
from blender_mcp.integrations.ai3d import Hunyuan3DProvider
from blender_mcp.integrations.ambientcg import AmbientCGClient
from blender_mcp.integrations.polyhaven import PolyHavenClient
from blender_mcp_protocol import PythonPolicy

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        find_blender_executable() is None,
        reason="No Blender executable installed on this machine",
    ),
]


def _extract_json(call_result: object) -> dict:
    if getattr(call_result, "is_error", False):
        content = getattr(call_result, "content", []) or []
        msg = content[0].text if content else "Unknown MCP tool error"
        raise RuntimeError(msg)
    structured = getattr(call_result, "structured_content", None)
    if isinstance(structured, dict):
        return structured
    content = getattr(call_result, "content", None)
    if content:
        return json.loads(content[0].text)
    raise AssertionError(f"Unexpected call_tool result: {call_result!r}")


def _png_bytes(color: tuple[int, int, int]) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (16, 16), color=color).save(buf, format="PNG")
    return buf.getvalue()


async def test_phase5_external_providers_end_to_end_in_blender(tmp_path: Path) -> None:
    """Download PBR textures, HDRI, and AI3D GLB through IntegrationsHub and apply inside real Blender 5.3."""
    proc = launch_blender_headless(allow_python=False, startup_timeout=45.0)
    settings = ServerSettings(
        host=proc.host,
        port=proc.port,
        token=proc.token,
        host_explicit=True,
        port_explicit=True,
        profile="full",
        python_policy=PythonPolicy.FALSE,
        allowed_dirs=[tmp_path],
        cache_dir=tmp_path / "asset_cache",
        audit_log=None,
    )
    mcp = create_server(settings, discover_plugins=False)
    runtime = mcp._blender_runtime  # type: ignore[attr-defined]
    hub = mcp._blender_integrations  # type: ignore[attr-defined]

    try:
        # First export a genuine GLB from Blender so our mock AI3D server serves valid 3D geometry
        sample_glb_path = tmp_path / "sample_cube.glb"
        _extract_json(await mcp.call_tool("export_file", {"filepath": str(sample_glb_path)}))
        valid_glb_bytes = sample_glb_path.read_bytes()

        albedo_png = _png_bytes((155, 105, 65))
        rough_png = _png_bytes((128, 128, 128))
        normal_png = _png_bytes((128, 128, 255))
        sky_png = _png_bytes((180, 210, 245))

        acg_zip_buf = io.BytesIO()
        with zipfile.ZipFile(acg_zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("Marble01_2K-PNG_Color.png", albedo_png)
            zf.writestr("Marble01_2K-PNG_Roughness.png", rough_png)
            zf.writestr("Marble01_2K-PNG_NormalGL.png", normal_png)
        acg_zip_bytes = acg_zip_buf.getvalue()

        def ph_handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/files/studio_env":
                return httpx.Response(
                    200,
                    json={"hdri": {"2k": {"hdr": {"url": "https://cdn.test/studio_env.png"}}}},
                )
            if request.url.path == "/files/oak_planks":
                return httpx.Response(
                    200,
                    json={
                        "Diffuse": {"2k": {"png": {"url": "https://cdn.test/oak_diff.png"}}},
                        "Rough": {"2k": {"png": {"url": "https://cdn.test/oak_rough.png"}}},
                        "nor_gl": {"2k": {"png": {"url": "https://cdn.test/oak_nor.png"}}},
                    },
                )
            if "studio_env" in str(request.url):
                return httpx.Response(200, content=sky_png)
            if "rough" in str(request.url):
                return httpx.Response(200, content=rough_png)
            if "nor" in str(request.url):
                return httpx.Response(200, content=normal_png)
            return httpx.Response(200, content=albedo_png)

        def acg_handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/api/v2/full_json":
                return httpx.Response(
                    200,
                    json={
                        "numberOfResults": 1,
                        "foundAssets": [
                            {
                                "assetId": "Marble01",
                                "downloadFolders": {
                                    "default": {
                                        "downloadFiletypeCategories": {
                                            "zip": {
                                                "downloads": [
                                                    {
                                                        "attribute": "2K-PNG",
                                                        "downloadLink": "https://cdn.test/Marble01.zip",
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
            return httpx.Response(200, content=acg_zip_bytes)

        def hy_handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                content=valid_glb_bytes,
                headers={"content-type": "model/gltf-binary"},
            )

        async with (
            httpx.AsyncClient(transport=httpx.MockTransport(ph_handler)) as ph_http,
            httpx.AsyncClient(transport=httpx.MockTransport(acg_handler)) as acg_http,
            httpx.AsyncClient(transport=httpx.MockTransport(hy_handler)) as hy_http,
        ):
            hub.polyhaven = PolyHavenClient(hub.cache, http_client=ph_http, base_url="https://api.test")
            hub.ambientcg = AmbientCGClient(hub.cache, http_client=acg_http, api_url="https://acg.test/api/v2/full_json")
            hub.ai3d.register(Hunyuan3DProvider(base_url="http://127.0.0.1:8080", http_client=hy_http))

            # 1. Poly Haven HDRI -> applied to World shader in real Blender
            hdri_res = _extract_json(
                await mcp.call_tool(
                    "polyhaven_apply_hdri",
                    {"asset_id": "studio_env", "resolution": "2k", "strength": 1.2, "rotation_degrees": 45.0},
                )
            )
            assert hdri_res["provider"] == "polyhaven"
            assert hdri_res["strength"] == pytest.approx(1.2)

            # 2. Poly Haven PBR texture -> wired to Principled BSDF and assigned to Cube
            tex_res = _extract_json(
                await mcp.call_tool(
                    "polyhaven_apply_texture",
                    {"asset_id": "oak_planks", "resolution": "2k", "assign_to": ["Cube"]},
                )
            )
            assert set(tex_res["channels_wired"]) == {"base_color", "roughness", "normal"}
            assert tex_res["assigned_to"] == ["Cube"]

            # 3. ambientCG zip material -> extracted safely & wired into Blender material
            acg_res = _extract_json(
                await mcp.call_tool(
                    "ambientcg_apply_material",
                    {"asset_id": "Marble01", "resolution": "2K-PNG"},
                )
            )
            assert set(acg_res["channels_wired"]) == {"base_color", "roughness", "normal"}

            # 4. AI 3D generation (local Hunyuan3D) -> real GLB imported into collection + aligned to ground
            gen_res = _extract_json(
                await mcp.call_tool(
                    "ai3d_generate",
                    {
                        "prompt": "minimalist ceramic vase",
                        "provider": "hunyuan3d",
                        "collection": "AI_Generated",
                        "align_ground": True,
                    },
                )
            )
            assert gen_res["provider"] == "hunyuan3d"
            assert len(gen_res["imported_objects"]) >= 1

            # 5. Asset cache reports all downloaded files
            cache_st = _extract_json(await mcp.call_tool("asset_cache_status", {}))
            assert cache_st["total_files"] >= 5
            assert "polyhaven" in cache_st["providers"]
            assert "ambientcg" in cache_st["providers"]
            assert "ai3d_hunyuan3d" in cache_st["providers"]
    finally:
        await runtime.bridge.close()
        proc.stop()
