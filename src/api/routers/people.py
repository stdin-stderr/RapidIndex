from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_session
from src.storage.models import TmdbMetadata, TmdbMetadataCast, TmdbPerson

router = APIRouter()


@router.get("/people/{tmdb_person_id}")
async def get_person(
    tmdb_person_id: int,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    result = await session.execute(
        select(TmdbPerson).where(TmdbPerson.tmdb_person_id == tmdb_person_id)
    )
    person = result.scalar_one_or_none()
    if person is None:
        raise HTTPException(status_code=404, detail="Person not found")

    titles_result = await session.execute(
        select(TmdbMetadata)
        .join(TmdbMetadataCast, TmdbMetadataCast.tmdb_metadata_id == TmdbMetadata.id)
        .where(TmdbMetadataCast.tmdb_person_id == tmdb_person_id)
        .order_by(TmdbMetadataCast.cast_order)
    )
    titles = list(titles_result.scalars().all())

    return {
        "tmdb_person_id": person.tmdb_person_id,
        "name": person.name,
        "profile_path": person.profile_path,
        "popularity": person.popularity,
        "titles": [
            {"tmdb_id": t.tmdb_id, "title": t.title, "tmdb_type": t.tmdb_type}
            for t in titles
        ],
    }
