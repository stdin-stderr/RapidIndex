# Storage — Database Schema

`storage/models.py`, `storage/db.py`, `storage/repositories/`

PostgreSQL is the sole persistent store. Redis is an optional response cache (see [utils.md](utils.md)).

Migrations are managed by Alembic (`storage/migrations/`). Every service mode runs the migration
check at startup; a PostgreSQL advisory lock ensures only the first container to connect actually
executes the migration. All others wait until the schema is ready.

---

## Tables

### `scan_state`
Watermark tracking for each ingester.

```
scan_state
  id           serial PK
  source_name  text UNIQUE   -- "xxxclub" | "spotnet:free.pt"
  watermark    text          -- ingester-specific position value
  updated_at   timestamptz
```

---

### `releases`
One row per indexed source artifact. `source_key` is globally UNIQUE and prevents the same
artifact from being stored twice when it is seen again by the same source, by another mirror,
or by another ingester using the same artifact identifier.

`source_key` is not a cross-protocol content identity. A torrent info hash and a Spotnet key
for the same movie or scene are different artifacts and may produce separate `releases` rows.
They can still converge through enrichment by linking to the same TMDB title or TPDB scene.

```
releases
  id              uuid PK default gen_random_uuid()
  source_type     text          -- "torrent" | "usenet"
  source_name     text          -- "xxxclub" | "spotnet"
  source_key      text UNIQUE   -- artifact key: info_hash, spotnet_key, or source-specific stable key
  raw_title       text
  raw_category    text
  file_size_bytes bigint
  published_at    timestamptz
  date            date          -- parsed from title or metadata; nullable
  quality         text          -- "SD" | "HD" | "FHD" | "UHD"
  content_type    text          -- "movie" | "tv" | "xxx" | "music" | "book" | "software" | "other"
  season          int           -- parsed from title for TV releases, nullable
  episode         int           -- parsed from title for TV releases, nullable

  -- Ingester-supplied hints (written once at index time, never overwritten on re-upsert)
  hints           jsonb         -- e.g. {"imdb_id": "tt1234567", "tmdb_id": "12345", "content_type": "movie"}

  -- Enrichment status
  enricher        text          -- "tmdb_movie" | "tmdb_tv" | "tpdb" | "skip"
  metadata_status text          -- "pending" | "matched" | "skipped" | "match_failed"
  metadata_score  float
  matched_at      timestamptz

  -- Timestamps
  indexed_at      timestamptz default now()
  updated_at      timestamptz
```

---

### `usenet_releases`
1:1 with `releases` where `source_type = 'usenet'`.

```
usenet_releases
  release_id   uuid PK FK → releases.id
  groups       text          -- newsgroup(s) the article was posted to
  poster       text          -- article poster address
  nzb_xml      bytea NOT NULL -- full NZB file assembled at index time by Spotnet ingester
```

---

### `torrent_releases`
1:1 with `releases` where `source_type = 'torrent'`.

```
torrent_releases
  release_id   uuid PK FK → releases.id
  info_hash    text          -- 40-char hex SHA-1
  magnet_uri   text
  size_bytes   bigint
  seeders      int
  leechers     int
```

---

### `pending_enrichment`
PostgreSQL-backed work queue. See [pipeline.md](pipeline.md).

```
pending_enrichment
  id           serial PK
  release_id   uuid FK → releases.id
  enricher     text
  attempts     int default 0  -- no-match attempts only; API errors do not increment this
  next_attempt timestamptz    -- NULL means ready now
  created_at   timestamptz
```

---

### `tmdb_metadata`
One row per unique TMDB title (movie or TV show). Multiple releases can link to the same title.

```
tmdb_metadata
  id              serial PK
  tmdb_id         int UNIQUE
  imdb_id         text          -- "tt1234567"; indexed for Newznab imdbid= lookups
  tvdb_id         int           -- indexed for Newznab tvdbid= lookups
  external_ids    jsonb         -- full TMDB external_ids response (trakt, wikidata, etc.)
  tmdb_type       text          -- "movie" | "tv"
  title           text
  original_title  text
  overview        text
  release_year    int
  rating          float
  genres          jsonb
  poster_path     text
  backdrop_path   text
  extra           jsonb         -- TV: season_count, episode_count, networks
  fetched_at      timestamptz
```

---

### `release_tmdb_titles`
Join table between releases and TMDB metadata. One release maps to one title; one title may have many releases.

```
release_tmdb_titles
  release_id   uuid FK → releases.id
  tmdb_id      int  FK → tmdb_metadata.tmdb_id
  PRIMARY KEY (release_id, tmdb_id)
```

---

### `tmdb_people`
Actor profiles, shared across all titles. One row per unique TMDB person ID. Updated on re-encounter if profile data has changed.

```
tmdb_people
  id              serial PK
  tmdb_person_id  int UNIQUE NOT NULL
  name            text NOT NULL
  profile_path    text
  popularity      float
  imdb_id         text
  extra           jsonb         -- gender, known_for_department, homepage, etc.
  fetched_at      timestamptz
```

---

### `tmdb_metadata_cast`
Links actors to the titles they appear in, with character name and billing order. One row per (title, actor) pair.

```
tmdb_metadata_cast
  tmdb_metadata_id  int FK → tmdb_metadata(id) ON DELETE CASCADE
  tmdb_person_id    int FK → tmdb_people(tmdb_person_id) ON DELETE CASCADE
  character         text          -- character name as credited (nullable — some cast entries have none)
  cast_order        int           -- position in TMDB cast list; 0 = top-billed
  PRIMARY KEY (tmdb_metadata_id, tmdb_person_id)
```

---

### `tpdb_scenes`
One row per unique TPDB scene or movie. Multiple releases (different torrents or usenet posts
of the same scene) can link to the same `tpdb_scenes` row via `release_tpdb_scenes`.

```
tpdb_scenes
  id              uuid PK       -- TPDB UUID
  tpdb_type       text          -- "scene" | "movie"
  title           text
  description     text
  date            date
  duration_secs   int
  site_id         int FK → tpdb_sites.id
  performers      jsonb         -- denormalised array from TPDB performer profiles
  tags            jsonb
  poster_url      text
  background_url  text
  fetched_at      timestamptz
```

---

### `release_tpdb_scenes`
Many-to-many between releases and TPDB scenes. One release maps to one scene (the best match);
the many-to-many structure allows future cases where one binary contains multiple scenes.

```
release_tpdb_scenes
  release_id   uuid FK → releases.id
  scene_id     uuid FK → tpdb_scenes.id
  PRIMARY KEY (release_id, scene_id)
```

---

### `tpdb_sites`

```
tpdb_sites
  id          int PK
  name        text
  network_id  int FK → tpdb_networks.id
  slug        text
  logo_url    text
```

---

### `tpdb_networks`

```
tpdb_networks
  id      int PK
  name    text
  slug    text
```

---

### `tpdb_performers`
Full performer profiles, written on first encounter and updated on subsequent matches.

```
tpdb_performers
  id          uuid PK
  name        text
  gender      text
  birthday    date
  height_cm   int
  rating      float
  poster_url  text
  extra       jsonb         -- measurements, social links, aliases, etc.
  fetched_at  timestamptz
```

---

---

## Field Population

When a release is ingested and enriched, fields are populated from multiple sources:

| releases field | Source | Notes |
|---|---|---|
| `raw_title` | `RawRelease.raw_title` | Original title from source, never modified |
| `raw_category` | `RawRelease.raw_category` | Source-specific category string |
| `file_size_bytes` | `RawRelease.file_size_bytes` | Torrent or usenet total size |
| `published_at` | `RawRelease.published_at` | Source ingestion timestamp (not release date) |
| `date` | `ParsedTitle.release_date` | Release date extracted from title; nullable |
| `quality` | `ParsedTitle.resolution` | Mapped to "SD", "HD", "FHD", "UHD" |
| `season` | `ParsedTitle.season` | TV only; extracted from S##E## pattern |
| `episode` | `ParsedTitle.episode` | TV only; extracted from S##E## pattern |
| `content_type` | Router decision + TMDB/TPDB enrichment | "movie", "tv", "xxx", etc. |
| `hints` | `RawRelease.hints` | Ingester-supplied metadata (IMDB ID, TMDB ID, etc.) |

---

## Repositories

`storage/repositories/` contains one repository class per aggregate. Routers import repositories, not models directly.

| File | Responsibility |
|------|---------------|
| `release_repo.py` | Query/upsert releases + side-tables; filter by source, content type, quality, search term |
| `scene_repo.py` | Query tpdb_scenes with performer/site/tag filters |
| `performer_repo.py` | Query tpdb_performers with name search |
| `people_repo.py` | Upsert tmdb_people; query cast list for a given tmdb_metadata_id |
