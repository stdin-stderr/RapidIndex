from enum import StrEnum


class ContentCategory(StrEnum):
    MOVIE = "movie"
    TV = "tv"
    XXX = "xxx"
    MUSIC = "music"
    BOOK = "book"
    SOFTWARE = "software"
    OTHER = "other"
    VIDEO = "video"  # Spotnet generic video; router resolves to movie/tv via parser


_SPOTNET_MAP: dict[str, ContentCategory] = {
    "video": ContentCategory.VIDEO,
    "video:movies_hd": ContentCategory.MOVIE,
    "video:tv_hd": ContentCategory.TV,
    "xxx": ContentCategory.XXX,
    "audio": ContentCategory.MUSIC,
    "book": ContentCategory.BOOK,
    "image": ContentCategory.OTHER,
    "apps": ContentCategory.SOFTWARE,
}


# xxxclub categories that have no TPDB scene data — skip enrichment
_XXXCLUB_SKIP: frozenset[str] = frozenset({"Movies/DVD/WEB", "IMAGESET"})

_XXXCLUB_QUALITY: dict[str, str] = {
    "480p/SD": "SD",
    "720p/HD": "HD",
    "1080p/FullHD": "FHD",
    "2160p/UHD/4K": "UHD",
}


def should_skip_enrichment(source: str, raw: str) -> bool:
    """Return True if this release should not be sent to an enricher."""
    return source == "xxxclub" and raw in _XXXCLUB_SKIP


def extract_quality(source: str, raw: str) -> str | None:
    """Return a normalised quality string for sources that encode it in the category."""
    if source == "xxxclub":
        return _XXXCLUB_QUALITY.get(raw)
    return None


def normalise_category(source: str, raw: str) -> ContentCategory:
    """Map a source-specific raw category string to a ContentCategory.

    xxxclub content is always XXX regardless of the raw quality tag.
    Spotnet categories are mapped via a fixed table.
    Generic HTML ingesters pass through the raw value directly.
    """
    if source == "xxxclub":
        return ContentCategory.XXX

    if source == "spotnet":
        return _SPOTNET_MAP.get(raw.lower(), ContentCategory.OTHER)

    try:
        return ContentCategory(raw.lower())
    except ValueError:
        return ContentCategory.OTHER
