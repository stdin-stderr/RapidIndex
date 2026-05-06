"""Fetch releases with all data needed to build Newznab/Torznab feed items."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.storage.models import Release, ReleaseTmdbTitle

_TMDB_IMG = "https://image.tmdb.org/t/p/w500"
_TMDB_IMG_FULL = "https://image.tmdb.org/t/p/original"


async def load_feed_releases(
    session: AsyncSession,
    releases: list[Release],
    source_type: str,
) -> list[Release]:
    """Re-fetch releases with TMDB metadata and source side-table eager-loaded."""
    ids = [r.id for r in releases]
    if not ids:
        return []
    opts = [selectinload(Release.tmdb_titles).selectinload(ReleaseTmdbTitle.tmdb_metadata)]
    if source_type == "usenet":
        opts.append(selectinload(Release.usenet))
    else:
        opts.append(selectinload(Release.torrent))
    stmt = (
        select(Release)
        .where(Release.id.in_(ids))
        .options(*opts)
        .order_by(Release.indexed_at.desc())
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


def tmdb_for(release: Release):
    return release.tmdb_titles[0].tmdb_metadata if release.tmdb_titles else None


def cover_url(path: str | None) -> str | None:
    return f"{_TMDB_IMG}{path}" if path else None


def backdrop_url(path: str | None) -> str | None:
    return f"{_TMDB_IMG_FULL}{path}" if path else None
