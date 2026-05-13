import logging

import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.exceptions import HTTPException

from redakt.config import settings
from redakt.models.anonymize import AnonymizeRequest, AnonymizeResponse
from redakt.services.anonymizer import anonymize_entities
from redakt.services.audit import log_anonymization
from redakt.services.language import detect_language
from redakt.services.presidio import PresidioClient, get_presidio_client
from redakt.utils import (
    filter_by_closed_world,
    filter_by_entity_thresholds,
    merge_allow_lists,
    merge_entity_thresholds,
    validate_allow_list,
)

logger = logging.getLogger("redakt")
router = APIRouter(prefix="/api", tags=["anonymization"])


class AnonymizationError(Exception):
    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail


class AnonymizationResult:
    def __init__(
        self,
        anonymized_text: str,
        mappings: dict[str, str],
        entity_types: list[str],
        language: str,
        language_confidence: float | None = None,
        allow_list_count: int | None = None,
        closed_world_suppressed_count: int = 0,
        closed_world_filtering_override: bool | None = None,
    ):
        self.anonymized_text = anonymized_text
        self.mappings = mappings
        self.entity_types = entity_types
        self.language = language
        self.language_confidence = language_confidence
        self.allow_list_count = allow_list_count
        self.closed_world_suppressed_count = closed_world_suppressed_count
        self.closed_world_filtering_override = closed_world_filtering_override


async def run_anonymization(
    text: str,
    language: str,
    score_threshold: float,
    presidio: PresidioClient,
    entities: list[str] | None = None,
    allow_list: list[str] | None = None,
    entity_score_thresholds: dict[str, float] | None = None,
    closed_world_filtering: bool | None = None,
) -> AnonymizationResult:
    """Shared anonymization logic used by both API and web routes."""
    # Empty text — return unchanged
    if not text or not text.strip():
        return AnonymizationResult(
            text, {}, [], settings.language_detection_fallback,
            language_confidence=None,
        )

    # Resolve language
    language_confidence: float | None = None
    if language == "auto":
        detection = await detect_language(text)
        resolved_language = detection.language
        language_confidence = detection.confidence
    else:
        resolved_language = language
        language_confidence = None  # Manual override

    # Validate language
    if resolved_language not in settings.supported_languages:
        raise AnonymizationError(
            status_code=400,
            detail=f"Language '{resolved_language}' is not supported. Supported languages: {', '.join(settings.supported_languages)}",
        )

    # Validate per-request allow list (fail-closed)
    if allow_list:
        validate_allow_list(allow_list)

    # Merge allow lists
    merged_allow_list = merge_allow_lists(settings.allow_list, allow_list)

    # Call Presidio Analyzer
    try:
        results = await presidio.analyze(
            text=text,
            language=resolved_language,
            score_threshold=score_threshold,
            entities=entities,
            allow_list=merged_allow_list,
        )
    except httpx.ConnectError:
        raise AnonymizationError(
            status_code=503, detail="Presidio Analyzer service is unavailable"
        )
    except httpx.TimeoutException:
        raise AnonymizationError(
            status_code=504, detail="PII anonymization service timed out"
        )
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code >= 500:
            raise AnonymizationError(
                status_code=502, detail="PII detection service returned an error"
            )
        raise

    merged_thresholds = merge_entity_thresholds(
        settings.entity_score_thresholds, entity_score_thresholds
    )
    results = filter_by_entity_thresholds(results, merged_thresholds)

    # SEC-002a gate precedence: HIPAA auto-force > SEC-001a gate > per-request > instance default.
    # Capture the raw per-request value before REPLACE merge (for audit field, REQ-013).
    request_value = (
        closed_world_filtering
        if settings.allow_per_request_closed_world_override
        else None
    )
    effective_cwf = (
        request_value if request_value is not None else settings.closed_world_filtering
    )
    # When SEC-001a gate discards the request value, audit field records null (not the caller's value).
    audit_cwf_override = closed_world_filtering if request_value is not None else None

    results, suppressed_count = filter_by_closed_world(
        results,
        enabled=effective_cwf,
        strong_anchors=settings.strong_anchors_set,
        quasi_identifiers=settings.quasi_identifiers_set,
    )

    # Anonymize: resolve overlaps, generate placeholders, replace text
    anonymized_text, mappings, entity_types = anonymize_entities(text, results)

    return AnonymizationResult(
        anonymized_text, mappings, entity_types, resolved_language, language_confidence,
        allow_list_count=len(merged_allow_list) if merged_allow_list else None,
        closed_world_suppressed_count=suppressed_count,
        closed_world_filtering_override=audit_cwf_override,
    )


@router.post("/anonymize")
async def anonymize(
    request: Request,
    body: AnonymizeRequest,
    presidio: PresidioClient = Depends(get_presidio_client),
) -> AnonymizeResponse:
    try:
        result = await run_anonymization(
            text=body.text,
            language=body.language,
            score_threshold=body.score_threshold
            if body.score_threshold is not None
            else settings.default_score_threshold,
            presidio=presidio,
            entities=body.entities,
            allow_list=body.allow_list,
            entity_score_thresholds=body.entity_score_thresholds,
            closed_world_filtering=body.closed_world_filtering,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except AnonymizationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)

    source = "web_ui" if request.headers.get("HX-Request") else "api"
    log_anonymization(
        entity_count=len(result.mappings),
        entities_found=result.entity_types,
        language_detected=result.language,
        source=source,
        allow_list_count=result.allow_list_count,
        operator="replace",
        closed_world_suppressed_count=result.closed_world_suppressed_count,
        closed_world_filtering_override=result.closed_world_filtering_override,
    )

    return AnonymizeResponse(
        anonymized_text=result.anonymized_text,
        mappings=result.mappings,
        language_detected=result.language,
        language_confidence=result.language_confidence,
    )
