# Configuration

`config.py` — Pydantic `BaseSettings`. All values read from environment variables or a `.env` file.

---

## Database

| Variable | Default | Required |
|----------|---------|----------|
| `DATABASE_URL` | — | yes |
| `REDIS_URL` | — | no — disables response caching if unset |

---

## External API keys

| Variable | Default | Required |
|----------|---------|----------|
| `TMDB_API_KEY` | — | no — SFW enrichment disabled if unset |
| `TPDB_API_KEY` | — | no — NSFW enrichment disabled if unset |

Debrid API keys are **never in config**. See [api/stremio.md](api/stremio.md).

---

## Ingesters

### xxxclub

| Variable | Default | Description |
|----------|---------|-------------|
| `XXXCLUB_ENABLED` | `false` | Enable the xxxclub ingester |
| `XXXCLUB_INTERVAL_SECONDS` | `3600` | How often to scrape |
| `XXXCLUB_PAGE_CONCURRENCY` | `3` | Concurrent page fetches |

### Spotnet

| Variable | Default | Description |
|----------|---------|-------------|
| `SPOTNET_ENABLED` | `false` | Enable the Spotnet ingester |
| `SPOTNET_NNTP_HOST` | — | NNTP server hostname |
| `SPOTNET_NNTP_PORT` | `563` | NNTP SSL port |
| `SPOTNET_NNTP_USER` | — | NNTP username |
| `SPOTNET_NNTP_PASS` | — | NNTP password |
| `SPOTNET_NEWSGROUPS` | `free.pt` | Comma-separated newsgroup list |
| `SPOTNET_MAX_AGE_DAYS` | `90` | How far back to scan on first run |
| `SPOTNET_INTERVAL_SECONDS` | `3600` | How often to poll |

> NNTP credentials are only needed in the **Spotnet ingester container**. The API container
> does not require them — NZBs are assembled at index time and stored in the database.

---

## Pipeline / enrichment

| Variable | Default | Description |
|----------|---------|-------------|
| `ENRICHER_WORKERS` | `4` | Concurrent enricher worker tasks |
| `METADATA_MIN_SCORE` | `0.65` | Minimum match score for TPDB |
| `TMDB_REQUESTS_PER_10S` | `40` | TMDB rate limit |
| `TPDB_REQUESTS_PER_SECOND` | `5` | TPDB rate limit |
| `RE_ENRICH_FAILED_AFTER_DAYS` | — | Re-queue `match_failed` releases after N days (disabled if unset) |
| `TMDB_CAST_LIMIT` | `20` | Max cast members stored per title; `0` = unlimited |

---

## API server

| Variable | Default | Description |
|----------|---------|-------------|
| `API_HOST` | `0.0.0.0` | Bind address |
| `API_PORT` | `8000` | Port |
| `API_BASE_URL` | `http://localhost:8000` | Public base URL (used in Stremio manifest) |

---

## Stremio

| Variable | Default | Description |
|----------|---------|-------------|
| `STREMIO_ENABLED` | `true` | Register `/stremio/` routes |
