from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_session
from src.storage.repositories.performer_repo import get_performer, search_performers

router = APIRouter()


def _performer_dict(p) -> dict[str, Any]:
    return {
        "id": str(p.id),
        "name": p.name,
        "gender": p.gender,
        "birthday": p.birthday.isoformat() if p.birthday else None,
        "height_cm": p.height_cm,
        "rating": p.rating,
        "poster_url": p.poster_url,
    }


@router.get("/performers")
async def list_performers(
    q: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(30, ge=1, le=250),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    performers = await search_performers(
        session, name=q, limit=per_page, offset=(page - 1) * per_page
    )
    return {"page": page, "per_page": per_page, "results": [_performer_dict(p) for p in performers]}


@router.get("/performers/{performer_id}")
async def get_performer_detail(
    performer_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    p = await get_performer(session, performer_id)
    if p is None:
        raise HTTPException(status_code=404, detail="Performer not found")
    return _performer_dict(p)
