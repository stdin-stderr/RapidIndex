from typing import Any, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import Text, cast as sa_cast, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_session
from src.storage.models import TpdbScene
from src.storage.repositories.scene_repo import search_scenes

router = APIRouter()


def _scene_dict(s) -> dict[str, Any]:
    return {
        "id": str(s.id),
        "tpdb_type": s.tpdb_type,
        "title": s.title,
        "date": s.date.isoformat() if s.date else None,
        "duration_secs": s.duration_secs,
        "site_id": s.site_id,
        "performers": s.performers,
        "tags": s.tags,
        "poster_url": s.poster_url,
    }


@router.get("/scenes")
async def list_scenes(
    q: Optional[str] = Query(None),
    performer: Optional[str] = Query(None),
    site: Optional[str] = Query(None),
    tag: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(30, ge=1, le=250),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    scenes = await search_scenes(
        session, q=q, performer=performer, tag=tag,
        limit=per_page, offset=(page - 1) * per_page,
    )
    return {"page": page, "per_page": per_page, "results": [_scene_dict(s) for s in scenes]}


@router.get("/movies")
async def list_tpdb_movies(
    q: Optional[str] = Query(None),
    performer: Optional[str] = Query(None),
    site: Optional[str] = Query(None),
    tag: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(30, ge=1, le=250),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    stmt = select(TpdbScene).where(TpdbScene.tpdb_type == "movie")
    if q:
        stmt = stmt.where(TpdbScene.title.ilike(f"%{q}%"))
    if performer:
        stmt = stmt.where(sa_cast(TpdbScene.performers, Text).ilike(f"%{performer}%"))
    if tag:
        stmt = stmt.where(sa_cast(TpdbScene.tags, Text).ilike(f"%{tag}%"))
    stmt = stmt.order_by(TpdbScene.date.desc().nullslast()).limit(per_page).offset((page - 1) * per_page)
    result = await session.execute(stmt)
    scenes = list(result.scalars().all())
    return {"page": page, "per_page": per_page, "results": [_scene_dict(s) for s in scenes]}
