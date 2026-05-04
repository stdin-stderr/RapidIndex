# Enrichers — Base Interface

`enrichers/base.py`

---

## EnrichmentResult

```python
@dataclass
class EnrichmentResult:
    matched: bool
    score: float        # 0.0–1.0; 0.0 if not matched
    external_id: str    # tmdb_id or tpdb_id, empty string if not matched
    metadata: dict      # enricher-specific; stored as JSONB on the linked table
```

---

## Enricher ABC

```python
class Enricher(ABC):
    @abstractmethod
    async def enrich(
        self,
        release: RawRelease,
        parsed: ParsedTitle,
    ) -> EnrichmentResult: ...
```

Each enricher is instantiated once at startup and reused for the lifetime of the worker process. Enrichers are stateless between calls except for the shared `RateLimiter` instance.

---

## Retry and failure handling

The enricher worker handles retries — enrichers do not retry internally. If an enricher raises an exception or returns `matched=False`, the worker:

1. Increments `attempts` on the `pending_enrichment` row.
2. Sets `next_attempt = now() + 2^attempts minutes` (exponential backoff).
3. After 5 attempts, sets `metadata_status = "match_failed"` and stops retrying.

`match_failed` releases can be re-queued by the optional re-enricher sweep (e.g. nightly), in case TMDB or TPDB has added data since first indexing.
