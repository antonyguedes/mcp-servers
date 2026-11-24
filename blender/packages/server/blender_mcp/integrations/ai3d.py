# SPDX-License-Identifier: MIT
"""Unified AI 3D model generation provider interface and registry.

Built-in providers:
- Hyper3D Rodin (`HYPER3D_API_KEY`)
- Hunyuan3D Cloud or Local Self-Hosted (`HUNYUAN3D_API_KEY` or `HUNYUAN3D_BASE_URL`)
- Tripo3D (`TRIPO_API_KEY`)
- Meshy (`MESHY_API_KEY`)
- TRELLIS Local/Self-Hosted (`TRELLIS_BASE_URL`)
"""

from __future__ import annotations

import abc
import asyncio
import base64
import hashlib
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import httpx

from blender_mcp.config import ServerSettings
from blender_mcp.integrations.cache import USER_AGENT, AssetCache

ProgressCallback = Callable[[float, str], Awaitable[None]]


async def _emit(cb: ProgressCallback | None, fraction: float, message: str) -> None:
    if cb is not None:
        await cb(max(0.0, min(1.0, fraction)), message)


class AI3DProvider(abc.ABC):
    """Abstract interface implemented by all text/image-to-3D generation providers."""

    name: str
    env_hint: str
    supports_text: bool = True
    supports_image: bool = True

    @abc.abstractmethod
    def is_configured(self) -> bool:
        """Return True if credentials or a self-hosted endpoint are configured."""

    @abc.abstractmethod
    async def generate(
        self,
        *,
        prompt: str | None,
        image_path: Path | None,
        output_dir: Path,
        cache: AssetCache,
        on_progress: ProgressCallback | None = None,
        poll_interval: float = 2.0,
        timeout_sec: float = 300.0,
    ) -> Path:
        """Generate a 3D model and return the local path to the downloaded `.glb`/`.gltf`."""

    def describe(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "configured": self.is_configured(),
            "supports_text": self.supports_text,
            "supports_image": self.supports_image,
            "env_vars": self.env_hint,
        }


class Hyper3DRodinProvider(AI3DProvider):
    """Hyper3D Rodin text-to-3D & image-to-3D cloud API."""

    name = "hyper3d"
    env_hint = "HYPER3D_API_KEY"

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = "https://hyperhuman.deemos.com/api/v2",
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self._http = http_client

    def is_configured(self) -> bool:
        return bool(self.api_key)

    async def generate(
        self,
        *,
        prompt: str | None,
        image_path: Path | None,
        output_dir: Path,
        cache: AssetCache,
        on_progress: ProgressCallback | None = None,
        poll_interval: float = 2.0,
        timeout_sec: float = 300.0,
    ) -> Path:
        headers = {"Authorization": f"Bearer {self.api_key}", "User-Agent": USER_AGENT}
        owns = self._http is None
        client = self._http or httpx.AsyncClient(follow_redirects=True, timeout=60.0)
        try:
            await _emit(on_progress, 0.05, "Submitting Hyper3D Rodin task")
            data: dict[str, Any] = {"geometry_file_format": "glb", "material": "PBR"}
            if prompt:
                data["prompt"] = prompt
            files = None
            if image_path is not None:
                files = {"images": (image_path.name, image_path.read_bytes(), "image/png")}
            resp = await client.post(f"{self.base_url}/rodin", headers=headers, data=data, files=files)
            resp.raise_for_status()
            created = resp.json()
            sub_key = created.get("jobs", {}).get("subscription_key") or created.get("uuid")
            task_uuid = created.get("uuid") or sub_key

            elapsed = 0.0
            while elapsed < timeout_sec:
                await _emit(on_progress, min(0.85, 0.1 + elapsed / max(timeout_sec, 1.0)), "Generating 3D mesh (Hyper3D)")
                st_resp = await client.post(
                    f"{self.base_url}/status",
                    headers=headers,
                    json={"subscription_key": sub_key},
                )
                st_resp.raise_for_status()
                jobs = st_resp.json().get("jobs") or []
                statuses = {str(j.get("status", "")).lower() for j in jobs if isinstance(j, dict)}
                if statuses and all(s in ("done", "completed", "succeeded") for s in statuses):
                    break
                if any(s in ("failed", "error") for s in statuses):
                    raise RuntimeError(f"Hyper3D generation failed: {st_resp.json()}")
                await asyncio.sleep(poll_interval)
                elapsed += poll_interval
            else:
                raise TimeoutError(f"Hyper3D task timed out after {timeout_sec}s")

            dl_resp = await client.post(
                f"{self.base_url}/download",
                headers=headers,
                json={"task_uuid": task_uuid},
            )
            dl_resp.raise_for_status()
            items = dl_resp.json().get("list") or []
            glb_item = next(
                (i for i in items if isinstance(i, dict) and str(i.get("name", "")).lower().endswith(".glb")),
                items[0] if items else None,
            )
            if not isinstance(glb_item, dict) or "url" not in glb_item:
                raise RuntimeError("Hyper3D download response contained no model URL")
            await _emit(on_progress, 0.92, "Downloading generated GLB")
            dest = output_dir / "model.glb"
            return await cache.download_file(str(glb_item["url"]), dest, client=client)
        finally:
            if owns:
                await client.aclose()


class Hunyuan3DProvider(AI3DProvider):
    """Hunyuan3D provider supporting BOTH local self-hosted servers and cloud APIs."""

    name = "hunyuan3d"
    env_hint = "HUNYUAN3D_BASE_URL (local) or HUNYUAN3D_API_KEY (cloud)"

    def __init__(
        self,
        *,
        api_key: str = "",
        base_url: str = "",
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self._http = http_client

    def is_configured(self) -> bool:
        return bool(self.base_url or self.api_key)

    async def generate(
        self,
        *,
        prompt: str | None,
        image_path: Path | None,
        output_dir: Path,
        cache: AssetCache,
        on_progress: ProgressCallback | None = None,
        poll_interval: float = 2.0,
        timeout_sec: float = 300.0,
    ) -> Path:
        endpoint = self.base_url or "https://api.hunyuan3d.cloud/v1"
        headers = {"User-Agent": USER_AGENT}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload: dict[str, Any] = {"output_format": "glb"}
        if prompt:
            payload["prompt"] = prompt
        if image_path is not None:
            payload["image"] = base64.b64encode(image_path.read_bytes()).decode("ascii")

        owns = self._http is None
        client = self._http or httpx.AsyncClient(follow_redirects=True, timeout=timeout_sec)
        try:
            await _emit(on_progress, 0.1, f"Requesting 3D generation from Hunyuan3D ({endpoint})")
            resp = await client.post(f"{endpoint}/generate", headers=headers, json=payload)
            resp.raise_for_status()

            content_type = resp.headers.get("content-type", "").lower()
            dest = output_dir / "model.glb"
            if "application/octet-stream" in content_type or "model/gltf-binary" in content_type or resp.content[:4] == b"glTF":
                dest.write_bytes(resp.content)
                await _emit(on_progress, 1.0, "Received GLB directly from Hunyuan3D")
                return dest

            body = resp.json()
            if isinstance(body, dict) and body.get("glb_url"):
                await _emit(on_progress, 0.9, "Downloading Hunyuan3D GLB")
                return await cache.download_file(str(body["glb_url"]), dest, client=client)

            if isinstance(body, dict) and body.get("glb_base64"):
                dest.write_bytes(base64.b64decode(str(body["glb_base64"])))
                await _emit(on_progress, 1.0, "Decoded Hunyuan3D GLB")
                return dest

            # Async task polling protocol (`task_id` / `id`)
            task_id = body.get("task_id") or body.get("id")
            if not task_id:
                raise RuntimeError(f"Unexpected Hunyuan3D response: {body}")

            elapsed = 0.0
            while elapsed < timeout_sec:
                await _emit(on_progress, min(0.85, 0.2 + elapsed / max(timeout_sec, 1.0)), "Polling Hunyuan3D job")
                st = await client.get(f"{endpoint}/tasks/{task_id}", headers=headers)
                st.raise_for_status()
                sdata = st.json()
                status = str(sdata.get("status", "")).lower()
                if status in ("completed", "succeeded", "done"):
                    model_url = sdata.get("glb_url") or sdata.get("model_url")
                    if not model_url:
                        raise RuntimeError(f"Hunyuan3D task finished without model_url: {sdata}")
                    return await cache.download_file(str(model_url), dest, client=client)
                if status in ("failed", "error"):
                    raise RuntimeError(f"Hunyuan3D generation failed: {sdata}")
                await asyncio.sleep(poll_interval)
                elapsed += poll_interval
            raise TimeoutError(f"Hunyuan3D task {task_id} timed out after {timeout_sec}s")
        finally:
            if owns:
                await client.aclose()


class Tripo3DProvider(AI3DProvider):
    """Tripo3D v2 API provider (`TRIPO_API_KEY`)."""

    name = "tripo"
    env_hint = "TRIPO_API_KEY"

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = "https://api.tripo3d.ai/v2/openapi",
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self._http = http_client

    def is_configured(self) -> bool:
        return bool(self.api_key)

    async def generate(
        self,
        *,
        prompt: str | None,
        image_path: Path | None,
        output_dir: Path,
        cache: AssetCache,
        on_progress: ProgressCallback | None = None,
        poll_interval: float = 2.0,
        timeout_sec: float = 300.0,
    ) -> Path:
        headers = {"Authorization": f"Bearer {self.api_key}", "User-Agent": USER_AGENT}
        owns = self._http is None
        client = self._http or httpx.AsyncClient(follow_redirects=True, timeout=60.0)
        try:
            await _emit(on_progress, 0.05, "Submitting Tripo3D task")
            payload: dict[str, Any] = (
                {"type": "image_to_model", "file": {"type": "png", "data": base64.b64encode(image_path.read_bytes()).decode("ascii")}}
                if image_path is not None
                else {"type": "text_to_model", "prompt": prompt or ""}
            )
            resp = await client.post(f"{self.base_url}/task", headers=headers, json=payload)
            resp.raise_for_status()
            task_id = resp.json().get("data", {}).get("task_id")
            if not task_id:
                raise RuntimeError(f"Tripo3D returned no task_id: {resp.json()}")

            elapsed = 0.0
            while elapsed < timeout_sec:
                st = await client.get(f"{self.base_url}/task/{task_id}", headers=headers)
                st.raise_for_status()
                tdata = st.json().get("data") or {}
                status = str(tdata.get("status", "")).lower()
                pct = float(tdata.get("progress", 0)) / 100.0
                await _emit(on_progress, max(0.1, min(0.9, pct)), f"Tripo3D status: {status}")
                if status == "success":
                    out = tdata.get("output") or {}
                    url = out.get("pbr_model") or out.get("model") or out.get("base_model")
                    if not url:
                        raise RuntimeError(f"Tripo3D task succeeded without model URL: {tdata}")
                    return await cache.download_file(str(url), output_dir / "model.glb", client=client)
                if status in ("failed", "cancelled", "unknown"):
                    raise RuntimeError(f"Tripo3D task failed: {tdata}")
                await asyncio.sleep(poll_interval)
                elapsed += poll_interval
            raise TimeoutError(f"Tripo3D task {task_id} timed out")
        finally:
            if owns:
                await client.aclose()


class MeshyProvider(AI3DProvider):
    """Meshy v2 API provider (`MESHY_API_KEY`)."""

    name = "meshy"
    env_hint = "MESHY_API_KEY"

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = "https://api.meshy.ai/openapi/v2",
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self._http = http_client

    def is_configured(self) -> bool:
        return bool(self.api_key)

    async def generate(
        self,
        *,
        prompt: str | None,
        image_path: Path | None,
        output_dir: Path,
        cache: AssetCache,
        on_progress: ProgressCallback | None = None,
        poll_interval: float = 2.0,
        timeout_sec: float = 300.0,
    ) -> Path:
        headers = {"Authorization": f"Bearer {self.api_key}", "User-Agent": USER_AGENT}
        owns = self._http is None
        client = self._http or httpx.AsyncClient(follow_redirects=True, timeout=60.0)
        try:
            await _emit(on_progress, 0.05, "Submitting Meshy task")
            if image_path is not None:
                b64 = base64.b64encode(image_path.read_bytes()).decode("ascii")
                url_path = "/image-to-3d"
                payload: dict[str, Any] = {"image_url": f"data:image/png;base64,{b64}", "enable_pbr": True}
            else:
                url_path = "/text-to-3d"
                payload = {"mode": "preview", "prompt": prompt or "", "art_style": "realistic"}
            resp = await client.post(f"{self.base_url}{url_path}", headers=headers, json=payload)
            resp.raise_for_status()
            task_id = resp.json().get("result")
            if not task_id:
                raise RuntimeError(f"Meshy returned no task id: {resp.json()}")

            elapsed = 0.0
            while elapsed < timeout_sec:
                st = await client.get(f"{self.base_url}{url_path}/{task_id}", headers=headers)
                st.raise_for_status()
                data = st.json()
                status = str(data.get("status", "")).upper()
                pct = float(data.get("progress", 0)) / 100.0
                await _emit(on_progress, max(0.1, min(0.9, pct)), f"Meshy status: {status}")
                if status == "SUCCEEDED":
                    glb_url = (data.get("model_urls") or {}).get("glb")
                    if not glb_url:
                        raise RuntimeError(f"Meshy task succeeded without glb URL: {data}")
                    return await cache.download_file(str(glb_url), output_dir / "model.glb", client=client)
                if status in ("FAILED", "EXPIRED", "CANCELED"):
                    raise RuntimeError(f"Meshy task failed: {data}")
                await asyncio.sleep(poll_interval)
                elapsed += poll_interval
            raise TimeoutError(f"Meshy task {task_id} timed out")
        finally:
            if owns:
                await client.aclose()


class TrellisProvider(AI3DProvider):
    """Self-hosted TRELLIS local server provider (`TRELLIS_BASE_URL`)."""

    name = "trellis"
    env_hint = "TRELLIS_BASE_URL"

    def __init__(self, base_url: str, *, http_client: httpx.AsyncClient | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self._http = http_client

    def is_configured(self) -> bool:
        return bool(self.base_url)

    async def generate(
        self,
        *,
        prompt: str | None,
        image_path: Path | None,
        output_dir: Path,
        cache: AssetCache,
        on_progress: ProgressCallback | None = None,
        poll_interval: float = 2.0,
        timeout_sec: float = 300.0,
    ) -> Path:
        del poll_interval
        owns = self._http is None
        client = self._http or httpx.AsyncClient(follow_redirects=True, timeout=timeout_sec)
        try:
            await _emit(on_progress, 0.1, f"Calling local TRELLIS server ({self.base_url})")
            payload: dict[str, Any] = {}
            if prompt:
                payload["prompt"] = prompt
            if image_path is not None:
                payload["image_base64"] = base64.b64encode(image_path.read_bytes()).decode("ascii")
            resp = await client.post(f"{self.base_url}/generate", json=payload, headers={"User-Agent": USER_AGENT})
            resp.raise_for_status()
            dest = output_dir / "model.glb"
            if resp.content[:4] == b"glTF":
                dest.write_bytes(resp.content)
                await _emit(on_progress, 1.0, "Received GLB from TRELLIS")
                return dest
            body = resp.json()
            if body.get("glb_url"):
                return await cache.download_file(str(body["glb_url"]), dest, client=client)
            if body.get("glb_base64"):
                dest.write_bytes(base64.b64decode(str(body["glb_base64"])))
                return dest
            raise RuntimeError(f"Unexpected TRELLIS response: {body}")
        finally:
            if owns:
                await client.aclose()


class AI3DRegistry:
    """Registry managing built-in and plugin-contributed AI 3D providers."""

    def __init__(self, cache: AssetCache, settings: ServerSettings) -> None:
        self.cache = cache
        self._providers: dict[str, AI3DProvider] = {}
        self.register(Hyper3DRodinProvider(settings.hyper3d_api_key, base_url=settings.hyper3d_base_url))
        self.register(
            Hunyuan3DProvider(
                api_key=settings.hunyuan3d_api_key,
                base_url=settings.hunyuan3d_base_url,
            )
        )
        self.register(Tripo3DProvider(settings.tripo_api_key))
        self.register(MeshyProvider(settings.meshy_api_key))
        self.register(TrellisProvider(settings.trellis_base_url))

    def register(self, provider: AI3DProvider) -> None:
        self._providers[provider.name.lower()] = provider

    def list_providers(self) -> list[dict[str, Any]]:
        return [p.describe() for p in self._providers.values()]

    def resolve(self, name: str | None = None) -> AI3DProvider:
        if name:
            key = name.strip().lower()
            prov = self._providers.get(key)
            if prov is None:
                raise ValueError(
                    f"Unknown AI 3D provider {name!r}. Available: {', '.join(sorted(self._providers))}."
                )
            if not prov.is_configured():
                raise PermissionError(
                    f"AI 3D provider {prov.name!r} is not configured. Set {prov.env_hint}."
                )
            return prov

        for prov in self._providers.values():
            if prov.is_configured():
                return prov
        hints = ", ".join(f"{p.name}: {p.env_hint}" for p in self._providers.values())
        raise PermissionError(f"No AI 3D provider is configured. Set one of: {hints}.")

    async def generate(
        self,
        *,
        prompt: str | None = None,
        image_path: Path | None = None,
        provider_name: str | None = None,
        on_progress: ProgressCallback | None = None,
    ) -> tuple[AI3DProvider, Path]:
        if not prompt and image_path is None:
            raise ValueError("Provide either 'prompt' (text-to-3D) or 'image_path' (image-to-3D).")
        prov = self.resolve(provider_name)
        key_src = f"{prov.name}:{prompt or ''}:{image_path or ''}"
        digest = hashlib.sha256(key_src.encode("utf-8")).hexdigest()[:12]
        out_dir = self.cache.asset_dir(f"ai3d_{prov.name}", digest, "glb")
        glb_path = await prov.generate(
            prompt=prompt,
            image_path=image_path,
            output_dir=out_dir,
            cache=self.cache,
            on_progress=on_progress,
        )
        self.cache.write_metadata(
            out_dir,
            {"provider": prov.name, "prompt": prompt, "image_path": str(image_path) if image_path else None},
        )
        return prov, glb_path
