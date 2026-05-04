# NZB Builder

`nzb/builder.py`

NZB files are assembled **at index time** by the Spotnet ingester during NNTP ingestion. The
complete NZB XML is stored immediately as `usenet_releases.nzb_xml BYTEA`. The API serves it
directly from the database — no NNTP connection is required at download time.

This fully decouples the API container from NNTP and eliminates any race conditions that would
arise from lazy on-demand assembly. The trade-off is that the Spotnet ingester is slower:
it must make one NNTP round-trip per article to assemble the NZB before storing the release.

---

## Interface

```python
async def build_nzb(message_ids: list[str], nntp: NNTPClient) -> bytes:
    """Fetch segment articles from NNTP and return assembled NZB XML bytes.
    Called by the Spotnet ingester at index time."""
```

---

## Assembly steps

1. Receive the list of NNTP message-IDs from the Spotnet `<NZB>` element.
2. Fetch each segment article body from the NNTP server.
3. Concatenate raw bodies.
4. Unescape Spotnet encoding: `=C`→`\n`, `=B`→`\r`, `=A`→NUL, `=D`→`=`.
5. Raw-deflate decompress: `zlib.decompress(data, -15)`.
6. Return NZB XML as `bytes` — stored in `usenet_releases.nzb_xml BYTEA`.

---

## API download

`GET /nzb/:release_id` reads `usenet_releases.nzb_xml` and returns it as an
`application/x-nzb` attachment. No NNTP credentials are needed in the API container.

If `nzb_xml` is NULL (legacy row or assembly failure), the endpoint returns `404 Not Found`.

---

## NNTP connection

Only the **Spotnet ingester container** needs NNTP credentials:

```env
SPOTNET_NNTP_HOST=news.example.com
SPOTNET_NNTP_PORT=563
SPOTNET_NNTP_USER=...
SPOTNET_NNTP_PASS=...
```

The `api` container requires no NNTP configuration.
