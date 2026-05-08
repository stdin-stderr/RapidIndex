import hashlib
import json
import os
from typing import Any

_client = None


def _redis():
    global _client
    if _client is None:
        url = os.environ.get("REDIS_URL")
        if not url:
            return None
        import redis
        _client = redis.from_url(url, decode_responses=True, socket_connect_timeout=1)
    return _client


def make_key(namespace: str, **params) -> str:
    raw = json.dumps(params, sort_keys=True, default=str)
    return f"ui:{namespace}:{hashlib.md5(raw.encode()).hexdigest()}"


def cache_get(key: str) -> Any | None:
    r = _redis()
    if r is None:
        return None
    try:
        val = r.get(key)
        return json.loads(val) if val else None
    except Exception:
        return None


def cache_set(key: str, data: Any, ttl: int) -> None:
    r = _redis()
    if r is None:
        return
    try:
        r.set(key, json.dumps(data), ex=ttl)
    except Exception:
        pass
