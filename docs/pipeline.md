# Pipeline

The pipeline moves releases from ingesters into the database with metadata attached. It has three components: the enrichment queue, the ingester scheduler, and the enricher worker.

---

## Queue — `pipeline/queue.py`

A PostgreSQL table used as a crash-safe work queue. No message broker needed.

```
pending_enrichment
  id           serial PK
  release_id   uuid FK → releases.id
  enricher     text          -- "tmdb_movie" | "tmdb_tv" | "tpdb" | "skip"
  attempts     int default 0  -- counts no-match responses only, not API errors
  next_attempt timestamptz   -- NULL means ready now
  created_at   timestamptz
```

Workers claim batches atomically:

```sql
SELECT * FROM pending_enrichment
WHERE next_attempt IS NULL OR next_attempt <= now()
LIMIT 10
FOR UPDATE SKIP LOCKED
```

This allows multiple worker processes to pull from the queue simultaneously without coordination. Unclaimed rows survive restarts.

---

## Ingester Scheduler — `pipeline/ingester_scheduler.py`

One `asyncio` task per configured ingester. Runs only in `ingester` process mode or in
`all` mode for local development. It does not run in the `worker` process.

**Per interval:**
1. Call `ingester.fetch_new()` — yields `RawRelease` objects.
2. For each release: upsert into `releases` + source side-table by `source_key`.
3. For new releases only: insert into `pending_enrichment`.
4. Update `scan_state` watermark after the full batch completes successfully.

The scheduler does not call the content router or any enricher — it only writes raw data and queues work.

---

## Enricher Worker — `pipeline/enricher_worker.py`

Runs only in the `worker` process or in `all` mode for local development. Configurable
concurrency (default 4). It does not run ingesters.

**Per item:**
1. Claim a batch from `pending_enrichment`.
2. Load the full release from the database.
3. Call `content_router.route(release)` → `(EnricherType, ParsedTitle)`.
4. If `SKIP`: mark `metadata_status = "skipped"`, delete from queue.
5. Otherwise: call `enricher.enrich(release, parsed)`.
6. On success: write metadata + join rows, mark `metadata_status = "matched"`, delete from queue.
7. On **API error** (network failure, 5xx): do **not** increment `attempts`. The HTTP client
   backs off with exponential retry. The queue item remains at its current `next_attempt`.
8. On **no match** (API returns 0 results): increment `attempts`, set
   `next_attempt = now() + 7 days`.
9. After **2 no-match attempts**: mark `metadata_status = "match_failed"`, delete from queue.

The distinction matters: a brief API outage should not burn retry attempts on releases that
would match once the API recovers.

---

## Failure states

| `metadata_status` | Meaning |
|-------------------|---------|
| `pending` | In `pending_enrichment` queue, not yet processed |
| `matched` | Successfully enriched; metadata row linked |
| `skipped` | Content type has no enricher, or enricher key not configured |
| `match_failed` | Two no-match responses across two attempts (7 days apart); stopped retrying |

---

## Optional: Re-enricher sweep

A nightly scheduled task (not a continuous worker) that re-queues all `match_failed` releases
older than a configurable window. Useful because TMDB and TPDB may add data after first indexing.

Enabled by setting `RE_ENRICH_FAILED_AFTER_DAYS` (default: disabled).
