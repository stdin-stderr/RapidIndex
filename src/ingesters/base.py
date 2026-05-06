from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import AsyncIterator, Literal


@dataclass
class RawRelease:
    source_type: Literal["torrent", "usenet"]
    source_name: str
    source_key: str
    raw_title: str
    raw_category: str | None
    file_size_bytes: int | None
    published_at: datetime | None

    # Torrent-only
    info_hash: str | None = None
    magnet_uri: str | None = None
    seeders: int | None = None
    leechers: int | None = None

    # Usenet-only
    newsgroup: str | None = None
    nzb_segments: str | None = None  # pipe-delimited NNTP message-IDs
    nzb_xml: bytes | None = None     # assembled at index time; stored in usenet_releases
    poster: str | None = None

    # Optional enrichment hints (written once; never overwritten on re-upsert)
    hints: dict[str, str] | None = None


class Ingester(ABC):
    @abstractmethod
    async def fetch_new(self) -> AsyncIterator[RawRelease]:
        """Yield only releases not yet seen (uses internal watermark)."""

    @property
    @abstractmethod
    def interval_seconds(self) -> int:
        """How often the scheduler should call fetch_new()."""

    @property
    @abstractmethod
    def source_name(self) -> str:
        """Unique identifier used in source_name and scan_state."""
