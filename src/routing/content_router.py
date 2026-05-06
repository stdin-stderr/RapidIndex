from enum import Enum

from src.config import Settings
from src.parsing.title_parser import ParsedTitle, parse_title
from src.storage.models import Release
from src.utils.categories import ContentCategory, normalise_category


class EnricherType(Enum):
    TPDB       = "tpdb"
    TMDB_MOVIE = "tmdb_movie"
    TMDB_TV    = "tmdb_tv"
    SKIP       = "skip"


_HINT_MAP: dict[str, EnricherType] = {
    "movie": EnricherType.TMDB_MOVIE,
    "tv":    EnricherType.TMDB_TV,
    "xxx":   EnricherType.TPDB,
}

_SKIP_RAW = {"audio", "image", "apps"}


def route(release: Release, settings: Settings) -> tuple[EnricherType, ParsedTitle]:
    """Parse title and decide enricher. Called by enricher worker at dequeue time."""
    parsed = parse_title(release.raw_title)
    enricher = _pick_enricher(release, parsed)
    return _apply_key_check(enricher, settings), parsed


def _pick_enricher(release: Release, parsed: ParsedTitle) -> EnricherType:
    hints = release.hints or {}
    raw_cat = (release.raw_category or "").lower()

    # Priority 0 — hint override
    hint = _HINT_MAP.get(hints.get("content_type", ""))
    if hint is not None:
        return hint

    # Priority 1 — explicit xxx raw category (Spotnet cat 7)
    if raw_cat == "xxx":
        return EnricherType.TPDB

    # Priority 2 — xxxclub source always routes to TPDB
    if release.source_name == "xxxclub":
        return EnricherType.TPDB

    # Priority 4 — non-video categories → skip enrichment
    if raw_cat in _SKIP_RAW:
        return EnricherType.SKIP

    # Priority 5/6 — normalised category
    if raw_cat:
        cat = normalise_category(release.source_name, raw_cat)
        if cat == ContentCategory.MOVIE:
            return EnricherType.TMDB_MOVIE
        if cat == ContentCategory.TV:
            return EnricherType.TMDB_TV
        # ContentCategory.VIDEO falls through to parser-based detection below

    # Priority 7 — parser detected a season number → TV
    if parsed.season is not None:
        return EnricherType.TMDB_TV

    # Priority 8 — fallback
    return EnricherType.TMDB_MOVIE


def _apply_key_check(enricher: EnricherType, settings: Settings) -> EnricherType:
    if enricher == EnricherType.TPDB and not settings.tpdb_api_key:
        return EnricherType.SKIP
    if enricher in (EnricherType.TMDB_MOVIE, EnricherType.TMDB_TV) and not settings.tmdb_api_key:
        return EnricherType.SKIP
    return enricher
