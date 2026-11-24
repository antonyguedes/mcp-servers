# SPDX-License-Identifier: MIT
"""Multi-instance Blender bridge pool with session discovery and instance switching."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, replace
from typing import Any

from blender_mcp.bridge.client import BridgeClient, NotificationCallback
from blender_mcp.config import ServerSettings
from blender_mcp_protocol import BridgeError, BridgeErrorCode, HandshakeResponse


def _pid_is_alive(pid: int | None) -> bool:
    if pid is None or pid <= 0:
        return True
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return True


@dataclass
class InstanceRecord:
    instance_id: str
    host: str
    port: int
    token: str
    pid: int | None = None
    blender_version_string: str = ""
    filepath: str = ""
    background: bool = False


class BridgePool:
    """Manages connections to one or more running Blender instances simultaneously."""

    def __init__(
        self,
        settings: ServerSettings,
        *,
        default_bridge: BridgeClient | None = None,
    ) -> None:
        self.settings = settings
        self._default_client = default_bridge or BridgeClient(settings)
        self._clients: dict[str, BridgeClient] = {}
        self._records: dict[str, InstanceRecord] = {}
        self._active_id: str | None = None
        self._listeners: list[NotificationCallback] = []

    def add_notification_listener(self, cb: NotificationCallback) -> None:
        if cb not in self._listeners:
            self._listeners.append(cb)
        self._default_client.add_notification_listener(cb)
        for client in self._clients.values():
            client.add_notification_listener(cb)

    def register_instance(
        self,
        instance_id: str,
        *,
        host: str,
        port: int,
        token: str,
        blender_version_string: str = "",
        filepath: str = "",
        background: bool = False,
        select: bool = False,
    ) -> InstanceRecord:
        rec = InstanceRecord(
            instance_id=instance_id,
            host=host,
            port=port,
            token=token,
            blender_version_string=blender_version_string,
            filepath=filepath,
            background=background,
        )
        self._records[instance_id] = rec
        inst_settings = replace(
            self.settings,
            host=host,
            port=port,
            token=token,
            host_explicit=True,
            port_explicit=True,
        )
        client = BridgeClient(inst_settings)
        for cb in self._listeners:
            client.add_notification_listener(cb)
        self._clients[instance_id] = client
        if select or self._active_id is None:
            self._active_id = instance_id
        return rec

    def discover_instances(self) -> list[dict[str, Any]]:
        """Scan `sessions_dir/*.json` (and prune dead PIDs), returning all known instances."""
        sdir = self.settings.sessions_dir
        if sdir.is_dir():
            for path in sorted(sdir.glob("*.json")):
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    if not isinstance(data, dict):
                        continue
                    iid = str(data.get("instance_id") or path.stem)
                    pid = data.get("pid")
                    if isinstance(pid, int) and not _pid_is_alive(pid):
                        path.unlink(missing_ok=True)
                        continue
                    if iid not in self._records:
                        self.register_instance(
                            iid,
                            host=str(data.get("host", self.settings.host)),
                            port=int(data.get("port", self.settings.port)),
                            token=str(data.get("token", "")),
                            blender_version_string=str(data.get("blender_version_string", "")),
                            filepath=str(data.get("filepath", "")),
                            background=bool(data.get("background", False)),
                            select=False,
                        )
                        self._records[iid].pid = pid if isinstance(pid, int) else None
                except Exception:
                    continue

        items: list[dict[str, Any]] = []
        for iid, rec in self._records.items():
            client = self._clients.get(iid)
            items.append(
                {
                    "instance_id": iid,
                    "host": rec.host,
                    "port": rec.port,
                    "pid": rec.pid,
                    "blender_version": rec.blender_version_string,
                    "filepath": rec.filepath,
                    "background": rec.background,
                    "connected": client.is_connected if client else False,
                    "active": iid == self._active_id,
                }
            )
        return items

    def select_instance(self, instance_id: str) -> dict[str, Any]:
        self.discover_instances()
        if instance_id not in self._clients:
            raise BridgeError(
                BridgeErrorCode.NOT_FOUND,
                f"Blender instance {instance_id!r} not found.",
                suggestions=list(self._clients.keys()),
            )
        self._active_id = instance_id
        rec = self._records[instance_id]
        return {
            "active_instance_id": instance_id,
            "host": rec.host,
            "port": rec.port,
            "blender_version": rec.blender_version_string,
        }

    def get_client(self, instance_id: str | None = None) -> BridgeClient:
        target_id = instance_id or self._active_id
        if target_id is not None and target_id in self._clients:
            return self._clients[target_id]
        if instance_id is not None:
            self.discover_instances()
            if instance_id in self._clients:
                return self._clients[instance_id]
            raise BridgeError(
                BridgeErrorCode.NOT_FOUND,
                f"Blender instance {instance_id!r} not found.",
                suggestions=list(self._clients.keys()),
            )
        return self._default_client

    @property
    def active_instance_id(self) -> str | None:
        if self._active_id is not None:
            return self._active_id
        hs = self._default_client.handshake
        return hs.instance_id if hs is not None else None

    @property
    def handshake(self) -> HandshakeResponse | None:
        return self.get_client().handshake

    async def connect(self, instance_id: str | None = None) -> HandshakeResponse:
        return await self.get_client(instance_id).connect()

    async def call(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        timeout: float | None = None,
        audit: bool = False,
        instance_id: str | None = None,
    ) -> Any:
        return await self.get_client(instance_id).call(
            method,
            params,
            timeout=timeout,
            audit=audit,
        )

    async def close(self) -> None:
        await self._default_client.close()
        for client in self._clients.values():
            await client.close()
