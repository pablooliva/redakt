import logging

import httpx
from fastapi import APIRouter, Depends, Query, Request
from fastapi.exceptions import HTTPException

from redakt.config import settings
from redakt.models.detect import (
    DetectDetailedResponse,
    DetectRequest,
    DetectResponse,
    EntityDetail,
)
from redakt.services.audit import log_detection
from redakt.services.language import detect_language
from redakt.services.presidio import PresidioClient, get_presidio_client

logger = logging.getLogger("redakt")
router = APIRouter(prefix="/api", tags=["detection"])


class DetectionError(Exception):
    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail


class DetectionResult:
    def __init__(
        self,
        has_pii: bool,
        entity_count: int,
        entity_types: list[str],
        language: str,
        raw_results: list[dict] | None = None,
    ):
        self.has_pii = has_pii
        self.entity_count = entity_count
        self.entity_types = entity_types
        self.language = language
        self.raw_results = raw_results or []


async def run_detection(
    text: str,
    language: str,
    score_threshold: float,
    presidio: PresidioClient,
    entities: list[str] | None = None,
    allow_list: list[str] | None = None,
) -> DetectionResult:
    """Shared detection logic used by both API and web routes."""
    # Handle empty text first — before any other validation
    if not text or not text.strip():
        return DetectionResult(
            has_pii=False, entity_count=0, entity_types=[], language="unknown"
        )

    # Resolve language
    if language == "auto":
        resolved_language = await detect_language(text)
    else:
        resolved_language = language

    # Validate language
    if resolved_language not in settings.supported_languages:
        raise DetectionError(
            status_code=400,
            detail=f"Language '{resolved_language}' is not supported. Supported languages: {', '.join(settings.supported_languages)}",
        )

    # Merge allow lists
    merged_allow_list = list(settings.allow_list)
    if allow_list:
        merged_allow_list.extend(allow_list)

    # Call Presidio
    try:
        results = await presidio.analyze(
            text=text,
            language=resolved_language,
            score_threshold=score_threshold,
            entities=entities,
            allow_list=merged_allow_list or None,
        )
    except httpx.ConnectError:
        raise DetectionError(status_code=503, detail="Presidio Analyzer service is unavailable")
    except httpx.TimeoutException:
        raise DetectionError(status_code=504, detail="PII detection service timed out")
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code >= 500:
            raise DetectionError(
                status_code=502, detail="PII detection service returned an error"
            )
        raise

    entity_types = sorted(set(r["entity_type"] for r in results))

    return DetectionResult(
        has_pii=len(results) > 0,
        entity_count=len(results),
        entity_types=entity_types,
        language=resolved_language,
        raw_results=results,
    )


@router.post("/detect")
async def detect_pii(
    request: Request,
    body: DetectRequest,
    verbose: bool = Query(default=False),
    presidio: PresidioClient = Depends(get_presidio_client),
) -> DetectResponse | DetectDetailedResponse:
    try:
        result = await run_detection(
            text=body.text,
            language=body.language,
            score_threshold=body.score_threshold if body.score_threshold is not None else settings.default_score_threshold,
            presidio=presidio,
            entities=body.entities,
            allow_list=body.allow_list,
        )
    except DetectionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)

    source = "web_ui" if request.headers.get("HX-Request") else "api"
    log_detection(
        entity_count=result.entity_count,
        entity_types=result.entity_types,
        language=result.language,
        source=source,
    )

    if verbose:
        return DetectDetailedResponse(
            has_pii=result.has_pii,
            entity_count=result.entity_count,
            entities_found=result.entity_types,
            language_detected=result.language,
            details=[
                EntityDetail(
                    entity_type=r["entity_type"],
                    start=r["start"],
                    end=r["end"],
                    score=r["score"],
                )
                for r in result.raw_results
            ],
        )

    return DetectResponse(
        has_pii=result.has_pii,
        entity_count=result.entity_count,
        entities_found=result.entity_types,
        language_detected=result.language,
    )
