"""Ingester scheduler.

Runs each configured ingester on its interval. For every RawRelease yielded,
normalises the category, determines the enricher, and upserts into the DB.
The content router (pipeline/enricher_worker.py) re-routes at dequeue time
using the parsed title, so the enricher stored here is a best-effort value.
"""

from __future__ import annotations

import asyncio
import logging

from src.ingesters.base import Ingester, RawRelease
from src.storage.repositories.release_repo import upsert_release
from src.utils.categories import ContentCategory, normalise_category

log = logging.getLogger(__name__)


def _enricher_for(ct: ContentCategory) -> str:
    if ct == ContentCategory.XXX:
        return "tpdb"
    if ct == ContentCategory.TV:
        return "tmdb_tv"
    if ct in (ContentCategory.MOVIE, ContentCategory.VIDEO):
        return "tmdb_movie"
    return "skip"


async def _process_release(session_factory, raw: RawRelease) -> None:
    content_type = normalise_category(raw.source_name, raw.raw_category or "")
    enricher = _enricher_for(content_type)
    metadata_status = "pending" if enricher != "skip" else "skipped"

    async with session_factory() as session:
        await upsert_release(
            session,
            source_type=raw.source_type,
            source_name=raw.source_name,
            source_key=raw.source_key,
            raw_title=raw.raw_title,
            raw_category=raw.raw_category,
            file_size_bytes=raw.file_size_bytes,
            published_at=raw.published_at,
            quality=None,
            content_type=str(content_type),
            season=None,
            episode=None,
            hints=raw.hints,
            enricher=enricher,
            metadata_status=metadata_status,
            newsgroup=raw.newsgroup,
            poster=raw.poster,
            nzb_xml=raw.nzb_xml,
            info_hash=raw.info_hash,
            magnet_uri=raw.magnet_uri,
            seeders=raw.seeders,
            leechers=raw.leechers,
            files=raw.files,
        )


async def run_ingester(ingester: Ingester, session_factory) -> None:
    """Run one ingester forever: fetch_new() then sleep for interval_seconds."""
    while True:
        try:
            log.info("Ingester %s: starting fetch", ingester.source_name)
            async for raw in ingester.fetch_new():
                try:
                    await _process_release(session_factory, raw)
                except Exception as exc:
                    log.error(
                        "Ingester %s: failed to upsert %r: %s",
                        ingester.source_name, raw.source_key, exc,
                    )
            log.info("Ingester %s: fetch complete", ingester.source_name)
        except Exception as exc:
            log.exception("Ingester %s: cycle failed: %s", ingester.source_name, exc)

        log.info(
            "Ingester %s: sleeping %ds until next run",
            ingester.source_name, ingester.interval_seconds,
        )
        await asyncio.sleep(ingester.interval_seconds)


async def run_ingesters(ingesters: list[Ingester], session_factory) -> None:
    """Launch all ingesters as concurrent asyncio tasks."""
    tasks = [asyncio.create_task(run_ingester(ing, session_factory)) for ing in ingesters]
    await asyncio.gather(*tasks)
