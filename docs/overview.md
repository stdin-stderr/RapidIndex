# Overview

A unified, pre-indexing media scraper that ingests releases from **usenet** and **torrent** sources, enriches them with metadata from **TMDB** (movies/TV) and **ThePornDB** (NSFW content), and exposes the indexed results over a REST + Newznab + Torznab + Stremio API.

All ingestion and enrichment runs in background workers. The API only reads from the database — nothing is fetched on-demand.

---

## Data Flow

```
┌──────────────────────────────────────────────────────────┐
│                       INGESTERS                          │
│                                                          │
│  ┌───────────────────────┐   ┌────────────────────────┐  │
│  │     TorrentSite       │   │      SpotnetNNTP       │  │
│  │       xxxclub         │   │  (py_spotweb protocol) │  │
│  │                       │   │  incl. XXX category    │  │
│  └──────────┬────────────┘   └───────────┬────────────┘  │
└─────────────┼────────────────────────────┼───────────────┘
              │                             │
              └─────────────┬───────────────┘
                            │  RawRelease (normalised)
                   ┌────────▼────────┐
                   │  Release Queue  │  pending_enrichment table
                   └────────┬────────┘
                            │
              ┌─────────────▼──────────────┐
              │       Content Router        │  NSFW vs SFW
              │   + parsing/title_parser    │  Spotnet cat.7 → TPDB
              └──────┬──────────────────────┘
                     │
         ┌───────────┴────────────┐
         │                        │
  ┌──────▼──────┐         ┌───────▼──────┐
  │ TMDB Matcher│         │ TPDB Matcher │
  │ (movies/TV) │         │ (NSFW scenes │
  └──────┬──────┘         │  & movies)   │
         │                └───────┬──────┘
         └───────────┬────────────┘
                     │
            ┌────────▼────────┐
            │   PostgreSQL    │
            │  releases       │
            │  usenet/torrent │
            │  side-tables    │
            │  tmdb_metadata  │
            │  tpdb_scenes    │
            │  tpdb_performers│
            └────────┬────────┘
                     │
         ┌───────────┴────────────┐
         │                        │
  ┌──────▼──────┐         ┌───────▼──────┐
  │  REST API   │         │   Stremio    │
  │  + Newznab  │         │   + Debrid   │
  │  + Torznab  │         └──────────────┘
  └─────────────┘
```

---

## Core Principles

| Principle | Description |
|-----------|-------------|
| **Pre-indexed** | Workers ingest and enrich continuously. The API never triggers a live fetch. |
| **Pluggable ingesters** | Each source implements a common interface. Adding a new source is one new file. |
| **Split schema** | `releases` holds shared fields; `usenet_releases` and `torrent_releases` are 1:1 side-tables. |
| **Content routing** | A rule-based router picks the enricher. Spotnet XXX (cat. 7) routes to TPDB, same as xxxclub. |
| **Idempotent ingestion** | `source_key` deduplicates globally. Re-ingesting a known key is a no-op. Cross-source merging is intentional. |
| **Rate-aware enrichment** | A token-bucket enforces per-API rate limits. API errors use automatic backoff without consuming retry attempts. |
| **UI-agnostic API** | No web UI. The `api/` layer is thin — repositories handle all queries — so a UI can be added later. |
| **Stateless credentials** | Debrid API keys are never stored. They travel in the Stremio URL path. |
| **Fully decoupled API** | The API container has no dependency on NNTP, ingesters, or the enrichment worker. NZBs are pre-assembled at index time. |
| **Horizontal-ready** | Each service runs as its own Docker container. PostgreSQL coordinates all workers. |

---

## Module Dependency Direction

```
api → storage ← pipeline ← enrichers ← parsing
                               ↑
                           ingesters
                                      nzb (imported by ingesters/spotnet)
              utils  (imported by all layers)
              routing (imported by pipeline)
```

No layer imports from `api/`. Storage is the only shared dependency between the API and the pipeline.

---

## File Map

```
rapidindex/
├── ingesters/
│   ├── base.py
│   ├── torrent/
│   │   ├── base.py
│   │   └── xxxclub.py
│   └── usenet/
│       ├── base.py
│       └── spotnet.py
├── parsing/
│   └── title_parser.py
├── enrichers/
│   ├── base.py
│   ├── tmdb.py
│   └── tpdb.py
├── routing/
│   └── content_router.py
├── nzb/
│   └── builder.py
├── pipeline/
│   ├── queue.py
│   ├── ingester_scheduler.py
│   └── enricher_worker.py
├── storage/
│   ├── db.py
│   ├── models.py
│   └── repositories/
│       ├── release_repo.py
│       ├── scene_repo.py
│       └── performer_repo.py
├── utils/
│   ├── rate_limiter.py
│   ├── http.py
│   └── categories.py
├── api/
│   ├── app.py
│   ├── routers/
│   │   ├── releases.py
│   │   ├── scenes.py
│   │   ├── performers.py
│   │   ├── titles.py
│   │   └── newznab.py
│   └── stremio/
│       ├── addon.py
│       └── debrid/
│           ├── base.py
│           ├── torbox.py
│           ├── realdebrid.py
│           ├── alldebrid.py
│           └── premiumize.py
├── config.py
├── main.py
├── Dockerfile
└── docker-compose.yml
```

---

## Further Reading

- [composition.md](composition.md) — how parts connect, what is optional, example configurations
- [ingesters/base.md](ingesters/base.md) — ingester interface and `RawRelease`
- [ingesters/xxxclub.md](ingesters/xxxclub.md) — xxxclub.to torrent scraper
- [ingesters/spotnet.md](ingesters/spotnet.md) — Spotnet/NNTP usenet ingester
- [parsing.md](parsing.md) — title parser
- [routing.md](routing.md) — content router
- [enrichers/base.md](enrichers/base.md) — enricher interface
- [enrichers/tmdb.md](enrichers/tmdb.md) — TMDB enricher
- [enrichers/tpdb.md](enrichers/tpdb.md) — ThePornDB enricher
- [pipeline.md](pipeline.md) — queue, scheduler, worker
- [nzb.md](nzb.md) — NZB assembly at index time
- [storage.md](storage.md) — full database schema
- [utils.md](utils.md) — shared utilities
- [api/rest.md](api/rest.md) — REST endpoints
- [api/newznab.md](api/newznab.md) — Newznab/Torznab endpoint
- [api/stremio.md](api/stremio.md) — Stremio addon and debrid
- [config.md](config.md) — configuration reference
- [deployment.md](deployment.md) — Docker Compose and entrypoint modes
