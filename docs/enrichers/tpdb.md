# Enricher — ThePornDB (TPDB)

`enrichers/tpdb.py`

Matches NSFW releases (from xxxclub torrents and Spotnet XXX usenet) to scenes and movies using the ThePornDB API. Multi-pass matching logic ported from xxxclub_scraper.

---

## Enabled by

```env
TPDB_API_KEY=...
```

If not set, all releases routed to `TPDB` are skipped with `metadata_status = "skipped"`.

---

## Rate limit

5 requests per second. Enforced via `utils/rate_limiter.py`.

---

## Match passes — scenes

Four passes, each progressively looser. The first pass to exceed the score threshold wins.

| Pass | Search parameters |
|------|------------------|
| 1 | `clean_title` + `site_name` + `release_date` (strict date window ±3 days) |
| 2 | `clean_title` + `site_name` (date ignored) |
| 3 | `clean_title` only |
| 4 | Performer names extracted from title |

---

## Scoring

Each candidate returned by the TPDB search is scored:

| Component | Weight | Notes |
|-----------|--------|-------|
| Title similarity | 35–70% | `SequenceMatcher` ratio; higher weight when site also matches |
| Site name match | 25–30% | Normalised slug comparison |
| Date proximity | 0–40% | Linear decay from 0 days (full weight) to 30 days (zero weight) |

Minimum acceptance threshold: **0.65** (configurable via `METADATA_MIN_SCORE`).

---

## Stored metadata

Written to `tpdb_scenes` and linked via `release_tpdb_scenes`:

- `tpdb_id`, `tpdb_type`: `"scene"` or `"movie"`
- `title`, `description`, `date`, `duration_secs`
- `site_id` → `tpdb_sites`
- `performers` JSONB: denormalised array from TPDB performer profiles
- `tags` JSONB
- `poster_url`, `background_url`

Performer profiles are also written to `tpdb_performers` for independent querying (e.g. `GET /api/v1/performers`).

Site and network records are written to `tpdb_sites` / `tpdb_networks` on first encounter.
