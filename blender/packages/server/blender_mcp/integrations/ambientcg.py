# SPDX-License-Identifier: MIT
"""ambientCG CC0 PBR material integration (no API key required)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx

from blender_mcp.integrations.cache import USER_AGENT, AssetCache

AMBIENTCG_API = "https://ambientcg.com/api/v2/full_json"


def _classify_pbr_filename(filename: str) -> str | None:
    low = filename.lower()
    if not low.endswith((".png", ".jpg", ".jpeg", ".exr")):
        return None
    if "_color" in low or "_albedo" in low:
        return "base_color"
    if "_roughness" in low:
        return "roughness"
    if "_normalgl" in low:
        return "normal"
    if "_metalness" in low or "_metallic" in low:
        return "metallic"
    if "_opacity" in low or "_alpha" in low:
        return "alpha"
    if "_emission" in low:
        return "emission_color"
    return None


class AmbientCGClient:
    """Async client for ambientCG's public CC0 PBR material catalog."""

    def __init__(
        self,
        cache: AssetCache,
        *,
        http_client: httpx.AsyncClient | None = None,
        api_url: str = AMBIENTCG_API,
    ) -> None:
        self.cache = cache
        self._http = http_client
        self.api_url = api_url

    async def _query(self, params: dict[str, Any]) -> dict[str, Any]:
        owns = self._http is None
        client = self._http or httpx.AsyncClient(follow_redirects=True, timeout=30.0)
        try:
            resp = await client.get(
                self.api_url,
                params=params,
                headers={"User-Agent": USER_AGENT},
            )
            resp.raise_for_status()
            data = resp.json()
            return data if isinstance(data, dict) else {}
        finally:
            if owns:
                await client.aclose()

    async def search(self, *, query: str = "", limit: int = 20) -> dict[str, Any]:
        lim = max(1, min(limit, 50))
        params: dict[str, Any] = {
            "type": "Material",
            "limit": lim,
            "include": "tagData,displayData",
        }
        if query.strip():
            params["q"] = query.strip()
        data = await self._query(params)
        assets = data.get("foundAssets") or []
        results = [
            {
                "id": a.get("assetId"),
                "name": a.get("displayName") or a.get("assetId"),
                "category": a.get("displayCategory"),
                "tags": (a.get("tags") or [])[:10],
            }
            for a in assets
            if isinstance(a, dict)
        ]
        return {
            "provider": "ambientcg",
            "total_matches": int(data.get("numberOfResults", len(results))),
            "results": results,
        }

    async def download_material_maps(
        self,
        asset_id: str,
        *,
        resolution: str = "2K-PNG",
    ) -> dict[str, Path]:
        """Download and extract an ambientCG material zip, returning `{channel: local_path}`."""
        dest_dir = self.cache.asset_dir("ambientcg", asset_id, resolution)
        existing_maps = self._scan_maps(dest_dir)
        if existing_maps:
            return existing_maps

        data = await self._query({"id": asset_id, "include": "downloadData"})
        assets = data.get("foundAssets") or []
        if not assets:
            raise ValueError(f"ambientCG asset {asset_id!r} not found.")

        dl_folders = assets[0].get("downloadFolders") or {}
        default_folder = dl_folders.get("default") or next(iter(dl_folders.values()), {})
        dl_categories = default_folder.get("downloadFiletypeCategories") or {}
        zip_cat = dl_categories.get("zip") or next(iter(dl_categories.values()), {})
        downloads = zip_cat.get("downloads") or []

        chosen = next(
            (d for d in downloads if str(d.get("attribute", "")).upper() == resolution.upper()),
            downloads[0] if downloads else None,
        )
        if not isinstance(chosen, dict) or "downloadLink" not in chosen:
            raise ValueError(f"No zip download link found for ambientCG asset {asset_id!r} ({resolution}).")

        zip_path = dest_dir / f"{asset_id}_{resolution}.zip"
        await self.cache.download_file(str(chosen["downloadLink"]), zip_path, client=self._http)
        self.cache.safe_extract_zip(zip_path, dest_dir)
        zip_path.unlink(missing_ok=True)

        maps = self._scan_maps(dest_dir)
        if not maps:
            raise ValueError(f"ambientCG archive for {asset_id!r} contained no recognized PBR maps.")
        self.cache.write_metadata(
            dest_dir,
            {"provider": "ambientcg", "asset_id": asset_id, "resolution": resolution, "channels": list(maps.keys())},
        )
        return maps

    @staticmethod
    def _scan_maps(directory: Path) -> dict[str, Path]:
        found: dict[str, Path] = {}
        for f in sorted(directory.rglob("*")):
            if not f.is_file():
                continue
            ch = _classify_pbr_filename(f.name)
            if ch and ch not in found:
                found[ch] = f
        return found
