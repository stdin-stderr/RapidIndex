from typing import Any, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_session
from src.storage.repositories.release_repo import search_releases

router = APIRouter()


@router.get("/releases")
async def list_releases(
    q: Optional[str] = Query(None),
    source_type: Optional[str] = Query(None),
    content_type: Optional[str] = Query(None),
    quality: Optional[str] = Query(None),
    metadata_status: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(30, ge=1, le=250),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    offset = (page - 1) * per_page
    releases = await search_releases(
        session,
        q=q,
        source_type=source_type,
        content_type=content_type,
        quality=quality,
        metadata_status=metadata_status,
        limit=per_page,
        offset=offset,
    )
    return {
        "page": page,
        "per_page": per_page,
        "results": [
            {
                "id": str(r.id),
                "source_type": r.source_type,
                "source_name": r.source_name,
                "raw_title": r.raw_title,
                "content_type": r.content_type,
                "quality": r.quality,
                "season": r.season,
                "episode": r.episode,
                "file_size_bytes": r.file_size_bytes,
                "published_at": r.published_at.isoformat() if r.published_at else None,
                "metadata_status": r.metadata_status,
                "metadata_score": r.metadata_score,
                "indexed_at": r.indexed_at.isoformat() if r.indexed_at else None,
            }
            for r in releases
        ],
    }
