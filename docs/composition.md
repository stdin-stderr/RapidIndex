# Composition — How Parts Fit Together

Every component is independently toggleable. You can run only xxxclub, only Spotnet, or any
combination, with or without each enricher, with or without the Stremio addon.

---

## Component Dependency Map

```
                    ┌──────────────┐
                    │  PostgreSQL  │  always required
                    └──────┬───────┘
                           │
           ┌───────────────┼───────────────┐
           │               │               │
    ┌──────▼──────┐ ┌──────▼──────┐ ┌─────▼──────┐
    │   Worker    │ │   REST API  │ │  Newznab/  │
    │ (enrichers) │ │  (FastAPI)  │ │  Torznab   │
    └──────┬──────┘ └─────────────┘ └────────────┘
           │
    ┌──────┴──────────────┐
    │      Ingesters      │  each runs as its own container
    │  spotnet | xxxclub  │
    └──────┬──────────────┘
           │
    ┌──────▼──────────────┐
    │    Enrichers         │  optional per content type
    │  TMDB / TPDB / both │
    └─────────────────────┘
```

NZBs are assembled by the Spotnet ingester at index time and stored in the database.
The API serves them directly — no NNTP connection at request time.

---

## What Is Always Required

| Component | Why |
|-----------|-----|
| PostgreSQL | Primary store for all releases and metadata |
| `storage/` | ORM models and repositories — used by pipeline and API |
| `config.py` | Settings loader |
| `main.py` | Entrypoint |

---

## What Is Optional

| Component | Enabled by | Effect when disabled |
|-----------|-----------|----------------------|
| xxxclub ingester | `XXXCLUB_ENABLED=true` | No torrent releases from xxxclub |
| Spotnet ingester | `SPOTNET_ENABLED=true` | No usenet releases |
| TMDB enricher | `TMDB_API_KEY` set | SFW releases stored without metadata; Newznab movie/TV search still works but returns unmatched releases |
| TPDB enricher | `TPDB_API_KEY` set | NSFW releases stored without scene/performer metadata |
| Redis cache | `REDIS_URL` set | API calls to TMDB/TPDB go uncached; higher API usage |
| Stremio addon | `STREMIO_ENABLED=true` | `/stremio/` routes not registered |

---

## Example Configurations

### Only xxxclub (torrents, NSFW)

```env
XXXCLUB_ENABLED=true
SPOTNET_ENABLED=false
TPDB_API_KEY=...
# TMDB_API_KEY not set — no SFW enrichment needed
STREMIO_ENABLED=true
```

What happens:
- xxxclub ingester runs on its interval
- All releases route to TPDB (xxxclub always → TPDB)
- Releases indexed with scene/performer metadata
- Stremio streams via magnet or debrid
- Newznab endpoint available but returns no usenet content

---

### Only Spotnet (usenet, SFW + NSFW)

```env
XXXCLUB_ENABLED=false
SPOTNET_ENABLED=true
SPOTNET_NNTP_HOST=news.example.com
SPOTNET_NNTP_USER=...
SPOTNET_NNTP_PASS=...
TMDB_API_KEY=...
TPDB_API_KEY=...
STREMIO_ENABLED=false
```

What happens:
- Spotnet ingester polls NNTP newsgroups, assembles NZBs at index time
- SFW video → TMDB enrichment; XXX (cat. 7) → TPDB enrichment
- Newznab endpoint serves all releases to Sonarr/Radarr/SABnzbd
- NZB files served directly from `usenet_releases.nzb_xml` — no NNTP at request time
- Stremio not available (no magnet/info_hash for usenet releases)

---

### Full stack (torrents + usenet, SFW + NSFW)

```env
XXXCLUB_ENABLED=true
SPOTNET_ENABLED=true
SPOTNET_NNTP_HOST=news.example.com
SPOTNET_NNTP_USER=...
SPOTNET_NNTP_PASS=...
TMDB_API_KEY=...
TPDB_API_KEY=...
REDIS_URL=redis://redis:6379
STREMIO_ENABLED=true
```

What happens:
- Both ingesters run as separate containers on their own schedules
- Content router directs each release to the correct enricher
- REST, Newznab, Torznab, and Stremio APIs all active
- NZBs pre-assembled and stored; API container has no NNTP dependency
- Redis caches TMDB/TPDB responses

---

## How Ingesters Connect to Enrichers

Ingesters and enrichers are **not directly coupled**. The connection is:

```
Ingester → RawRelease → Queue → Content Router → Enricher
```

1. An ingester emits a `RawRelease` with a `raw_category` string and a `source_name`.
2. The `ingester_scheduler` writes the release to the DB and pushes it to `pending_enrichment`.
3. The `enricher_worker` picks it up and calls the content router.
4. The router reads `raw_category` and `source_name` to decide which enricher to call.
5. The enricher has no knowledge of which ingester produced the release.

Adding a new ingester does not require touching any enricher. Adding a new enricher only
requires adding a routing rule and a registry entry.

---

## How the API Connects to Everything

The API is **fully read-only** — it only queries the database and has no dependencies on
ingesters, enrichers, the pipeline queue, or NNTP. This means:

- The API container can restart without affecting ongoing ingestion.
- The worker and ingester containers can restart without dropping API availability.
- A future web UI can be added as a separate service reading the same database with zero
  changes to the pipeline or enrichers.

---

## Enricher Skipping Rules

If an enricher's API key is not configured, the content router returns `EnricherType.SKIP`
for that content type. The enricher worker writes `metadata_status = "skipped"` and moves on.
The release is still stored and fully queryable — it just has no metadata attached.

| `TMDB_API_KEY` | `TPDB_API_KEY` | SFW releases | NSFW releases |
|:-:|:-:|--------------|---------------|
| ✓ | ✓ | enriched with TMDB | enriched with TPDB |
| ✓ | — | enriched with TMDB | stored, no metadata |
| — | ✓ | stored, no metadata | enriched with TPDB |
| — | — | stored, no metadata | stored, no metadata |
