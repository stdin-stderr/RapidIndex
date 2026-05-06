from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_session
from src.storage.models import ReleaseTmdbTitle, TmdbMetadata
from src.storage.repositories.people_repo import get_cast_for_title

router = APIRouter()


@router.get("/titles")
async def list_titles(
    q: Optional[str] = Query(None),
    type: Optional[str] = Query(None),
    year: Optional[int] = Query(None),
    imdb_id: Optional[str] = Query(None),
    tmdb_id: Optional[int] = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(30, ge=1, le=250),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    stmt = select(TmdbMetadata)
    if q:
        stmt = stmt.where(TmdbMetadata.title.ilike(f"%{q}%"))
    if type:
        stmt = stmt.where(TmdbMetadata.tmdb_type == type)
    if year:
        stmt = stmt.where(TmdbMetadata.release_year == year)
    if imdb_id:
        stmt = stmt.where(TmdbMetadata.imdb_id == imdb_id)
    if tmdb_id:
        stmt = stmt.where(TmdbMetadata.tmdb_id == tmdb_id)
    stmt = stmt.order_by(TmdbMetadata.tmdb_id.desc()).limit(per_page).offset((page - 1) * per_page)
    rows = list((await session.execute(stmt)).scalars().all())

    return {
        "page": page,
        "per_page": per_page,
        "results": [
            {
                "tmdb_id": t.tmdb_id,
                "tmdb_type": t.tmdb_type,
                "title": t.title,
                "original_title": t.original_title,
                "release_year": t.release_year,
                "overview": t.overview,
                "rating": t.rating,
                "genres": t.genres,
                "poster_path": t.poster_path,
                "imdb_id": t.imdb_id,
                "tvdb_id": t.tvdb_id,
            }
            for t in rows
        ],
    }


@router.get("/titles/{tmdb_id}/cast")
async def get_cast(
    tmdb_id: int,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    result = await session.execute(
        select(TmdbMetadata).where(TmdbMetadata.tmdb_id == tmdb_id)
    )
    title = result.scalar_one_or_none()
    if title is None:
        raise HTTPException(status_code=404, detail="Title not found")

    cast = await get_cast_for_title(session, title.id)
    return {
        "tmdb_id": tmdb_id,
        "cast": [
            {
                "tmdb_person_id": p.tmdb_person_id,
                "name": p.name,
                "profile_path": p.profile_path,
            }
            for p in cast
        ],
    }
