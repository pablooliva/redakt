import asyncio
import logging
from functools import lru_cache
from typing import NamedTuple

from lingua import Language, LanguageDetectorBuilder

from redakt.config import settings

logger = logging.getLogger("redakt")

LINGUA_TO_ISO = {
    Language.ENGLISH: "en",
    Language.GERMAN: "de",
    Language.SPANISH: "es",
}

ISO_TO_LINGUA = {v: k for k, v in LINGUA_TO_ISO.items()}


class LanguageDetection(NamedTuple):
    language: str
    confidence: float | None


def validate_language_config() -> None:
    """Validate language configuration at startup (REQ-002, REQ-004).

    Checks that all supported_languages are in ISO_TO_LINGUA and that the
    fallback language is in supported_languages. Raises ValueError on failure.
    """
    unsupported = [
        code for code in settings.supported_languages if code not in ISO_TO_LINGUA
    ]
    if unsupported:
        msg = (
            f"Language configuration error: supported_languages contains codes "
            f"not available in ISO_TO_LINGUA mapping: {unsupported}. "
            f"Available codes: {sorted(ISO_TO_LINGUA.keys())}"
        )
        logger.error(msg)
        raise ValueError(msg)

    # Lingua requires at least 2 languages to build a detector
    lingua_capable = [
        code for code in settings.supported_languages if code in ISO_TO_LINGUA
    ]
    if len(lingua_capable) < 2:
        msg = (
            f"Language configuration error: at least 2 supported_languages with "
            f"Lingua mappings are required for auto-detection, but only found "
            f"{lingua_capable}. Available Lingua codes: {sorted(ISO_TO_LINGUA.keys())}"
        )
        logger.error(msg)
        raise ValueError(msg)

    if settings.language_detection_fallback not in settings.supported_languages:
        msg = (
            f"Language configuration error: language_detection_fallback "
            f"'{settings.language_detection_fallback}' is not in "
            f"supported_languages {settings.supported_languages}"
        )
        logger.error(msg)
        raise ValueError(msg)


@lru_cache(maxsize=1)
def _build_detector():
    lingua_languages = []
    for code in settings.supported_languages:
        lingua_lang = ISO_TO_LINGUA.get(code)
        if lingua_lang is not None:
            lingua_languages.append(lingua_lang)

    if len(lingua_languages) < 2:
        # Lingua requires at least 2 languages
        # Fall back to all mapped languages
        lingua_languages = list(LINGUA_TO_ISO.keys())

    return (
        LanguageDetectorBuilder.from_languages(*lingua_languages)
        .with_minimum_relative_distance(0.25)
        .build()
    )


async def detect_language(text: str) -> LanguageDetection:
    fallback = settings.language_detection_fallback

    if not text or not text.strip():
        logger.info(
            "Language detection skipped for empty text",
            extra={
                "language_detected": fallback,
                "language_confidence": None,
                "language_fallback": True,
                "language_fallback_reason": "empty_text",
            },
        )
        return LanguageDetection(fallback, None)

    try:
        result = await asyncio.wait_for(
            asyncio.get_running_loop().run_in_executor(None, _detect_sync, text),
            timeout=settings.language_detection_timeout,
        )
        logger.debug(
            "Language detected: %s (confidence: %s)",
            result.language,
            result.confidence,
            extra={
                "language_detected": result.language,
                "language_confidence": result.confidence,
                "language_fallback": False,
            },
        )
        return result
    except asyncio.TimeoutError:
        logger.warning(
            "Language detection timed out after %.1fs, falling back to '%s'",
            settings.language_detection_timeout,
            fallback,
            extra={
                "language_detected": fallback,
                "language_confidence": 0.0,
                "language_fallback": True,
                "language_fallback_reason": "timeout",
            },
        )
        return LanguageDetection(fallback, 0.0)
    except Exception:
        logger.error(
            "Language detection failed, falling back to '%s'",
            fallback,
            exc_info=True,
            extra={
                "language_detected": fallback,
                "language_confidence": 0.0,
                "language_fallback": True,
                "language_fallback_reason": "exception",
            },
        )
        return LanguageDetection(fallback, 0.0)


def _detect_sync(text: str) -> LanguageDetection:
    detector = _build_detector()
    result = detector.detect_language_of(text)
    if result is None or result not in LINGUA_TO_ISO:
        fallback = settings.language_detection_fallback
        logger.info(
            "Lingua returned %s, falling back to '%s'",
            result,
            fallback,
            extra={
                "language_detected": fallback,
                "language_confidence": 0.0,
                "language_fallback": True,
                "language_fallback_reason": "ambiguous",
            },
        )
        return LanguageDetection(fallback, 0.0)

    detected_iso = LINGUA_TO_ISO[result]

    # Compute confidence
    confidence: float | None = None
    try:
        confidence_values = detector.compute_language_confidence_values(text)
        for cv in confidence_values:
            if cv.language == result:
                confidence = cv.value
                break
        if confidence is None:
            confidence = 0.0
    except Exception:
        logger.warning(
            "Confidence computation failed for detected language '%s'",
            detected_iso,
            exc_info=True,
            extra={
                "language_detected": detected_iso,
                "language_confidence": None,
                "language_fallback": False,
                "language_fallback_reason": "confidence_unavailable",
            },
        )
        confidence = None

    return LanguageDetection(detected_iso, confidence)
