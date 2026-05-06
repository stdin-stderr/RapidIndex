# RapidIndex

Unified usenet + torrent pre-indexer with metadata enrichment. Background workers ingest and enrich continuously; the API is read-only.

## Project layout

```
docs/           Full architecture docs (start here for context)
src/
  ingesters/    One file per source: spotnet.py, xxxclub.py
  pipeline/     Scheduler, queue logic, enricher worker
  enrichers/    tmdb.py (SFW), tpdb.py (NSFW)
  parser/       Unified title parser
  api/          REST, Newznab+Torznab, Stremio handlers
  db/           Migrations, repositories, schema
main.py         Entry point — see "Running services" below
```

## Data flow

```
Ingester → RawRelease → pending_enrichment queue → Enricher Worker → releases table → API
```

## Schema: core table + source side-tables

`releases` holds shared fields (title, quality, content_type, enrichment state, metadata FKs).
Source-specific payload lives in 1:1 side-tables:

```
releases            id, source_type, raw_title, quality, content_type, metadata_status, ...
usenet_releases     release_id FK, groups, poster, nzb_xml BYTEA NOT NULL
torrent_releases    release_id FK, info_hash, magnet, size_bytes, seeders, leechers
```

Adding a new source type (DDL, IRC, etc.) = new side-table, no changes to `releases`.

`source_key` is globally `UNIQUE` (intentional). Same content appearing on multiple sources
merges into one row. Spotnet keys (`h7zTfNCJveAPDP3aQTnGk@spot.net`) and torrent info_hashes
are structurally different — collision risk is zero in practice.

## NZB assembly

NZBs are assembled at **index time** by the Spotnet ingester during NNTP ingestion. The
complete NZB is stored immediately as `usenet_releases.nzb_xml BYTEA`. The API serves it
directly — no NNTP credentials required in the API container.

This makes the Spotnet ingester slower (one NNTP round-trip per article) but fully decouples
the API from NNTP and eliminates any JIT race conditions.

## Content types

`content_type` enum covers all categories now and in the future:

| value | Newznab cat | Enricher |
|-------|-------------|----------|
| `movie` | 2000 | TMDB_MOVIE |
| `tv` | 5000 | TMDB_TV |
| `xxx` | 6000 | TPDB |
| `music` | 3000 | *(reserved — SKIP for now)* |
| `book` | 7000 | *(reserved — SKIP for now)* |
| `software` | 4000 | *(reserved — SKIP for now)* |
| `other` | 1000 | SKIP |

Unenriched types (`music`, `book`, `software`) are indexed and searchable immediately;
enrichment metadata is added once a matching enricher is registered.

## Enrichment routing

| Signal | content_type |
|--------|-------------|
| Spotnet cat 7 / source `xxxclub` | `xxx` |
| Audio categories (Newznab 3xxx) | `music` → SKIP |
| Book categories (Newznab 7xxx) | `book` → SKIP |
| Software categories (Newznab 4xxx) | `software` → SKIP |
| Movie categories | `movie` |
| TV categories / parsed S##E## | `tv` |
| Fallback | `movie` |

Enricher registry (add new enrichers here, no router changes needed):

```python
ENRICHERS = {
    "tmdb_movie": TMDBEnricher,
    "tmdb_tv":    TMDBEnricher,
    "tpdb":       TPDBEnricher,
    # "musicbrainz": MusicBrainzEnricher,  # future
}
```

## Retry and failure logic

- **API errors** (network failure, 5xx): do not increment `attempts`. The HTTP client
  backs off automatically. Retried transparently until the API recovers.
- **No match** (API returns 0 results): increment `attempts`. Retry once after 7 days.
  After the second no-match, mark `metadata_status = "match_failed"` and stop retrying.
- **`match_failed`** releases can be re-queued by the optional re-enricher sweep
  (`RE_ENRICH_FAILED_AFTER_DAYS`).

## Running services

Each component runs as its own process and Docker service:

```
python main.py api                  # REST + Newznab/Torznab + Stremio
python main.py worker               # enrichment workers only
python main.py ingester spotnet     # Spotnet/NNTP ingester
python main.py ingester xxxclub     # xxxclub torrent ingester
python main.py all                  # everything in one process (dev only)
```

All services share the same PostgreSQL. Disabling a service = remove or comment its
block in `docker-compose.yml`. No code changes required.

**Migrations:** migrate.py must run after the postgress database and before all other services in the docker compose. With depends_on and condition: service_completed_successfully.

## Key design rules

- One `releases` row per `source_key`; side-table row per source type.
- Global `source_key` uniqueness is intentional — same content from multiple sources merges.
- NZB assembled at index time, stored as BYTEA in `usenet_releases.nzb_xml`.
- API container requires no NNTP credentials.
- Debrid API keys never stored server-side — encoded in Stremio config URL.
- All ingesters share a common interface and emit `RawRelease`.
- Queue uses `FOR UPDATE SKIP LOCKED` — safe for multiple worker containers.
- Optional components disabled by omitting their env var (no API key → feature off).
- Enricher registry is a plain dict — adding a new enricher requires no router changes.
- API errors never count as enrichment failures — only genuine no-match responses do.

## APIs

- `GET /api/v1/releases` — filterable release list
- `GET /api/v1/titles` — TMDB titles
- `GET /api/v1/scenes` + `/performers` — TPDB entities
- `/api?t=...` — Newznab (Sonarr/Radarr/SABnzbd compatible)
- `/torznab?t=...` — Torznab (Prowlarr/Jackett compatible)
- `/stremio/{config}/` — Stremio addon with debrid stream resolution

## Docs index

See `/docs` for the full architecture:
- `architecture.md` — system overview
- `ingesters.md` — ingester interface contract
- `pipeline.md` — queue and worker design
- `enrichers.md` — TMDB / TPDB matching logic
- `schema.md` — full PostgreSQL schema
- `api.md` — REST / Newznab / Torznab / Stremio spec
- `deployment.md` — Docker Compose, scaling, migrations
