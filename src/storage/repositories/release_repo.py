from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import delete, exists, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.storage.models import PendingEnrichment, Release, ReleaseTmdbTitle, ReleaseTpdbScene, TmdbMetadata, TorrentFile, TorrentRelease, TpdbScene, UsenetFile, UsenetRelease


async def upsert_release(
    session: AsyncSession,
    *,
    source_type: str,
    source_name: str,
    source_key: str,
    raw_title: str,
    raw_category: Optional[str],
    file_size_bytes: Optional[int],
    published_at: Optional[datetime],
    date=None,
    quality: Optional[str],
    content_type: Optional[str],
    season: Optional[int],
    episode: Optional[int],
    hints: Optional[dict],
    enricher: str,
    metadata_status: str = "pending",
    # Usenet-specific
    newsgroup: Optional[str] = None,
    poster: Optional[str] = None,
    nzb_xml: Optional[bytes] = None,
    # Torrent-specific
    info_hash: Optional[str] = None,
    magnet_uri: Optional[str] = None,
    seeders: Optional[int] = None,
    leechers: Optional[int] = None,
    # File metadata
    files: Optional[list[dict]] = None,
) -> Release:
    stmt = (
        insert(Release)
        .values(
            source_type=source_type,
            source_name=source_name,
            source_key=source_key,
            raw_title=raw_title,
            raw_category=raw_category,
            file_size_bytes=file_size_bytes,
            published_at=published_at,
            date=date,
            quality=quality,
            content_type=content_type,
            season=season,
            episode=episode,
            hints=hints,
            enricher=enricher,
            metadata_status=metadata_status,
        )
        .on_conflict_do_update(
            index_elements=["source_key"],
            set_={
                # Only mutable fields — hints is intentionally excluded (written once).
                "updated_at": datetime.now(timezone.utc),
            },
        )
        .returning(Release)
    )
    result = await session.execute(stmt)
    release = result.scalar_one()

    if source_type == "usenet" and nzb_xml is not None:
        side = insert(UsenetRelease).values(
            release_id=release.id,
            groups=newsgroup,
            poster=poster,
            nzb_xml=nzb_xml,
        ).on_conflict_do_nothing()
        await session.execute(side)

    elif source_type == "torrent":
        side = (
            insert(TorrentRelease)
            .values(
                release_id=release.id,
                info_hash=info_hash,
                magnet_uri=magnet_uri,
                size_bytes=file_size_bytes,
                seeders=seeders,
                leechers=leechers,
            )
            .on_conflict_do_update(
                index_elements=["release_id"],
                set_={"seeders": seeders, "leechers": leechers},
            )
        )
        await session.execute(side)

    # Insert file metadata
    if files:
        if source_type == "usenet":
            # Delete existing files for this release (idempotent re-index)
            await session.execute(delete(UsenetFile).where(UsenetFile.release_id == release.id))
            # Insert new files
            for f in files:
                await session.execute(
                    insert(UsenetFile).values(
                        release_id=release.id,
                        filename=f.get("filename"),
                        file_size_bytes=f.get("file_size_bytes", 0),
                        file_index=f.get("file_index", 0),
                        segment_ids=f.get("segment_ids", []),
                    )
                )
        elif source_type == "torrent":
            # Delete existing files for this release (idempotent re-index)
            await session.execute(delete(TorrentFile).where(TorrentFile.release_id == release.id))
            # Insert new files
            for f in files:
                await session.execute(
                    insert(TorrentFile).values(
                        release_id=release.id,
                        filename=f.get("filename"),
                        file_size_bytes=f.get("file_size_bytes", 0),
                        file_index=f.get("file_index", 0),
                    )
                )

    if metadata_status == "pending":
        already_queued = await session.scalar(
            select(exists().where(PendingEnrichment.release_id == release.id))
        )
        if not already_queued:
            await session.execute(
                insert(PendingEnrichment).values(
                    release_id=release.id,
                    enricher=enricher,
                )
            )

    await session.commit()
    return release


async def get_by_source_key(session: AsyncSession, source_key: str) -> Optional[Release]:
    result = await session.execute(
        select(Release).where(Release.source_key == source_key)
    )
    return result.scalar_one_or_none()


async def search_releases(
    session: AsyncSession,
    *,
    q: Optional[str] = None,
    content_type: Optional[str] = None,
    quality: Optional[str] = None,
    source_type: Optional[str] = None,
    metadata_status: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> list[Release]:
    stmt = select(Release)
    if q:
        stmt = stmt.where(Release.raw_title.ilike(f"%{q}%"))
    if content_type:
        stmt = stmt.where(Release.content_type == content_type)
    if quality:
        stmt = stmt.where(Release.quality == quality)
    if source_type:
        stmt = stmt.where(Release.source_type == source_type)
    if metadata_status:
        stmt = stmt.where(Release.metadata_status == metadata_status)
    stmt = stmt.order_by(Release.indexed_at.desc()).limit(limit).offset(offset)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def count_releases(
    session: AsyncSession,
    *,
    q: Optional[str] = None,
    content_type: Optional[str] = None,
    quality: Optional[str] = None,
    source_type: Optional[str] = None,
    metadata_status: Optional[str] = None,
) -> int:
    stmt = select(func.count()).select_from(Release)
    if q:
        stmt = stmt.where(Release.raw_title.ilike(f"%{q}%"))
    if content_type:
        stmt = stmt.where(Release.content_type == content_type)
    if quality:
        stmt = stmt.where(Release.quality == quality)
    if source_type:
        stmt = stmt.where(Release.source_type == source_type)
    if metadata_status:
        stmt = stmt.where(Release.metadata_status == metadata_status)
    return await session.scalar(stmt) or 0


async def query_tmdb_releases(
    session: AsyncSession,
    *,
    tmdb_id: Optional[int] = None,
    imdb_id: Optional[str] = None,
    tvdb_id: Optional[int] = None,
    q: Optional[str] = None,
    content_type: Optional[str] = None,
    season: Optional[int] = None,
    episode: Optional[int] = None,
    source_type: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> list[Release]:
    stmt = select(Release).join(ReleaseTmdbTitle, ReleaseTmdbTitle.release_id == Release.id)

    needs_metadata = imdb_id is not None or tvdb_id is not None or (
        tmdb_id is None and content_type is not None
    )
    if needs_metadata:
        stmt = stmt.join(TmdbMetadata, TmdbMetadata.tmdb_id == ReleaseTmdbTitle.tmdb_id)

    if tmdb_id is not None:
        stmt = stmt.where(ReleaseTmdbTitle.tmdb_id == tmdb_id)
    elif imdb_id is not None:
        stmt = stmt.where(TmdbMetadata.imdb_id == imdb_id)
    elif tvdb_id is not None:
        stmt = stmt.where(TmdbMetadata.tvdb_id == tvdb_id)

    if content_type is not None:
        stmt = stmt.where(Release.content_type == content_type)
        if needs_metadata:
            stmt = stmt.where(TmdbMetadata.tmdb_type == content_type)

    if season is not None:
        stmt = stmt.where(Release.season == season)
    if episode is not None:
        stmt = stmt.where(Release.episode == episode)
    if source_type is not None:
        stmt = stmt.where(Release.source_type == source_type)
    if q:
        stmt = stmt.where(Release.raw_title.ilike(f"%{q}%"))

    if needs_metadata:
        stmt = stmt.distinct()

    stmt = stmt.order_by(Release.indexed_at.desc()).limit(limit).offset(offset)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def count_tmdb_releases(
    session: AsyncSession,
    *,
    tmdb_id: Optional[int] = None,
    imdb_id: Optional[str] = None,
    tvdb_id: Optional[int] = None,
    q: Optional[str] = None,
    content_type: Optional[str] = None,
    season: Optional[int] = None,
    episode: Optional[int] = None,
    source_type: Optional[str] = None,
) -> int:
    needs_metadata = imdb_id is not None or tvdb_id is not None or (
        tmdb_id is None and content_type is not None
    )
    base = select(Release.id).join(ReleaseTmdbTitle, ReleaseTmdbTitle.release_id == Release.id)
    if needs_metadata:
        base = base.join(TmdbMetadata, TmdbMetadata.tmdb_id == ReleaseTmdbTitle.tmdb_id)
    if tmdb_id is not None:
        base = base.where(ReleaseTmdbTitle.tmdb_id == tmdb_id)
    elif imdb_id is not None:
        base = base.where(TmdbMetadata.imdb_id == imdb_id)
    elif tvdb_id is not None:
        base = base.where(TmdbMetadata.tvdb_id == tvdb_id)
    if content_type is not None:
        base = base.where(Release.content_type == content_type)
        if needs_metadata:
            base = base.where(TmdbMetadata.tmdb_type == content_type)
    if season is not None:
        base = base.where(Release.season == season)
    if episode is not None:
        base = base.where(Release.episode == episode)
    if source_type is not None:
        base = base.where(Release.source_type == source_type)
    if q:
        base = base.where(Release.raw_title.ilike(f"%{q}%"))
    if needs_metadata:
        base = base.distinct()
    return await session.scalar(select(func.count()).select_from(base.subquery())) or 0


async def count_tpdb_releases(
    session: AsyncSession,
    *,
    tpdb_id: Optional[str] = None,
    q: Optional[str] = None,
    source_type: Optional[str] = None,
) -> int:
    base = (
        select(Release.id)
        .join(ReleaseTpdbScene, ReleaseTpdbScene.release_id == Release.id)
        .where(Release.content_type == "xxx")
    )
    if tpdb_id:
        base = base.where(ReleaseTpdbScene.scene_id == UUID(tpdb_id))
    if q:
        base = base.join(TpdbScene, TpdbScene.id == ReleaseTpdbScene.scene_id)
        base = base.where(
            Release.raw_title.ilike(f"%{q}%") | TpdbScene.title.ilike(f"%{q}%")
        )
    if source_type:
        base = base.where(Release.source_type == source_type)
    return await session.scalar(select(func.count()).select_from(base.distinct().subquery())) or 0


async def query_tpdb_releases(
    session: AsyncSession,
    *,
    tpdb_id: Optional[str] = None,
    q: Optional[str] = None,
    source_type: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> list[Release]:
    stmt = (
        select(Release)
        .join(ReleaseTpdbScene, ReleaseTpdbScene.release_id == Release.id)
        .where(Release.content_type == "xxx")
    )
    if tpdb_id:
        stmt = stmt.where(ReleaseTpdbScene.scene_id == UUID(tpdb_id))
    if q:
        stmt = stmt.join(TpdbScene, TpdbScene.id == ReleaseTpdbScene.scene_id)
        stmt = stmt.where(
            Release.raw_title.ilike(f"%{q}%") | TpdbScene.title.ilike(f"%{q}%")
        )
    if source_type:
        stmt = stmt.where(Release.source_type == source_type)
    stmt = stmt.distinct().order_by(Release.indexed_at.desc()).limit(limit).offset(offset)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def claim_enrichment_batch(
    session: AsyncSession,
    batch_size: int = 10,
    lease_minutes: int = 5,
    enricher_types: list[str] | None = None,
) -> list[PendingEnrichment]:
    """Atomically claim a batch and stamp a lease so other workers skip them.

    Uses a CTE with FOR UPDATE SKIP LOCKED to select candidates, then
    immediately updates next_attempt to now+lease so the rows are invisible
    to concurrent workers even after this session commits.
    """
    now = datetime.now(timezone.utc)
    lease_until = now + timedelta(minutes=lease_minutes)

    ready = (
        (PendingEnrichment.next_attempt == None)  # noqa: E711
        | (PendingEnrichment.next_attempt <= now)
    )
    cte = (
        select(PendingEnrichment.id)
        .where(ready if enricher_types is None else ready & PendingEnrichment.enricher.in_(enricher_types))
        .limit(batch_size)
        .with_for_update(skip_locked=True)
        .cte("claimed")
    )
    stmt = (
        update(PendingEnrichment)
        .where(PendingEnrichment.id.in_(select(cte.c.id)))
        .values(next_attempt=lease_until)
        .returning(PendingEnrichment)
    )
    result = await session.execute(stmt)
    items = list(result.scalars().all())
    await session.commit()
    return items


async def complete_enrichment(
    session: AsyncSession,
    pending_id: int,
    score: float,
    matched_at: datetime,
    release_id: UUID,
    tmdb_id: Optional[int] = None,
    scene_id: Optional[UUID] = None,
) -> None:
    await session.execute(
        update(Release)
        .where(Release.id == release_id)
        .values(
            metadata_status="matched",
            metadata_score=score,
            matched_at=matched_at,
            updated_at=datetime.now(timezone.utc),
        )
    )
    await session.execute(
        delete(PendingEnrichment).where(PendingEnrichment.id == pending_id)
    )
    await session.commit()


async def fail_enrichment(
    session: AsyncSession,
    pending_id: int,
    release_id: UUID,
    retry_after: Optional[datetime],
) -> None:
    row = await session.get(PendingEnrichment, pending_id)
    if row is None:
        return

    if retry_after is None:
        # Second no-match — permanently failed
        await session.execute(
            update(Release)
            .where(Release.id == release_id)
            .values(metadata_status="match_failed", updated_at=datetime.now(timezone.utc))
        )
        await session.delete(row)
    else:
        row.attempts += 1
        row.next_attempt = retry_after

    await session.commit()
