# Ingesters — Base Interface

`ingesters/base.py`

---

## RawRelease

The normalised output of every ingester. All fields specific to a source type are nullable so torrent and usenet releases share the same type.

```python
@dataclass
class RawRelease:
    source_type: Literal["torrent", "usenet"]
    source_name: str            # "xxxclub" | "spotnet" | "generic:<name>"
    source_key: str             # stable dedup key — info_hash or spotnet_key
    raw_title: str
    raw_category: str | None    # site-specific; normalised by utils/categories.py
    file_size_bytes: int | None
    published_at: datetime | None

    # Torrent-only
    info_hash: str | None
    magnet_uri: str | None
    seeders: int | None
    leechers: int | None

    # Usenet-only
    newsgroup: str | None
    nzb_segments: str | None    # pipe-delimited NNTP message-IDs: "<a@n>|<b@n>|"
    poster: str | None
```

---

## Ingester ABC

```python
class Ingester(ABC):
    @abstractmethod
    async def fetch_new(self) -> AsyncIterator[RawRelease]:
        """Yield only releases not yet seen (uses internal watermark)."""

    @property
    @abstractmethod
    def interval_seconds(self) -> int:
        """How often the scheduler should call fetch_new()."""

    @property
    @abstractmethod
    def source_name(self) -> str:
        """Unique identifier used in source_name and scan_state."""
```

---

## Watermark

Each ingester tracks its own position in `scan_state` so re-runs never re-emit already-indexed releases.

```
scan_state
  source_name  text UNIQUE   -- matches Ingester.source_name
  watermark    text          -- ingester-specific: date string / article number / etc.
  updated_at   timestamptz
```

The ingester reads its watermark at startup and writes it after each successful batch. What the watermark contains is internal to each ingester:

| Ingester | Watermark value |
|----------|----------------|
| xxxclub | ISO date of newest `date_added` seen |
| spotnet | Last NNTP article number per newsgroup |
| generic_html | ISO date of newest release seen |

---

## Scheduler Contract

The `pipeline/ingester_scheduler.py` calls each ingester on its `interval_seconds`. The ingester is responsible for:
- Yielding only **new** releases (not re-emitting historical ones on every run)
- Being safe to run concurrently with other ingesters
- Updating its own watermark after each successful fetch

The scheduler is responsible for:
- Upserting each `RawRelease` into `releases` by `source_key`
- Enqueuing new releases in `pending_enrichment`
- Skipping releases whose `source_key` already exists (already indexed)
