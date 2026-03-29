"""E2E tests for language auto-detection with manual override (SPEC-004).

Tests language toggle behavior, confidence label display, and manual override
across all three pages (detect, anonymize, documents).

Requires: Docker Compose stack running (Redakt on port 8000 + Presidio services).
Run with: uv run pytest tests/e2e/test_language_e2e.py -v --headed
"""

import re

from playwright.sync_api import Page, expect


# Texts that Lingua reliably detects
ENGLISH_TEXT = "Please contact John Smith at john.smith@example.com regarding his account."
GERMAN_TEXT = (
    "Bitte kontaktieren Sie Hans Mueller unter hans.mueller@example.com "
    "bezüglich seines Kontos bei der Deutschen Bank in Berlin."
)


class TestDetectPageLanguage:
    """Language toggle and confidence on the detect page."""

    def test_auto_radio_selected_by_default(self, page: Page, base_url: str):
        page.goto(f"{base_url}/detect")
        auto_radio = page.locator("input[name='language'][value='auto']")
        expect(auto_radio).to_be_checked()

    def test_auto_detect_shows_language_and_confidence(self, page: Page, base_url: str):
        page.goto(f"{base_url}/detect")
        page.locator("#text").fill(ENGLISH_TEXT)
        page.locator("button[type=submit]").click()

        meta = page.locator(".meta")
        expect(meta).to_be_visible(timeout=15_000)
        meta_text = meta.text_content()
        assert "Language: en" in meta_text
        # Confidence label should be shown for auto-detect
        assert "Confidence:" in meta_text

    def test_manual_override_respected(self, page: Page, base_url: str):
        """Override to 'de' when submitting English text -- language_detected should be 'de'."""
        page.goto(f"{base_url}/detect")
        page.locator("input[name='language'][value='de']").check()
        page.locator("#text").fill(ENGLISH_TEXT)
        page.locator("button[type=submit]").click()

        meta = page.locator(".meta")
        expect(meta).to_be_visible(timeout=15_000)
        meta_text = meta.text_content()
        assert "Language: de" in meta_text

    def test_manual_override_hides_confidence(self, page: Page, base_url: str):
        """Manual override should not show confidence label."""
        page.goto(f"{base_url}/detect")
        page.locator("input[name='language'][value='en']").check()
        page.locator("#text").fill(GERMAN_TEXT)
        page.locator("button[type=submit]").click()

        meta = page.locator(".meta")
        expect(meta).to_be_visible(timeout=15_000)
        meta_text = meta.text_content()
        assert "Language: en" in meta_text
        assert "Confidence:" not in meta_text


class TestAnonymizePageLanguage:
    """Language toggle and confidence on the anonymize page."""

    def test_auto_radio_selected_by_default(self, page: Page, base_url: str):
        page.goto(f"{base_url}/anonymize")
        auto_radio = page.locator("input[name='language'][value='auto']")
        expect(auto_radio).to_be_checked()

    def test_auto_detect_shows_confidence(self, page: Page, base_url: str):
        page.goto(f"{base_url}/anonymize")
        page.locator("#text").fill(ENGLISH_TEXT)
        page.locator("button[type=submit]").click()

        meta = page.locator(".meta")
        expect(meta).to_be_visible(timeout=15_000)
        meta_text = meta.text_content()
        assert "Language: en" in meta_text
        assert "Confidence:" in meta_text

    def test_manual_override_no_confidence(self, page: Page, base_url: str):
        page.goto(f"{base_url}/anonymize")
        page.locator("input[name='language'][value='de']").check()
        page.locator("#text").fill(ENGLISH_TEXT)
        page.locator("button[type=submit]").click()

        meta = page.locator(".meta")
        expect(meta).to_be_visible(timeout=15_000)
        meta_text = meta.text_content()
        assert "Language: de" in meta_text
        assert "Confidence:" not in meta_text


class TestDocumentsPageLanguage:
    """Language toggle and confidence on the documents page."""

    def test_auto_radio_selected_by_default(self, page: Page, base_url: str):
        page.goto(f"{base_url}/documents")
        auto_radio = page.locator("input[name='language'][value='auto']")
        expect(auto_radio).to_be_checked()
