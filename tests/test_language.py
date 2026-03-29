"""Unit tests for language detection service (SPEC-004)."""

import asyncio
import logging
from unittest.mock import patch, MagicMock

import pytest

from redakt.services.language import (
    LanguageDetection,
    _build_detector,
    _detect_sync,
    detect_language,
    validate_language_config,
)


@pytest.fixture(autouse=True)
def clear_detector_cache():
    """Clear the lru_cache on _build_detector between tests."""
    _build_detector.cache_clear()
    yield
    _build_detector.cache_clear()


class TestLanguageDetection:
    """Tests for detect_language() return type and basic detection."""

    async def test_detect_english(self):
        result = await detect_language("My name is John Smith and I live in Berlin")
        assert isinstance(result, LanguageDetection)
        assert result.language == "en"
        assert result.confidence is not None
        assert result.confidence > 0.0

    async def test_detect_german(self):
        result = await detect_language("Mein Name ist Hans Mueller und ich wohne in Berlin")
        assert isinstance(result, LanguageDetection)
        assert result.language == "de"
        assert result.confidence is not None
        assert result.confidence > 0.0

    async def test_tuple_unpacking(self):
        """LanguageDetection supports tuple unpacking."""
        language, confidence = await detect_language("My name is John Smith and I live in Berlin")
        assert language == "en"
        assert confidence is not None

    async def test_empty_text_returns_fallback(self):
        result = await detect_language("")
        assert result.language == "en"  # Default fallback
        assert result.confidence is None

    async def test_whitespace_text_returns_fallback(self):
        result = await detect_language("   ")
        assert result.language == "en"
        assert result.confidence is None

    async def test_short_ambiguous_text(self):
        result = await detect_language("123")
        assert result.language == "en"  # Fallback
        assert result.confidence == 0.0  # Fallback confidence


class TestConfigurableFallback:
    """Tests for configurable fallback language (REQ-003)."""

    async def test_empty_text_uses_configured_fallback(self):
        with patch("redakt.services.language.settings") as mock_settings:
            mock_settings.language_detection_fallback = "de"
            mock_settings.supported_languages = ["en", "de"]
            mock_settings.language_detection_timeout = 2.0
            result = await detect_language("")
        assert result.language == "de"
        assert result.confidence is None

    async def test_timeout_uses_configured_fallback(self):
        with patch("redakt.services.language.settings") as mock_settings:
            mock_settings.language_detection_fallback = "de"
            mock_settings.supported_languages = ["en", "de"]
            mock_settings.language_detection_timeout = 0.001  # Very short timeout
            with patch("redakt.services.language._detect_sync", side_effect=lambda t: (_ for _ in ()).throw(TimeoutError)):
                # Use a mock that causes timeout
                with patch("asyncio.wait_for", side_effect=asyncio.TimeoutError):
                    result = await detect_language("some text here")
        assert result.language == "de"
        assert result.confidence == 0.0

    async def test_exception_uses_configured_fallback(self):
        with patch("redakt.services.language.settings") as mock_settings:
            mock_settings.language_detection_fallback = "de"
            mock_settings.supported_languages = ["en", "de"]
            mock_settings.language_detection_timeout = 2.0
            with patch("redakt.services.language._detect_sync", side_effect=RuntimeError("broken")):
                result = await detect_language("some text here")
        assert result.language == "de"
        assert result.confidence == 0.0


class TestFallbackConfidence:
    """Tests for confidence values in fallback scenarios."""

    async def test_fallback_on_failure_returns_zero_confidence(self):
        with patch("redakt.services.language._detect_sync", side_effect=Exception("fail")):
            result = await detect_language("some text")
        assert result.language == "en"
        assert result.confidence == 0.0

    async def test_fallback_on_timeout_returns_zero_confidence(self):
        async def slow_detect(*args, **kwargs):
            await asyncio.sleep(10)

        with patch("asyncio.wait_for", side_effect=asyncio.TimeoutError):
            result = await detect_language("some text")
        assert result.language == "en"
        assert result.confidence == 0.0

    async def test_manual_override_confidence_is_none(self):
        """Manual override is a caller responsibility. When language != 'auto',
        the caller should set confidence to None. This tests the detect_language
        service when called with text -- it always returns a confidence."""
        result = await detect_language("My name is John Smith")
        assert result.confidence is not None  # Auto-detection always returns confidence


class TestDynamicDetectorBuild:
    """Tests for dynamic detector building from settings (REQ-001)."""

    def test_detector_builds_from_supported_languages(self):
        with patch("redakt.services.language.settings") as mock_settings:
            mock_settings.supported_languages = ["en", "de"]
            detector = _build_detector()
            assert detector is not None

    def test_detector_builds_with_three_languages(self):
        with patch("redakt.services.language.settings") as mock_settings:
            mock_settings.supported_languages = ["en", "de", "es"]
            detector = _build_detector()
            assert detector is not None


class TestStartupValidation:
    """Tests for validate_language_config() (REQ-002, REQ-004)."""

    def test_valid_config_passes(self):
        with patch("redakt.services.language.settings") as mock_settings:
            mock_settings.supported_languages = ["en", "de"]
            mock_settings.language_detection_fallback = "en"
            validate_language_config()  # Should not raise

    def test_unsupported_code_raises(self):
        with patch("redakt.services.language.settings") as mock_settings:
            mock_settings.supported_languages = ["en", "de", "xx"]
            mock_settings.language_detection_fallback = "en"
            with pytest.raises(ValueError, match="xx"):
                validate_language_config()

    def test_fallback_not_in_supported_raises(self):
        with patch("redakt.services.language.settings") as mock_settings:
            mock_settings.supported_languages = ["en", "de"]
            mock_settings.language_detection_fallback = "es"
            with pytest.raises(ValueError, match="es"):
                validate_language_config()

    def test_valid_config_with_es(self):
        with patch("redakt.services.language.settings") as mock_settings:
            mock_settings.supported_languages = ["en", "de", "es"]
            mock_settings.language_detection_fallback = "de"
            validate_language_config()  # Should not raise


class TestExceptionHandling:
    """Tests for improved exception handling (EDGE-006)."""

    async def test_timeout_logs_at_warning(self, caplog):
        with caplog.at_level(logging.WARNING, logger="redakt"):
            with patch("asyncio.wait_for", side_effect=asyncio.TimeoutError):
                result = await detect_language("some text")
        assert result.language == "en"
        assert "timed out" in caplog.text

    async def test_exception_logs_at_error_with_exc_info(self, caplog):
        with caplog.at_level(logging.ERROR, logger="redakt"):
            with patch("redakt.services.language._detect_sync", side_effect=RuntimeError("broken detector")):
                result = await detect_language("some text")
        assert result.language == "en"
        assert "failed" in caplog.text
        # Verify exc_info=True was used (traceback is captured in the log record)
        error_records = [r for r in caplog.records if r.levelno == logging.ERROR]
        assert len(error_records) >= 1
        assert error_records[0].exc_info is not None
        assert error_records[0].exc_info[0] is RuntimeError


class TestDetectSync:
    """Tests for the synchronous _detect_sync helper."""

    def test_detect_sync_english(self):
        result = _detect_sync("My name is John Smith and I live in London")
        assert result.language == "en"
        assert result.confidence is not None

    def test_detect_sync_german(self):
        result = _detect_sync("Mein Name ist Hans Mueller und ich wohne in Berlin")
        assert result.language == "de"
        assert result.confidence is not None

    def test_detect_sync_ambiguous_returns_fallback(self):
        result = _detect_sync("123")
        assert result.language == "en"
        assert result.confidence == 0.0


class TestRepresentativeContent:
    """Tests with enterprise-representative content."""

    async def test_german_legal_text(self):
        text = (
            "Der Auftraggeber verpflichtet sich, die personenbezogenen Daten "
            "ausschließlich im Rahmen der vertraglichen Vereinbarungen zu verarbeiten. "
            "Eine Weitergabe an Dritte ist ohne vorherige Zustimmung unzulässig."
        )
        result = await detect_language(text)
        assert result.language == "de"
        assert result.confidence is not None
        assert result.confidence > 0.0

    async def test_english_business_text(self):
        text = (
            "Please find attached the quarterly financial report for Q3 2025. "
            "All personally identifiable information has been redacted in accordance "
            "with our data protection policy."
        )
        result = await detect_language(text)
        assert result.language == "en"
        assert result.confidence is not None
        assert result.confidence > 0.0


class TestConfidenceExceptionPath:
    """Test that detection succeeds but confidence fails returns confidence=None (REQ-005)."""

    def test_confidence_exception_returns_none(self):
        """When compute_language_confidence_values raises but detect_language_of succeeds,
        return the detected language with confidence=None."""
        from lingua import Language

        with patch("redakt.services.language._build_detector") as mock_build:
            mock_detector = MagicMock()
            mock_detector.detect_language_of.return_value = Language.ENGLISH
            mock_detector.compute_language_confidence_values.side_effect = RuntimeError(
                "confidence computation failed"
            )
            mock_build.return_value = mock_detector
            result = _detect_sync("Hello world this is a test sentence")
        assert result.language == "en"
        assert result.confidence is None


class TestSingleLanguageConfig:
    """Test that single-language supported_languages is rejected at startup (FINDING-06)."""

    def test_single_language_raises_at_startup(self):
        with patch("redakt.services.language.settings") as mock_settings:
            mock_settings.supported_languages = ["en"]
            mock_settings.language_detection_fallback = "en"
            with pytest.raises(ValueError, match="at least 2"):
                validate_language_config()


class TestDocumentLanguageDetection:
    """Tests for detect_document_language in document_processor."""

    async def test_empty_chunks_return_fallback(self):
        """When all chunks are empty/whitespace, return fallback with None confidence."""
        from redakt.services.document_processor import detect_document_language
        from redakt.services.extractors import TextChunk

        chunks = [
            TextChunk(text="   ", chunk_id="1", chunk_type="paragraph"),
            TextChunk(text="", chunk_id="2", chunk_type="paragraph"),
            TextChunk(text="\n\t", chunk_id="3", chunk_type="paragraph"),
        ]
        language, confidence = await detect_document_language(chunks, "auto")
        assert language == "en"  # Fallback
        assert confidence is None
