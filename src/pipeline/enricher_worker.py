"""Enricher worker.

Drains the pending_enrichment queue: claims batches, routes each release to the
correct enricher, writes metadata, and marks releases as matched or failed.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, update
from sqlalchemy.dialects.postgresql import insert

from src.config import Settings
from src.enrichers.base import Enricher
from src.enrichers.tmdb import TMDBEnricher
from src.routing.content_router import EnricherType, route
from src.storage.models import (
    PendingEnrichment,
    Release,
    ReleaseTmdbTitle,
    TmdbMetadata,
    TpdbNetwork,
    TpdbSite,
)
from src.storage.repositories.people_repo import get_cast_for_title, upsert_cast, upsert_person
from src.storage.repositories.performer_repo import upsert_performer
from src.storage.repositories.release_repo import claim_enrichment_batch, complete_enrichment, fail_enrichment
from src.storage.repositories.scene_repo import link_release_to_scene, upsert_scene
from src.utils.http import get_client

log = logging.getLogger(__name__)

_MAX_ATTEMPTS = 2
_BATCH_SIZE = 10
_SLEEP_EMPTY = 5.0


def _build_enrichers(settings: Settings) -> dict[EnricherType, Enricher]:
    client = get_client()
    tmdb = TMDBEnricher(settings, client)
    enrichers: dict[EnricherType, Enricher] = {
        EnricherType.TMDB_MOVIE: tmdb,
        EnricherType.TMDB_TV: tmdb,
    }
    if settings.tpdb_api_key:
        try:
            from src.enrichers.tpdb import TPDBEnricher
            enrichers[EnricherType.TPDB] = TPDBEnricher(settings, client)
        except ModuleNotFoundError:
            log.warning("tpdb_api_key is set but src/enrichers/tpdb.py is not implemented yet — skipping TPDB enricher")
    return enrichers


async def _write_tmdb_match(session, release_id, metadata: dict, parsed) -> None:
    """Upsert TmdbMetadata, link join row, write cast if new."""
    now = datetime.now(timezone.utc)

    tmdb_fields = {k: v for k, v in metadata.items() if k != "cast"}
    tmdb_stmt = (
        insert(TmdbMetadata)
        .values(**tmdb_fields, fetched_at=now)
        .on_conflict_do_update(
            index_elements=["tmdb_id"],
            set_={k: v for k, v in tmdb_fields.items() if k != "tmdb_id"},
        )
        .returning(TmdbMetadata)
    )
    result = await session.execute(tmdb_stmt)
    tmdb_row = result.scalar_one()
    await session.commit()

    join_stmt = (
        insert(ReleaseTmdbTitle)
        .values(release_id=release_id, tmdb_id=tmdb_row.tmdb_id)
        .on_conflict_do_nothing()
    )
    await session.execute(join_stmt)
    await session.commit()

    # Write cast only if this title has no cast yet (avoids duplicate API cost).
    existing = await get_cast_for_title(session, tmdb_row.id)
    if not existing:
        for member in metadata.get("cast", []):
            await upsert_person(session, {
                "tmdb_person_id": member["tmdb_person_id"],
                "name": member["name"],
                "profile_path": member.get("profile_path"),
                "popularity": member.get("popularity"),
                "fetched_at": now,
            })
            await upsert_cast(
                session,
                tmdb_metadata_id=tmdb_row.id,
                tmdb_person_id=member["tmdb_person_id"],
                character=member.get("character"),
                cast_order=member.get("cast_order", 0),
            )

    # Write back parsed fields to the release row.
    await session.execute(
        update(Release)
        .where(Release.id == release_id)
        .values(
            season=parsed.season,
            episode=parsed.episode,
            quality=parsed.resolution,
            date=parsed.release_date,
            updated_at=now,
        )
    )
    await session.commit()


async def _write_tpdb_match(session, release_id, metadata: dict, parsed) -> None:
    """Upsert TpdbScene + site/network/performers, link to release."""
    now = datetime.now(timezone.utc)

    # 1. Upsert network (FK dep for site)
    site = metadata.get("site")
    site_id: int | None = None
    if site:
        if network := site.get("network"):
            await session.execute(
                insert(TpdbNetwork)
                .values(id=network["id"], name=network.get("name"), slug=network.get("slug"))
                .on_conflict_do_update(
                    index_elements=["id"],
                    set_={"name": network.get("name"), "slug": network.get("slug")},
                )
            )
            await session.commit()

        # 2. Upsert site
        site_id = site["id"]
        network_id = site.get("network", {}).get("id") if site.get("network") else None
        await session.execute(
            insert(TpdbSite)
            .values(
                id=site_id,
                name=site.get("name"),
                slug=site.get("slug"),
                logo_url=site.get("logo_url"),
                network_id=network_id,
            )
            .on_conflict_do_update(
                index_elements=["id"],
                set_={
                    "name": site.get("name"),
                    "slug": site.get("slug"),
                    "logo_url": site.get("logo_url"),
                    "network_id": network_id,
                },
            )
        )
        await session.commit()

    # 3. Upsert scene
    scene_data = {
        k: v for k, v in metadata.items()
        if k not in ("site", "performer_profiles")
    }
    scene_data["site_id"] = site_id
    scene_data["fetched_at"] = now
    await upsert_scene(session, scene_data)

    # 4. Link release → scene
    await link_release_to_scene(session, release_id, metadata["id"])

    # 5. Upsert performer rows (normalised table)
    for profile in metadata.get("performer_profiles") or []:
        if profile.get("id"):
            await upsert_performer(session, {**profile, "fetched_at": now})

    # 6. Write back parsed fields to the release row
    await session.execute(
        update(Release)
        .where(Release.id == release_id)
        .values(quality=parsed.resolution, date=parsed.release_date, updated_at=now)
    )
    await session.commit()


async def _mark_skipped(session, pending_id: int, release_id) -> None:
    await session.execute(
        update(Release)
        .where(Release.id == release_id)
        .values(metadata_status="skipped", updated_at=datetime.now(timezone.utc))
    )
    await session.execute(
        delete(PendingEnrichment).where(PendingEnrichment.id == pending_id)
    )
    await session.commit()


async def _process_item(
    session,
    item: PendingEnrichment,
    settings: Settings,
    enrichers: dict[EnricherType, Enricher],
) -> None:
    release = await session.get(Release, item.release_id)
    if release is None:
        log.warning("pending item %d has no release, removing", item.id)
        await session.execute(
            delete(PendingEnrichment).where(PendingEnrichment.id == item.id)
        )
        await session.commit()
        return

    enricher_type, parsed = route(release, settings)

    if enricher_type == EnricherType.SKIP:
        log.debug("skipping %s (%s)", release.raw_title, release.raw_category)
        await _mark_skipped(session, item.id, release.id)
        return

    enricher = enrichers.get(enricher_type)
    if enricher is None:
        log.debug("no enricher for %s, skipping %s", enricher_type, release.raw_title)
        await _mark_skipped(session, item.id, release.id)
        return

    try:
        result = await enricher.enrich(release, parsed)
    except Exception as exc:
        # API/network error — don't count as a failure attempt, leave in queue.
        log.warning("enricher error for %r: %s", release.raw_title, exc)
        return

    if result.matched:
        log.info(
            "matched %r → %s (score=%.2f tmdb=%s)",
            release.raw_title, enricher_type.value, result.score, result.external_id,
        )
        if enricher_type in (EnricherType.TMDB_MOVIE, EnricherType.TMDB_TV):
            await _write_tmdb_match(session, release.id, result.metadata, parsed)
        elif enricher_type == EnricherType.TPDB:
            await _write_tpdb_match(session, release.id, result.metadata, parsed)
        await complete_enrichment(
            session,
            pending_id=item.id,
            score=result.score,
            matched_at=datetime.now(timezone.utc),
            release_id=release.id,
        )
    else:
        log.debug("no match for %r (attempts=%d)", release.raw_title, item.attempts)
        if item.attempts >= _MAX_ATTEMPTS - 1:
            retry_after = None  # permanently failed after second no-match
        else:
            retry_after = datetime.now(timezone.utc) + timedelta(days=7)
        await fail_enrichment(session, item.id, release.id, retry_after)


async def run_worker(session_factory, settings: Settings) -> None:
    """Drain the pending_enrichment queue forever."""
    enrichers = _build_enrichers(settings)
    log.info("Enricher worker started (batch=%d, max_attempts=%d)", _BATCH_SIZE, _MAX_ATTEMPTS)

    while True:
        async with session_factory() as session:
            batch = await claim_enrichment_batch(session, batch_size=_BATCH_SIZE)

        if not batch:
            await asyncio.sleep(_SLEEP_EMPTY)
            continue

        for item in batch:
            async with session_factory() as session:
                try:
                    await _process_item(session, item, settings, enrichers)
                except Exception as exc:
                    log.exception("unexpected error processing item %d: %s", item.id, exc)


async def run_workers(session_factory, settings: Settings) -> None:
    """Launch N concurrent worker tasks."""
    tasks = [
        asyncio.create_task(run_worker(session_factory, settings))
        for _ in range(settings.enricher_workers)
    ]
    await asyncio.gather(*tasks)
