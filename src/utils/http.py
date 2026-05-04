import asyncio
import json
import logging

import aiohttp

from src.config import settings

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = aiohttp.ClientTimeout(total=30)
_MAX_RETRIES = 5
_BASE_BACKOFF = 1.0  # seconds


class HttpClient:
    """Shared HTTP client with retry logic and optional Redis GET caching."""

    def __init__(self) -> None:
        self._session: aiohttp.ClientSession | None = None
        self._redis: "redis.asyncio.Redis | None" = None  # type: ignore[name-defined]
        self._redis_ready = False

    def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=_DEFAULT_TIMEOUT)
        return self._session

    async def _get_redis(self):
        if self._redis_ready:
            return self._redis
        if settings.redis_url:
            try:
                import redis.asyncio as aioredis

                self._redis = aioredis.from_url(settings.redis_url, decode_responses=True)
                await self._redis.ping()
            except Exception:
                logger.warning("Redis unavailable — response caching disabled")
                self._redis = None
        self._redis_ready = True
        return self._redis

    async def get(self, url: str, *, ttl: int = 600, **kwargs) -> dict:
        """GET url, returning parsed JSON. Caches in Redis when available."""
        redis = await self._get_redis()

        if redis is not None:
            cached = await redis.get(url)
            if cached is not None:
                return json.loads(cached)

        data = await self._request("GET", url, **kwargs)

        if redis is not None:
            await redis.set(url, json.dumps(data), ex=ttl)

        return data

    async def _request(self, method: str, url: str, **kwargs) -> dict:
        session = self._get_session()
        backoff = _BASE_BACKOFF

        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                async with session.request(method, url, **kwargs) as resp:
                    if resp.status == 429:
                        retry_after = float(resp.headers.get("Retry-After", backoff))
                        logger.debug("429 from %s, waiting %.1fs", url, retry_after)
                        await asyncio.sleep(retry_after)
                        backoff = min(backoff * 2, 60)
                        continue

                    if resp.status >= 500:
                        if attempt == _MAX_RETRIES:
                            resp.raise_for_status()
                        logger.debug("5xx from %s (attempt %d), backing off %.1fs", url, attempt, backoff)
                        await asyncio.sleep(backoff)
                        backoff = min(backoff * 2, 60)
                        continue

                    resp.raise_for_status()
                    return await resp.json()

            except aiohttp.ClientResponseError:
                raise
            except aiohttp.ClientError as exc:
                if attempt == _MAX_RETRIES:
                    raise
                logger.debug("Client error on %s (attempt %d): %s", url, attempt, exc)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)

        raise RuntimeError(f"Exhausted retries for {url}")  # unreachable

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
        if self._redis:
            await self._redis.aclose()


_client: HttpClient | None = None


def get_client() -> HttpClient:
    """Return the process-wide HttpClient singleton."""
    global _client
    if _client is None:
        _client = HttpClient()
    return _client
