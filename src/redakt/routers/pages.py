import json
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from redakt.config import settings
from redakt.routers.anonymize import AnonymizationError, AnonymizationResult, run_anonymization
from redakt.routers.detect import DetectionError, run_detection
from redakt.services.audit import log_anonymization, log_detection
from redakt.services.presidio import PresidioClient, get_presidio_client

logger = logging.getLogger("redakt")
router = APIRouter(tags=["pages"])
templates = Jinja2Templates(directory=str(Path(settings.base_dir) / "templates"))


@router.get("/detect", response_class=HTMLResponse)
async def detect_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "detect.html")


@router.post("/detect/submit", response_class=HTMLResponse)
async def detect_submit(
    request: Request,
    text: str = Form(""),
    language: str = Form("auto"),
    presidio: PresidioClient = Depends(get_presidio_client),
) -> HTMLResponse:
    # Enforce text size limit (API route uses Pydantic; form route needs manual check)
    if len(text) > settings.max_text_length:
        return templates.TemplateResponse(
            request,
            "partials/detect_results.html",
            {"error": f"Text exceeds maximum length of {settings.max_text_length} characters."},
        )

    try:
        result = await run_detection(
            text=text,
            language=language,
            score_threshold=settings.default_score_threshold,
            presidio=presidio,
        )
    except DetectionError as exc:
        error_messages = {
            503: "Service is starting up, please wait...",
            504: "Detection service timed out. Please try again.",
        }
        return templates.TemplateResponse(
            request,
            "partials/detect_results.html",
            {"error": error_messages.get(exc.status_code, exc.detail)},
        )

    log_detection(
        entity_count=result.entity_count,
        entity_types=result.entity_types,
        language=result.language,
        source="web_ui",
    )

    return templates.TemplateResponse(
        request,
        "partials/detect_results.html",
        {
            "has_pii": result.has_pii,
            "entity_count": result.entity_count,
            "entities_found": result.entity_types,
            "language_detected": result.language,
        },
    )


@router.get("/anonymize", response_class=HTMLResponse)
async def anonymize_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "anonymize.html")


@router.post("/anonymize/submit", response_class=HTMLResponse)
async def anonymize_submit(
    request: Request,
    text: str = Form(""),
    language: str = Form("auto"),
    presidio: PresidioClient = Depends(get_presidio_client),
) -> HTMLResponse:
    if len(text) > settings.max_text_length:
        return templates.TemplateResponse(
            request,
            "partials/anonymize_results.html",
            {"error": f"Text exceeds maximum length of {settings.max_text_length} characters."},
        )

    try:
        result = await run_anonymization(
            text=text,
            language=language,
            score_threshold=settings.default_score_threshold,
            presidio=presidio,
        )
    except AnonymizationError as exc:
        error_messages = {
            503: "Service is starting up, please wait...",
            504: "Anonymization timed out. Please try again.",
        }
        return templates.TemplateResponse(
            request,
            "partials/anonymize_results.html",
            {"error": error_messages.get(exc.status_code, exc.detail)},
        )

    log_anonymization(
        entity_count=len(result.mappings),
        entity_types=result.entity_types,
        language=result.language,
        source="web_ui",
    )

    return templates.TemplateResponse(
        request,
        "partials/anonymize_results.html",
        {
            "anonymized_text": result.anonymized_text,
            "mappings": result.mappings,
            "mappings_json": json.dumps(result.mappings),
            "mapping_count": len(result.mappings),
            "language_detected": result.language,
        },
    )
