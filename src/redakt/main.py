from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from redakt.config import settings
from redakt.routers import anonymize, detect, health, pages
from redakt.services.audit import setup_logging


BASE_DIR = Path(settings.base_dir)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' https://unpkg.com; "
            "style-src 'self'; "
            "img-src 'self'; "
            "connect-src 'self'"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response


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

app.add_middleware(SecurityHeadersMiddleware)

app.include_router(anonymize.router)
app.include_router(detect.router)
app.include_router(health.router)
app.include_router(pages.router)

app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
