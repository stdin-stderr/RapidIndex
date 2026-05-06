import asyncio
import os
from collections.abc import AsyncGenerator
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

_MIGRATIONS_DIR = Path(__file__).parent / "migrations"

_engine = None
_session_factory = None


def _get_database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL environment variable is not set")
    return url


def get_engine():
    global _engine
    if _engine is None:
        _engine = create_async_engine(_get_database_url(), pool_pre_ping=True)
    return _engine


def get_session_factory():
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _session_factory


async def run_migrations() -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config()
    cfg.set_main_option("script_location", str(_MIGRATIONS_DIR))
    cfg.set_main_option("sqlalchemy.url", _get_database_url())
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, lambda: command.upgrade(cfg, "head"))
