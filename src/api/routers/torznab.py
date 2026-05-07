import re
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_session
from src.api.feed import load_feed_releases
from src.api.xml_builder import (
    cat_to_content_type,
    make_caps_response,
    make_torznab_feed,
    xml_error,
)
from src.config import settings
from src.storage.models import TorrentRelease
from src.storage.repositories.release_repo import (
    count_releases,
    count_tmdb_releases,
    count_tpdb_releases,
    query_tmdb_releases,
    query_tpdb_releases,
    search_releases,
)

router = APIRouter()

_CAT_RE = re.compile(r"^\d+(,\d+)*$")


async def _feed(session: AsyncSession, releases, *, offset: int, total: int):
    return make_torznab_feed(
        await load_feed_releases(session, releases, "torrent"),
        settings.api_base_url,
        offset=offset,
        total=total,
    )


@router.get("")
@router.get("/")
async def torznab(
    t: str = Query(...),
    q: Optional[str] = Query(None),
    cat: Optional[str] = Query(None),
    imdbid: Optional[str] = Query(None),
    tmdbid: Optional[int] = Query(None),
    tvdbid: Optional[int] = Query(None),
    tpdbid: Optional[str] = Query(None),
    season: Optional[int] = Query(None),
    ep: Optional[int] = Query(None),
    id: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
):
    if t == "caps":
        return make_caps_response(is_torznab=True)

    if t == "get":
        if not id:
            return xml_error(200, "Missing parameter: id")
        result = await session.execute(
            select(TorrentRelease).where(TorrentRelease.release_id == UUID(id))
        )
        row = result.scalar_one_or_none()
        if row is None or not row.magnet_uri:
            return xml_error(300, "No such item")
        return RedirectResponse(url=row.magnet_uri, status_code=302)

    if cat and not _CAT_RE.match(cat):
        return xml_error(201, "Incorrect parameter: cat")

    content_type = cat_to_content_type(cat) if cat else None

    if t == "search":
        releases, total = await _search_with_count(
            session, q=q, content_type=content_type, source_type="torrent",
            limit=limit, offset=offset,
        )
        return await _feed(session, releases, offset=offset, total=total)

    if t in ("movie", "movie-search", "moviesearch"):
        releases, total = await _tmdb_with_count(
            session, tmdb_id=tmdbid, imdb_id=imdbid, q=q,
            content_type="movie", source_type="torrent", limit=limit, offset=offset,
        )
        return await _feed(session, releases, offset=offset, total=total)

    if t in ("tv", "tvsearch", "tv-search"):
        releases, total = await _tmdb_with_count(
            session, tmdb_id=tmdbid, imdb_id=imdbid, tvdb_id=tvdbid,
            q=q, content_type="tv", season=season, episode=ep,
            source_type="torrent", limit=limit, offset=offset,
        )
        return await _feed(session, releases, offset=offset, total=total)

    if t in ("adult", "adult-search", "adultsearch"):
        releases, total = await _tpdb_with_count(
            session, tpdb_id=tpdbid, q=q, source_type="torrent", limit=limit, offset=offset,
        )
        return await _feed(session, releases, offset=offset, total=total)

    return xml_error(202, "No such function")


async def _search_with_count(session, *, q, content_type, source_type, limit, offset):
    releases = await search_releases(session, q=q, content_type=content_type, source_type=source_type, limit=limit, offset=offset)
    total = await count_releases(session, q=q, content_type=content_type, source_type=source_type)
    return releases, total


async def _tmdb_with_count(session, *, tmdb_id=None, imdb_id=None, tvdb_id=None, q=None,
                           content_type=None, season=None, episode=None, source_type=None,
                           limit, offset):
    releases = await query_tmdb_releases(session, tmdb_id=tmdb_id, imdb_id=imdb_id, tvdb_id=tvdb_id,
                                         q=q, content_type=content_type, season=season, episode=episode,
                                         source_type=source_type, limit=limit, offset=offset)
    total = await count_tmdb_releases(session, tmdb_id=tmdb_id, imdb_id=imdb_id, tvdb_id=tvdb_id,
                                      q=q, content_type=content_type, season=season, episode=episode,
                                      source_type=source_type)
    return releases, total


async def _tpdb_with_count(session, *, tpdb_id=None, q=None, source_type=None, limit, offset):
    releases = await query_tpdb_releases(session, tpdb_id=tpdb_id, q=q, source_type=source_type, limit=limit, offset=offset)
    total = await count_tpdb_releases(session, tpdb_id=tpdb_id, q=q, source_type=source_type)
    return releases, total
