# Utils

`utils/`

Shared infrastructure imported by multiple layers. No layer other than `utils/` itself is imported here.

---

## `utils/rate_limiter.py`

Async token-bucket rate limiter. One instance per external API, shared across all concurrent enricher workers.

```python
class RateLimiter:
    def __init__(self, rate: int, per_seconds: int): ...
    async def acquire(self) -> None: ...  # blocks until a token is available
```

Usage:
```python
tmdb_limiter = RateLimiter(rate=40, per_seconds=10)
await tmdb_limiter.acquire()
response = await session.get(url)
```

---

## `utils/http.py`

Factory for a shared `aiohttp.ClientSession`. All outgoing HTTP (TMDB, TPDB, torrent sites, debrid APIs) goes through this.

Features:
- Configurable timeout (default 30 s)
- Automatic retry on 429 and 5xx with exponential backoff
- Optional Redis response cache: if `REDIS_URL` is set, GET responses are cached by URL with a configurable TTL (default 600 s for TMDB, 3600 s for TPDB)

---

## `utils/categories.py`

Maps `raw_category` strings from all ingester sources to a normalised `ContentCategory` used by the content router and stored on `releases.content_type`.

| Source | Raw value | Normalised |
|--------|-----------|------------|
| xxxclub | `SD`, `HD`, `FullHD`, `UHD` | quality tag only; content type always `xxx` |
| Spotnet | `"video"` | `VIDEO` |
| Spotnet | `"video:movies_hd"` | `MOVIE` |
| Spotnet | `"video:tv_hd"` | `TV` |
| Spotnet | `"xxx"` | `XXX` |
| Spotnet | `"audio"`, `"image"`, `"apps"` | `OTHER` (skipped by router) |
| Generic HTML | Site-configured `content_type` | Passthrough |
