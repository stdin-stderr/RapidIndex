"""Entry point for RapidIndex services.

Usage:
    python main.py ingester spotnet
    python main.py ingester xxxclub
    python main.py worker tmdb
    python main.py worker tpdb
    python main.py api
    python main.py all          # dev only — runs everything in one process
"""

from __future__ import annotations

import asyncio
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("main")


def _session_factory():
    from src.storage.db import get_session_factory
    return get_session_factory()


async def run_worker_mode(enricher_filter: str) -> None:
    from src.config import settings
    from src.pipeline.enricher_worker import run_worker
    log.info("Starting enricher worker (%s)", enricher_filter)
    await run_worker(_session_factory(), settings, enricher_filter)


async def run_ingester(name: str) -> None:
    from src.config import settings
    from src.pipeline.ingester_scheduler import run_ingesters

    if name == "spotnet":
        if not settings.spotnet_nntp_host:
            log.error("SPOTNET_NNTP_HOST is not set")
            sys.exit(1)
        from src.ingesters.usenet.spotnet import SpotnetIngester
        ingesters = [SpotnetIngester(settings, _session_factory())]
    elif name == "xxxclub":
        from src.ingesters.torrent.xxxclub import XXXClubIngester
        ingesters = [XXXClubIngester(settings, _session_factory())]
    else:
        log.error("Unknown ingester: %s", name)
        sys.exit(1)

    log.info("Starting ingester: %s", name)
    await run_ingesters(ingesters, _session_factory())


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    mode = sys.argv[1]

    if mode == "ingester":
        if len(sys.argv) < 3:
            log.error("Usage: python main.py ingester <name>")
            sys.exit(1)
        asyncio.run(run_ingester(sys.argv[2]))

    elif mode == "worker":
        if len(sys.argv) < 3 or sys.argv[2] not in ("tmdb", "tpdb"):
            log.error("Usage: python main.py worker <tmdb|tpdb>")
            sys.exit(1)
        asyncio.run(run_worker_mode(sys.argv[2]))

    elif mode == "api":
        import uvicorn
        from src.api.app import app
        from src.config import settings
        uvicorn.run(app, host=settings.api_host, port=settings.api_port, log_level="info")

    elif mode == "all":
        log.error("Mode 'all' not yet implemented")
        sys.exit(1)

    else:
        log.error("Unknown mode: %s", mode)
        sys.exit(1)


if __name__ == "__main__":
    main()
