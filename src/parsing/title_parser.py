import re
from dataclasses import dataclass
from datetime import date, datetime

import PTT


@dataclass
class ParsedTitle:
    clean_title: str
    year: int | None
    season: int | None
    episode: int | None
    resolution: str | None  # "SD" | "HD" | "FHD" | "UHD"
    release_group: str | None
    site_name: str | None  # first token — used by TPDB matcher
    release_date: date | None


_RES_MAP = {
    "4k": "UHD",
    "2160p": "UHD",
    "1080p": "FHD",
    "720p": "HD",
    "480p": "SD",
    "576p": "SD",
}

_BRACKET_PREFIX = re.compile(r'^\s*\[([^\]]+)\]')

# Last dot-separated token as group fallback (e.g. "…1080p.seleZen.mkv")
_DOT_GROUP = re.compile(r'\.([A-Za-z][A-Za-z0-9]{1,})\.[a-z]{2,4}$', re.I)
_NOT_GROUP = re.compile(r'^(DL|WEB|BD|BR|Rip|HD|SD|Cam|TS|TC|R5|SCR|DVDSCR|\d+p|4[Kk])$', re.I)

# xxxclub-style date embedded after site name: "SiteName YY MM DD Scene Title"
_XXXDATE = re.compile(r'\b(\d{2})\s+(\d{2})\s+(\d{2})\b')
_NOISE_TAIL = re.compile(r'\bXXX\b\s*$', re.I)


def parse_title(raw_title: str) -> ParsedTitle:
    ptt = PTT.parse_title(raw_title)

    title: str = ptt.get("title") or raw_title.strip()
    year: int | None = ptt.get("year")
    season: int | None = (ptt.get("seasons") or [None])[0]
    episode: int | None = (ptt.get("episodes") or [None])[0]

    # Resolution
    resolution: str | None = _RES_MAP.get((ptt.get("resolution") or "").lower())

    # site_name + release_group
    # [Studio] prefix: PTT puts it in 'group'; we want it as site_name
    bracket = _BRACKET_PREFIX.match(raw_title.strip())
    ptt_site = ptt.get("site")
    ptt_group = ptt.get("group")

    if ptt_site:
        site_name = ptt_site
        release_group = ptt_group
    elif bracket:
        site_name = bracket.group(1).strip()
        release_group = None  # the bracket studio is not a release group
    else:
        site_name = None
        release_group = ptt_group

    # Dot-group fallback: when PTT found no group and the filename has a trailing ".Group.ext"
    if not release_group:
        dg = _DOT_GROUP.search(raw_title)
        if dg and not _NOT_GROUP.match(dg.group(1)):
            release_group = dg.group(1)

    # release_date from PTT
    release_date: date | None = None
    date_str: str | None = ptt.get("date")
    if date_str:
        try:
            release_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            pass

    # xxxclub date-in-title fallback when PTT misses it
    if not release_date:
        dm = _XXXDATE.search(raw_title)
        if dm:
            try:
                release_date = date(2000 + int(dm.group(1)), int(dm.group(2)), int(dm.group(3)))
            except ValueError:
                pass

    # xxxclub title correction: PTT returns only the site name as title when the
    # format is "SiteName YY MM DD Scene Title". Extract the real title from after the date.
    if release_date:
        raw_words = raw_title.strip().split()
        if raw_words and title == raw_words[0]:
            dm = _XXXDATE.search(raw_title)
            if dm:
                after = raw_title[dm.end():].strip()
                after = _NOISE_TAIL.sub("", after).strip()
                if after:
                    title = after
                    if not site_name:
                        site_name = raw_words[0]

    return ParsedTitle(
        clean_title=title,
        year=year,
        season=season,
        episode=episode,
        resolution=resolution,
        release_group=release_group,
        site_name=site_name,
        release_date=release_date,
    )


if __name__ == "__main__":
    import sys

    raw = sys.argv[1]
    p = parse_title(raw)
    print(f"Input:  {raw}")
    print(f"  clean_title   = {p.clean_title!r}")
    print(f"  year          = {p.year}")
    print(f"  season/ep     = {p.season} / {p.episode}")
    print(f"  resolution    = {p.resolution}")
    print(f"  release_group = {p.release_group}")
    print(f"  site_name     = {p.site_name}")
    print(f"  release_date  = {p.release_date}")
