# API — Newznab Endpoint

`api/routers/newznab.py`

A Newznab-compatible query endpoint. **This is output-only** — it exposes the indexed database to external usenet clients. It does not ingest any data.

Compatible clients: Sonarr, Radarr, Lidarr, SABnzbd, NZBGet, nzbhydra2.

---

## Endpoints

```
GET /api?t=caps
GET /api?t=search&q=...&cat=...&limit=...&offset=...
GET /api?t=movie&imdbid=tt1234567
GET /api?t=tvsearch&tvdbid=...&season=...&ep=...
GET /nzb/:release_id
```

---

## Caps

`?t=caps` advertises the server's capabilities to clients. Returns XML describing supported search types, categories, and limits.

---

## Search (`?t=search`)

Full-text search across all releases. Parameters:

| Param | Description |
|-------|-------------|
| `q` | Search term (matched against `raw_title`) |
| `cat` | Newznab category filter (comma-separated). Maps to internal `content_type` |
| `limit` | Max results (default 100, max 250) |
| `offset` | Pagination offset |

Category mapping:

| Newznab cat | Internal |
|-------------|----------|
| `2000`–`2999` | `movie` |
| `3000`–`3999` | `music` |
| `4000`–`4999` | `software` |
| `5000`–`5999` | `tv` |
| `6000`–`6999` | `xxx` |
| `7000`–`7999` | `book` |
| other / unmapped | `other` |

---

## Movie lookup (`?t=movie`)

Looks up by IMDB id (`imdbid=tt1234567`). Queries `tmdb_metadata.imdb_id` → returns all releases linked to that title.

---

## TV lookup (`?t=tvsearch`)

Looks up by TVDB id with optional season/episode filter. Queries `tmdb_metadata.tvdb_id`
and filters against the parsed `releases.season` / `releases.episode` fields written during
ingestion from the shared title parser.

---

## NZB download (`GET /nzb/:release_id`)

Reads the stored `usenet_releases.nzb_xml` bytes and returns them as an
`application/x-nzb` attachment. The API does not connect to NNTP and does not require NNTP
credentials. If no stored NZB exists for the release, returns `404`.

See [nzb.md](../nzb.md) for assembly details.

---

## Response format

All search endpoints return Newznab RSS XML as required by the spec.
