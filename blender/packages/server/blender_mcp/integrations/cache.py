# SPDX-License-Identifier: MIT
"""Local disk asset cache with deduplication and Zip-Slip-safe archive extraction."""

from __future__ import annotations

import json
import re
import shutil
import time
import zipfile
from pathlib import Path
from typing import Any

import httpx

_SAFE_SEGMENT_RE = re.compile(r"[^A-Za-z0-9._-]+")
USER_AGENT = "blender-mcp/1.0.0 (+https://github.com/antonyguedes/mcp-servers)"


def _sanitize_key(raw: str) -> str:
    cleaned = _SAFE_SEGMENT_RE.sub("_", raw.strip()).strip("._")
    return cleaned or "asset"


class AssetCache:
    """Manages cached downloads under `<cache_dir>/<provider>/<asset_id>/<variant>/`."""

    def __init__(self, root: Path) -> None:
        self.root = root.expanduser().resolve()

    def asset_dir(self, provider: str, asset_id: str, variant: str = "default") -> Path:
        path = self.root / _sanitize_key(provider) / _sanitize_key(asset_id) / _sanitize_key(variant)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def write_metadata(self, target_dir: Path, meta: dict[str, Any]) -> None:
        payload = {"cached_at": round(time.time(), 3), **meta}
        (target_dir / "_metadata.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def read_metadata(self, target_dir: Path) -> dict[str, Any] | None:
        meta_path = target_dir / "_metadata.json"
        if not meta_path.is_file():
            return None
        try:
            data = json.loads(meta_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else None
        except Exception:
            return None

    async def download_file(
        self,
        url: str,
        dest: Path,
        *,
        client: httpx.AsyncClient | None = None,
        headers: dict[str, str] | None = None,
        force: bool = False,
    ) -> Path:
        """Download `url` to `dest` atomically, skipping if already cached."""
        dest.parent.mkdir(parents=True, exist_ok=True)
        if not force and dest.is_file() and dest.stat().st_size > 0:
            return dest

        merged_headers = {"User-Agent": USER_AGENT, **(headers or {})}
        owns_client = client is None
        http = client or httpx.AsyncClient(follow_redirects=True, timeout=120.0)
        tmp = dest.with_suffix(dest.suffix + ".part")
        try:
            async with http.stream("GET", url, headers=merged_headers) as resp:
                resp.raise_for_status()
                with tmp.open("wb") as fh:
                    async for chunk in resp.aiter_bytes(65536):
                        fh.write(chunk)
            tmp.replace(dest)
            return dest
        except Exception:
            tmp.unlink(missing_ok=True)
            raise
        finally:
            if owns_client:
                await http.aclose()

    def safe_extract_zip(self, zip_path: Path, dest_dir: Path) -> list[Path]:
        """Extract zip archive while strictly blocking Zip-Slip path traversal."""
        dest_root = dest_dir.resolve()
        dest_root.mkdir(parents=True, exist_ok=True)
        extracted: list[Path] = []
        with zipfile.ZipFile(zip_path, "r") as zf:
            for member in zf.infolist():
                if member.is_dir():
                    continue
                target = (dest_root / member.filename).resolve()
                try:
                    target.relative_to(dest_root)
                except ValueError as exc:
                    raise ValueError(
                        f"Refusing unsafe archive member {member.filename!r} escaping cache directory"
                    ) from exc
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(member, "r") as src, target.open("wb") as dst:
                    shutil.copyfileobj(src, dst)
                extracted.append(target)
        return extracted

    def status(self) -> dict[str, Any]:
        if not self.root.is_dir():
            return {
                "cache_dir": str(self.root),
                "total_files": 0,
                "total_bytes": 0,
                "providers": {},
            }
        total_files = 0
        total_bytes = 0
        providers: dict[str, dict[str, int]] = {}
        for provider_dir in sorted(p for p in self.root.iterdir() if p.is_dir()):
            p_files = 0
            p_bytes = 0
            for f in provider_dir.rglob("*"):
                if f.is_file() and f.name != "_metadata.json":
                    p_files += 1
                    p_bytes += f.stat().st_size
            providers[provider_dir.name] = {"files": p_files, "bytes": p_bytes}
            total_files += p_files
            total_bytes += p_bytes
        return {
            "cache_dir": str(self.root),
            "total_files": total_files,
            "total_bytes": total_bytes,
            "providers": providers,
        }

    def clear(self, provider: str | None = None) -> dict[str, Any]:
        target = (self.root / _sanitize_key(provider)) if provider else self.root
        removed = False
        if target.exists():
            shutil.rmtree(target)
            removed = True
        return {"cleared": str(target), "removed": removed}
