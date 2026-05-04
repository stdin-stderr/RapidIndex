# Parsing — Title Parser

`parsing/title_parser.py`

Shared by the content router and both enrichers. Extracted and unified from the regex logic in xxxclub_scraper and py_spotweb.

---

## Output

```python
@dataclass
class ParsedTitle:
    clean_title: str          # title with year/tags/resolution/group stripped
    year: int | None
    season: int | None        # from S01E02
    episode: int | None       # from S01E02
    resolution: str | None    # "SD" | "HD" | "FHD" | "UHD"
    release_group: str | None # e.g. "YIFY", "NTG"
    site_name: str | None     # first token — used by TPDB matcher
    release_date: date | None # explicit date in title (DD.MM.YYYY or YY MM DD)

def parse_title(raw_title: str) -> ParsedTitle: ...
```

---

## Patterns handled

| Pattern | Example |
|---------|---------|
| Spotnet/TPDB style | `SiteName - Performers - SceneTitle` |
| xxxclub date style | `SiteName 23 04 15 Scene Title XXX` |
| Standard scene | `Title.2023.1080p.BluRay.x264-GROUP` |
| Season/episode | `Show.Name.S01E02.1080p` |
| Bracketed studio | `[StudioName] Movie Title (2022)` |
| Year suffix | `Movie Title 2023` |

---

## Usage

```python
parsed = parse_title(release.raw_title)
enricher_type, parsed = content_router.route(release)
result = await enricher.enrich(release, parsed)
```

`parse_title()` is called once per release inside the content router. The result is passed through to the enricher — it is never called twice for the same release.

The parsed fields are then saved to the `releases` table:
- `parsed.year` → stored separately (currently derived from TMDB enrichment)
- `parsed.season`, `parsed.episode` → stored in `releases.season`, `releases.episode`
- `parsed.resolution` → mapped to `releases.quality` ("SD", "HD", "FHD", "UHD")
- `parsed.release_date` → stored in `releases.date`
