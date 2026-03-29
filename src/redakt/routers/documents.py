"""Document upload API endpoint and web routes."""

import asyncio
import logging
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, Form, Request, UploadFile
from fastapi.exceptions import HTTPException
from fastapi.responses import JSONResponse

from redakt.config import settings
from redakt.models.document import DocumentMetadata, DocumentUploadResponse
from redakt.services.audit import log_document_upload
from redakt.services.document_processor import (
    DocumentProcessingError,
    process_document,
    validate_file,
)
from redakt.services.extractors import ExtractionError
from redakt.services.presidio import PresidioClient, get_presidio_client

logger = logging.getLogger("redakt")
router = APIRouter(prefix="/api", tags=["documents"])

# Server-side concurrency limiter for document uploads
_upload_semaphore: asyncio.Semaphore | None = None


def _get_upload_semaphore() -> asyncio.Semaphore:
    global _upload_semaphore
    if _upload_semaphore is None:
        _upload_semaphore = asyncio.Semaphore(settings.max_concurrent_uploads)
    return _upload_semaphore


def _sanitize_extension(filename: str | None) -> str:
    """Extract and validate file extension from filename.

    Strips path components, limits length, and extracts the extension only.
    """
    if not filename:
        return ""
    # Strip path components for security
    name = Path(filename).name
    # Limit filename length (255 is typical filesystem max)
    if len(name) > 255:
        name = name[-255:]
    # Get extension (lowercase)
    suffix = Path(name).suffix.lower()
    return suffix


def _parse_comma_separated(value: str | None) -> list[str] | None:
    """Parse comma-separated form field into list, ignoring empties."""
    if not value:
        return None
    items = [item.strip() for item in value.split(",") if item.strip()]
    return items if items else None


@router.post("/documents/upload")
async def upload_document(
    request: Request,
    file: UploadFile,
    language: str = Form("auto"),
    score_threshold: float | None = Form(None),
    entities: str | None = Form(None),
    allow_list: str | None = Form(None),
    presidio: PresidioClient = Depends(get_presidio_client),
) -> DocumentUploadResponse:
    """Upload a document for PII anonymization."""
    # Parse comma-separated fields
    parsed_entities = _parse_comma_separated(entities)
    parsed_allow_list = _parse_comma_separated(allow_list)

    # Read file content
    raw = await file.read()
    file_size = len(raw)

    # Get file extension
    extension = _sanitize_extension(file.filename)

    # Acquire upload semaphore (non-blocking)
    sem = _get_upload_semaphore()
    if sem.locked():
        raise HTTPException(
            status_code=429,
            detail="Too many documents are being processed. Please try again shortly.",
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
                    score_threshold=score_threshold,
                    entities=parsed_entities,
                    allow_list=parsed_allow_list,
                ),
                timeout=settings.document_processing_timeout,
            )
    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=504,
            detail="Document processing timed out. The file may contain too many text cells "
            "to process within the time limit.",
        )
    except ExtractionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)
    except DocumentProcessingError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)
    except httpx.ConnectError:
        raise HTTPException(
            status_code=503,
            detail="PII detection service is currently unavailable. Please try again later.",
        )
    except httpx.TimeoutException:
        raise HTTPException(
            status_code=504,
            detail="PII detection timed out. The document may be too large or complex. "
            "Please try a smaller file.",
        )
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code >= 500:
            raise HTTPException(
                status_code=502,
                detail="PII detection service returned an error.",
            )
        raise

    # Audit log (no PII: no filename, no content)
    source = "web_ui" if request.headers.get("HX-Request") else "api"
    entity_types = result.pop("entity_types", [])
    log_document_upload(
        file_type=extension.lstrip("."),
        file_size_bytes=file_size,
        entity_count=len(result["mappings"]),
        entity_types=entity_types,
        language=result["language_detected"],
        source=source,
    )

    return DocumentUploadResponse(
        anonymized_content=result["anonymized_content"],
        anonymized_structured=result["anonymized_structured"],
        mappings=result["mappings"],
        language_detected=result["language_detected"],
        language_confidence=result.get("language_confidence"),
        source_format=result["source_format"],
        metadata=DocumentMetadata(**result["metadata"]),
    )
