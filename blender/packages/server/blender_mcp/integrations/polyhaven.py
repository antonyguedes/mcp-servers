# SPDX-License-Identifier: MIT
"""Poly Haven CC0 integration (HDRIs, PBR Textures, and 3D Models — no API key required)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx

from blender_mcp.integrations.cache import USER_AGENT, AssetCache

POLYHAVEN_API = "https://api.polyhaven.com"

# Map Poly Haven texture channel names -> blender-mcp Principled BSDF channels
_PH_CHANNEL_MAP: dict[str, str] = {
    "Diffuse": "base_color",
    "col": "base_color",
    "albedo": "base_color",
    "Rough": "roughness",
    "rough": "roughness",
    "nor_gl": "normal",
    "Normal": "normal",
    "Metal": "metallic",
    "metal": "metallic",
}


class PolyHavenClient:
    """Async client for Poly Haven's public CC0 asset catalog."""

    def __init__(
        self,
        cache: AssetCache,
        *,
        http_client: httpx.AsyncClient | None = None,
        base_url: str = POLYHAVEN_API,
    ) -> None:
        self.cache = cache
        self._http = http_client
        self.base_url = base_url.rstrip("/")

    async def _get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        owns = self._http is None
        client = self._http or httpx.AsyncClient(follow_redirects=True, timeout=30.0)
        try:
            resp = await client.get(
                f"{self.base_url}{path}",
                params=params,
                headers={"User-Agent": USER_AGENT},
            )
            resp.raise_for_status()
            return resp.json()
        finally:
            if owns:
                await client.aclose()

    async def search(
        self,
        *,
        asset_type: str = "all",
        query: str = "",
        categories: list[str] | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {}
        t = asset_type.strip().lower()
        if t in ("hdris", "textures", "models"):
            params["t"] = t
        if categories:
            params["c"] = ",".join(categories)

        catalog = await self._get_json("/assets", params=params)
        q = query.strip().lower()
        matches: list[dict[str, Any]] = []
        for asset_id, meta in catalog.items():
            if not isinstance(meta, dict):
                continue
            name = str(meta.get("name", asset_id))
            tags = [str(x) for x in meta.get("tags", [])]
            cats = [str(x) for x in meta.get("categories", [])]
            if q and q not in asset_id.lower() and q not in name.lower() and not any(q in tg.lower() for tg in tags + cats):
                continue
            matches.append(
                {
                    "id": asset_id,
                    "name": name,
                    "type": meta.get("type"),
                    "categories": cats,
                    "tags": tags[:10],
                    "download_count": meta.get("download_count", 0),
                }
            )
        matches.sort(key=lambda m: int(m.get("download_count") or 0), reverse=True)
        lim = max(1, min(limit, 50))
        return {
            "provider": "polyhaven",
            "total_matches": len(matches),
            "results": matches[:lim],
        }

    async def download_hdri(
        self,
        asset_id: str,
        *,
        resolution: str = "2k",
        file_format: str = "hdr",
    ) -> Path:
        files = await self._get_json(f"/files/{asset_id}")
        hdri_block = files.get("hdri") or {}
        res_block = hdri_block.get(resolution) or next(iter(hdri_block.values()), None)
        if not isinstance(res_block, dict):
            raise ValueError(f"Poly Haven asset {asset_id!r} has no HDRI files for resolution {resolution!r}.")
        fmt_block = res_block.get(file_format) or next(iter(res_block.values()), None)
        if not isinstance(fmt_block, dict) or "url" not in fmt_block:
            raise ValueError(f"Poly Haven HDRI {asset_id!r} missing download URL for format {file_format!r}.")

        url = str(fmt_block["url"])
        ext = Path(url.split("?")[0]).suffix or f".{file_format}"
        dest_dir = self.cache.asset_dir("polyhaven", asset_id, f"hdri_{resolution}_{file_format}")
        dest = dest_dir / f"{asset_id}_{resolution}{ext}"
        await self.cache.download_file(url, dest, client=self._http)
        self.cache.write_metadata(dest_dir, {"provider": "polyhaven", "asset_id": asset_id, "kind": "hdri", "url": url})
        return dest

    async def download_texture_maps(
        self,
        asset_id: str,
        *,
        resolution: str = "2k",
        preferred_format: str = "jpg",
    ) -> dict[str, Path]:
        """Download PBR texture maps and return `{canonical_channel: local_path}`."""
        files = await self._get_json(f"/files/{asset_id}")
        dest_dir = self.cache.asset_dir("polyhaven", asset_id, f"tex_{resolution}")
        downloaded: dict[str, Path] = {}

        for ph_channel, canonical in _PH_CHANNEL_MAP.items():
            if canonical in downloaded:
                continue
            ch_block = files.get(ph_channel)
            if not isinstance(ch_block, dict):
                continue
            res_block = ch_block.get(resolution) or next(iter(ch_block.values()), None)
            if not isinstance(res_block, dict):
                continue
            fmt_block = (
                res_block.get(preferred_format)
                or res_block.get("png")
                or res_block.get("jpg")
                or next(iter(res_block.values()), None)
            )
            if not isinstance(fmt_block, dict) or "url" not in fmt_block:
                continue
            url = str(fmt_block["url"])
            fname = Path(url.split("?")[0]).name or f"{asset_id}_{canonical}.{preferred_format}"
            dest = dest_dir / fname
            await self.cache.download_file(url, dest, client=self._http)
            downloaded[canonical] = dest

        if not downloaded:
            raise ValueError(f"No downloadable PBR texture maps found for Poly Haven asset {asset_id!r}.")
        self.cache.write_metadata(
            dest_dir,
            {"provider": "polyhaven", "asset_id": asset_id, "kind": "texture", "channels": list(downloaded.keys())},
        )
        return downloaded

    async def download_model(
        self,
        asset_id: str,
        *,
        resolution: str = "2k",
    ) -> Path:
        """Download a Poly Haven 3D model (glTF + included sidecar assets) into cache."""
        files = await self._get_json(f"/files/{asset_id}")
        gltf_block = files.get("gltf") or {}
        res_block = gltf_block.get(resolution) or next(iter(gltf_block.values()), None)
        if not isinstance(res_block, dict):
            raise ValueError(f"Poly Haven model {asset_id!r} has no glTF package for {resolution!r}.")
        pkg = res_block.get("gltf") or next(iter(res_block.values()), None)
        if not isinstance(pkg, dict) or "url" not in pkg:
            raise ValueError(f"Poly Haven model {asset_id!r} missing glTF download URL.")

        dest_dir = self.cache.asset_dir("polyhaven", asset_id, f"model_{resolution}")
        main_url = str(pkg["url"])
        main_name = Path(main_url.split("?")[0]).name or f"{asset_id}.gltf"
        main_path = dest_dir / main_name
        await self.cache.download_file(main_url, main_path, client=self._http)

        # Download included .bin / texture sidecar files preserving relative layout
        includes = pkg.get("include") or {}
        if isinstance(includes, dict):
            for rel_path, inc_info in includes.items():
                if not isinstance(inc_info, dict) or "url" not in inc_info:
                    continue
                target = (dest_dir / rel_path).resolve()
                target.relative_to(dest_dir.resolve())
                await self.cache.download_file(str(inc_info["url"]), target, client=self._http)

        self.cache.write_metadata(dest_dir, {"provider": "polyhaven", "asset_id": asset_id, "kind": "model"})
        return main_path
