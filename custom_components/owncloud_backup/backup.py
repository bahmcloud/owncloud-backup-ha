from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
from collections.abc import AsyncIterator, Callable, Coroutine
from typing import Any

from homeassistant.components.backup import (
    AgentBackup,
    BackupAgent,
    BackupAgentError,
    BackupNotFound,
)

from homeassistant.core import HomeAssistant, callback

from .const import (
    DATA_BACKUP_AGENT_LISTENERS,
    DATA_CLIENT,
    DOMAIN,
    META_SUFFIX,
    SPOOL_FLUSH_BYTES,
    TAR_PREFIX,
    TAR_SUFFIX,
)
from .webdav_client import WebDavClient

_LOGGER = logging.getLogger(__name__)


def _make_tar_name(backup_id: str) -> str:
    return f"{TAR_PREFIX}{backup_id}{TAR_SUFFIX}"


def _make_meta_name(backup_id: str) -> str:
    return f"{TAR_PREFIX}{backup_id}{META_SUFFIX}"


def _agentbackup_from_dict(d: dict[str, Any]) -> AgentBackup:
    """Best-effort create AgentBackup across HA versions."""
    from_dict = getattr(AgentBackup, "from_dict", None)
    if callable(from_dict):
        return from_dict(d)  # type: ignore[misc]
    return AgentBackup(**d)  # type: ignore[arg-type]


async def _spool_stream_to_tempfile(stream: AsyncIterator[bytes]) -> tuple[str, int]:
    """Spool an async byte stream into a temporary file and return (path, size).

    This avoids chunked WebDAV uploads and improves compatibility with reverse proxies.
    """
    fd, path = tempfile.mkstemp(prefix="owncloud_backup_", suffix=".tar")
    os.close(fd)

    size = 0
    buf = bytearray()

    try:
        async for chunk in stream:
            if not chunk:
                continue
            buf.extend(chunk)
            size += len(chunk)

            if len(buf) >= SPOOL_FLUSH_BYTES:
                data = bytes(buf)
                buf.clear()
                await asyncio.to_thread(_write_bytes_to_file, path, data, append=True)

        if buf:
            await asyncio.to_thread(_write_bytes_to_file, path, bytes(buf), append=True)

        return path, size

    except Exception:
        # Ensure no leftovers on failure
        try:
            os.remove(path)
        except OSError:
            pass
        raise


def _write_bytes_to_file(path: str, data: bytes, *, append: bool) -> None:
    mode = "ab" if append else "wb"
    with open(path, mode) as f:
        f.write(data)
        f.flush()


class OwnCloudBackupAgent(BackupAgent):
    """Backup agent storing backups in ownCloud via WebDAV."""

    domain = DOMAIN
    name = "ownCloud (WebDAV)"
    unique_id = "owncloud_webdav_backup_agent_v1"

    def __init__(self, client: WebDavClient) -> None:
        self._client = client

    async def async_upload_backup(
        self,
        *,
        open_stream: Callable[[], Coroutine[Any, Any, AsyncIterator[bytes]]],
        backup: AgentBackup,
        **kwargs: Any,
    ) -> None:
        """Upload a backup + metadata sidecar.

        To avoid chunked uploads (which often break behind proxies), we spool
        the stream to a temp file and upload with a Content-Length.
        """
        temp_path: str | None = None
        try:
            tar_name = _make_tar_name(backup.backup_id)
            meta_name = _make_meta_name(backup.backup_id)

            # 1) Spool tar stream to temp file
            stream = await open_stream()
            temp_path, size = await _spool_stream_to_tempfile(stream)

            # 2) Upload tar file with Content-Length
            await self._client.put_file(tar_name, temp_path, size)

            # 3) Upload metadata JSON (small)
            meta_bytes = json.dumps(backup.to_dict(), ensure_ascii=False).encode("utf-8")
            await self._client.put_bytes(meta_name, meta_bytes)

        except Exception as err:  # noqa: BLE001
            raise BackupAgentError(f"Upload to ownCloud failed: {err}") from err
        finally:
            if temp_path:
                try:
                    os.remove(temp_path)
                except OSError:
                    pass

    async def async_list_backups(self, **kwargs: Any) -> list[AgentBackup]:
        """List backups by reading metadata sidecars; fallback to tar stat if missing."""
        try:
            names = await self._client.listdir()

            meta_files = {n for n in names if n.startswith(TAR_PREFIX) and n.endswith(META_SUFFIX)}
            tar_files = {n for n in names if n.startswith(TAR_PREFIX) and n.endswith(TAR_SUFFIX)}

            backups: list[AgentBackup] = []

            # 1) Load metadata sidecars (limited concurrency)
            sem = asyncio.Semaphore(5)

            async def fetch_meta(meta_name: str) -> None:
                async with sem:
                    raw = await self._client.get_bytes(meta_name)
                try:
                    d = json.loads(raw.decode("utf-8"))
                    backups.append(_agentbackup_from_dict(d))
                except Exception as err:  # noqa: BLE001
                    _LOGGER.warning("Skipping invalid metadata %s: %s", meta_name, err)

            await asyncio.gather(*(fetch_meta(m) for m in meta_files))

            # 2) Fallback: tar without meta -> synthesize minimal AgentBackup
            known_ids = {b.backup_id for b in backups}
            for tar_name in tar_files:
                backup_id = tar_name.removeprefix(TAR_PREFIX).removesuffix(TAR_SUFFIX)
                if backup_id in known_ids:
                    continue

                info = await self._client.stat(tar_name)
                d = {
                    "backup_id": backup_id,
                    "name": f"ownCloud backup ({backup_id})",
                    "date": info.get("modified_iso", ""),
                    "size": info.get("size", 0),
                    "protected": False,
                }
                backups.append(_agentbackup_from_dict(d))

            backups.sort(key=lambda b: str(b.date), reverse=True)
            return backups

        except Exception as err:  # noqa: BLE001
            raise BackupAgentError(f"Listing backups failed: {err}") from err

    async def async_get_backup(self, backup_id: str, **kwargs: Any) -> AgentBackup:
        """Return a single backup's metadata; fallback to tar stat if missing."""
        meta_name = _make_meta_name(backup_id)
        tar_name = _make_tar_name(backup_id)

        # 1) Try meta
        try:
            raw = await self._client.get_bytes(meta_name)
            d = json.loads(raw.decode("utf-8"))
            return _agentbackup_from_dict(d)
        except FileNotFoundError:
            pass
        except Exception as err:  # noqa: BLE001
            raise BackupAgentError(f"Get backup metadata failed: {err}") from err

        # 2) Fallback to tar stat
        try:
            info = await self._client.stat(tar_name)
            d = {
                "backup_id": backup_id,
                "name": f"ownCloud backup ({backup_id})",
                "date": info.get("modified_iso", ""),
                "size": info.get("size", 0),
                "protected": False,
            }
            return _agentbackup_from_dict(d)
        except FileNotFoundError as err:
            raise BackupNotFound(f"Backup not found: {backup_id}") from err
        except Exception as err:  # noqa: BLE001
            raise BackupAgentError(f"Get backup failed: {err}") from err

    async def async_download_backup(self, backup_id: str, **kwargs: Any) -> AsyncIterator[bytes]:
        """Download tar as async bytes iterator (used for restore)."""
        tar_name = _make_tar_name(backup_id)
        try:
            stream = await self._client.get_stream(tar_name)
            async for chunk in stream:
                yield chunk
        except FileNotFoundError as err:
            raise BackupNotFound(f"Backup not found: {backup_id}") from err
        except Exception as err:  # noqa: BLE001
            raise BackupAgentError(f"Download failed: {err}") from err

    async def async_delete_backup(self, backup_id: str, **kwargs: Any) -> None:
        """Delete tar + metadata sidecar (best-effort)."""
        tar_name = _make_tar_name(backup_id)
        meta_name = _make_meta_name(backup_id)

        tar_missing = False
        meta_missing = False

        try:
            await self._client.delete(tar_name)
        except FileNotFoundError:
            tar_missing = True

        try:
            await self._client.delete(meta_name)
        except FileNotFoundError:
            meta_missing = True

        if tar_missing and meta_missing:
            raise BackupNotFound(f"Backup not found: {backup_id}")


async def async_get_backup_agents(hass: HomeAssistant) -> list[BackupAgent]:
    """Return a list of backup agents."""
    if DOMAIN not in hass.data:
        return []

    agents: list[BackupAgent] = []
    for entry_data in hass.data[DOMAIN].values():
        client: WebDavClient = entry_data[DATA_CLIENT]
        agents.append(OwnCloudBackupAgent(client))

    return agents


@callback
def async_register_backup_agents_listener(
    hass: HomeAssistant,
    *,
    listener: Callable[[], None],
    **kwargs: Any,
) -> Callable[[], None]:
    """Register a listener to be called when agents are added or removed."""
    hass.data.setdefault(DATA_BACKUP_AGENT_LISTENERS, []).append(listener)

    @callback
    def remove_listener() -> None:
        hass.data[DATA_BACKUP_AGENT_LISTENERS].remove(listener)

    return remove_listener

