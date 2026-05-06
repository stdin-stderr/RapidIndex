"""xxxclub.to detail-page ingester.

Iterates through torrent detail pages by sequential ID
(https://xxxclub.to/torrents/details/{id}). Resumable via a watermark
that stores the last processed ID. Yields RawRelease objects for every
valid torrent page encountered.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone
from typing import AsyncIterator
from urllib.parse import parse_qs, urlparse

from bs4 import BeautifulSoup

from src.config import Settings
from src.ingesters.base import Ingester, RawRelease
from src.storage.repositories.scan_state_repo import get_watermark, set_watermark
from src.utils.http import get_client

log = logging.getLogger(__name__)

_BASE_URL = "https://xxxclub.to/torrents/details"
_DATE_FMT = "%d %B %Y %H:%M:%S"

_SIZE_UNITS = {"b": 1, "kb": 1024, "mb": 1024**2, "gb": 1024**3, "tb": 1024**4}


def _parse_size(s: str) -> int | None:
    m = re.match(r"([\d.]+)\s*([a-z]+)", s.strip(), re.I)
    if not m:
        return None
    multiplier = _SIZE_UNITS.get(m.group(2).lower())
    if multiplier is None:
        return None
    return int(float(m.group(1)) * multiplier)


def _extract_info_hash(magnet: str) -> str | None:
    m = re.search(r"btih:([0-9a-fA-F]{40})", magnet)
    return m.group(1).lower() if m else None


def _get_li_value(soup: BeautifulSoup, label: str) -> str | None:
    """Find the <li> whose first <span> matches label and return the last <span> text."""
    for li in soup.select("div.detailsdescr li"):
        spans = li.find_all("span", recursive=False)
        if spans and spans[0].get_text(strip=True) == label:
            return spans[-1].get_text(strip=True) if len(spans) >= 3 else None
    return None


def _parse_detail_page(torrent_id: int, html: str) -> RawRelease | None:
    soup = BeautifulSoup(html, "lxml")

    details = soup.find("div", class_="detailsdiv")
    if not details:
        return None

    title_tag = details.find("h1")
    raw_title = title_tag.get_text(strip=True) if title_tag else None
    if not raw_title:
        return None

    # Category
    raw_category: str | None = None
    for li in details.select("div.detailsdescr li"):
        spans = li.find_all("span", recursive=False)
        if spans and spans[0].get_text(strip=True) == "Category":
            a = li.find("a")
            raw_category = a.get_text(strip=True) if a else None
            break

    # Size
    size_str = _get_li_value(soup, "Size")
    file_size_bytes = _parse_size(size_str) if size_str else None

    # Added date
    published_at: datetime | None = None
    date_str = _get_li_value(soup, "Added Date")
    if date_str:
        try:
            published_at = datetime.strptime(date_str.strip(), _DATE_FMT).replace(
                tzinfo=timezone.utc
            )
        except ValueError:
            log.debug("Could not parse date %r for id %d", date_str, torrent_id)

    # Seeders / leechers
    seeders: int | None = None
    leechers: int | None = None
    see = details.find("font", class_="see")
    lee = details.find("font", class_="lee")
    if see:
        try:
            seeders = int(see.get_text(strip=True))
        except ValueError:
            pass
    if lee:
        try:
            leechers = int(lee.get_text(strip=True))
        except ValueError:
            pass

    # Magnet + info_hash
    magnet_tag = details.find("a", class_=lambda c: c and "b-o-s" in c)
    magnet_uri: str | None = magnet_tag["href"] if magnet_tag else None
    info_hash: str | None = _extract_info_hash(magnet_uri) if magnet_uri else None

    if not info_hash:
        # Fallback: try torrent download link
        dl_tag = details.find("a", class_=lambda c: c and "b-o-p" in c)
        if dl_tag:
            path = urlparse(dl_tag.get("href", "")).path
            candidate = path.rstrip("/").split("/")[-1]
            if re.fullmatch(r"[0-9a-fA-F]{40}", candidate):
                info_hash = candidate.lower()

    if not info_hash:
        log.debug("No info_hash found for id %d", torrent_id)
        return None

    # Files
    files: list[dict] = []
    filestable = details.find("div", class_="filestable")
    if filestable:
        rows = filestable.select("ul li")
        for idx, row in enumerate(rows[1:]):  # skip header row
            spans = row.find_all("span")
            if len(spans) >= 2:
                name = spans[0].get_text(strip=True)
                size = _parse_size(spans[1].get_text(strip=True))
                if name:
                    files.append({"filename": name, "file_size_bytes": size or 0, "file_index": idx})

    # Hints
    uploader = _get_li_value(soup, "Uploader")
    downloads = _get_li_value(soup, "Downloads")
    collection_tag = None
    for li in details.select("div.detailsdescr li"):
        spans = li.find_all("span", recursive=False)
        if spans and spans[0].get_text(strip=True) == "Collection":
            a = li.find("a")
            collection_tag = a.get_text(strip=True) if a else None
            break

    poster_tag = details.find("img", class_="detailsposter")
    poster_url = poster_tag["src"] if poster_tag else None

    hints: dict[str, str] = {}
    if uploader:
        hints["uploader"] = uploader
    if downloads:
        hints["downloads"] = downloads
    if collection_tag:
        hints["collection"] = collection_tag
    if poster_url:
        hints["poster_url"] = poster_url

    return RawRelease(
        source_type="torrent",
        source_name="xxxclub",
        source_key=info_hash,
        raw_title=raw_title,
        raw_category=raw_category,
        file_size_bytes=file_size_bytes,
        published_at=published_at,
        info_hash=info_hash,
        magnet_uri=magnet_uri,
        seeders=seeders,
        leechers=leechers,
        files=files or None,
        hints=hints or None,
    )


class XXXClubIngester(Ingester):
    source_name = "xxxclub"

    def __init__(self, settings: Settings, session_factory) -> None:
        self._settings = settings
        self._session_factory = session_factory

    @property
    def interval_seconds(self) -> int:
        return self._settings.xxxclub_interval_seconds

    async def fetch_new(self) -> AsyncIterator[RawRelease]:
        http = get_client()
        delay = self._settings.xxxclub_request_delay_ms / 1000.0
        error_limit = self._settings.xxxclub_consecutive_error_limit

        async with self._session_factory() as session:
            watermark = await get_watermark(session, "xxxclub")

        start_id = int(watermark) + 1 if watermark else self._settings.xxxclub_start_id
        log.info("xxxclub: starting from id %d", start_id)

        consecutive_errors = 0
        current_id = start_id

        while True:
            url = f"{_BASE_URL}/{current_id}"
            try:
                html = await http.fetch_text(url)
            except Exception as exc:
                log.warning("xxxclub: fetch error for id %d: %s", current_id, exc)
                current_id += 1
                await asyncio.sleep(delay)
                continue

            await asyncio.sleep(delay)

            is_error = "errordiv" in html or "detailsdiv" not in html

            async with self._session_factory() as session:
                await set_watermark(session, "xxxclub", str(current_id))

            if is_error:
                consecutive_errors += 1
                log.debug("xxxclub: id %d is an error page (%d consecutive)", current_id, consecutive_errors)
                if consecutive_errors >= error_limit:
                    log.info(
                        "xxxclub: %d consecutive error pages — stopping at id %d",
                        consecutive_errors, current_id,
                    )
                    break
                current_id += 1
                continue

            consecutive_errors = 0
            release = _parse_detail_page(current_id, html)
            if release:
                log.debug("xxxclub: yielding %s (id %d)", release.info_hash, current_id)
                yield release
            else:
                log.debug("xxxclub: id %d parsed but no release extracted", current_id)

            current_id += 1
