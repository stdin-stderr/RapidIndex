import asyncio
import time


class RateLimiter:
    """Async token-bucket rate limiter. One instance per external API."""

    def __init__(self, rate: int, per_seconds: int) -> None:
        self._rate = rate
        self._per_seconds = per_seconds
        self._tokens: float = rate
        self._last_refill: float = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Block until a token is available, then consume it."""
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_refill
            self._tokens = min(
                self._rate,
                self._tokens + self._rate * elapsed / self._per_seconds,
            )
            self._last_refill = now

            if self._tokens < 1:
                wait = (1 - self._tokens) * self._per_seconds / self._rate
                await asyncio.sleep(wait)
                self._tokens = 0
            else:
                self._tokens -= 1
