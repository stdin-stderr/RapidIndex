# Ingester — xxxclub.to

`ingesters/torrent/xxxclub.py`

Scrapes the xxxclub.to torrent site for NSFW torrent releases. Ported from the existing xxxclub_scraper project.

---

## Enabled by

```env
XXXCLUB_ENABLED=true
XXXCLUB_INTERVAL_SECONDS=3600   # default
```

---

## What it fetches

Two modes, both run on each interval:

| Mode | URL | Purpose |
|------|-----|---------|
| Browse | `/torrents/browse/all/` | Paginated full catalogue; stops when watermark date is reached |
| Top 100 | `/torrents/top100/*` | Popularity lists per category |

Extracted per release: `info_hash` (from element ID), magnet link, title, seeders, leechers, size, date, category, uploader, images.

---

## Source key

`info_hash` — the torrent's 40-character hex hash. Globally unique and stable.

---

## Watermark

ISO date string of the newest `date_added` seen in the last run. On the next run, browsing stops when a release older than or equal to the watermark is encountered. Stored in `scan_state` under `source_name = "xxxclub"`.

---

## Category output

Emits the raw xxxclub category string as `raw_category`. `utils/categories.py` normalises it:

| Raw | Internal |
|-----|----------|
| `SD` | `quality=SD` |
| `HD` | `quality=HD` |
| `FullHD` | `quality=FHD` |
| `UHD` | `quality=UHD` |

`source_name = "xxxclub"` is itself a routing signal — the content router always sends xxxclub releases to TPDB regardless of category.

---

## Notes

- Uses `aiohttp` via `utils/http.py`; parses HTML with BeautifulSoup (lxml)
- Concurrent page fetching configurable via `XXXCLUB_PAGE_CONCURRENCY`
- No authentication required
