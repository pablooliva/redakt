from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from redakt.config import settings
from redakt.routers import detect, health, pages
from redakt.services.audit import setup_logging


BASE_DIR = Path(settings.base_dir)


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging(settings.log_level)
    app.state.http_client = httpx.AsyncClient(timeout=settings.presidio_timeout)
    yield
    await app.state.http_client.aclose()


app = FastAPI(
    title="Redakt",
    description="Enterprise PII detection and anonymization API",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(detect.router)
app.include_router(health.router)
app.include_router(pages.router)

app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
