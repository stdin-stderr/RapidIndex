# API — Stremio Addon + Debrid

`api/stremio/addon.py`, `api/stremio/debrid/`

---

## Enabled by

```env
STREMIO_ENABLED=true
```

When disabled, all `/stremio/` routes are not registered.

---

## Config-in-URL pattern

Debrid API keys are **never stored server-side**. They travel in the Stremio addon URL, base64url-encoded alongside the service name. This is the same approach used by Torrentio.

`{config}` is a base64url-encoded JSON object:

```json
{"service": "torbox", "apiKey": "user-api-key-here"}
```

The server decodes it on each request, instantiates the debrid client, uses it, and discards it. The key is never written to disk, logs, or the database.

---

## Endpoints

```
GET /stremio/manifest.json
    → Unconfigured manifest. Installs the addon without debrid support.
    → Stream links are direct magnet URIs.

GET /stremio/{config}/manifest.json
    → Configured manifest for the specified debrid service.

GET /stremio/{config}/catalog/:type/:id.json
    → Catalog browsing. type = "movie" | "series" | "xxx"

GET /stremio/{config}/stream/:type/:id.json
    → Stream resolution. Returns debrid download URLs or magnet fallback.
```

---

## Stream resolution

For each release matching the requested title:

1. Decode `{config}` → `(service, apiKey)`.
2. Instantiate the appropriate `DebridClient(api_key)`.
3. Call `client.resolve(info_hash, file_index)`.
4. If cached: return the direct download URL.
5. If not cached: return the magnet URI as fallback.

For usenet releases (no magnet): only cached debrid results are returned. If none, the release is omitted from the stream list.

---

## Debrid clients

`api/stremio/debrid/`

Each provider implements the abstract interface:

```python
class DebridClient(ABC):
    def __init__(self, api_key: str): ...

    @abstractmethod
    async def resolve(self, info_hash: str, file_index: int) -> str | None:
        """Returns a direct download URL, or None if not cached."""
```

| File | Provider |
|------|---------|
| `torbox.py` | TorBox |
| `realdebrid.py` | Real-Debrid |
| `alldebrid.py` | AllDebrid |
| `premiumize.py` | Premiumize |

---

## Non-Stremio callers

For any future client (e.g. a web UI) that needs debrid resolution outside of Stremio, the API key must be passed per-request. There is no server-side session or stored credential path.
