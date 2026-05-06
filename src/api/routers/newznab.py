from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_session
from src.api.feed import load_feed_releases
from src.api.xml_builder import (
    cat_to_content_type,
    make_caps_response,
    make_newznab_feed,
)
from src.config import settings
from src.storage.models import UsenetRelease
from src.storage.repositories.release_repo import (
    query_tmdb_releases,
    query_tpdb_releases,
    search_releases,
)

router = APIRouter()


async def _feed(session: AsyncSession, releases):
    return make_newznab_feed(
        await load_feed_releases(session, releases, "usenet"),
        settings.api_base_url,
    )


@router.get("")
@router.get("/")
async def newznab(
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
        return make_caps_response(is_torznab=False)

    if t == "get":
        if not id:
            raise HTTPException(status_code=400, detail="id parameter required")
        result = await session.execute(
            select(UsenetRelease).where(UsenetRelease.release_id == UUID(id))
        )
        row = result.scalar_one_or_none()
        if row is None or not row.nzb_xml:
            raise HTTPException(status_code=404, detail="NZB not found")
        return Response(
            content=row.nzb_xml,
            media_type="application/x-nzb",
            headers={"Content-Disposition": f'attachment; filename="{id}.nzb"'},
        )

    if t == "search":
        content_type = cat_to_content_type(cat) if cat else None
        releases = await search_releases(
            session, q=q, content_type=content_type,
            source_type="usenet", limit=limit, offset=offset,
        )
        return await _feed(session, releases)

    if t in ("movie", "movie-search", "moviesearch"):
        releases = await query_tmdb_releases(
            session, tmdb_id=tmdbid, imdb_id=imdbid, q=q,
            content_type="movie", source_type="usenet", limit=limit, offset=offset,
        )
        return await _feed(session, releases)

    if t in ("tv", "tvsearch", "tv-search"):
        releases = await query_tmdb_releases(
            session, tmdb_id=tmdbid, imdb_id=imdbid, tvdb_id=tvdbid,
            q=q, content_type="tv", season=season, episode=ep,
            source_type="usenet", limit=limit, offset=offset,
        )
        return await _feed(session, releases)

    if t in ("adult", "adult-search", "adultsearch"):
        releases = await query_tpdb_releases(
            session, tpdb_id=tpdbid, q=q,
            source_type="usenet", limit=limit, offset=offset,
        )
        return await _feed(session, releases)

    return make_newznab_feed([], settings.api_base_url)
