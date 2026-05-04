# Content Router

`routing/content_router.py`

Decides which enricher a release should be sent to. Called once per release by the enricher worker, after the release is dequeued.

---

## Interface

```python
def route(release: RawRelease) -> tuple[EnricherType, ParsedTitle]:
    """Parse the title and return which enricher to use."""
```

Returns both the enricher type and the parsed title so the enricher does not need to re-parse.

---

## EnricherType

```python
class EnricherType(Enum):
    TPDB        = "tpdb"
    TMDB_MOVIE  = "tmdb_movie"
    TMDB_TV     = "tmdb_tv"
    SKIP        = "skip"        # enricher API key not configured, or non-video category
```

---

## Routing Rules

Rules are evaluated in priority order. First match wins.

| Priority | Condition | Result |
|----------|-----------|--------|
| 0 | `hints.content_type` is set to a valid value | that type (overrides all below) |
| 1 | `raw_category == "xxx"` (Spotnet cat. 7) | `TPDB` |
| 2 | `source_name == "xxxclub"` | `TPDB` |
| 3 | `source_name` starts with `"generic:"` and site config sets `content_type="xxx"` | `TPDB` |
| 4 | `raw_category` in `{"audio", "image", "apps"}` | `SKIP` |
| 5 | `raw_category` maps to Movies | `TMDB_MOVIE` |
| 6 | `raw_category` maps to TV | `TMDB_TV` |
| 7 | `ParsedTitle.season` is not None | `TMDB_TV` |
| 8 | Fallback | `TMDB_MOVIE` |

Valid `hints.content_type` values: `"movie"` → `TMDB_MOVIE`, `"tv"` → `TMDB_TV`, `"xxx"` → `TPDB`. Other values are ignored and routing falls through to priority 1.

---

## Enricher skipping

If the API key for the chosen enricher is not configured, the router downgrades the result to `SKIP`. The enricher worker writes `metadata_status = "skipped"` without calling any external API.

| Chosen enricher | Key missing | Final result |
|----------------|------------|--------------|
| `TPDB` | `TPDB_API_KEY` not set | `SKIP` |
| `TMDB_MOVIE` | `TMDB_API_KEY` not set | `SKIP` |
| `TMDB_TV` | `TMDB_API_KEY` not set | `SKIP` |
