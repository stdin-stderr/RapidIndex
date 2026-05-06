import re
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.api.deps import get_session
from src.storage.models import Release, UsenetRelease

router = APIRouter()

_UNSAFE = re.compile(r'[\\/:*?"<>|]')


def _safe_filename(title: str) -> str:
    return _UNSAFE.sub("_", title).strip() or "download"


@router.get("/{release_id}")
async def download_nzb(
    release_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> Response:
    result = await session.execute(
        select(UsenetRelease)
        .where(UsenetRelease.release_id == release_id)
        .options(selectinload(UsenetRelease.release))
    )
    row = result.scalar_one_or_none()
    if row is None or not row.nzb_xml:
        raise HTTPException(status_code=404, detail="NZB not found")
    title = _safe_filename(row.release.raw_title if row.release else str(release_id))
    return Response(
        content=row.nzb_xml,
        media_type="application/x-nzb",
        headers={"Content-Disposition": f'attachment; filename="{title}.nzb"'},
    )
