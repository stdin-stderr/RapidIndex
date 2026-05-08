import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import urlencode
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from jinja2 import pass_context
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.api.deps import get_session
from src.storage.models import (
    Release,
    ReleaseTpdbScene,
    TorrentRelease,
    TpdbNetwork,
    TpdbPerformer,
    TpdbScene,
    TpdbSite,
    UsenetRelease,
)
from src.storage.repositories.performer_repo import get_performer, search_performers
from src.storage.repositories.release_repo import search_releases
from src.storage.repositories.scene_repo import (
    get_max_seeders_for_scenes,
    get_scene,
    search_scenes,
)
from src.utils import debrid as debrid_mod
from src.utils import ui_cache as cache

router = APIRouter()

_TEMPLATE_DIR = Path(__file__).parent.parent.parent.parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATE_DIR))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def format_duration(seconds) -> str:
    if seconds is None:
        return ""
    h, rem = divmod(int(seconds), 3600)
    m = rem // 60
    if h:
        return f"{h}h {m:02d}m"
    return f"{m}m"


def format_date(dt) -> str:
    if dt is None:
        return ""
    if isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt)
        except ValueError:
            return dt
    now = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    delta = now - dt
    seconds = int(delta.total_seconds())
    if seconds < 0:
        return dt.strftime("%Y-%m-%d")
    if seconds < 7 * 86400:
        if seconds < 3600:
            return f"{max(1, seconds // 60)}m ago"
        if seconds < 86400:
            return f"{seconds // 3600}h ago"
        return f"{seconds // 86400}d ago"
    return dt.strftime("%Y-%m-%d")


def format_size(size_bytes) -> str:
    if size_bytes is None:
        return "—"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} PB"


def page_url(base_path: str, params: dict, page: int) -> str:
    args = {k: v for k, v in params.items() if k != "page" and v is not None and v != ""}
    args["page"] = page
    return base_path + "?" + urlencode(args)


def query_url(base_path: str, params: dict) -> str:
    args = {k: v for k, v in params.items() if v}
    return base_path + ("?" + urlencode(args) if args else "")


def _normalize_performers(raw) -> list[dict]:
    if not raw:
        return []
    if isinstance(raw, list):
        return [
            {
                "name": p.get("name") or p.get("slug") or "",
                "uuid": str(p.get("uuid") or p.get("id") or ""),
                "image_url": p.get("image") or p.get("image_url") or p.get("poster_url") or p.get("thumbnail") or "",
            }
            for p in raw
            if isinstance(p, dict)
        ]
    if isinstance(raw, dict):
        return [
            {
                "name": v.get("name") or v.get("slug") or "",
                "uuid": str(k),
                "image_url": v.get("image") or v.get("image_url") or v.get("poster_url") or v.get("thumbnail") or "",
            }
            for k, v in raw.items()
            if isinstance(v, dict)
        ]
    return []


def _normalize_tags(raw) -> list[str]:
    if not raw:
        return []
    if isinstance(raw, list):
        return [t if isinstance(t, str) else (t.get("name") or t.get("slug") or "") for t in raw]
    if isinstance(raw, dict):
        return list(raw.keys())
    return []


def _scene_to_dict(scene: TpdbScene, max_seeders: int = 0, torrent_release_id: str | None = None) -> dict:
    site = scene.site
    performers = _normalize_performers(scene.performers)
    tags = _normalize_tags(scene.tags)
    return {
        "id": str(scene.id),
        "tpdb_type": scene.tpdb_type,
        "title": scene.title,
        "date": scene.date.isoformat() if scene.date else None,
        "duration_secs": scene.duration_secs,
        "duration_human": format_duration(scene.duration_secs),
        "description": scene.description,
        "poster_url": scene.poster_url,
        "background_url": scene.background_url,
        "site_id": scene.site_id,
        "site_name": site.name if site else None,
        "site_logo_url": site.logo_url if site else None,
        "site_uuid": str(scene.site_id) if scene.site_id else None,
        "network_name": (site.network.name if site and site.network else None) if hasattr(site, "network") else None,
        "network_uuid": str(site.network_id) if site and site.network_id else None,
        "performers": performers,
        "tags": tags,
        "max_seeders": max_seeders,
        "torrent_release_id": torrent_release_id,
        "torrents": [],
        "usenet_releases": [],
    }


async def _enrich_scenes_with_seeders(session: AsyncSession, scenes: list[TpdbScene]) -> list[dict]:
    """Convert scenes to dicts and attach download links (torrents + usenet)."""
    scene_ids = [s.id for s in scenes]
    seeders_map = await get_max_seeders_for_scenes(session, scene_ids)

    torrents_map: dict[UUID, list[dict]] = {}
    release_id_map: dict[UUID, str | None] = {}

    if scene_ids:
        torrent_q = (
            select(
                ReleaseTpdbScene.scene_id,
                Release.id.label("release_id"),
                Release.raw_title,
                Release.quality,
                TorrentRelease.info_hash,
                TorrentRelease.magnet_uri,
                TorrentRelease.size_bytes,
                TorrentRelease.seeders,
                TorrentRelease.leechers,
            )
            .join(Release, Release.id == ReleaseTpdbScene.release_id)
            .join(TorrentRelease, TorrentRelease.release_id == Release.id)
            .where(ReleaseTpdbScene.scene_id.in_(scene_ids))
        )
        result = await session.execute(torrent_q)
        rows = result.all()
        best: dict[UUID, tuple[str, int]] = {}
        for scene_id, release_id, raw_title, quality, info_hash, magnet_uri, size_bytes, seeders, leechers in rows:
            s = seeders or 0
            torrents_map.setdefault(scene_id, []).append({
                "info_hash": info_hash or "",
                "magnet": magnet_uri or (f"magnet:?xt=urn:btih:{info_hash}" if info_hash else ""),
                "title": raw_title or "",
                "resolution": quality or "",
                "size_bytes": size_bytes,
                "seeders": seeders,
                "leechers": leechers,
            })
            if scene_id not in best or s > best[scene_id][1]:
                best[scene_id] = (str(release_id), s)
        release_id_map = {k: v[0] for k, v in best.items()}

    usenet_map: dict[UUID, list[dict]] = {}
    if scene_ids:
        usenet_q = (
            select(
                ReleaseTpdbScene.scene_id,
                Release.id.label("release_id"),
                Release.raw_title,
                Release.quality,
                Release.file_size_bytes,
            )
            .join(Release, Release.id == ReleaseTpdbScene.release_id)
            .join(UsenetRelease, UsenetRelease.release_id == Release.id)
            .where(ReleaseTpdbScene.scene_id.in_(scene_ids))
        )
        u_result = await session.execute(usenet_q)
        for scene_id, release_id, raw_title, quality, file_size_bytes in u_result.all():
            usenet_map.setdefault(scene_id, []).append({
                "release_id": str(release_id),
                "nzb_url": f"/nzb/{release_id}",
                "title": raw_title or "",
                "resolution": quality or "",
                "size_bytes": file_size_bytes,
            })

    result_scenes = []
    for s in scenes:
        d = _scene_to_dict(s, max_seeders=seeders_map.get(s.id, 0), torrent_release_id=release_id_map.get(s.id))
        d["torrents"] = torrents_map.get(s.id, [])
        d["usenet_releases"] = usenet_map.get(s.id, [])
        result_scenes.append(d)
    return result_scenes


VALID_PER_PAGE_SCENES = {30, 60, 90}
VALID_PER_PAGE_PERFORMERS = {48, 96, 192}


# ---------------------------------------------------------------------------
# Root redirect
# ---------------------------------------------------------------------------

@router.get("/", response_class=HTMLResponse)
async def index():
    return RedirectResponse(url="/xxx", status_code=302)


# ---------------------------------------------------------------------------
# XXX — Scenes
# ---------------------------------------------------------------------------

@router.get("/xxx", response_class=HTMLResponse)
async def xxx_scenes(
    request: Request,
    q: str = Query(default=""),
    tag: str = Query(default=""),
    sort_by: str = Query(default="seeders"),
    per_page: int = Query(default=30),
    page: int = Query(default=1, ge=1),
    session: AsyncSession = Depends(get_session),
):
    limit = per_page if per_page in VALID_PER_PAGE_SCENES else 30
    if sort_by not in ("seeders", "date"):
        sort_by = "seeders"
    scenes_raw = await search_scenes(
        session,
        q=q or None,
        tag=tag or None,
        sort_by=sort_by,
        limit=limit,
        offset=(page - 1) * limit,
    )
    scenes = await _enrich_scenes_with_seeders(session, scenes_raw)
    scenes_json = json.dumps(scenes, default=str).replace("</", "<\\/")

    base_args = {"q": q, "tag": tag, "sort_by": sort_by, "per_page": limit}
    return templates.TemplateResponse(request, "xxx/scenes.html", {
        "active_page": "xxx_scenes",
        "scenes": scenes,
        "scenes_json": scenes_json,
        "q": q, "tag": tag,
        "sort_by": sort_by, "per_page": limit,
        "top_url": query_url("/xxx", {**base_args, "sort_by": "seeders"}),
        "latest_url": query_url("/xxx", {**base_args, "sort_by": "date"}),
        "page": page,
        "has_prev": page > 1,
        "has_next": len(scenes) == limit,
        "prev_url": page_url("/xxx", base_args, page - 1),
        "next_url": page_url("/xxx", base_args, page + 1),
    })


# ---------------------------------------------------------------------------
# XXX — Performers
# ---------------------------------------------------------------------------

@router.get("/xxx/performers", response_class=HTMLResponse)
async def xxx_performers(
    request: Request,
    q: str = Query(default=""),
    per_page: int = Query(default=48),
    page: int = Query(default=1, ge=1),
    session: AsyncSession = Depends(get_session),
):
    limit = per_page if per_page in VALID_PER_PAGE_PERFORMERS else 48
    performers = await search_performers(session, name=q or None, limit=limit, offset=(page - 1) * limit)
    base_args = {"q": q, "per_page": limit}
    return templates.TemplateResponse(request, "xxx/performers.html", {
        "active_page": "xxx_performers",
        "performers": performers,
        "q": q, "per_page": limit,
        "page": page,
        "has_prev": page > 1,
        "has_next": len(performers) == limit,
        "prev_url": page_url("/xxx/performers", base_args, page - 1),
        "next_url": page_url("/xxx/performers", base_args, page + 1),
    })


@router.get("/xxx/performer/{performer_id}", response_class=HTMLResponse)
async def xxx_performer(
    request: Request,
    performer_id: UUID,
    q: str = Query(default=""),
    per_page: int = Query(default=30),
    page: int = Query(default=1, ge=1),
    session: AsyncSession = Depends(get_session),
):
    performer = await get_performer(session, performer_id)
    if performer is None:
        raise HTTPException(status_code=404, detail="Performer not found")

    limit = per_page if per_page in VALID_PER_PAGE_SCENES else 30
    scenes_raw = await search_scenes(
        session,
        q=q or None,
        performer=performer.name,
        sort_by="date",
        limit=limit,
        offset=(page - 1) * limit,
    )
    scenes = await _enrich_scenes_with_seeders(session, scenes_raw)
    scenes_json = json.dumps(scenes, default=str).replace("</", "<\\/")

    extra = performer.extra or {}
    base_args = {"q": q, "per_page": limit}
    return templates.TemplateResponse(request, "xxx/performer.html", {
        "active_page": "xxx_performers",
        "performer": performer,
        "performer_extra": extra,
        "scenes": scenes,
        "scenes_json": scenes_json,
        "q": q, "per_page": limit, "page": page,
        "has_prev": page > 1,
        "has_next": len(scenes) == limit,
        "prev_url": page_url(f"/xxx/performer/{performer_id}", base_args, page - 1),
        "next_url": page_url(f"/xxx/performer/{performer_id}", base_args, page + 1),
    })


# ---------------------------------------------------------------------------
# XXX — Sites
# ---------------------------------------------------------------------------

@router.get("/xxx/sites", response_class=HTMLResponse)
async def xxx_sites(
    request: Request,
    q: str = Query(default=""),
    session: AsyncSession = Depends(get_session),
):
    stmt = select(TpdbSite).options(selectinload(TpdbSite.network))
    if q:
        stmt = stmt.where(TpdbSite.name.ilike(f"%{q}%"))
    stmt = stmt.order_by(TpdbSite.name)
    result = await session.execute(stmt)
    sites = list(result.scalars().all())
    return templates.TemplateResponse(request, "xxx/sites.html", {
        "active_page": "xxx_sites",
        "sites": sites,
        "q": q,
    })


@router.get("/xxx/site/{site_id}", response_class=HTMLResponse)
async def xxx_site(
    request: Request,
    site_id: int,
    q: str = Query(default=""),
    per_page: int = Query(default=30),
    page: int = Query(default=1, ge=1),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(TpdbSite).options(selectinload(TpdbSite.network)).where(TpdbSite.id == site_id)
    )
    site = result.scalar_one_or_none()
    if site is None:
        raise HTTPException(status_code=404, detail="Site not found")

    limit = per_page if per_page in VALID_PER_PAGE_SCENES else 30
    scenes_raw = await search_scenes(
        session,
        q=q or None,
        site_id=site_id,
        sort_by="seeders",
        limit=limit,
        offset=(page - 1) * limit,
    )
    scenes = await _enrich_scenes_with_seeders(session, scenes_raw)
    scenes_json = json.dumps(scenes, default=str).replace("</", "<\\/")

    base_args = {"q": q, "per_page": limit}
    return templates.TemplateResponse(request, "xxx/site.html", {
        "active_page": "xxx_sites",
        "site": site,
        "scenes": scenes,
        "scenes_json": scenes_json,
        "q": q, "per_page": limit, "page": page,
        "has_prev": page > 1,
        "has_next": len(scenes) == limit,
        "prev_url": page_url(f"/xxx/site/{site_id}", base_args, page - 1),
        "next_url": page_url(f"/xxx/site/{site_id}", base_args, page + 1),
    })


# ---------------------------------------------------------------------------
# XXX — Networks
# ---------------------------------------------------------------------------

@router.get("/xxx/networks", response_class=HTMLResponse)
async def xxx_networks(
    request: Request,
    q: str = Query(default=""),
    session: AsyncSession = Depends(get_session),
):
    stmt = select(TpdbNetwork).options(selectinload(TpdbNetwork.sites))
    if q:
        stmt = stmt.where(TpdbNetwork.name.ilike(f"%{q}%"))
    stmt = stmt.order_by(TpdbNetwork.name)
    result = await session.execute(stmt)
    networks = list(result.scalars().all())
    return templates.TemplateResponse(request, "xxx/networks.html", {
        "active_page": "xxx_networks",
        "networks": networks,
        "q": q,
    })


@router.get("/xxx/network/{network_id}", response_class=HTMLResponse)
async def xxx_network(
    request: Request,
    network_id: int,
    per_page: int = Query(default=30),
    page: int = Query(default=1, ge=1),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(TpdbNetwork).options(selectinload(TpdbNetwork.sites)).where(TpdbNetwork.id == network_id)
    )
    network = result.scalar_one_or_none()
    if network is None:
        raise HTTPException(status_code=404, detail="Network not found")

    limit = per_page if per_page in VALID_PER_PAGE_SCENES else 30
    scenes_raw = await search_scenes(
        session,
        network_id=network_id,
        sort_by="seeders",
        limit=limit,
        offset=(page - 1) * limit,
    )
    scenes = await _enrich_scenes_with_seeders(session, scenes_raw)
    scenes_json = json.dumps(scenes, default=str).replace("</", "<\\/")

    base_args = {"per_page": limit}
    return templates.TemplateResponse(request, "xxx/network.html", {
        "active_page": "xxx_networks",
        "network": network,
        "scenes": scenes,
        "scenes_json": scenes_json,
        "per_page": limit, "page": page,
        "has_prev": page > 1,
        "has_next": len(scenes) == limit,
        "prev_url": page_url(f"/xxx/network/{network_id}", base_args, page - 1),
        "next_url": page_url(f"/xxx/network/{network_id}", base_args, page + 1),
    })


# ---------------------------------------------------------------------------
# Releases (all content types)
# ---------------------------------------------------------------------------

@router.get("/releases", response_class=HTMLResponse)
async def releases_page(
    request: Request,
    q: str = Query(default=""),
    source_type: str = Query(default=""),
    content_type: str = Query(default=""),
    per_page: int = Query(default=50),
    page: int = Query(default=1, ge=1),
    session: AsyncSession = Depends(get_session),
):
    limit = min(per_page, 250)
    releases = await search_releases(
        session,
        q=q or None,
        source_type=source_type or None,
        content_type=content_type or None,
        limit=limit,
        offset=(page - 1) * limit,
    )
    for r in releases:
        r._size_human = format_size(r.file_size_bytes)
        r._date_label = format_date(r.published_at)

    base_args = {"q": q, "source_type": source_type, "content_type": content_type, "per_page": limit}
    return templates.TemplateResponse(request, "releases.html", {
        "active_page": "releases",
        "releases": releases,
        "q": q, "source_type": source_type, "content_type": content_type,
        "per_page": limit, "page": page,
        "has_prev": page > 1,
        "has_next": len(releases) == limit,
        "prev_url": page_url("/releases", base_args, page - 1),
        "next_url": page_url("/releases", base_args, page + 1),
    })


# ---------------------------------------------------------------------------
# Stream page
# ---------------------------------------------------------------------------

@router.get("/stream/{release_id}", response_class=HTMLResponse)
async def stream_page(
    request: Request,
    release_id: UUID,
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(Release)
        .options(selectinload(Release.torrent), selectinload(Release.tpdb_scenes).selectinload(ReleaseTpdbScene.scene).selectinload(TpdbScene.site))
        .where(Release.id == release_id)
    )
    release = result.scalar_one_or_none()
    if release is None:
        raise HTTPException(status_code=404, detail="Release not found")
    if release.torrent is None:
        raise HTTPException(status_code=404, detail="No torrent data for this release")

    # Find linked TPDB scene if any
    tpdb_link = release.tpdb_scenes[0] if release.tpdb_scenes else None
    scene = tpdb_link.scene if tpdb_link else None
    site = scene.site if scene else None

    # Fetch all torrent releases linked to the same scene(s)
    scene_ids = [rts.scene_id for rts in release.tpdb_scenes]
    if scene_ids:
        all_tr_result = await session.execute(
            select(Release, TorrentRelease)
            .join(TorrentRelease, TorrentRelease.release_id == Release.id)
            .join(ReleaseTpdbScene, ReleaseTpdbScene.release_id == Release.id)
            .where(ReleaseTpdbScene.scene_id.in_(scene_ids))
            .order_by(TorrentRelease.seeders.desc().nulls_last())
        )
        seen_release_ids: set = set()
        torrents_list = []
        for rel, tr in all_tr_result.unique().all():
            if rel.id in seen_release_ids:
                continue
            seen_release_ids.add(rel.id)
            torrents_list.append({
                "info_hash": tr.info_hash or "",
                "magnet": tr.magnet_uri or (f"magnet:?xt=urn:btih:{tr.info_hash}" if tr.info_hash else ""),
                "title": rel.raw_title,
                "resolution": rel.quality or "",
                "size_bytes": tr.size_bytes,
                "seeders": tr.seeders,
                "leechers": tr.leechers,
            })
    else:
        torrent = release.torrent
        torrents_list = [{
            "info_hash": torrent.info_hash or "",
            "magnet": torrent.magnet_uri or (f"magnet:?xt=urn:btih:{torrent.info_hash}" if torrent.info_hash else ""),
            "title": release.raw_title,
            "resolution": release.quality or "",
            "size_bytes": torrent.size_bytes,
            "seeders": torrent.seeders,
            "leechers": torrent.leechers,
        }]

    release_dict = {
        "id": str(release.id),
        "title": release.raw_title,
        "date": release.date.isoformat() if release.date else None,
        "duration_human": format_duration(scene.duration_secs if scene else None),
        "description": scene.description if scene else None,
        "poster_url": scene.poster_url if scene else None,
        "background_url": scene.background_url if scene else None,
        "site_name": site.name if site else None,
        "site_logo_url": site.logo_url if site else None,
        "site_uuid": str(site.id) if site else None,
        "performers": _normalize_performers(scene.performers if scene else None),
        "tags": _normalize_tags(scene.tags if scene else None),
        "torrents": torrents_list,
    }

    return templates.TemplateResponse(request, "stream.html", {
        "active_page": "stream",
        "release": release,
        "release_dict": release_dict,
        "release_json": json.dumps(release_dict, default=str).replace("</", "<\\/"),
        "debrid_services": debrid_mod.DebridClient.SUPPORTED_SERVICES,
        "services_json": json.dumps(debrid_mod.DebridClient.SUPPORTED_SERVICES).replace("</", "<\\/"),
    })


# ---------------------------------------------------------------------------
# Library
# ---------------------------------------------------------------------------

@router.get("/library", response_class=HTMLResponse)
async def library_page(request: Request):
    return templates.TemplateResponse(request, "library.html", {"active_page": "library"})


@router.get("/api/ui/library")
async def library_content(
    service: str = Query(default=""),
    key: str = Query(default=""),
    session: AsyncSession = Depends(get_session),
):
    if not service or not key:
        raise HTTPException(status_code=400, detail="service and key required")
    try:
        client = debrid_mod.DebridClient(service, key)
        items, total = client.list_magnets(limit=500)
        all_items = list(items)
        offset = 500
        while offset < total:
            more, _ = client.list_magnets(limit=500, offset=offset)
            all_items.extend(more)
            offset += 500

        hash_added: dict[str, str] = {}
        for item in all_items:
            h = (item.get("hash") or "").lower()
            if h:
                hash_added[h] = item.get("added_at") or item.get("created_at") or ""

        hashes = list(hash_added.keys())
        if not hashes:
            return JSONResponse({"scenes": [], "unmatched": [], "total_debrid": total})

        # Find matching torrent releases
        from sqlalchemy import func
        tr_result = await session.execute(
            select(TorrentRelease, Release)
            .join(Release, Release.id == TorrentRelease.release_id)
            .where(TorrentRelease.info_hash.in_(hashes))
        )
        matched_rows = tr_result.all()

        if not matched_rows:
            unmatched = [{"info_hash": h, "title": "", "seeders": None} for h in hashes]
            return JSONResponse({"scenes": [], "unmatched": unmatched, "total_debrid": total})

        matched_release_ids = [row[1].id for row in matched_rows]
        matched_hashes = {row[0].info_hash.lower() for row in matched_rows if row[0].info_hash}

        # Find TPDB scenes linked to these releases
        scene_result = await session.execute(
            select(ReleaseTpdbScene, TpdbScene)
            .join(TpdbScene, TpdbScene.id == ReleaseTpdbScene.scene_id)
            .options(selectinload(TpdbScene.site))
            .where(ReleaseTpdbScene.release_id.in_(matched_release_ids))
        )
        scene_rows = scene_result.all()

        # Build scene dicts grouped by scene_id
        scene_map: dict[UUID, tuple[TpdbScene, list[dict]]] = {}
        release_to_torrent: dict[UUID, TorrentRelease] = {row[1].id: row[0] for row in matched_rows}

        for rts, scene in scene_rows:
            tr = release_to_torrent.get(rts.release_id)
            if scene.id not in scene_map:
                scene_map[scene.id] = (scene, [])
            if tr:
                scene_map[scene.id][1].append({
                    "info_hash": tr.info_hash or "",
                    "magnet": tr.magnet_uri or "",
                    "title": "",
                    "size_bytes": tr.size_bytes,
                    "seeders": tr.seeders,
                    "leechers": tr.leechers,
                })

        scene_dicts = []
        for scene_id, (scene, torrents) in scene_map.items():
            max_s = max((t.get("seeders") or 0 for t in torrents), default=0)
            d = _scene_to_dict(scene, max_seeders=max_s)
            d["torrents"] = torrents
            # Best release_id for stream link
            best_tr = release_to_torrent.get(next(
                (rts.release_id for rts, sc in scene_rows if sc.id == scene_id), None
            ))
            if best_tr:
                # Find the release_id that has max seeders
                best_rts = max(
                    [rts for rts, sc in scene_rows if sc.id == scene_id],
                    key=lambda r: (release_to_torrent.get(r.release_id) or TorrentRelease()).seeders or 0
                )
                d["torrent_release_id"] = str(best_rts.release_id)
            # Add debrid_added_at from hash_added
            scene_hashes = [t["info_hash"].lower() for t in torrents if t.get("info_hash")]
            dates = [hash_added[h] for h in scene_hashes if hash_added.get(h)]
            d["debrid_added_at"] = max(dates) if dates else ""
            d["duration_human"] = format_duration(scene.duration_secs)
            scene_dicts.append(d)

        scene_dicts.sort(key=lambda s: s.get("debrid_added_at") or "", reverse=True)

        unmatched_hashes = [h for h in hashes if h not in matched_hashes]
        unmatched = [{"info_hash": h, "title": "", "seeders": None, "debrid_added_at": hash_added.get(h, "")} for h in unmatched_hashes]

        return JSONResponse({"scenes": scene_dicts, "unmatched": unmatched, "total_debrid": total})

    except debrid_mod.DebridAuthError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except debrid_mod.DebridError as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Configure
# ---------------------------------------------------------------------------

@router.get("/configure", response_class=HTMLResponse)
async def configure_page(request: Request):
    return templates.TemplateResponse(request, "configure.html", {"active_page": "configure"})


# ---------------------------------------------------------------------------
# Debrid API endpoints (called from JS)
# ---------------------------------------------------------------------------

@router.post("/api/ui/streams/check")
async def streams_check(request: Request):
    body = await request.json()
    service = body.get("service", "")
    key = body.get("key", "")
    hashes = body.get("hashes", [])
    if not service or not key or not hashes:
        raise HTTPException(status_code=400, detail="service, key, and hashes required")
    try:
        client = debrid_mod.DebridClient(service, key)
        cached = client.check_cached(hashes)
    except debrid_mod.DebridAuthError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return JSONResponse(content=cached)


@router.get("/api/ui/streams/url/{service}/{info_hash}")
def streams_url(service: str, info_hash: str, key: str = Query(default="")):
    if not key:
        raise HTTPException(status_code=400, detail="key query parameter required")
    cache_key = cache.make_key("stream_url", service=service, info_hash=info_hash, key=key)
    if (hit := cache.cache_get(cache_key)) is not None:
        return JSONResponse(hit)
    try:
        client = debrid_mod.DebridClient(service, key)
        url = client.get_stream_url(f"magnet:?xt=urn:btih:{info_hash}")
        if not url:
            return JSONResponse({"status": "error", "message": "No playable file found"})
        result = {"status": "ok", "url": url}
        cache.cache_set(cache_key, result, ttl=600)
        return JSONResponse(result)
    except debrid_mod.DebridPendingError:
        return JSONResponse({"status": "pending"})
    except debrid_mod.DebridAuthError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except debrid_mod.DebridError as e:
        return JSONResponse({"status": "error", "message": str(e)})


@router.post("/api/ui/queue-stream")
async def queue_stream(request: Request):
    body = await request.json()
    service = body.get("service", "")
    key = body.get("key", "")
    magnet = body.get("magnet", "")
    if not service or not key or not magnet:
        raise HTTPException(status_code=400, detail="service, key, and magnet required")
    try:
        client = debrid_mod.DebridClient(service, key)
        url = client.get_stream_url(magnet)
        return JSONResponse({"status": "ok", "url": url})
    except debrid_mod.DebridPendingError:
        return JSONResponse({"status": "queued", "check_after_seconds": 30})
    except debrid_mod.DebridAuthError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except debrid_mod.DebridError as e:
        return JSONResponse({"status": "error", "message": str(e)})
