from contextlib import asynccontextmanager
from pathlib import Path

# CRITICAL: defuse stdlib XML parsers BEFORE any library that uses XML (openpyxl, python-docx)
import defusedxml
defusedxml.defuse_stdlib()

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from redakt.config import settings
from redakt.routers import anonymize, deanonymize, detect, documents, health, pages
from redakt.services.audit import setup_logging
from redakt.services.language import validate_language_config
from redakt.utils import validate_instance_allow_list


BASE_DIR = Path(settings.base_dir)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' https://unpkg.com; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self'; "
            "connect-src 'self'"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging(
        log_level=settings.log_level,
        audit_log_file=settings.audit_log_file,
        audit_log_max_bytes=settings.audit_log_max_bytes,
        audit_log_backup_count=settings.audit_log_backup_count,
    )
    validate_language_config()
    settings.allow_list = validate_instance_allow_list(settings.allow_list)
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
app.include_router(deanonymize.router)
app.include_router(detect.router)
app.include_router(documents.router)
app.include_router(health.router)
app.include_router(pages.router)

app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
