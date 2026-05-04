# Ingester — Spotnet / NNTP

`ingesters/usenet/spotnet.py`

Indexes a Spotnet-formatted NNTP newsgroup. Ported from the py_spotweb project.

---

## Enabled by

```env
SPOTNET_ENABLED=true
SPOTNET_NNTP_HOST=news.example.com
SPOTNET_NNTP_PORT=563
SPOTNET_NNTP_USER=...
SPOTNET_NNTP_PASS=...
SPOTNET_NEWSGROUPS=free.pt          # comma-separated for multiple groups
SPOTNET_MAX_AGE_DAYS=90
```

---

## What it fetches

Connects to the NNTP server over SSL and scans each configured newsgroup for Spotnet-formatted articles. On first run, binary-searches the article range to find the cutoff corresponding to `SPOTNET_MAX_AGE_DAYS` — avoiding a full re-download of the group history.

Each article body contains base64 line-folded XML (`X-XML:` header) describing the release:

- Title, poster, category, sub-category codes, file size, description, website link
- `<NZB>` segment — pipe-delimited NNTP message-IDs for the actual content

---

## Source key

`spotnet_key` — the unique identifier embedded in the Spotnet XML. Stable across re-scans.

---

## Watermark

Last NNTP article number scanned per newsgroup. Stored in `scan_state` under `source_name = "spotnet:<newsgroup>"` (e.g. `"spotnet:free.pt"`). On subsequent runs, scanning starts from `watermark + 1`.

---

## Category mapping

Spotnet categories are mapped to `raw_category` before being passed to the content router:

| Spotnet code | raw_category | Routes to |
|-------------|--------------|-----------|
| `0` (video) | `"video"` | TMDB (movie or TV based on sub-cat) |
| `0` + sub `a0` | `"video:movies_hd"` | TMDB movie |
| `0` + sub `b4` | `"video:tv_hd"` | TMDB TV |
| `1` (audio) | `"audio"` | skipped (no enricher) |
| `2` (image/ebook) | `"image"` | skipped |
| `3` (apps) | `"apps"` | skipped |
| `7` (XXX) | `"xxx"` | **TPDB** |

---

## NZB assembly

The ingester reads the segment message-IDs from the Spotnet `<NZB>` element, fetches the
segment articles over NNTP, assembles the complete NZB XML during indexing, and stores it in
`usenet_releases.nzb_xml`.

The API serves the stored NZB bytes directly. It never connects to NNTP and does not need
NNTP credentials. See [nzb.md](../nzb.md).

---

## Notes

- Lazy NNTP reconnection with exponential backoff on connection loss
- Signature verification (SPOTSIGN_V2) supported but optional
- Multiple newsgroups scanned sequentially within a single ingester run
