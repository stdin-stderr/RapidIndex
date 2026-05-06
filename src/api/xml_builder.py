"""Shared XML helpers for Newznab and Torznab responses."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from email.utils import format_datetime
from typing import TYPE_CHECKING, Any

from fastapi import Response

from src.api.feed import backdrop_url, cover_url, tmdb_for

if TYPE_CHECKING:
    from src.storage.models import Release

_NNS = "http://www.newznab.com/DTD/2010/feeds/attributes/"
_TNS = "https://torznab.com/feed-specification"

_CONTENT_TYPE_TO_CAT: dict[str, int] = {
    "movie": 2000,
    "tv": 5000,
    "xxx": 6000,
    "music": 3000,
    "book": 7000,
    "software": 4000,
    "other": 8000,
}

# (parent_id, parent_name, [(subcat_id, subcat_name), ...])
_CATEGORIES: list[tuple[str, str, list[tuple[str, str]]]] = [
    ("2000", "Movies", [
        ("2010", "Foreign"),
        ("2030", "SD"),
        ("2040", "HD"),
        ("2045", "UHD"),
        ("2050", "BluRay"),
        ("2060", "3D"),
        ("2020", "Other"),
    ]),
    ("5000", "TV", [
        ("5020", "Foreign"),
        ("5030", "SD"),
        ("5040", "HD"),
        ("5045", "UHD"),
        ("5060", "Sport"),
        ("5070", "Anime"),
        ("5080", "Documentary"),
        ("5050", "Other"),
    ]),
    ("6000", "XXX", [
        ("6010", "DVD"),
        ("6020", "WMV"),
        ("6030", "XviD"),
        ("6040", "x264"),
        ("6050", "Pack"),
        ("6060", "ImgSet"),
        ("6070", "Other"),
    ]),
    ("3000", "Audio", [
        ("3010", "MP3"),
        ("3020", "Video"),
        ("3030", "Audiobook"),
        ("3040", "Lossless"),
        ("3050", "Other"),
    ]),
    ("7000", "Books", [
        ("7010", "Mags"),
        ("7020", "Ebook"),
        ("7030", "Comics"),
    ]),
    ("4000", "PC", [
        ("4010", "0day"),
        ("4020", "ISO"),
        ("4030", "Mac"),
        ("4035", "Linux"),
        ("4040", "Mobile-Other"),
        ("4050", "Games"),
        ("4060", "Mobile-iOS"),
        ("4070", "Mobile-Android"),
        ("4090", "Tutorials"),
    ]),
    ("8000", "Other", [
        ("8010", "Misc"),
    ]),
]

_CAT_RANGES = [
    (2000, 2999, "movie"),
    (3000, 3999, "music"),
    (4000, 4999, "software"),
    (5000, 5999, "tv"),
    (6000, 6999, "xxx"),
    (7000, 7999, "book"),
    (8000, 8999, "other"),
]


def newznab_cat(content_type: str | None) -> int:
    return _CONTENT_TYPE_TO_CAT.get(content_type or "other", 8000)


# Subcategory IDs based on content_type + quality
_SUBCAT_MAP: dict[str, dict[str, int]] = {
    "tv":    {"UHD": 5045, "FHD": 5040, "HD": 5040, "SD": 5030},
    "movie": {"UHD": 2045, "FHD": 2040, "HD": 2040, "SD": 2030},
    "xxx":   {"UHD": 6040, "FHD": 6040, "HD": 6040, "SD": 6030},
}

_SUBCAT_LABEL: dict[int, str] = {
    5045: "TV > UHD", 5040: "TV > HD", 5030: "TV > SD", 5050: "TV > Other",
    5070: "TV > Anime", 5080: "TV > Documentary", 5060: "TV > Sport",
    2045: "Movies > UHD", 2040: "Movies > HD", 2030: "Movies > SD",
    2050: "Movies > BluRay", 2060: "Movies > 3D", 2020: "Movies > Other",
    6045: "XXX > UHD", 6040: "XXX > x264", 6030: "XXX > XviD", 6010: "XXX > DVD",
    3000: "Audio", 7000: "Books", 4000: "PC", 8000: "Other",
}


def newznab_subcat(content_type: str | None, quality: str | None) -> int:
    ct = content_type or "other"
    q = (quality or "").upper()
    submap = _SUBCAT_MAP.get(ct)
    if submap and q in submap:
        return submap[q]
    # fallback: parent category + "Other" offset
    base = newznab_cat(ct)
    return {2000: 2020, 5000: 5050, 6000: 6070}.get(base, base)


def subcat_label(subcat: int) -> str:
    return _SUBCAT_LABEL.get(subcat, str(subcat))


def cat_to_content_type(cat_str: str) -> str | None:
    for part in cat_str.split(","):
        try:
            c = int(part.strip())
        except ValueError:
            continue
        for lo, hi, ct in _CAT_RANGES:
            if lo <= c <= hi:
                return ct
    return None


def _rss_root(ns_attr: str) -> ET.Element:
    ET.register_namespace("newznab", _NNS)
    ET.register_namespace("torznab", _TNS)
    return ET.Element("rss", version="2.0")


def _channel(rss: ET.Element, title: str, url: str) -> ET.Element:
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = title
    ET.SubElement(channel, "link").text = url
    ET.SubElement(channel, "description").text = title
    return channel


def _pubdate(release: Release) -> str:
    if release.published_at:
        return format_datetime(release.published_at)
    return ""


def _add_attr(item: ET.Element, ns: str, name: str, value: Any) -> None:
    if value is None or value == "":
        return
    ET.SubElement(item, f"{{{ns}}}attr", name=name, value=str(value))


def _genre_value(genres: Any) -> str | None:
    if not genres:
        return None
    if isinstance(genres, list):
        return ", ".join(str(g) for g in genres if g)
    return None


def _external_id(metadata: Any, key: str) -> Any:
    if not metadata or not isinstance(metadata.external_ids, dict):
        return None
    return metadata.external_ids.get(key)


def _rating_value(rating: float | None) -> str | None:
    if rating is None:
        return None
    return f"{rating:g}/10"


def _year_value(release: Release, metadata: Any) -> int | None:
    if metadata and metadata.release_year is not None:
        return metadata.release_year
    if release.date:
        return release.date.year
    if release.published_at:
        return release.published_at.year
    return None


def _add_common_attrs(item: ET.Element, ns: str, r: Release, *, cat: int, size: str, guid: str) -> None:
    metadata = tmdb_for(r)
    year = _year_value(r, metadata)

    ET.SubElement(item, f"{{{ns}}}attr", name="category", value=str(cat))
    ET.SubElement(item, f"{{{ns}}}attr", name="size", value=size)
    _add_attr(item, ns, "guid", guid)
    _add_attr(item, ns, "tag", r.raw_category)
    _add_attr(item, ns, "year", year)
    if metadata:
        _add_attr(item, ns, "tmdb", metadata.tmdb_id)
        _add_attr(item, ns, "coverurl", cover_url(metadata.poster_path))
        _add_attr(item, ns, "backdropurl", backdrop_url(metadata.backdrop_path))
        _add_attr(item, ns, "genre", _genre_value(metadata.genres))
        _add_attr(item, ns, "imdb", metadata.imdb_id)
        _add_attr(item, ns, "imdbscore", _rating_value(metadata.rating))
        _add_attr(item, ns, "imdbtitle", metadata.title)
        _add_attr(item, ns, "imdbplot", metadata.overview)
        _add_attr(item, ns, "imdbyear", metadata.release_year)

        if metadata.tmdb_type == "tv":
            _add_attr(item, ns, "tvtitle", metadata.title)
            _add_attr(item, ns, "tvdbid", metadata.tvdb_id)
            _add_attr(item, ns, "tvmazeid", _external_id(metadata, "tvmaze_id"))

    if r.season is not None:
        _add_attr(item, ns, "season", r.season)
    if r.episode is not None:
        _add_attr(item, ns, "episode", r.episode)


def make_newznab_feed(releases: list[Release], base_url: str) -> Response:
    rss = _rss_root("newznab")
    channel = _channel(rss, "RapidIndex", base_url)
    for r in releases:
        _newznab_item(channel, r, base_url)
    return _render(rss)


def _newznab_item(channel: ET.Element, r: Release, base_url: str) -> None:
    cat = newznab_subcat(r.content_type, r.quality)
    label = subcat_label(cat)
    guid = str(r.id)
    size = str(r.file_size_bytes or 0)

    item = ET.SubElement(channel, "item")
    ET.SubElement(item, "title").text = r.raw_title
    ET.SubElement(item, "guid", isPermaLink="false").text = guid
    ET.SubElement(item, "pubDate").text = _pubdate(r)
    ET.SubElement(item, "category").text = label
    ET.SubElement(item, "description").text = r.raw_title
    ET.SubElement(
        item, "enclosure",
        url=f"{base_url}/nzb/{r.id}",
        type="application/x-nzb",
        length=size,
    )
    ns = _NNS
    _add_common_attrs(item, ns, r, cat=cat, size=size, guid=guid)
    if r.usenet:
        _add_attr(item, ns, "poster", r.usenet.poster)
        _add_attr(item, ns, "group", r.usenet.groups)
    _add_attr(item, ns, "usenetdate", _pubdate(r))


def make_torznab_feed(releases: list[Release], base_url: str) -> Response:
    rss = _rss_root("torznab")
    channel = _channel(rss, "RapidIndex", base_url)
    for r in releases:
        _torznab_item(channel, r)
    return _render(rss)


def _torznab_item(channel: ET.Element, r: Release) -> None:
    cat = newznab_subcat(r.content_type, r.quality)
    label = subcat_label(cat)
    torrent = r.torrent
    guid = str(r.id)
    magnet = (torrent.magnet_uri or "") if torrent else ""
    size = str((torrent.size_bytes if torrent else None) or r.file_size_bytes or 0)

    item = ET.SubElement(channel, "item")
    ET.SubElement(item, "title").text = r.raw_title
    ET.SubElement(item, "guid", isPermaLink="false").text = guid
    ET.SubElement(item, "pubDate").text = _pubdate(r)
    ET.SubElement(item, "category").text = label
    ET.SubElement(item, "description").text = r.raw_title
    ET.SubElement(
        item, "enclosure",
        url=magnet,
        type="application/x-bittorrent;x-scheme-handler/magnet",
        length=size,
    )
    ns = _TNS
    _add_common_attrs(item, ns, r, cat=cat, size=size, guid=guid)
    if torrent:
        _add_attr(item, ns, "seeders", torrent.seeders)
        _add_attr(item, ns, "leechers", torrent.leechers)
        if torrent.seeders is not None and torrent.leechers is not None:
            _add_attr(item, ns, "peers", torrent.seeders + torrent.leechers)
        _add_attr(item, ns, "infohash", torrent.info_hash.lower() if torrent.info_hash else None)
        _add_attr(item, ns, "magneturl", torrent.magnet_uri)


def make_caps_response(is_torznab: bool = False) -> Response:
    caps = ET.Element("caps")
    ET.SubElement(
        caps, "server",
        appversion="1.0.0",
        version="0.5",
        title="RapidIndex",
        strapline="",
        url="",
    )
    ET.SubElement(caps, "limits", max="500", default="100")
    ET.SubElement(caps, "registration", available="no", open="no")
    searching = ET.SubElement(caps, "searching")
    ET.SubElement(searching, "search", available="yes", supportedParams="q")
    ET.SubElement(
        searching, "tv-search", available="yes",
        supportedParams="q,tvdbid,tmdbid,imdbid,season,ep,year,genre",
    )
    ET.SubElement(
        searching, "movie-search", available="yes",
        supportedParams="q,imdbid,tmdbid,genre,year",
    )
    categories = ET.SubElement(caps, "categories")
    for cat_id, cat_name, subcats in _CATEGORIES:
        cat_el = ET.SubElement(categories, "category", id=cat_id, name=cat_name)
        for sub_id, sub_name in subcats:
            ET.SubElement(cat_el, "subcat", id=sub_id, name=sub_name)
    return _render(caps)


def _render(root: ET.Element) -> Response:
    body = ET.tostring(root, encoding="unicode", xml_declaration=False)
    return Response(
        content=f'<?xml version="1.0" encoding="UTF-8"?>\n{body}',
        media_type="text/xml",
    )
