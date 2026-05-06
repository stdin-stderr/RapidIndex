from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_session
from src.api.feed import load_feed_releases
from src.api.xml_builder import (
    cat_to_content_type,
    make_caps_response,
    make_torznab_feed,
)
from src.config import settings
from src.storage.models import Release, TorrentRelease
from src.storage.repositories.release_repo import (
    query_tmdb_releases,
    query_tpdb_releases,
    search_releases,
)

router = APIRouter()


async def _feed(session: AsyncSession, releases: list[Release]):
    return make_torznab_feed(
        await load_feed_releases(session, releases, "torrent"),
        settings.api_base_url,
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
            raise HTTPException(status_code=400, detail="id parameter required")
        result = await session.execute(
            select(TorrentRelease).where(TorrentRelease.release_id == UUID(id))
        )
        row = result.scalar_one_or_none()
        if row is None or not row.magnet_uri:
            raise HTTPException(status_code=404, detail="Torrent not found")
        return RedirectResponse(url=row.magnet_uri, status_code=302)

    if t == "search":
        content_type = cat_to_content_type(cat) if cat else None
        releases = await search_releases(
            session, q=q, content_type=content_type,
            source_type="torrent", limit=limit, offset=offset,
        )
        return await _feed(session, releases)

    if t in ("movie", "movie-search", "moviesearch"):
        releases = await query_tmdb_releases(
            session, tmdb_id=tmdbid, imdb_id=imdbid, q=q,
            content_type="movie", source_type="torrent", limit=limit, offset=offset,
        )
        return await _feed(session, releases)

    if t in ("tv", "tvsearch", "tv-search"):
        releases = await query_tmdb_releases(
            session, tmdb_id=tmdbid, imdb_id=imdbid, tvdb_id=tvdbid,
            q=q, content_type="tv", season=season, episode=ep,
            source_type="torrent", limit=limit, offset=offset,
        )
        return await _feed(session, releases)

    if t in ("adult", "adult-search", "adultsearch"):
        releases = await query_tpdb_releases(
            session, tpdb_id=tpdbid, q=q,
            source_type="torrent", limit=limit, offset=offset,
        )
        return await _feed(session, releases)

    return make_torznab_feed([], settings.api_base_url)
