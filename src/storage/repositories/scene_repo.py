from typing import Optional
from uuid import UUID

from sqlalchemy import Text, cast, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.storage.models import ReleaseTpdbScene, TpdbScene


async def upsert_scene(session: AsyncSession, scene_data: dict) -> TpdbScene:
    stmt = (
        insert(TpdbScene)
        .values(**scene_data)
        .on_conflict_do_update(
            index_elements=["id"],
            set_={k: v for k, v in scene_data.items() if k != "id"},
        )
        .returning(TpdbScene)
    )
    result = await session.execute(stmt)
    scene = result.scalar_one()
    await session.commit()
    return scene


async def link_release_to_scene(
    session: AsyncSession, release_id: UUID, scene_id: UUID
) -> None:
    stmt = (
        insert(ReleaseTpdbScene)
        .values(release_id=release_id, scene_id=scene_id)
        .on_conflict_do_nothing()
    )
    await session.execute(stmt)
    await session.commit()


async def get_scene(session: AsyncSession, scene_id: UUID) -> Optional[TpdbScene]:
    result = await session.execute(
        select(TpdbScene).where(TpdbScene.id == scene_id)
    )
    return result.scalar_one_or_none()


async def search_scenes(
    session: AsyncSession,
    *,
    q: Optional[str] = None,
    performer: Optional[str] = None,
    site_id: Optional[int] = None,
    tag: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> list[TpdbScene]:
    stmt = select(TpdbScene)
    if q:
        stmt = stmt.where(TpdbScene.title.ilike(f"%{q}%"))
    if site_id is not None:
        stmt = stmt.where(TpdbScene.site_id == site_id)
    if performer:
        stmt = stmt.where(cast(TpdbScene.performers, Text).ilike(f"%{performer}%"))
    if tag:
        stmt = stmt.where(cast(TpdbScene.tags, Text).ilike(f"%{tag}%"))
    stmt = stmt.order_by(TpdbScene.date.desc().nullslast()).limit(limit).offset(offset)
    result = await session.execute(stmt)
    return list(result.scalars().all())
