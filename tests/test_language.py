from unittest.mock import patch, MagicMock

import pytest

from redakt.services.language import detect_language, _detect_sync


class TestLanguageDetection:
    async def test_detect_english(self):
        result = await detect_language("My name is John Smith and I live in Berlin")
        assert result == "en"

    async def test_detect_german(self):
        result = await detect_language("Mein Name ist Hans Mueller und ich wohne in Berlin")
        assert result == "de"

    async def test_empty_text_returns_en(self):
        result = await detect_language("")
        assert result == "en"

    async def test_whitespace_text_returns_en(self):
        result = await detect_language("   ")
        assert result == "en"

    async def test_fallback_on_failure(self):
        with patch("redakt.services.language._detect_sync", side_effect=Exception("fail")):
            result = await detect_language("some text")
        assert result == "en"

    async def test_short_ambiguous_text(self):
        result = await detect_language("123")
        assert result == "en"  # fallback
