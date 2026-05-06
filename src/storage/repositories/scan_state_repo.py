from datetime import datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.storage.models import ScanState


async def get_watermark(session: AsyncSession, source_name: str) -> str | None:
    result = await session.execute(
        select(ScanState.watermark).where(ScanState.source_name == source_name)
    )
    return result.scalar_one_or_none()


async def set_watermark(session: AsyncSession, source_name: str, watermark: str) -> None:
    await session.execute(
        insert(ScanState)
        .values(source_name=source_name, watermark=watermark, updated_at=datetime.utcnow())
        .on_conflict_do_update(
            index_elements=["source_name"],
            set_={"watermark": watermark, "updated_at": datetime.utcnow()},
        )
    )
    await session.commit()
