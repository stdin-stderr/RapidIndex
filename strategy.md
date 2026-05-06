# RapidIndex — Build Strategy

End goal: a unified usenet + torrent pre-indexer that ingests continuously from Spotnet (NNTP)
and torrent sites (like clubxxx), enriches with TMDB/TPDB metadata, and exposes everything via a REST +
Newznab/Torznab + Stremio API.

---

## What is already done ✅

| Area | Files |
|------|-------|
| DB models + migrations | `src/storage/models.py`, `src/storage/migrations/` |
| Release repository | `src/storage/repositories/release_repo.py` |
| Scene / performer / people repos | `src/storage/repositories/{scene,performer,people}_repo.py` |
| Scan state repo | `src/storage/repositories/scan_state_repo.py` |
| DB engine + session factory | `src/storage/db.py` — `get_session_factory()` |
| Utils: rate limiter, HTTP, categories | `src/utils/{rate_limiter,http,categories}.py` |
| Ingester base | `src/ingesters/base.py` — `RawRelease`, `Ingester` ABC |
| NNTP client (raw SSL, no nntplib) | `src/ingesters/usenet/nntp.py` — `NNTPClient` |
| NZB builder | `src/nzb/builder.py` — `build_nzb()` |
| Spotnet ingester | `src/ingesters/usenet/spotnet.py` — `SpotnetIngester` |
| Pipeline scheduler | `src/pipeline/ingester_scheduler.py` — `run_ingesters()` |
| Entry point (ingester mode) | `main.py` |
| Docker: db + migrate + ingester-spotnet | `docker-compose.yml`, `Dockerfile` |

**Verified working:** 131 Spotnet releases indexed, NZBs assembled, in Postgres.  
`pending_enrichment` has 114 queued rows waiting for enrichers.

---

## Build order

### Step 1 — Title parser  `src/parsing/title_parser.py`

Everything downstream (router, enrichers, worker) depends on this. Build it first.

Spec: `docs/parsing.md`

```python
# src/parsing/title_parser.py
@dataclass
class ParsedTitle:
    clean_title: str
    year: int | None
    season: int | None        # from S01E02
    episode: int | None
    resolution: str | None    # "SD" | "HD" | "FHD" | "UHD"
    release_group: str | None # "YIFY", "NTG", etc.
    site_name: str | None     # first token — used by TPDB
    release_date: date | None # explicit date in title

def parse_title(raw_title: str) -> ParsedTitle: ...
```

Patterns to handle (from `docs/parsing.md`):
- `SiteName - Performers - SceneTitle` (Spotnet/TPDB)
- `SiteName 23 04 15 Scene Title XXX` (xxxclub date)
- `Title.2023.1080p.BluRay.x264-GROUP`
- `Show.Name.S01E02.1080p`
- `[StudioName] Movie Title (2022)`

Resolution mapping: `1080p/FHD → "FHD"`, `720p/HD → "HD"`, `2160p/4K/UHD → "UHD"`, else `"SD"`.

After parsing, the worker stores back to `releases`: `season`, `episode`, `quality` (resolution), `date`.

---

### Step 2 — Content router  `src/routing/content_router.py`

Spec: `docs/routing.md`

```python
class EnricherType(Enum):
    TPDB       = "tpdb"
    TMDB_MOVIE = "tmdb_movie"
    TMDB_TV    = "tmdb_tv"
    SKIP       = "skip"

def route(release: Release, settings: Settings) -> tuple[EnricherType, ParsedTitle]:
    """Parse title and decide enricher. Called by enricher worker at dequeue time."""
```

Routing rules (priority order, first match wins):

| Priority | Condition | Result |
|----------|-----------|--------|
| 0 | `hints["content_type"]` is set | that type |
| 1 | `raw_category == "xxx"` | `TPDB` |
| 2 | `source_name == "xxxclub"` | `TPDB` |
| 4 | `raw_category` in `{"audio","image","apps"}` | `SKIP` |
| 5 | `raw_category` maps to movie | `TMDB_MOVIE` |
| 6 | `raw_category` maps to TV | `TMDB_TV` |
| 7 | `ParsedTitle.season is not None` | `TMDB_TV` |
| 8 | fallback | `TMDB_MOVIE` |

Downgrade to `SKIP` if the required API key is not configured.

Key input: `src/storage/models.py:Release` (reads `raw_category`, `source_name`, `hints`).  
Key input: `src/utils/categories.py:ContentCategory` and `_SPOTNET_MAP`.

---

### Step 3 — Enricher base + TMDB + TPDB  (can be built in parallel)

#### 3a — `src/enrichers/base.py`
Spec: `docs/enrichers/base.md`

```python
@dataclass
class EnrichmentResult:
    matched: bool
    score: float       # 0.0–1.0
    external_id: str   # tmdb_id or tpdb_id, empty if no match
    metadata: dict

class Enricher(ABC):
    @abstractmethod
    async def enrich(self, release: Release, parsed: ParsedTitle) -> EnrichmentResult: ...
```

#### 3b — `src/enrichers/tmdb.py`
Spec: `docs/enrichers/tmdb.md`

- Rate limit: 40 req/10s — use `src/utils/rate_limiter.py:RateLimiter(40, 10)`
- HTTP: use `src/utils/http.py:HttpClient` (retry + Redis cache built in)
- Hint fast-path: check `release.hints` for `tmdb_id`, `imdb_id`, `tvdb_id` before search
- Fuzzy match: `difflib.SequenceMatcher` ratio ≥ 0.6
- After match: fetch external IDs + cast (see `docs/enrichers/tmdb.md` for cast upsert logic)
- Write to: `src/storage/repositories/people_repo.py` (`upsert_person`, `upsert_cast`)
- Link via: `ReleaseTmdbTitle` in `src/storage/models.py`

#### 3c — `src/enrichers/tpdb.py`
Spec: `docs/enrichers/tpdb.md`

- Rate limit: 5 req/s — use `src/utils/rate_limiter.py:RateLimiter(5, 1)`
- 4-pass matching: `clean_title + site + date` → `clean_title + site` → `clean_title` → performer names
- Scoring: title similarity (35–70%) + site match (25–30%) + date proximity (0–40%), threshold 0.65
- Write to: `src/storage/repositories/scene_repo.py` (`upsert_scene`, `link_release_to_scene`)
- Also write to: `src/storage/repositories/performer_repo.py` (`upsert_performer`)
- `site_name` comes from `ParsedTitle.site_name` (first token of title)

---

### Step 4 — Enricher worker  `src/pipeline/enricher_worker.py`

Spec: `docs/pipeline.md`

```python
ENRICHERS: dict[str, Enricher] = {
    "tmdb_movie": TMDBEnricher(settings, http_client),
    "tmdb_tv":    TMDBEnricher(settings, http_client),
    "tpdb":       TPDBEnricher(settings, http_client),
}

async def run_worker(session_factory, settings: Settings) -> None:
    while True:
        batch = await claim_enrichment_batch(session, batch_size=10)  # FOR UPDATE SKIP LOCKED
        for item in batch:
            release = await session.get(Release, item.release_id)
            enricher_type, parsed = route(release, settings)
            if enricher_type == EnricherType.SKIP:
                # mark skipped, delete from queue
            else:
                result = await ENRICHERS[item.enricher].enrich(release, parsed)
                if result.matched:
                    # write metadata + join rows, mark matched, delete from queue
                    # also write back season/episode/quality/date from parsed
                else:
                    # no match: increment attempts, set next_attempt = now() + 7 days
                    # after 2 attempts: mark match_failed, delete from queue
```

Key repos used:
- `src/storage/repositories/release_repo.py`: `claim_enrichment_batch`, `complete_enrichment`, `fail_enrichment`
- `src/storage/repositories/{scene,people}_repo.py` (via enrichers)

Concurrency: `asyncio.gather(*[run_worker(...) for _ in range(settings.enricher_workers)])`

---

### Step 5 — xxxclub ingester  `src/ingesters/torrent/xxxclub.py`

Spec: `docs/ingesters/xxxclub.md`

Independent of enrichers — can be built alongside Step 3/4.

```python
class XXXClubIngester(Ingester):
    source_name = "xxxclub"
    # Scrapes /torrents/browse/all/ (paginated) + /torrents/top100/*
    # Uses src/utils/http.py:HttpClient for aiohttp requests
    # Parses HTML with BeautifulSoup (add beautifulsoup4/lxml to pyproject.toml)
    # Watermark: ISO date of newest date_added seen
    # source_key = info_hash (40-char hex)
    # Yields RawRelease(source_type="torrent", source_name="xxxclub", ...)
```

Enable in `.env`:
```env
XXXCLUB_ENABLED=true
```

Enable in `docker-compose.yml` (already stubbed, commented out):
```yaml
ingester-xxxclub:
  command: python main.py ingester xxxclub
```

Add to `main.py` ingester dispatch alongside spotnet.

---

### Step 6 — REST API  `src/api/`

Spec: `docs/api/rest.md`

Framework: FastAPI (not in pyproject.toml yet — add `fastapi` + `uvicorn[standard]`).

```
src/api/
  app.py          — FastAPI app, register routers
  routers/
    releases.py   — GET /api/v1/releases
    titles.py     — GET /api/v1/titles, /titles/:id/cast
    scenes.py     — GET /api/v1/scenes
    performers.py — GET /api/v1/performers
    newznab.py    — GET /api?t=...  +  GET /nzb/:release_id
```

All queries go through existing repositories:
- `src/storage/repositories/release_repo.py:search_releases()`
- `src/storage/repositories/scene_repo.py:search_scenes()`
- `src/storage/repositories/performer_repo.py:search_performers()`

Newznab category → content_type mapping (from `docs/api/newznab.md`):

| Newznab cat | content_type |
|-------------|--------------|
| 2000–2999 | `movie` |
| 3000–3999 | `music` |
| 4000–4999 | `software` |
| 5000–5999 | `tv` |
| 6000–6999 | `xxx` |
| 7000–7999 | `book` |

NZB download: `GET /nzb/:release_id` reads `usenet_releases.nzb_xml` bytes directly — no NNTP.

---

### Step 7 — Stremio addon  `src/api/stremio/`

Spec: `docs/api/stremio.md`

Build after REST API. Requires torrent releases (from xxxclub) for stream resolution.

```
src/api/stremio/
  addon.py                  — catalog + stream endpoints
  debrid/
    base.py                 — DebridClient ABC: resolve(info_hash, file_index) -> str | None
    torbox.py
    realdebrid.py
    alldebrid.py
    premiumize.py
```

Config-in-URL pattern: `{config}` = base64url `{"service": "torbox", "apiKey": "..."}`.
Key: never stored server-side, decoded per request and discarded.

Enable in `.env`: `STREMIO_ENABLED=true`

---

### Step 8 — Wire remaining main.py modes + Docker services

```python
# main.py additions
elif mode == "worker":
    asyncio.run(run_worker_mode())
elif mode == "api":
    uvicorn.run("src.api.app:app", host=settings.api_host, port=settings.api_port)
elif mode == "all":
    # asyncio.gather of ingester + worker + api tasks
```

Uncomment in `docker-compose.yml` (stubs already there):
```yaml
api:
  command: python main.py api
worker:
  command: python main.py worker
ingester-xxxclub:
  command: python main.py ingester xxxclub
```

All three depend on `migrate: condition: service_completed_successfully`.

---

## Dependency graph

```
parse_title()
    └── content_router.route()
            └── enricher_worker
                    ├── TMDBEnricher  ← TMDB_API_KEY
                    └── TPDBEnricher  ← TPDB_API_KEY

SpotnetIngester ──┐
XXXClubIngester ──┼── ingester_scheduler ── upsert_release() ── pending_enrichment queue
                  │                                                     │
                  └─────────────────────────────────────────────────────┘
                                                                         ↓
                                                                  enricher_worker
                                                                         ↓
                                                                  releases (matched)
                                                                         ↓
                                                    REST API / Newznab / Stremio
```

## Key config fields (Settings in `src/config.py`)

```python
# Already present — nothing to add for Steps 1–4
tmdb_api_key: str | None        # Step 3b — TMDB enricher
tpdb_api_key: str | None        # Step 3c — TPDB enricher
enricher_workers: int = 4       # Step 4 — worker concurrency
metadata_min_score: float = 0.65  # Step 3c — TPDB threshold

# Need to add for Steps 6–7
# fastapi / uvicorn already has api_host, api_port in Settings
stremio_enabled: bool = True    # Step 7 — already in Settings
```

## Notes for future agents

- **Do not re-read all docs** — the snippets above contain the essential contracts.
- `src/storage/repositories/release_repo.py:upsert_release()` is the single write path for ingesters; its full signature is in that file.
- `src/storage/repositories/release_repo.py:claim_enrichment_batch()` uses `FOR UPDATE SKIP LOCKED` — safe for concurrent worker containers.
- `src/utils/http.py:HttpClient` wraps aiohttp with retry + optional Redis caching. Pass `redis_url` from settings to enable caching.
- `src/utils/rate_limiter.py:RateLimiter(rate, per_seconds)` — async token bucket, call `await limiter.acquire()` before each API request.
- The `enricher` column in `pending_enrichment` was written by the scheduler as a best-effort value; the worker **re-routes** via `content_router.route()` at dequeue time for correctness.
- `usenet_releases.nzb_xml` is `BYTEA NOT NULL` at the DB level — only create the side-table row when NZB bytes are available.
