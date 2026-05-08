import logging
import os
import re
from typing import Any
from urllib.parse import quote

import requests

from src.utils import ui_cache as cache

_log = logging.getLogger(__name__)

DEBRID_TIMEOUT = 10
STREMTHRU_URL = os.environ.get("STREMTHRU_URL", "https://stremthru.13377001.xyz")
_CLIENT_IP = "0.0.0.0"

_VIDEO_EXTS = (".mp4", ".mkv", ".avi", ".mov", ".wmv", ".m4v", ".ts", ".webm")


class DebridError(Exception):
    def __init__(self, service: str, message: str, display_message: str = ""):
        super().__init__(message)
        self.service = service
        self.message = message
        self.display_message = display_message or message


class DebridAuthError(DebridError):
    pass


class DebridLinkGenerationError(DebridError):
    def __init__(self, service: str, message: str, error_code: str = "", upstream_error_code: str = "", payload: dict = None):
        super().__init__(service, message)
        self.error_code = error_code
        self.upstream_error_code = upstream_error_code
        self.payload = payload or {}

    @property
    def status_keys(self) -> list[str]:
        return [c for c in (self.error_code, self.upstream_error_code) if c]


class DebridPendingError(DebridError):
    def __init__(self, service: str, status: str):
        super().__init__(service, f"{service}: download in progress (status: {status})")
        self.status = status


class DebridClient:
    SUPPORTED_SERVICES = {
        "torbox": {"name": "TorBox", "icon": "TB"},
        "realdebrid": {"name": "Real-Debrid", "icon": "RD"},
        "alldebrid": {"name": "All-Debrid", "icon": "AD"},
        "premiumize": {"name": "Premiumize", "icon": "PM"},
        "debridlink": {"name": "Debrid-Link", "icon": "DL"},
        "debrider": {"name": "Debrider", "icon": "DB"},
        "easydebrid": {"name": "EasyDebrid", "icon": "ED"},
        "offcloud": {"name": "Offcloud", "icon": "OC"},
        "pikpak": {"name": "PikPak", "icon": "PP"},
    }

    _MAGNET_READY = frozenset({"cached", "downloaded"})
    _MAGNET_PENDING = frozenset({"queued", "downloading", "processing", "uploading"})
    _MAGNET_INVALID = frozenset({"failed", "invalid"})

    def __init__(self, service: str, api_key: str, sid: str = ""):
        if service not in self.SUPPORTED_SERVICES:
            raise ValueError(f"Unsupported debrid service: {service}")
        self._service = service
        self._api_key = api_key
        self._config = self.SUPPORTED_SERVICES[service]
        self._base = f"{STREMTHRU_URL}/v0/store"
        self._sid = sid
        self._session = requests.Session()

    def get_user(self) -> dict:
        try:
            resp = self._session.get(
                f"{self._base}/user?client_ip={_CLIENT_IP}",
                headers=self._headers(),
                timeout=DEBRID_TIMEOUT,
            )
            body = resp.json()
            data = body.get("data")
            if resp.status_code != 200 or not data:
                error = body.get("error") or {}
                msg = (error.get("message") if isinstance(error, dict) else str(error)) or f"{self._service}: Invalid API key."
                raise DebridAuthError(self._service, msg)
            return data
        except DebridAuthError:
            raise
        except requests.RequestException as e:
            raise DebridAuthError(self._service, f"{self._service}: Failed to check account: {e}")

    def list_magnets(self, limit: int = 500, offset: int = 0) -> tuple[list[dict], int]:
        try:
            resp = self._session.get(
                f"{self._base}/magnets?limit={limit}&offset={offset}&client_ip={_CLIENT_IP}",
                headers=self._headers(),
                timeout=DEBRID_TIMEOUT,
            )
            if resp.status_code == 200:
                data = resp.json().get("data") or {}
                return data.get("items") or [], int(data.get("total_items", 0))
            _log.warning(f"{self._service} list_magnets returned {resp.status_code}")
            return [], 0
        except requests.RequestException as e:
            _log.warning(f"{self._service} list_magnets error: {e}")
            return [], 0

    def check_cached(self, hashes: "str | list[str]", bypass_cache: bool = False) -> dict[str, bool]:
        if isinstance(hashes, str):
            hashes = [hashes]
        hashes = [h.lower() for h in hashes]

        result: dict[str, bool] = {}

        if not bypass_cache:
            for h in hashes:
                cached = self._get_cache(f"check:{h}")
                if cached is not None:
                    result[h] = cached

        uncached = [h for h in hashes if h not in result]
        if uncached:
            api_result = self._check_cached_stremthru(uncached)
            result.update(api_result)
            for h, is_cached in api_result.items():
                self._set_cache(f"check:{h}", is_cached, ttl=3600)

        return result

    def _check_cached_stremthru(self, hashes: list[str]) -> dict[str, bool]:
        result: dict[str, bool] = {h: False for h in hashes}
        try:
            magnets = [self._to_magnet(h) for h in hashes]
            magnet_param = quote(",".join(magnets), safe=":,")
            url = (
                f"{self._base}/magnets/check"
                f"?magnet={magnet_param}"
                f"&client_ip={_CLIENT_IP}"
                f"&sid={self._sid}"
            )
            resp = self._session.get(url, headers=self._headers(), timeout=DEBRID_TIMEOUT)
            if resp.status_code == 200:
                items = (resp.json().get("data") or {}).get("items") or []
                for item in items:
                    h = (item.get("hash") or "").lower()
                    if h:
                        result[h] = item.get("status") == "cached"
            else:
                _log.warning(f"{self._service} check_cached returned {resp.status_code}: {resp.text[:200]}")
        except requests.RequestException as e:
            _log.warning(f"{self._service} check_cached error: {e}")
        return result

    def get_stream_url(self, magnet: str) -> str:
        try:
            magnet = self._to_magnet(magnet)
            info_hash = self._extract_hash_from_magnet(magnet)
            if not info_hash:
                _log.warning(f"{self._service} could not extract hash from magnet")
                return ""

            magnet_data = self._add_magnet_stremthru(magnet)
            if not magnet_data:
                _log.warning(f"{self._service} failed to add magnet")
                return ""

            status = magnet_data.get("status", "")
            if status in self._MAGNET_PENDING:
                raise DebridPendingError(self._service, status)
            if status in self._MAGNET_INVALID:
                raise DebridError(self._service, f"{self._service}: torrent failed (status: {status})")

            files = magnet_data.get("files") or []
            if not files:
                files = self._get_files_stremthru(info_hash)
            if not files:
                _log.warning(f"{self._service} no files found")
                return ""

            video_files = [f for f in files if f.get("name", "").lower().endswith(_VIDEO_EXTS)]
            if not video_files:
                video_files = files

            best = max(video_files, key=lambda f: f.get("size") or 0)
            file_link = best.get("link")
            if not file_link:
                _log.warning(f"{self._service} file has no link field")
                return ""

            return self._generate_link_stremthru(file_link)

        except DebridError:
            raise
        except Exception as e:
            _log.warning(f"{self._service} get_stream_url error: {e}")
            return ""

    def _add_magnet_stremthru(self, magnet: str) -> dict:
        try:
            resp = self._session.post(
                f"{self._base}/magnets?client_ip={_CLIENT_IP}",
                json={"magnet": magnet},
                headers=self._headers(),
                timeout=DEBRID_TIMEOUT,
            )
            if resp.status_code in (200, 201):
                return resp.json().get("data") or {}
            _log.warning(f"{self._service} add_magnet failed: {resp.status_code}: {resp.text[:200]}")
            return {}
        except requests.RequestException as e:
            _log.warning(f"{self._service} add_magnet error: {e}")
            return {}

    def _get_files_stremthru(self, info_hash: str) -> list[dict]:
        try:
            resp = self._session.get(
                f"{self._base}/magnets/{info_hash}?client_ip={_CLIENT_IP}",
                headers=self._headers(),
                timeout=DEBRID_TIMEOUT,
            )
            if resp.status_code == 200:
                return (resp.json().get("data") or {}).get("files") or []
            _log.warning(f"{self._service} get_files failed: {resp.status_code}")
            return []
        except requests.RequestException as e:
            _log.warning(f"{self._service} get_files error: {e}")
            return []

    def _generate_link_stremthru(self, file_link: str) -> str:
        try:
            resp = self._session.post(
                f"{self._base}/link/generate?client_ip={_CLIENT_IP}",
                json={"link": file_link},
                headers=self._headers(),
                timeout=DEBRID_TIMEOUT,
            )
            if resp.status_code == 200:
                return (resp.json().get("data") or {}).get("link") or ""
            _log.warning(f"{self._service} generate_link failed: {resp.status_code}: {resp.text[:200]}")
            return ""
        except requests.RequestException as e:
            _log.warning(f"{self._service} generate_link error: {e}")
            return ""

    def _headers(self) -> dict:
        return {
            "X-StremThru-Store-Name": self._service,
            "X-StremThru-Store-Authorization": f"Bearer {self._api_key}",
            "User-Agent": "rapidindex-debrid",
        }

    @staticmethod
    def _extract_hash_from_magnet(magnet: str) -> str | None:
        m = re.search(r"xt=urn:btih:([a-fA-F0-9]{32,})", magnet, re.IGNORECASE)
        return m.group(1).lower() if m else None

    @staticmethod
    def _to_magnet(magnet_or_hash: str) -> str:
        if magnet_or_hash.startswith("magnet:"):
            return magnet_or_hash
        return f"magnet:?xt=urn:btih:{magnet_or_hash}"

    def _get_cache(self, suffix: str) -> Any | None:
        return cache.cache_get(f"{self._service}:{suffix}")

    def _set_cache(self, suffix: str, data: Any, ttl: int) -> None:
        cache.cache_set(f"{self._service}:{suffix}", data, ttl)
