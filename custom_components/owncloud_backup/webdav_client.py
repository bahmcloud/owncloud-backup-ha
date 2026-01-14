from __future__ import annotations

import base64
import logging
import os
import xml.etree.ElementTree as ET
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Final
from urllib.parse import quote, urljoin

import aiohttp
from aiohttp import ClientResponseError, ClientSession
from yarl import URL

_LOGGER = logging.getLogger(__name__)

DAV_NS: Final = "{DAV:}"


class WebDavClient:
    """Minimal WebDAV client for ownCloud Classic.

    It auto-detects commonly used ownCloud DAV roots:
    - remote.php/dav/files/<user>/
    - remote.php/webdav/
    """

    def __init__(
        self,
        *,
        session: ClientSession,
        base_url: str,
        username: str,
        password: str,
        backup_path: str,
    ) -> None:
        self._session = session
        self._base_url = base_url.rstrip("/") + "/"
        self._username = username
        self._password = password
        self._backup_path = backup_path.strip()

        self._dav_roots = [
            f"remote.php/dav/files/{quote(username)}/",
            "remote.php/webdav/",
        ]
        self._cached_root: str | None = None

        # Non-restrictive client timeouts for potentially long WebDAV operations
        self._timeout_long = aiohttp.ClientTimeout(
            total=None, connect=60, sock_connect=60, sock_read=None
        )

    def _auth_header(self) -> str:
        token = base64.b64encode(f"{self._username}:{self._password}".encode("utf-8")).decode("ascii")
        return f"Basic {token}"

    def _headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        headers = {"Authorization": self._auth_header()}
        if extra:
            headers.update(extra)
        return headers

    def _folder_rel(self) -> str:
        p = self._backup_path.strip()
        if not p.startswith("/"):
            p = "/" + p
        return p.lstrip("/")

    async def _pick_working_root(self) -> str:
        """Return a DAV root that works (by PROPFIND depth 0). Cache result."""
        if self._cached_root is not None:
            return self._cached_root

        last_err: Exception | None = None
        for root in self._dav_roots:
            url = urljoin(self._base_url, root)
            try:
                async with self._session.request(
                    "PROPFIND",
                    url,
                    headers=self._headers(
                        {"Depth": "0", "Content-Type": "application/xml; charset=utf-8"}
                    ),
                    data=(
                        b'<?xml version="1.0"?>'
                        b'<d:propfind xmlns:d="DAV:"><d:prop><d:resourcetype/></d:prop></d:propfind>'
                    ),
                    raise_for_status=True,
                    timeout=self._timeout_long,
                ):
                    self._cached_root = root
                    return root
            except Exception as err:  # noqa: BLE001
                last_err = err

        raise last_err or RuntimeError("No working DAV root found")

    async def _base_folder_url(self) -> str:
        root = await self._pick_working_root()
        rel = self._folder_rel().strip("/")
        return urljoin(self._base_url, root + (rel + "/" if rel else ""))

    async def ensure_backup_folder(self) -> None:
        """Ensure the backup folder exists (create intermediate folders best-effort)."""
        base_folder = await self._base_folder_url()

        # If folder exists -> done
        try:
            async with self._session.request(
                "PROPFIND",
                base_folder,
                headers=self._headers({"Depth": "0"}),
                raise_for_status=True,
                timeout=self._timeout_long,
            ):
                return
        except ClientResponseError as err:
            if err.status in (401, 403):
                raise
        except Exception:
            pass

        # Create folders one by one using MKCOL
        root = await self._pick_working_root()
        parts = [p for p in self._folder_rel().split("/") if p]
        current = urljoin(self._base_url, root)

        for part in parts:
            current = urljoin(current if current.endswith("/") else current + "/", quote(part) + "/")
            await self._mkcol_if_missing(current)

    async def _mkcol_if_missing(self, url: str) -> None:
        # exists?
        try:
            async with self._session.request(
                "PROPFIND",
                url,
                headers=self._headers({"Depth": "0"}),
                raise_for_status=True,
                timeout=self._timeout_long,
            ):
                return
        except ClientResponseError as err:
            if err.status in (401, 403):
                raise

        # create
        async with self._session.request(
            "MKCOL", url, headers=self._headers(), timeout=self._timeout_long
        ) as resp:
            if resp.status in (201, 405):
                return
            text = await resp.text()
            raise RuntimeError(f"MKCOL failed ({resp.status}): {text}")

    async def listdir(self) -> list[str]:
        """List file names in backup folder (Depth: 1)."""
        folder = await self._base_folder_url()

        async with self._session.request(
            "PROPFIND",
            folder,
            headers=self._headers({"Depth": "1", "Content-Type": "application/xml; charset=utf-8"}),
            data=(
                b'<?xml version="1.0"?>'
                b'<d:propfind xmlns:d="DAV:"><d:prop><d:displayname/></d:prop></d:propfind>'
            ),
            raise_for_status=True,
            timeout=self._timeout_long,
        ) as resp:
            body = await resp.text()

        try:
            root = ET.fromstring(body)
        except ET.ParseError as err:
            raise RuntimeError(f"Invalid PROPFIND response XML: {err}") from err

        names: list[str] = []
        for response in root.findall(f"{DAV_NS}response"):
            href_el = response.find(f"{DAV_NS}href")
            if href_el is None or not href_el.text:
                continue

            href = href_el.text
            try:
                u = URL(href)
                seg = u.path.rstrip("/").split("/")[-1]
            except Exception:
                seg = href.rstrip("/").split("/")[-1]

            if not seg:
                continue

            # Skip directory itself
            folder_leaf = self._folder_rel().rstrip("/").split("/")[-1]
            if seg == folder_leaf:
                continue

            names.append(seg)

        return sorted(set(names))

    def _file_url(self, folder_url: str, name: str) -> str:
        if not folder_url.endswith("/"):
            folder_url += "/"
        return urljoin(folder_url, quote(name))

    async def put_bytes(self, name: str, data: bytes) -> None:
        folder = await self._base_folder_url()
        url = self._file_url(folder, name)
        async with self._session.put(
            url,
            data=data,
            headers=self._headers({"Content-Length": str(len(data))}),
            raise_for_status=True,
            timeout=self._timeout_long,
        ):
            return

    async def put_file(self, name: str, path: str, size: int) -> None:
        """Upload a local file with an explicit Content-Length (non-chunked)."""
        folder = await self._base_folder_url()
        url = self._file_url(folder, name)

        # Ensure correct size if caller passes 0/unknown
        if size <= 0:
            try:
                size = os.path.getsize(path)
            except OSError:
                size = 0

        headers = {"Content-Length": str(size)} if size > 0 else {}

        # aiohttp will stream file content; with Content-Length set, proxies are usually happier.
        with open(path, "rb") as f:
            async with self._session.put(
                url,
                data=f,
                headers=self._headers(headers),
                raise_for_status=True,
                timeout=self._timeout_long,
            ):
                return

    async def put_stream(self, name: str, stream: AsyncIterator[bytes]) -> None:
        """Legacy method: chunked upload. Prefer put_file for better proxy compatibility."""
        folder = await self._base_folder_url()
        url = self._file_url(folder, name)

        async def gen():
            async for chunk in stream:
                yield chunk

        async with self._session.put(
            url,
            data=gen(),
            headers=self._headers(),
            raise_for_status=True,
            timeout=self._timeout_long,
        ):
            return

    async def get_bytes(self, name: str) -> bytes:
        folder = await self._base_folder_url()
        url = self._file_url(folder, name)
        async with self._session.get(url, headers=self._headers(), timeout=self._timeout_long) as resp:
            if resp.status == 404:
                raise FileNotFoundError(name)
            resp.raise_for_status()
            return await resp.read()

    async def get_stream(self, name: str) -> AsyncIterator[bytes]:
        folder = await self._base_folder_url()
        url = self._file_url(folder, name)
        resp = await self._session.get(url, headers=self._headers(), timeout=self._timeout_long)
        if resp.status == 404:
            await resp.release()
            raise FileNotFoundError(name)
        resp.raise_for_status()

        async def iterator() -> AsyncIterator[bytes]:
            try:
                async for chunk in resp.content.iter_chunked(1024 * 256):
                    yield chunk
            finally:
                resp.release()

        return iterator()

    async def delete(self, name: str) -> None:
        folder = await self._base_folder_url()
        url = self._file_url(folder, name)
        async with self._session.delete(url, headers=self._headers(), timeout=self._timeout_long) as resp:
            if resp.status == 404:
                raise FileNotFoundError(name)
            if resp.status in (200, 202, 204):
                return
            text = await resp.text()
            raise RuntimeError(f"DELETE failed ({resp.status}): {text}")

    async def stat(self, name: str) -> dict[str, object]:
        """Return size and modified time for a file using PROPFIND Depth: 0."""
        folder = await self._base_folder_url()
        url = self._file_url(folder, name)

        body = (
            b'<?xml version="1.0"?>'
            b'<d:propfind xmlns:d="DAV:">'
            b'  <d:prop>'
            b'    <d:getcontentlength />'
            b'    <d:getlastmodified />'
            b'  </d:prop>'
            b'</d:propfind>'
        )

        async with self._session.request(
            "PROPFIND",
            url,
            headers=self._headers({"Depth": "0", "Content-Type": "application/xml; charset=utf-8"}),
            data=body,
            timeout=self._timeout_long,
        ) as resp:
            if resp.status == 404:
                raise FileNotFoundError(name)
            resp.raise_for_status()
            xml = await resp.text()

        root = ET.fromstring(xml)
        resp_el = root.find(f"{DAV_NS}response")
        if resp_el is None:
            raise RuntimeError("Invalid PROPFIND stat response")

        prop_el = resp_el.find(f".//{DAV_NS}prop")
        if prop_el is None:
            raise RuntimeError("Invalid PROPFIND stat response (no prop)")

        size_el = prop_el.find(f"{DAV_NS}getcontentlength")
        lm_el = prop_el.find(f"{DAV_NS}getlastmodified")

        size = int(size_el.text) if (size_el is not None and size_el.text) else 0
        modified_raw = lm_el.text.strip() if (lm_el is not None and lm_el.text) else ""

        modified_iso = ""
        if modified_raw:
            try:
                dt = parsedate_to_datetime(modified_raw)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                modified_iso = dt.astimezone(timezone.utc).isoformat()
            except Exception:  # noqa: BLE001
                modified_iso = modified_raw
        else:
            modified_iso = datetime.now(timezone.utc).isoformat()

        return {
            "size": size,
            "modified_raw": modified_raw,
            "modified_iso": modified_iso,
        }
