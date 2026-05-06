"""NZB assembler for Spotnet segments.

Spotnet stores NZB content across multiple NNTP segment articles. Each segment
body uses custom byte escaping (=C/=B/=A/=D) and is raw-deflate compressed.
This module fetches, unescapes, and inflates them into a complete NZB XML blob,
which is stored in usenet_releases.nzb_xml at index time.

Ported from py_spotweb/src/scanner/spotnet.py.
"""

from __future__ import annotations

import asyncio
import logging
import zlib

log = logging.getLogger(__name__)


def _unspecial_zip_str(data: bytes) -> bytes:
    """Reverse Spotnet's custom byte escaping (SpotWeb unspecialZipStr equivalent).

    Order matters: process =C/=B/=A before =D so that =D= sequences decode correctly.
    """
    return (
        data
        .replace(b"=C", b"\n")
        .replace(b"=B", b"\r")
        .replace(b"=A", b"\x00")
        .replace(b"=D", b"=")
    )


def _assemble_nzb_sync(message_ids: list[str], nntp) -> bytes | None:
    """Synchronous NZB assembly — runs in a thread executor."""
    chunks: list[bytes] = []
    for mid in message_ids:
        body = nntp.fetch_segment_body(mid)
        if body:
            chunks.append(body)
        else:
            log.debug("NZB segment %s unavailable", mid)

    if not chunks:
        return None

    raw = _unspecial_zip_str(b"".join(chunks))
    try:
        return zlib.decompress(raw, -15)  # raw deflate = PHP gzinflate
    except zlib.error:
        return raw  # already uncompressed or unknown format


async def build_nzb(message_ids: list[str], nntp) -> bytes | None:
    """Fetch Spotnet NZB segment articles and return assembled NZB XML bytes.

    Called by the Spotnet ingester at index time. Runs blocking NNTP I/O in a
    thread executor so it does not block the event loop.
    """
    if not message_ids:
        return None
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _assemble_nzb_sync, message_ids, nntp)
