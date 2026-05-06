from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.api.deps import get_session
from src.storage.models import Release, TorrentFile, UsenetFile

router = APIRouter()


@router.get("/releases/{release_id}/files")
async def get_release_files(
    release_id: str = Path(..., description="Release ID (UUID)"),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Get file list for a release.

    Returns file metadata for both usenet and torrent sources.
    Files are indexed from 0; use file_index for debrid API integration.
    """
    try:
        uuid = UUID(release_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid release ID format")

    # Fetch release with files eagerly loaded
    stmt = (
        select(Release)
        .where(Release.id == uuid)
        .options(
            selectinload(Release.usenet_files),
            selectinload(Release.torrent_files),
        )
    )
    result = await session.execute(stmt)
    release = result.scalar_one_or_none()

    if not release:
        raise HTTPException(status_code=404, detail="Release not found")

    files: list[dict[str, Any]] = []

    if release.source_type == "usenet" and release.usenet_files:
        for f in sorted(release.usenet_files, key=lambda x: x.file_index):
            files.append(
                {
                    "file_index": f.file_index,
                    "filename": f.filename,
                    "file_size_bytes": f.file_size_bytes,
                }
            )
    elif release.source_type == "torrent" and release.torrent_files:
        for f in sorted(release.torrent_files, key=lambda x: x.file_index):
            files.append(
                {
                    "file_index": f.file_index,
                    "filename": f.filename,
                    "file_size_bytes": f.file_size_bytes,
                }
            )

    return {
        "release_id": str(release.id),
        "source_type": release.source_type,
        "file_count": len(files),
        "files": files,
    }
