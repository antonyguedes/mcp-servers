# SPDX-License-Identifier: MIT
"""Sketchfab 3D model search and glTF download integration (requires SKETCHFAB_API_KEY)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx

from blender_mcp.integrations.cache import USER_AGENT, AssetCache

SKETCHFAB_API = "https://api.sketchfab.com/v3"


class SketchfabClient:
    """Async Sketchfab v3 client for searching and downloading glTF 3D assets."""

    def __init__(
        self,
        cache: AssetCache,
        *,
        api_key: str = "",
        http_client: httpx.AsyncClient | None = None,
        base_url: str = SKETCHFAB_API,
    ) -> None:
        self.cache = cache
        self.api_key = api_key
        self._http = http_client
        self.base_url = base_url.rstrip("/")

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)

    def _headers(self) -> dict[str, str]:
        headers = {"User-Agent": USER_AGENT}
        if self.api_key:
            headers["Authorization"] = f"Token {self.api_key}"
        return headers

    async def search(
        self,
        query: str,
        *,
        max_face_count: int | None = None,
        animated: bool | None = None,
        categories: list[str] | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "type": "models",
            "q": query,
            "downloadable": "true",
            "count": max(1, min(limit, 24)),
        }
        if max_face_count is not None:
            params["max_face_count"] = max_face_count
        if animated is not None:
            params["animated"] = "true" if animated else "false"
        if categories:
            params["categories"] = ",".join(categories)

        owns = self._http is None
        client = self._http or httpx.AsyncClient(follow_redirects=True, timeout=30.0)
        try:
            resp = await client.get(f"{self.base_url}/search", params=params, headers=self._headers())
            resp.raise_for_status()
            data = resp.json()
        finally:
            if owns:
                await client.aclose()

        results = []
        for item in data.get("results") or []:
            if not isinstance(item, dict):
                continue
            license_info = item.get("license") or {}
            results.append(
                {
                    "uid": item.get("uid"),
                    "name": item.get("name"),
                    "face_count": item.get("faceCount"),
                    "vertex_count": item.get("vertexCount"),
                    "is_animated": bool(item.get("animationCount", 0)),
                    "license": license_info.get("label") if isinstance(license_info, dict) else None,
                    "viewer_url": item.get("viewerUrl"),
                }
            )
        return {"provider": "sketchfab", "results": results}

    async def download_model(self, uid: str) -> Path:
        if not self.is_configured:
            raise PermissionError(
                "Sketchfab downloads require SKETCHFAB_API_KEY to be set in environment variables."
            )

        dest_dir = self.cache.asset_dir("sketchfab", uid, "gltf")
        existing = self._find_model_file(dest_dir)
        if existing is not None:
            return existing

        owns = self._http is None
        client = self._http or httpx.AsyncClient(follow_redirects=True, timeout=60.0)
        try:
            resp = await client.get(f"{self.base_url}/models/{uid}/download", headers=self._headers())
            resp.raise_for_status()
            dl_data = resp.json()
        finally:
            if owns:
                await client.aclose()

        gltf_info = dl_data.get("gltf") or dl_data.get("glb") or next(iter(dl_data.values()), None)
        if not isinstance(gltf_info, dict) or "url" not in gltf_info:
            raise ValueError(f"Sketchfab model {uid!r} has no downloadable glTF/GLB package.")

        url = str(gltf_info["url"])
        if url.split("?")[0].lower().endswith(".glb"):
            glb_path = dest_dir / f"{uid}.glb"
            await self.cache.download_file(url, glb_path, client=self._http)
            self.cache.write_metadata(dest_dir, {"provider": "sketchfab", "uid": uid})
            return glb_path

        zip_path = dest_dir / f"{uid}.zip"
        await self.cache.download_file(url, zip_path, client=self._http)
        self.cache.safe_extract_zip(zip_path, dest_dir)
        zip_path.unlink(missing_ok=True)

        model_file = self._find_model_file(dest_dir)
        if model_file is None:
            raise ValueError(f"Sketchfab archive for {uid!r} did not contain a .gltf or .glb file.")
        self.cache.write_metadata(dest_dir, {"provider": "sketchfab", "uid": uid})
        return model_file

    @staticmethod
    def _find_model_file(directory: Path) -> Path | None:
        for ext in ("*.glb", "*.gltf"):
            found = sorted(directory.rglob(ext))
            if found:
                return found[0]
        return None
