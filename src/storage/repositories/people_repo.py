from typing import Optional

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.storage.models import TmdbMetadataCast, TmdbPerson


async def upsert_person(session: AsyncSession, person_data: dict) -> TmdbPerson:
    stmt = (
        insert(TmdbPerson)
        .values(**person_data)
        .on_conflict_do_update(
            index_elements=["tmdb_person_id"],
            set_={k: v for k, v in person_data.items() if k != "tmdb_person_id"},
        )
        .returning(TmdbPerson)
    )
    result = await session.execute(stmt)
    person = result.scalar_one()
    await session.commit()
    return person


async def upsert_cast(
    session: AsyncSession,
    tmdb_metadata_id: int,
    tmdb_person_id: int,
    character: Optional[str],
    cast_order: int,
) -> None:
    stmt = (
        insert(TmdbMetadataCast)
        .values(
            tmdb_metadata_id=tmdb_metadata_id,
            tmdb_person_id=tmdb_person_id,
            character=character,
            cast_order=cast_order,
        )
        .on_conflict_do_update(
            index_elements=["tmdb_metadata_id", "tmdb_person_id"],
            set_={"character": character, "cast_order": cast_order},
        )
    )
    await session.execute(stmt)
    await session.commit()


async def get_cast_for_title(
    session: AsyncSession, tmdb_metadata_id: int
) -> list[TmdbPerson]:
    stmt = (
        select(TmdbPerson)
        .join(
            TmdbMetadataCast,
            TmdbMetadataCast.tmdb_person_id == TmdbPerson.tmdb_person_id,
        )
        .where(TmdbMetadataCast.tmdb_metadata_id == tmdb_metadata_id)
        .order_by(TmdbMetadataCast.cast_order)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())
