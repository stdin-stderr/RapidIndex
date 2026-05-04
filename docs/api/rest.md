# API — REST Endpoints

`api/routers/releases.py`, `scenes.py`, `performers.py`, `titles.py`

Read-only. All responses come from the database — no live fetches.

No authentication required. Intended for local/private network use.

---

## Releases

```
GET /api/v1/releases
  ?source_type=torrent|usenet
  ?content_type=movie|tv|xxx|music|book|software|other
  ?quality=SD|HD|FHD|UHD
  ?metadata_status=pending|matched|skipped|match_failed
  ?q=<full-text search on raw_title>
  ?page=1
  ?per_page=30    (max 250)
```

Returns releases with their enrichment status. Does not inline metadata — clients follow up with `/titles` or `/scenes` if needed.

---

## TMDB Titles

```
GET /api/v1/titles
  ?type=movie|tv
  ?q=<search on title>
  ?year=<int>
  ?imdb_id=tt1234567
  ?tmdb_id=<int>
  ?page=1
  ?per_page=30
```

Returns TMDB metadata rows. Each result includes a `releases` count — how many indexed releases link to this title.

```
GET /api/v1/titles/:tmdb_id/cast
```

Returns the cast list for a title, ordered by `cast_order`. Each entry includes `tmdb_person_id`, `name`, `character`, `cast_order`, and `profile_path`.

---

## TMDB People

```
GET /api/v1/people/:tmdb_person_id
```

Returns a person's profile plus a list of titles they appear in (from `tmdb_metadata_cast`), ordered by `cast_order`.

---

## NSFW Scenes

```
GET /api/v1/scenes
  ?type=scene|movie
  ?performer=<name>
  ?site=<slug>
  ?tag=<tag>
  ?q=<search on title>
  ?page=1
  ?per_page=30
```

---

## NSFW Movies

```
GET /api/v1/movies
  ?site=<slug>
  ?performer=<name>
  ?q=<search on title>
  ?page=1
  ?per_page=30
```

---

## Performers

```
GET /api/v1/performers
  ?q=<name search>
  ?page=1
  ?per_page=30

GET /api/v1/performers/:id
```

---

## Response format

All list endpoints return:

```json
{
  "total": 1042,
  "page": 1,
  "per_page": 30,
  "results": [ ... ]
}
```
