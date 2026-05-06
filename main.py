"""Entry point for RapidIndex services.

Usage:
    python main.py ingester spotnet
    python main.py ingester xxxclub
    python main.py worker
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


async def run_ingester(name: str) -> None:
    from src.config import settings
    from src.pipeline.ingester_scheduler import run_ingesters

    if name == "spotnet":
        if not settings.spotnet_nntp_host:
            log.error("SPOTNET_NNTP_HOST is not set")
            sys.exit(1)
        from src.ingesters.usenet.spotnet import SpotnetIngester
        ingesters = [SpotnetIngester(settings, _session_factory())]
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

    elif mode in ("api", "worker", "all"):
        log.error("Mode '%s' not yet implemented", mode)
        sys.exit(1)

    else:
        log.error("Unknown mode: %s", mode)
        sys.exit(1)


if __name__ == "__main__":
    main()
