"""Spotnet/NNTP ingester.

Indexes Spotnet-formatted NNTP newsgroups. Connects over SSL, binary-searches
for the max-age cutoff on first run, then scans article headers and bodies,
parses the Spotnet XML, assembles NZB files at index time, and yields
RawRelease objects.

Ported from py_spotweb/src/scanner/spotnet.py and py_spotweb/src/scanner/main.py.
"""

from __future__ import annotations

import asyncio
import base64
import email.utils
import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import AsyncGenerator

from src.config import Settings
from src.ingesters.base import Ingester, RawRelease
from src.ingesters.usenet.nntp import NNTPClient
from src.nzb.builder import build_nzb
from src.nzb.extractor import extract_files_from_nzb
from src.storage.repositories.scan_state_repo import get_watermark, set_watermark

log = logging.getLogger(__name__)

_SUBCAT_RE = re.compile(r"(\d+)([aAbBcCdDzZ])(\d+)", re.IGNORECASE)
_BATCH_SIZE = 1000


# ---------------------------------------------------------------------------
# Internal parsed post (not exported — converted to RawRelease before yielding)
# ---------------------------------------------------------------------------

@dataclass
class _SpotnetPost:
    title: str
    poster: str
    file_size: int
    newsgroup: str
    nzb_segments: list[str] = field(default_factory=list)
    spotnet_category: int | None = None
    spotnet_subcats: list[str] = field(default_factory=list)  # e.g. ["a0", "z1"]
    spotnet_key: str | None = None
    spotnet_created: int | None = None


# ---------------------------------------------------------------------------
# Spotnet XML parser (ported from py_spotweb/src/scanner/spotnet.py)
# ---------------------------------------------------------------------------

def _parse_spotnet_body(lines: list[bytes]) -> _SpotnetPost | None:
    """Parse raw NNTP article lines (headers + body) into a _SpotnetPost.

    Returns None if the article is not a valid Spotnet post.
    """
    decoded = [
        line.decode("utf-8", errors="replace") if isinstance(line, bytes) else line
        for line in lines
    ]

    # Collect X-XML: header fragments (line-folded base64 XML)
    xml_parts: list[str] = []
    for line in decoded:
        stripped = line.rstrip("\r\n")
        if stripped.lower().startswith("x-xml:"):
            xml_parts.append(stripped[6:].lstrip(" "))

    if xml_parts:
        body = "".join(xml_parts)
    else:
        # Fallback: search body for XML marker
        body = "\n".join(decoded)
        for marker in ("<?xml", "<Spotnet", "<spotnet"):
            idx = body.find(marker)
            if idx != -1:
                body = body[idx:]
                break
        else:
            log.debug("No X-XML header or XML marker found in article")
            return None

    try:
        root = ET.fromstring(body)
    except ET.ParseError as exc:
        log.debug("XML parse failed, trying <Posting> extraction: %s", exc)
        m = re.search(r"<Posting>.*?</Posting>", body, re.DOTALL | re.IGNORECASE)
        if not m:
            return None
        try:
            root = ET.fromstring(f"<Spotnet>{m.group(0)}</Spotnet>")
        except ET.ParseError:
            return None

    posting = root.find(".//Posting") or root.find("Posting")
    if posting is None:
        return None

    def txt(tag: str) -> str:
        el = posting.find(tag)
        return (el.text or "").strip() if el is not None else ""

    title = txt("Title")
    if not title:
        return None

    spotnet_key: str | None = txt("Key") or None

    spotnet_created: int | None = None
    try:
        created_raw = txt("Created")
        if created_raw:
            spotnet_created = int(created_raw)
    except (ValueError, AttributeError):
        pass

    poster = txt("Poster")
    cat_raw = txt("Category")
    newsgroup = txt("Newsgroup") or "alt.binaries.ftd"

    # Spotnet XML uses 1-indexed categories; subtract 1 for 0-indexed
    # (0=Image/Video, 1=Sound, 2=Games, 3=Applications; 7=XXX is literal)
    try:
        spotnet_category = int(cat_raw) - 1 if cat_raw else None
    except ValueError:
        spotnet_category = None

    # Parse sub-category codes — wire format: <Sub>01a09</Sub> → "a9"
    subcat_codes: list[str] = []
    for el in posting.iter("Sub"):
        if el.text and el.text.strip():
            m = _SUBCAT_RE.search(el.text.strip())
            if m:
                subcat_codes.append(m.group(2).lower() + str(int(m.group(3))))
    if not subcat_codes:
        for el in posting.iter("SubCat"):
            if el.text and el.text.strip():
                m = _SUBCAT_RE.search(el.text.strip())
                if m:
                    subcat_codes.append(m.group(2).lower() + str(int(m.group(3))))

    # Auto-generate z-subcat for video posts that lack one
    if spotnet_category == 0 and not any(c.startswith("z") for c in subcat_codes):
        subcat_codes.append("z0")  # default to Movie

    try:
        file_size = int(txt("Size") or txt("FileSize") or "0")
    except ValueError:
        file_size = 0

    nzb_el = posting.find("NZB")
    segments: list[str] = []
    if nzb_el is not None:
        for seg in nzb_el.findall("Segment"):
            if seg.text and seg.text.strip():
                segments.append(seg.text.strip())

    return _SpotnetPost(
        title=title,
        poster=poster,
        file_size=file_size,
        newsgroup=newsgroup,
        nzb_segments=segments,
        spotnet_category=spotnet_category,
        spotnet_subcats=subcat_codes,
        spotnet_key=spotnet_key,
        spotnet_created=spotnet_created,
    )


# ---------------------------------------------------------------------------
# Category mapping
# ---------------------------------------------------------------------------

def _raw_category(spotnet_category: int | None, subcats: list[str]) -> str:
    """Map Spotnet category + sub-codes to a raw_category string.

    The returned strings match the keys in src/utils/categories.py _SPOTNET_MAP.
    """
    if spotnet_category == 7:
        return "xxx"
    if spotnet_category == 1:
        return "audio"
    if spotnet_category == 2:
        return "image"
    if spotnet_category == 3:
        return "apps"
    if spotnet_category == 0:
        if "z3" in subcats:   # Erotica
            return "xxx"
        if "z2" in subcats:   # Book
            return "book"
        if "z1" in subcats:   # Series
            return "video:tv_hd"
        return "video:movies_hd"  # z0=Movie or unknown
    return "video"


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------

def _parse_date(raw: str) -> datetime | None:
    try:
        return email.utils.parsedate_to_datetime(raw).astimezone(timezone.utc)
    except Exception:
        return None


def _bisect_cutoff(
    nntp: NNTPClient, low: int, high: int, cutoff: datetime, batch_size: int
) -> int:
    """Binary-search for the first article number at or after cutoff.

    Returns low when converged so the caller scans from there and filters
    individual articles by date — avoids missing posts at the window boundary.
    """
    lo, hi = low, high
    while hi - lo > batch_size:
        mid = (lo + hi) // 2
        batch = nntp.xover(mid, min(mid + 200, hi))
        if not batch:
            lo = mid
            continue
        first_date = _parse_date(batch[0].date)
        if not first_date or first_date < cutoff:
            lo = mid
        else:
            hi = mid
    log.info("Bisect converged: lo=%d hi=%d", lo, hi)
    return lo


# ---------------------------------------------------------------------------
# Ingester
# ---------------------------------------------------------------------------

class SpotnetIngester(Ingester):
    """Spotnet/NNTP usenet ingester.

    On each run, scans each configured newsgroup from the stored watermark,
    assembles NZB files at index time, and yields RawRelease objects.
    """

    def __init__(self, settings: Settings, session_factory):
        self._settings = settings
        self._session_factory = session_factory

    @property
    def source_name(self) -> str:
        return "spotnet"

    @property
    def interval_seconds(self) -> int:
        return self._settings.spotnet_interval_seconds

    async def fetch_new(self) -> AsyncGenerator[RawRelease, None]:
        loop = asyncio.get_event_loop()
        nntp = NNTPClient(
            host=self._settings.spotnet_nntp_host,
            port=self._settings.spotnet_nntp_port,
            ssl=True,
            username=self._settings.spotnet_nntp_user or "",
            password=self._settings.spotnet_nntp_pass or "",
        )
        await loop.run_in_executor(None, nntp.connect)
        try:
            for group in [g.strip() for g in self._settings.spotnet_newsgroups.split(",")]:
                if not group:
                    continue
                log.info("Spotnet: scanning group %s", group)
                async for raw in self._scan_group(nntp, group, loop):
                    yield raw
        finally:
            await loop.run_in_executor(None, nntp.quit)

    async def _scan_group(
        self,
        nntp: NNTPClient,
        group_name: str,
        loop: asyncio.AbstractEventLoop,
    ) -> AsyncGenerator[RawRelease, None]:
        cutoff = datetime.now(timezone.utc) - timedelta(days=self._settings.spotnet_max_age_days)

        async with self._session_factory() as session:
            watermark_str = await get_watermark(session, f"spotnet:{group_name}")
        watermark = int(watermark_str) if watermark_str else 0

        try:
            info = await loop.run_in_executor(None, nntp.group_info, group_name)
        except Exception as exc:
            log.warning("Could not select group %s: %s", group_name, exc)
            return

        log.info(
            "Spotnet %s: low=%d high=%d count=%d watermark=%d",
            group_name, info.low, info.high, info.count, watermark,
        )

        if watermark == 0:
            start = await loop.run_in_executor(
                None, _bisect_cutoff, nntp, info.low, info.high, cutoff, _BATCH_SIZE
            )
            log.info("Spotnet %s: bisect start=%d (high=%d)", group_name, start, info.high)
        else:
            start = watermark + 1

        if start > info.high:
            log.info("Spotnet %s: up to date (start=%d high=%d)", group_name, start, info.high)
            return

        pos = start
        while pos <= info.high:
            end = min(pos + _BATCH_SIZE - 1, info.high)

            try:
                batch = await loop.run_in_executor(None, nntp.xover, pos, end)
            except Exception as exc:
                log.warning(
                    "Spotnet %s: XOVER error at %d-%d: %s — reconnecting",
                    group_name, pos, end, exc,
                )
                try:
                    await loop.run_in_executor(None, nntp.connect)
                    batch = await loop.run_in_executor(None, nntp.xover, pos, end)
                except Exception as exc2:
                    log.error("Spotnet %s: XOVER retry failed: %s", group_name, exc2)
                    pos = end + 1
                    continue

            stored = skipped = failed = 0

            for art in batch:
                posted_at_nntp = _parse_date(art.date)
                if posted_at_nntp and posted_at_nntp < cutoff:
                    skipped += 1
                    continue

                lines = await loop.run_in_executor(None, nntp.fetch_article, art.message_id)
                if not lines:
                    log.debug("Spotnet %s: no article body for %s", group_name, art.message_id)
                    failed += 1
                    continue

                post = _parse_spotnet_body(lines)
                if not post:
                    log.debug(
                        "Spotnet %s: parse failed for %s (subject: %s)",
                        group_name, art.message_id, art.subject[:80],
                    )
                    failed += 1
                    continue

                nzb_xml: bytes | None = None
                files: list[dict[str, int | str | list[str]]] | None = None
                if post.nzb_segments:
                    try:
                        nzb_xml = await build_nzb(post.nzb_segments, nntp)
                        if nzb_xml:
                            log.debug(
                                "Spotnet %s: NZB assembled (%d bytes) for %r",
                                group_name, len(nzb_xml), post.title,
                            )
                            # Extract files from NZB XML
                            file_list = extract_files_from_nzb(nzb_xml)
                            if file_list:
                                files = [
                                    {
                                        "filename": f["filename"],
                                        "file_size_bytes": f["file_size_bytes"],
                                        "segment_ids": f["segment_ids"],
                                        "file_index": f["file_index"],
                                    }
                                    for f in file_list
                                ]
                    except Exception as exc:
                        log.warning(
                            "Spotnet %s: NZB assembly failed for %r: %s",
                            group_name, post.title, exc,
                        )

                published_at = (
                    datetime.fromtimestamp(post.spotnet_created, tz=timezone.utc)
                    if post.spotnet_created
                    else posted_at_nntp
                )

                yield RawRelease(
                    source_type="usenet",
                    source_name="spotnet",
                    source_key=art.message_id.strip("<>"),
                    raw_title=post.title,
                    raw_category=_raw_category(post.spotnet_category, post.spotnet_subcats),
                    file_size_bytes=post.file_size or None,
                    published_at=published_at,
                    newsgroup=group_name,
                    nzb_segments="|".join(post.nzb_segments) if post.nzb_segments else None,
                    nzb_xml=nzb_xml,
                    poster=post.poster or None,
                    files=files,
                )
                stored += 1

            # Update watermark after each batch so progress survives restarts
            async with self._session_factory() as session:
                await set_watermark(session, f"spotnet:{group_name}", str(end))
            watermark = end

            log.info(
                "Spotnet %s: batch %d-%d done — stored=%d skipped=%d failed=%d",
                group_name, pos, end, stored, skipped, failed,
            )
            pos = end + 1
