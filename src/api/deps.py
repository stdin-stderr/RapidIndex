from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from src.storage.db import get_session_factory


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with get_session_factory()() as session:
        yield session
