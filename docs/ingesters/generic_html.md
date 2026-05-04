# Ingester — Generic HTML Torrent Scraper

`ingesters/torrent/generic_html.py`

A config-driven HTML scraper for any paginated torrent site. Allows adding new torrent sources without writing Python.

---

## Enabled by

Add one or more entries to `GENERIC_TORRENT_SITES` in config (JSON array):

```json
[
  {
    "name": "mysite",
    "base_url": "https://mysite.example/torrents",
    "interval_seconds": 1800,
    "selectors": {
      "row": "tr.torrent-row",
      "title": "td.name a",
      "info_hash": "td.hash",
      "seeders": "td.seeders",
      "leechers": "td.leechers",
      "size": "td.size",
      "date": "td.date",
      "category": "td.category"
    },
    "pagination": "?page={n}",
    "date_format": "%Y-%m-%d",
    "content_type": "xxx"
  }
]
```

Each entry becomes a separate ingester instance with its own watermark and schedule.

---

## Source key

`info_hash` if available from the selector; otherwise a stable hash of `(name + title + date)`.

---

## Watermark

ISO date of newest release seen, same as xxxclub. Stored under `source_name = "generic:<name>"`.

---

## Category and content type routing

Set `content_type` in the site config to hint the content router:

| Value | Routes to |
|-------|-----------|
| `"xxx"` | TPDB |
| `"movie"` | TMDB movie |
| `"tv"` | TMDB TV |
| `"auto"` (default) | Content router decides from title/category |
