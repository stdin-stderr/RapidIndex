import difflib
import logging
import re
import uuid
from datetime import date, datetime, timezone
from urllib.parse import urlencode

from src.config import Settings
from src.enrichers.base import Enricher, EnrichmentResult
from src.parsing.title_parser import ParsedTitle
from src.storage.models import Release
from src.utils.http import HttpClient
from src.utils.rate_limiter import RateLimiter

log = logging.getLogger(__name__)

_BASE = "https://api.theporndb.net"
_PER_PAGE = 5


class TPDBEnricher(Enricher):
    def __init__(self, settings: Settings, http_client: HttpClient) -> None:
        self._settings = settings
        self._client = http_client
        self._limiter = RateLimiter(settings.tpdb_requests_per_second, 1)

    async def _get(self, path: str, **params) -> dict:
        await self._limiter.acquire()
        url = f"{_BASE}{path}"
        if params:
            url = f"{url}?{urlencode(params)}"
        headers = {
            "Authorization": f"Bearer {self._settings.tpdb_api_key}",
            "Accept": "application/json",
        }
        return await self._client.get(url, headers=headers)

    async def _search_scenes(
        self,
        parse: str,
        site: str | None = None,
        date_str: str | None = None,
    ) -> list[dict]:
        params: dict = {"parse": parse, "per_page": _PER_PAGE}
        if site:
            params["site"] = site
            params["site_operation"] = "Site/Network"
        if date_str:
            params["date"] = date_str
        data = await self._get("/scenes", **params)
        return data.get("data", [])

    async def enrich(self, release: Release, parsed: ParsedTitle) -> EnrichmentResult:
        min_score = self._settings.metadata_min_score
        clean = parsed.clean_title or ""
        site = parsed.site_name
        date_str = parsed.release_date.isoformat() if parsed.release_date else None

        torrent_ctx = {
            "meta_title": clean.lower(),
            "sitename": _normalise(site or ""),
            "release_date": parsed.release_date,
        }

        passes = [
            (clean, site, date_str),  # pass 1: title + site + date
            (clean, site, None),       # pass 2: title + site
            (clean, None, None),       # pass 3: title only
            (release.raw_title, None, None),  # pass 4: raw title, let TPDB parse performer names
        ]

        for query, s, d in passes:
            candidates = await self._search_scenes(query, site=s, date_str=d)
            scene_raw, score = _best_candidate(torrent_ctx, candidates, min_score)
            if scene_raw is not None:
                log.info(
                    "TPDB matched %r → %r (score=%.2f)",
                    release.raw_title,
                    scene_raw.get("title"),
                    score,
                )
                return EnrichmentResult(
                    matched=True,
                    score=score,
                    external_id=scene_raw.get("_id", ""),
                    metadata=_extract_metadata(scene_raw),
                )

        return EnrichmentResult(matched=False, score=0.0, external_id="")


# ---------------------------------------------------------------------------
# Scoring (ported from xxxclub_scraper/metadata_fetcher.py)
# ---------------------------------------------------------------------------

def _normalise(name: str) -> str:
    return re.sub(r"[\s\-_]", "", name).lower()


def _score(torrent_ctx: dict, raw: dict) -> float:
    meta_title = torrent_ctx["meta_title"]
    sitename = torrent_ctx["sitename"]
    release_date: date | None = torrent_ctx["release_date"]

    scene_title = (raw.get("title") or "").lower()
    site_raw = raw.get("site") or {}
    scene_site = _normalise(site_raw.get("name") or "")
    scene_date_str = raw.get("date") or ""

    title_sim = difflib.SequenceMatcher(None, meta_title, scene_title).ratio() if meta_title else 0.0
    for p in raw.get("performers") or []:
        parent = p.get("parent") or {}
        performer_sim = difflib.SequenceMatcher(
            None, meta_title, (parent.get("name") or p.get("name") or "").lower()
        ).ratio()
        if performer_sim > title_sim:
            title_sim = performer_sim

    if sitename and scene_site:
        site_sim = 1.0 if (sitename in scene_site or scene_site in sitename) else 0.0
    else:
        site_sim = 0.0

    date_sim = 0.0
    has_date = release_date is not None
    if has_date and scene_date_str:
        try:
            scene_date = date.fromisoformat(scene_date_str[:10])
            if release_date.month == 1 and release_date.day == 1:
                year_delta = abs(release_date.year - scene_date.year)
                date_sim = 1.0 if year_delta == 0 else (0.5 if year_delta == 1 else 0.0)
            else:
                delta = abs((release_date - scene_date).days)
                date_sim = 1.0 if delta == 0 else (0.5 if delta <= 30 else 0.0)
        except ValueError:
            pass

    if has_date:
        return 0.35 * title_sim + 0.25 * site_sim + 0.40 * date_sim
    return 0.70 * title_sim + 0.30 * site_sim


def _best_candidate(
    torrent_ctx: dict, candidates: list[dict], min_score: float
) -> tuple[dict | None, float]:
    best_raw: dict | None = None
    best_score = -1.0
    for raw in candidates:
        total = _score(torrent_ctx, raw)
        if total > best_score:
            best_score = total
            best_raw = raw
    if best_score >= min_score and best_raw is not None:
        return best_raw, best_score
    return None, best_score


# ---------------------------------------------------------------------------
# Metadata extraction
# ---------------------------------------------------------------------------

def _str_image(val) -> str | None:
    if val is None:
        return None
    if isinstance(val, str):
        return val or None
    if isinstance(val, dict):
        return (
            val.get("full") or val.get("large") or val.get("medium")
            or val.get("small") or val.get("url") or val.get("src")
            or val.get("path") or None
        )
    if isinstance(val, list) and val:
        return _str_image(val[0])
    return None


def _parse_date(val: str | None) -> date | None:
    if not val:
        return None
    try:
        return date.fromisoformat(val[:10])
    except (ValueError, TypeError):
        return None


def _performer_jsonb(p: dict) -> dict:
    parent = p.get("parent") or {}
    extras = parent.get("extras") or {}
    return {
        "id": parent.get("id"),
        "name": parent.get("name") or p.get("name", ""),
        "slug": parent.get("slug"),
        "gender": extras.get("gender"),
        "poster_url": _str_image(parent.get("image")),
    }


def _performer_profile(p: dict) -> dict | None:
    parent = p.get("parent") or {}
    performer_id = parent.get("id")
    if not performer_id:
        return None
    extras = parent.get("extras") or {}

    birthday = _parse_date(extras.get("birthday"))

    height_raw = extras.get("height")
    height_cm: int | None = None
    if height_raw is not None:
        try:
            height_cm = int(height_raw)
        except (TypeError, ValueError):
            pass

    return {
        "id": uuid.UUID(performer_id),
        "name": parent.get("name") or p.get("name", ""),
        "gender": extras.get("gender"),
        "birthday": birthday,
        "height_cm": height_cm,
        "rating": parent.get("rating"),
        "poster_url": _str_image(parent.get("image")),
        "extra": {
            "slug": parent.get("slug"),
            "bio": parent.get("bio"),
            "ethnicity": extras.get("ethnicity"),
            "nationality": extras.get("nationality"),
            "hair_colour": extras.get("hair_colour"),
            "eye_colour": extras.get("eye_colour"),
            "measurements": extras.get("measurements"),
            "cupsize": extras.get("cupsize"),
            "career_start_year": extras.get("career_start_year"),
            "career_end_year": extras.get("career_end_year"),
        },
    }


def _extract_site(site_raw: dict) -> dict | None:
    site_id = site_raw.get("id")
    if not site_id:
        return None
    network_raw = site_raw.get("network") or {}
    network: dict | None = None
    if network_raw.get("id"):
        network = {
            "id": network_raw["id"],
            "name": network_raw.get("name"),
            "slug": network_raw.get("short_name"),
        }
    return {
        "id": site_id,
        "name": site_raw.get("name"),
        "slug": site_raw.get("short_name"),
        "logo_url": _str_image(site_raw.get("logo")),
        "network": network,
    }


def _extract_metadata(raw: dict) -> dict:
    site_raw = raw.get("site") or {}
    site = _extract_site(site_raw)

    performers_raw = raw.get("performers") or []
    performers_jsonb = [_performer_jsonb(p) for p in performers_raw]
    performer_profiles = [
        prof for p in performers_raw
        if (prof := _performer_profile(p)) is not None
    ]

    tags = [t["name"] for t in (raw.get("tags") or []) if t.get("name")]

    scene_id_str = raw.get("_id")
    if scene_id_str:
        try:
            scene_id = uuid.UUID(str(scene_id_str))
        except (ValueError, AttributeError):
            scene_id = uuid.uuid5(uuid.NAMESPACE_URL, str(scene_id_str))
    else:
        scene_id = uuid.uuid4()

    return {
        "id": scene_id,
        "tpdb_type": (raw.get("type") or "scene").lower(),
        "title": raw.get("title"),
        "description": raw.get("description"),
        "date": _parse_date(raw.get("date")),
        "duration_secs": raw.get("duration"),
        "poster_url": _str_image(raw.get("posters") or raw.get("poster") or raw.get("image")),
        "background_url": _str_image(raw.get("background")),
        "performers": performers_jsonb,
        "tags": tags,
        "site": site,
        "performer_profiles": performer_profiles,
    }
