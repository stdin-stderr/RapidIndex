from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import delete, exists, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.storage.models import PendingEnrichment, Release, TorrentRelease, UsenetRelease


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
                "updated_at": datetime.utcnow(),
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
    stmt = stmt.order_by(Release.indexed_at.desc()).limit(limit).offset(offset)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def claim_enrichment_batch(
    session: AsyncSession, batch_size: int = 10, lease_minutes: int = 5
) -> list[PendingEnrichment]:
    """Atomically claim a batch and stamp a lease so other workers skip them.

    Uses a CTE with FOR UPDATE SKIP LOCKED to select candidates, then
    immediately updates next_attempt to now+lease so the rows are invisible
    to concurrent workers even after this session commits.
    """
    now = datetime.now(timezone.utc)
    lease_until = now + timedelta(minutes=lease_minutes)

    cte = (
        select(PendingEnrichment.id)
        .where(
            (PendingEnrichment.next_attempt == None)  # noqa: E711
            | (PendingEnrichment.next_attempt <= now)
        )
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
