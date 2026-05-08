from typing import Optional
from uuid import UUID

from sqlalchemy import Text, cast, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.storage.models import Release, ReleaseTpdbScene, TorrentRelease, TpdbScene, TpdbSite


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
    network_id: Optional[int] = None,
    tag: Optional[str] = None,
    sort_by: str = "seeders",
    limit: int = 100,
    offset: int = 0,
) -> list[TpdbScene]:
    stmt = select(TpdbScene).options(selectinload(TpdbScene.site).selectinload(TpdbSite.network))
    if q:
        stmt = stmt.where(TpdbScene.title.ilike(f"%{q}%"))
    if site_id is not None:
        stmt = stmt.where(TpdbScene.site_id == site_id)
    if network_id is not None:
        stmt = stmt.join(TpdbSite, TpdbSite.id == TpdbScene.site_id).where(TpdbSite.network_id == network_id)
    if performer:
        stmt = stmt.where(cast(TpdbScene.performers, Text).ilike(f"%{performer}%"))
    if tag:
        stmt = stmt.where(cast(TpdbScene.tags, Text).ilike(f"%{tag}%"))

    if sort_by == "seeders":
        seeder_subq = (
            select(func.coalesce(func.max(TorrentRelease.seeders), 0))
            .join(Release, Release.id == TorrentRelease.release_id)
            .join(ReleaseTpdbScene, ReleaseTpdbScene.release_id == Release.id)
            .where(ReleaseTpdbScene.scene_id == TpdbScene.id)
            .scalar_subquery()
        )
        stmt = stmt.order_by(seeder_subq.desc())
    else:
        stmt = stmt.order_by(TpdbScene.date.desc().nullslast())

    stmt = stmt.limit(limit).offset(offset)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_max_seeders_for_scenes(
    session: AsyncSession, scene_ids: list[UUID]
) -> dict[UUID, int]:
    """Return max seeders per scene_id for a list of scene IDs."""
    if not scene_ids:
        return {}
    stmt = (
        select(ReleaseTpdbScene.scene_id, func.coalesce(func.max(TorrentRelease.seeders), 0))
        .join(Release, Release.id == ReleaseTpdbScene.release_id)
        .join(TorrentRelease, TorrentRelease.release_id == Release.id)
        .where(ReleaseTpdbScene.scene_id.in_(scene_ids))
        .group_by(ReleaseTpdbScene.scene_id)
    )
    result = await session.execute(stmt)
    return {row[0]: row[1] for row in result.all()}
