# Deployment

---

## `main.py` modes

Each Docker service runs one mode. The `all` mode is for local development only.

```
python main.py api                      # FastAPI + uvicorn only
python main.py worker                   # Enrichment workers only
python main.py ingester spotnet         # Spotnet/NNTP ingester only
python main.py ingester xxxclub         # xxxclub torrent ingester only
python main.py all                      # Everything in one process (dev only)
```

---

## Migrations

Every mode runs the Alembic migration check at startup. A PostgreSQL advisory lock ensures
only the first container to connect executes the migration; all others wait until the schema
is ready before proceeding. No dedicated migration container is needed.

---

## Docker Compose

One service per component. All share the same image built from the project `Dockerfile`.

```yaml
services:

  db:
    image: postgres:16
    environment:
      POSTGRES_DB: scraper
      POSTGRES_USER: scraper
      POSTGRES_PASSWORD: scraper
    volumes:
      - db_data:/var/lib/postgresql/data

  redis:
    image: redis:7-alpine
    # optional — remove if REDIS_URL is not set

  api:
    build: .
    command: python main.py api
    env_file: .env
    ports:
      - "8000:8000"
    depends_on:
      - db

  worker:
    build: .
    command: python main.py worker
    env_file: .env
    depends_on:
      - db

  ingester-spotnet:
    build: .
    command: python main.py ingester spotnet
    env_file: .env
    depends_on:
      - db

  ingester-xxxclub:
    build: .
    command: python main.py ingester xxxclub
    env_file: .env
    depends_on:
      - db

volumes:
  db_data:
```

To disable a service: comment out or remove its block. No code changes required.

---

## `.env` file

Each container reads the same `.env`. Credentials not used by a given service are simply
ignored. Minimal example for full-stack operation:

```env
DATABASE_URL=postgresql+asyncpg://scraper:scraper@db/scraper
REDIS_URL=redis://redis:6379

TMDB_API_KEY=...
TPDB_API_KEY=...

XXXCLUB_ENABLED=true

SPOTNET_ENABLED=true
SPOTNET_NNTP_HOST=news.example.com
SPOTNET_NNTP_USER=...
SPOTNET_NNTP_PASS=...

API_BASE_URL=http://your-server-ip:8000
STREMIO_ENABLED=true
```

Debrid API keys are never in `.env`. See [api/stremio.md](api/stremio.md).

> Note: `SPOTNET_NNTP_*` credentials are only used by the `ingester-spotnet` container.
> The `api` container does not connect to NNTP.

---

## Scaling

To handle higher enrichment volume, run multiple `worker` containers. The `pending_enrichment`
queue uses `SELECT … FOR UPDATE SKIP LOCKED` so multiple workers pull from the queue safely
without coordination.

```yaml
  worker:
    build: .
    command: python main.py worker
    env_file: .env
    depends_on:
      - db
    deploy:
      replicas: 2
```
