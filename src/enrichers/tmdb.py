import difflib
import logging
from urllib.parse import urlencode

from src.config import Settings
from src.enrichers.base import Enricher, EnrichmentResult
from src.parsing.title_parser import ParsedTitle
from src.storage.models import Release
from src.utils.http import HttpClient
from src.utils.rate_limiter import RateLimiter

logger = logging.getLogger(__name__)

_BASE = "https://api.themoviedb.org/3"
_MIN_SCORE = 0.6


class TMDBEnricher(Enricher):
    def __init__(self, settings: Settings, http_client: HttpClient) -> None:
        self._settings = settings
        self._client = http_client
        self._limiter = RateLimiter(settings.tmdb_requests_per_10s, 10)

    def _url(self, path: str, **params) -> str:
        base = f"{_BASE}{path}"
        if params:
            return f"{base}?{urlencode(params)}"
        return base

    async def _get(self, path: str, **params) -> dict:
        await self._limiter.acquire()
        headers = {"Authorization": f"Bearer {self._settings.tmdb_api_key}"}
        return await self._client.get(self._url(path, **params), headers=headers)

    async def enrich(self, release: Release, parsed: ParsedTitle) -> EnrichmentResult:
        is_tv = release.enricher == "tmdb_tv"

        record, score = await self._try_hints(release, is_tv)
        if record is None:
            record, score = await self._fuzzy_search(parsed, is_tv)

        if record is None:
            return EnrichmentResult(matched=False, score=0.0, external_id="")

        tmdb_id = record["id"]
        kind = "tv" if is_tv else "movie"

        ext = await self._get(f"/{kind}/{tmdb_id}/external_ids")
        credits = await self._get(f"/{kind}/{tmdb_id}/credits")
        cast = _extract_cast(credits.get("cast", []), self._settings.tmdb_cast_limit)

        release_year = _parse_year(record, is_tv)
        extra = _build_extra(record) if is_tv else {}

        metadata = {
            "tmdb_id": tmdb_id,
            "tmdb_type": "tv" if is_tv else "movie",
            "title": record.get("title") or record.get("name", ""),
            "original_title": record.get("original_title") or record.get("original_name"),
            "overview": record.get("overview"),
            "release_year": release_year,
            "rating": record.get("vote_average"),
            "genres": [g["name"] for g in record.get("genres", [])],
            "poster_path": record.get("poster_path"),
            "backdrop_path": record.get("backdrop_path"),
            "imdb_id": ext.get("imdb_id"),
            "tvdb_id": ext.get("tvdb_id"),
            "external_ids": {k: v for k, v in ext.items() if k not in ("id", "imdb_id", "tvdb_id")},
            "extra": extra,
            "cast": cast,
        }

        return EnrichmentResult(matched=True, score=score, external_id=str(tmdb_id), metadata=metadata)

    async def _try_hints(self, release: Release, is_tv: bool) -> tuple[dict | None, float]:
        hints = release.hints or {}
        kind = "tv" if is_tv else "movie"

        if "tmdb_id" in hints:
            try:
                record = await self._get(f"/{kind}/{hints['tmdb_id']}")
                return record, 1.0
            except Exception:
                logger.debug("tmdb_id hint %s not found", hints["tmdb_id"])

        if "imdb_id" in hints:
            try:
                data = await self._get(f"/find/{hints['imdb_id']}", external_source="imdb_id")
                results = data.get("movie_results", []) + data.get("tv_results", [])
                if len(results) == 1:
                    record = await self._get(f"/{kind}/{results[0]['id']}")
                    return record, 1.0
            except Exception:
                logger.debug("imdb_id hint %s not found", hints["imdb_id"])

        if is_tv and "tvdb_id" in hints:
            try:
                data = await self._get(f"/find/{hints['tvdb_id']}", external_source="tvdb_id")
                results = data.get("tv_results", [])
                if len(results) == 1:
                    record = await self._get(f"/tv/{results[0]['id']}")
                    return record, 1.0
            except Exception:
                logger.debug("tvdb_id hint %s not found", hints["tvdb_id"])

        return None, 0.0

    async def _fuzzy_search(self, parsed: ParsedTitle, is_tv: bool) -> tuple[dict | None, float]:
        if is_tv:
            data = await self._get("/search/tv", query=parsed.clean_title)
            result, score = _best_match(data.get("results", []), parsed.clean_title, name_key="name")
            if result is None or score < _MIN_SCORE:
                return None, 0.0
            full = await self._get(f"/tv/{result['id']}")
            return full, score

        # Movie: try with year, fall back without
        params = {"query": parsed.clean_title}
        if parsed.year:
            params["year"] = str(parsed.year)
        data = await self._get("/search/movie", **params)
        result, score = _best_match(data.get("results", []), parsed.clean_title)

        if score < _MIN_SCORE and parsed.year:
            data = await self._get("/search/movie", query=parsed.clean_title)
            result, score = _best_match(data.get("results", []), parsed.clean_title)

        if result is None or score < _MIN_SCORE:
            return None, 0.0

        full = await self._get(f"/movie/{result['id']}")
        return full, score


def _best_match(
    results: list[dict],
    query: str,
    name_key: str = "title",
) -> tuple[dict | None, float]:
    if not results:
        return None, 0.0

    q = query.lower()

    def ratio(r: dict) -> float:
        return difflib.SequenceMatcher(None, q, (r.get(name_key) or "").lower()).ratio()

    best = max(results, key=ratio)
    return best, ratio(best)


def _extract_cast(cast_raw: list[dict], limit: int) -> list[dict]:
    return [
        {
            "tmdb_person_id": m["id"],
            "name": m["name"],
            "profile_path": m.get("profile_path"),
            "popularity": m.get("popularity"),
            "character": m.get("character"),
            "cast_order": m.get("order", i),
        }
        for i, m in enumerate(cast_raw[:limit])
    ]


def _parse_year(record: dict, is_tv: bool) -> int | None:
    date_str = record.get("first_air_date" if is_tv else "release_date") or ""
    if len(date_str) >= 4:
        try:
            return int(date_str[:4])
        except ValueError:
            pass
    return None


def _build_extra(record: dict) -> dict:
    return {
        "season_count": record.get("number_of_seasons"),
        "episode_count": record.get("number_of_episodes"),
        "networks": [n.get("name") for n in record.get("networks", [])],
    }
