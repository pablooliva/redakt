import asyncio
import json
import logging
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, Form, Request, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from redakt.config import settings
from redakt.models.document import DocumentMetadata
from redakt.routers.anonymize import AnonymizationError, AnonymizationResult, run_anonymization
from redakt.routers.detect import DetectionError, run_detection
from redakt.services.audit import log_anonymization, log_detection, log_document_upload
from redakt.routers.documents import _get_upload_semaphore
from redakt.services.document_processor import DocumentProcessingError, process_document
from redakt.services.extractors import ExtractionError
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
            "language_confidence": result.language_confidence,
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
            "language_confidence": result.language_confidence,
        },
    )


@router.get("/documents", response_class=HTMLResponse)
async def documents_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request, "documents.html", {"max_file_size": settings.max_file_size}
    )


@router.post("/documents/submit", response_class=HTMLResponse)
async def documents_submit(
    request: Request,
    file: UploadFile,
    language: str = Form("auto"),
    presidio: PresidioClient = Depends(get_presidio_client),
) -> HTMLResponse:
    raw = await file.read()
    file_size = len(raw)

    # Get extension
    extension = ""
    if file.filename:
        extension = Path(file.filename).suffix.lower()

    # Acquire upload semaphore (non-blocking, shared with API route)
    sem = _get_upload_semaphore()
    if sem.locked():
        return templates.TemplateResponse(
            request,
            "partials/document_results.html",
            {"error": "Too many documents are being processed. Please try again shortly."},
        )

    try:
        async with sem:
            result = await asyncio.wait_for(
                process_document(
                    raw=raw,
                    extension=extension,
                    file_size=file_size,
                    presidio=presidio,
                    language=language,
                ),
                timeout=settings.document_processing_timeout,
            )
    except asyncio.TimeoutError:
        return templates.TemplateResponse(
            request,
            "partials/document_results.html",
            {"error": "Document processing timed out. Please try a smaller file."},
        )
    except (ExtractionError, DocumentProcessingError) as exc:
        return templates.TemplateResponse(
            request,
            "partials/document_results.html",
            {"error": exc.message},
        )
    except httpx.ConnectError:
        return templates.TemplateResponse(
            request,
            "partials/document_results.html",
            {"error": "Service is starting up, please wait..."},
        )
    except httpx.TimeoutException:
        return templates.TemplateResponse(
            request,
            "partials/document_results.html",
            {"error": "Processing timed out. Please try again."},
        )
    except httpx.HTTPStatusError:
        return templates.TemplateResponse(
            request,
            "partials/document_results.html",
            {"error": "PII detection service returned an error."},
        )

    entity_types = result.pop("entity_types", [])
    log_document_upload(
        file_type=extension.lstrip("."),
        file_size_bytes=file_size,
        entity_count=len(result["mappings"]),
        entity_types=entity_types,
        language=result["language_detected"],
        source="web_ui",
    )

    metadata = result["metadata"]
    source_format = result["source_format"]

    # Prepare template context
    context = {
        "mappings": result["mappings"],
        "mappings_json": json.dumps(result["mappings"]),
        "mapping_count": len(result["mappings"]),
        "language_detected": result["language_detected"],
        "language_confidence": result.get("language_confidence"),
        "source_format": source_format,
        "chunks_analyzed": metadata["chunks_analyzed"],
        "warnings": metadata.get("warnings", []),
        "xlsx_sheets": None,
        "json_content": None,
        "anonymized_content": None,
    }

    if source_format == "xlsx" and result["anonymized_structured"]:
        context["xlsx_sheets"] = result["anonymized_structured"]
    elif source_format == "json" and result["anonymized_structured"] is not None:
        context["json_content"] = json.dumps(result["anonymized_structured"], indent=2)
    else:
        context["anonymized_content"] = result.get("anonymized_content", "")

    return templates.TemplateResponse(
        request, "partials/document_results.html", context
    )
