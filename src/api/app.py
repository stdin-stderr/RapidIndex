from fastapi import FastAPI

from src.api.routers import (
    files,
    newznab,
    nzb,
    performers,
    people,
    releases,
    scenes,
    titles,
    torznab,
)

app = FastAPI(title="RapidIndex", docs_url="/docs", redoc_url=None)

app.include_router(releases.router, prefix="/rest/v1", tags=["releases"])
app.include_router(files.router, prefix="/rest/v1", tags=["files"])
app.include_router(titles.router, prefix="/rest/v1", tags=["titles"])
app.include_router(people.router, prefix="/rest/v1", tags=["people"])
app.include_router(scenes.router, prefix="/rest/v1", tags=["scenes"])
app.include_router(performers.router, prefix="/rest/v1", tags=["performers"])
app.include_router(newznab.router, prefix="/newznab", tags=["newznab"])
app.include_router(torznab.router, prefix="/torznab", tags=["torznab"])
app.include_router(nzb.router, prefix="/nzb", tags=["nzb"])
