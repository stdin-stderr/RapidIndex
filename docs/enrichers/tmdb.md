# Enricher — TMDB

`enrichers/tmdb.py`

Matches SFW releases to movies and TV shows using The Movie Database API.

---

## Enabled by

```env
TMDB_API_KEY=...
```

If not set, all releases routed to `TMDB_MOVIE` or `TMDB_TV` are skipped with `metadata_status = "skipped"`.

---

## Rate limit

40 requests per 10 seconds (TMDB free tier). Enforced via `utils/rate_limiter.py`.

---

## Search strategy — movies

1. Search TMDB by `ParsedTitle.clean_title + year` (if year is available).
2. Score each result with `SequenceMatcher` on title similarity.
3. If best score < 0.6, retry without year.
4. Accept the highest-scoring result if score ≥ 0.6.

---

## Search strategy — TV

1. Search TMDB by `ParsedTitle.clean_title` (season/episode tokens stripped).
2. If `ParsedTitle.season` and `episode` are available, validate against the TMDB episode list for date cross-check.
3. Accept if score ≥ 0.6.

---

## External IDs

After a successful match, a second call is made to `/movie/{id}/external_ids` or `/tv/{id}/external_ids`. This returns all known IDs in one response:

| Field | Column | Use |
|-------|--------|-----|
| IMDB id | `tmdb_metadata.imdb_id` | Newznab `?t=movie&imdbid=` lookups |
| TVDB id | `tmdb_metadata.tvdb_id` | Newznab `?t=tvsearch&tvdbid=` lookups |
| All others | `tmdb_metadata.external_ids` JSONB | Trakt, Wikidata, Facebook, etc. |

---

## Stored metadata

Written to `tmdb_metadata` and linked via `release_tmdb_titles`:

- `tmdb_id`, `imdb_id`, `tvdb_id`, `external_ids`
- `tmdb_type`: `"movie"` or `"tv"`
- `title`, `original_title`, `overview`, `tagline`
- `release_year`, `rating`, `genres`
- `poster_path`, `backdrop_path`
- `extra` JSONB: season count, episode count, networks (TV only)
