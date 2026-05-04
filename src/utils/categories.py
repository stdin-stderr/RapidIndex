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
    "audio": ContentCategory.OTHER,
    "image": ContentCategory.OTHER,
    "apps": ContentCategory.OTHER,
}


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
