import asyncio
import logging
from functools import lru_cache

from lingua import Language, LanguageDetectorBuilder

from redakt.config import settings

logger = logging.getLogger("redakt")

LINGUA_TO_ISO = {
    Language.ENGLISH: "en",
    Language.GERMAN: "de",
}

ISO_TO_LINGUA = {v: k for k, v in LINGUA_TO_ISO.items()}


@lru_cache(maxsize=1)
def _build_detector():
    return (
        LanguageDetectorBuilder.from_languages(Language.ENGLISH, Language.GERMAN)
        .with_minimum_relative_distance(0.25)
        .build()
    )


async def detect_language(text: str) -> str:
    if not text or not text.strip():
        return "en"

    try:
        detected = await asyncio.wait_for(
            asyncio.get_running_loop().run_in_executor(None, _detect_sync, text),
            timeout=settings.language_detection_timeout,
        )
        return detected
    except (asyncio.TimeoutError, Exception):
        logger.warning("Language detection failed, falling back to 'en'")
        return "en"


def _detect_sync(text: str) -> str:
    detector = _build_detector()
    result = detector.detect_language_of(text)
    if result is None or result not in LINGUA_TO_ISO:
        return "en"
    return LINGUA_TO_ISO[result]
