from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.storage.models import TpdbPerformer


async def upsert_performer(session: AsyncSession, performer_data: dict) -> TpdbPerformer:
    stmt = (
        insert(TpdbPerformer)
        .values(**performer_data)
        .on_conflict_do_update(
            index_elements=["id"],
            set_={k: v for k, v in performer_data.items() if k != "id"},
        )
        .returning(TpdbPerformer)
    )
    result = await session.execute(stmt)
    performer = result.scalar_one()
    await session.commit()
    return performer


async def get_performer(
    session: AsyncSession, performer_id: UUID
) -> Optional[TpdbPerformer]:
    result = await session.execute(
        select(TpdbPerformer).where(TpdbPerformer.id == performer_id)
    )
    return result.scalar_one_or_none()


async def search_performers(
    session: AsyncSession,
    *,
    name: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> list[TpdbPerformer]:
    stmt = select(TpdbPerformer)
    if name:
        stmt = stmt.where(TpdbPerformer.name.ilike(f"%{name}%"))
    stmt = stmt.order_by(TpdbPerformer.name).limit(limit).offset(offset)
    result = await session.execute(stmt)
    return list(result.scalars().all())
